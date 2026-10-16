"""The WSGI app: a small route table, JSON helpers and the static files from dist/."""
import hashlib
import http
import json
import mimetypes
import pathlib
import re
import sqlite3
import sys
import time
import traceback

from . import db

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".css": "text/css; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}
MAX_BODY = 64 * 1024  # bytes; a bigger request body gets 413
# Files whose Cache-Control differs from the static default of "no-cache".
CACHE_CONTROL = {"questions.json": "private, no-cache"}
# Files in dist/ served only to someone signed in. Everything else there is open,
# because the sign-in page needs it.
SIGNED_IN_FILES = {"questions.json"}


class Response:
    def __init__(self, status=200, body=b"", content_type=None, headers=None):
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        if content_type:
            self.headers["Content-Type"] = content_type


def text(status, message, headers=None):
    return Response(status, (message + "\n").encode(), "text/plain; charset=utf-8", headers)


def json_response(value, status=200, headers=None):
    """A JSON answer. API answers are never cached (the app's default Cache-Control is no-store)."""
    body = json.dumps(value, ensure_ascii=False).encode()
    return Response(status, body, "application/json", headers)


def json_error(status, message):
    return json_response({"error": message}, status)


class HTTPError(Exception):
    """Raise from a handler to answer with a JSON error: `raise HTTPError(400, "name is missing")`."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def etag_for(body):
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def etag_matches(if_none_match, etag):
    if not if_none_match:
        return False
    tags = [t.strip().removeprefix("W/") for t in if_none_match.split(",")]
    return "*" in tags or etag in tags


def content_type_for(name):
    suffix = pathlib.PurePosixPath(name).suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def find_static(dist, path):
    """The file in dist/ that a URL path names, or None. Never a folder, never outside dist/."""
    name = "index.html" if path == "/" else path.removeprefix("/")
    parts = name.split("/")
    if not name or any(p in ("", ".", "..") or "\\" in p or "\0" in p for p in parts):
        return None
    root = dist.resolve()
    try:
        file = (root / name).resolve()
    except (OSError, ValueError):
        return None
    if not file.is_relative_to(root) or not file.is_file():
        return None
    return file


def serve_static(dist, file, environ):
    """Answer with a file that find_static() found, or a 304 if the client's copy is current."""
    try:
        body = file.read_bytes()
    except OSError:
        return text(404, "Not found")
    name = file.relative_to(dist.resolve()).as_posix()
    etag = etag_for(body)
    headers = {"Cache-Control": CACHE_CONTROL.get(name, "no-cache"), "ETag": etag}
    if etag_matches(environ.get("HTTP_IF_NONE_MATCH"), etag):
        return Response(304, b"", headers=headers)
    return Response(200, body, content_type_for(name), headers)


CSP = ("default-src 'none'; script-src {script}; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; connect-src 'self'; img-src 'self' data:; manifest-src 'self'; "
       "worker-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def script_source(dist):
    """The page script's hash from dist/csp.json, read fresh, or 'none' if it can't be read."""
    try:
        value = json.loads((dist / "csp.json").read_text())["script"]
    except (OSError, ValueError, KeyError, TypeError):
        return "'none'"
    if not isinstance(value, str) or not re.fullmatch(r"sha(256|384|512)-[A-Za-z0-9+/]+=*", value):
        return "'none'"
    return f"'{value}'"


def security_headers(dist):
    """Headers every response carries. No HSTS: TLS belongs to the proxy in front."""
    return {
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": CSP.format(script=script_source(dist)),
    }


class Request:
    """One request: its method, path and headers, and a database connection opened on first use."""

    def __init__(self, environ, app):
        self.environ = environ
        self.app = app
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        # WSGI hands the path over as bytes decoded as latin-1; paths are UTF-8.
        self.path = (environ.get("PATH_INFO") or "/").encode("latin-1").decode("utf-8", "replace")
        self._db = None
        self._body = None
        self.cookie = None  # a Set-Cookie value to send with the response

    def now(self):
        """The time now, in seconds since 1970, from the app's clock."""
        return self.app.clock()

    def set_cookie(self, value):
        """Send this Set-Cookie value with the response (the app has one cookie, so the last one wins)."""
        self.cookie = value

    def header(self, name, default=None):
        """A request header by its HTTP name, e.g. req.header("If-None-Match")."""
        key = name.upper().replace("-", "_")
        if key not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            key = "HTTP_" + key
        return self.environ.get(key, default)

    def content_length(self):
        try:
            return max(0, int(self.environ.get("CONTENT_LENGTH") or 0))
        except ValueError:
            raise HTTPError(400, "bad Content-Length") from None

    def body(self):
        """The request body as bytes, at most MAX_BODY. The app has already refused anything larger."""
        if self._body is None:
            stream = self.environ.get("wsgi.input")
            self._body = stream.read(min(self.content_length(), MAX_BODY)) if stream else b""
        return self._body

    def json(self):
        """The body parsed as JSON. 415 unless sent as application/json, 400 if it doesn't parse."""
        ctype = (self.header("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise HTTPError(415, "send the body as application/json")
        try:
            return json.loads(self.body())
        except (UnicodeDecodeError, ValueError):
            raise HTTPError(400, "the body is not valid JSON") from None

    @property
    def db(self):
        """This request's database connection (one per request, closed when it ends)."""
        if self._db is None:
            self._db = db.connect(self.app.instance_dir)
        return self._db

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None


# The route table: (method, path) -> handler(req) -> Response.
ROUTES = {}


def route(method, path, table=ROUTES):
    """Register a handler: `@route("POST", "/api/thing")`."""
    def register(handler):
        table[(method.upper(), path)] = handler
        return handler
    return register


@route("GET", "/robots.txt")
def robots(req):
    return Response(200, b"User-agent: *\nDisallow: /\n", "text/plain; charset=utf-8",
                    {"Cache-Control": "no-cache"})


@route("GET", "/healthz")
def healthz(req):
    try:
        req.db.execute("PRAGMA user_version").fetchone()
    except sqlite3.Error:
        return text(503, "Database unavailable")
    return text(200, "OK")


class App:
    """The WSGI app. `routes` defaults to ROUTES; tests may pass their own table."""

    def __init__(self, dist, instance_dir, origin, routes=None, clock=None):
        self.dist = pathlib.Path(dist)
        self.instance_dir = pathlib.Path(instance_dir)
        self.origin = origin
        self.routes = ROUTES if routes is None else routes
        self.clock = clock or time.time

    def handle(self, req):
        # Forgery protection: everything that changes something is a POST, and a POST
        # must come from a page on this Instance. Compared with the setting, never Host.
        if req.method == "POST" and req.header("Origin") != self.origin:
            return json_error(403, "this request did not come from this Instance")
        if req.content_length() > MAX_BODY:
            return json_error(413, f"the body is over {MAX_BODY // 1024} KB")
        method = "GET" if req.method == "HEAD" else req.method
        handler = self.routes.get((method, req.path))
        if handler is not None:
            return handler(req)
        file = find_static(self.dist, req.path)
        if file is not None:
            if file.name in SIGNED_IN_FILES and file.parent == self.dist.resolve() \
                    and auth.current_account(req) is None:
                return json_error(401, "signed-out")
            if method == "GET":
                return serve_static(self.dist, file, req.environ)
            return text(405, "Method not allowed", {"Allow": "GET, HEAD"})
        allowed = sorted({m for m, p in self.routes if p == req.path})
        if allowed:
            if "GET" in allowed and "HEAD" not in allowed:
                allowed.append("HEAD")
            return text(405, "Method not allowed", {"Allow": ", ".join(allowed)})
        return text(404, "Not found")

    def __call__(self, environ, start_response):
        req = Request(environ, self)
        try:
            resp = self.handle(req)
        except HTTPError as e:
            resp = json_error(e.status, e.message)
        except Exception:
            traceback.print_exc(file=environ.get("wsgi.errors", sys.stderr))
            resp = text(500, "Server error")
        finally:
            req.close()
        headers = {"Cache-Control": "no-store", **resp.headers, **security_headers(self.dist)}
        headers = list(headers.items())
        if req.cookie is not None:
            headers.append(("Set-Cookie", req.cookie))
        if resp.status != 304:
            headers.append(("Content-Length", str(len(resp.body))))
        status = http.HTTPStatus(resp.status)
        start_response(f"{status.value} {status.phrase}", headers)
        if req.method == "HEAD":
            return [b""]
        return [resp.body]


def make_app(dist, instance_dir, origin, routes=None, clock=None):
    """The WSGI app. `clock` returns the time in seconds (default time.time); tests pass a fake one."""
    return App(dist, instance_dir, origin, routes, clock)


# Route modules register into ROUTES when imported.
from . import auth  # noqa: E402
