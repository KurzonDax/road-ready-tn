"""Tests for the server: startup checks, the WSGI app, static files and headers, and
accounts, sign-in sessions and the Helper command.

Most tests call the WSGI app directly, with no network. The startup tests run
`python -m server` as a program, the way an Instance starts it.

Usage:
    python3 -m unittest tests/test_server.py
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run_server(env, timeout=10):
    """Run `python -m server` with only the given RRTN_ variables set, expecting it to exit."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith("RRTN_")}
    clean.update(env)
    return subprocess.run([sys.executable, "-m", "server"], cwd=ROOT, env=clean,
                          capture_output=True, text=True, timeout=timeout)


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningServer:
    """`python -m server` running in the background on a free port, for tests that need a real server.

        with RunningServer(instance_dir) as srv:
            urllib.request.urlopen(srv.url + "/healthz")
    """

    output = None

    def __init__(self, instance_dir, origin="https://permit.example.org", trusted_proxy="127.0.0.1"):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("RRTN_")}
        self.env.update(RRTN_DIR=str(instance_dir), RRTN_PORT=str(self.port),
                        RRTN_TRUSTED_PROXY=trusted_proxy, RRTN_ORIGIN=origin)

    def __enter__(self):
        import time
        import urllib.request
        self.proc = subprocess.Popen([sys.executable, "-m", "server"], cwd=ROOT, env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("server exited: " + self.proc.stdout.read())
            try:
                urllib.request.urlopen(self.url + "/healthz", timeout=1).close()
                return self
            except OSError:
                time.sleep(0.1)
        self.__exit__()
        raise RuntimeError("server did not answer /healthz in time")

    def __exit__(self, *exc):
        """Stop the server. What it wrote to stdout and stderr is then in `self.output`."""
        self.proc.terminate()
        try:
            self.output = self.proc.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.output = self.proc.communicate()[0]


class RunningTheServer(unittest.TestCase):
    def test_python_m_server_serves_the_built_page_and_answers_healthz(self):
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp, RunningServer(tmp) as srv:
            with urllib.request.urlopen(srv.url + "/healthz") as r:
                self.assertEqual(r.status, 200)
            with urllib.request.urlopen(srv.url + "/") as r:
                self.assertEqual(r.status, 200)
                self.assertEqual(r.read(), (ROOT / "dist" / "index.html").read_bytes())
                self.assertIn("script-src '", r.headers["Content-Security-Policy"])
            self.assertTrue((pathlib.Path(tmp) / "rrtn.db").is_file())


class StartupChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.good = {"RRTN_DIR": self.tmp.name, "RRTN_TRUSTED_PROXY": "127.0.0.1",
                     "RRTN_ORIGIN": "https://permit.example.org"}

    def tearDown(self):
        self.tmp.cleanup()

    def assert_refuses(self, env, *words):
        r = run_server(env)
        self.assertNotEqual(r.returncode, 0)
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, f"expected a one-line message, got {r.stderr!r}")
        for w in words:
            self.assertIn(w, lines[0])

    def test_missing_origin_exits_with_a_message_naming_it(self):
        env = dict(self.good)
        del env["RRTN_ORIGIN"]
        self.assert_refuses(env, "RRTN_ORIGIN")

    def test_missing_trusted_proxy_exits_with_a_message_naming_it(self):
        env = dict(self.good)
        del env["RRTN_TRUSTED_PROXY"]
        self.assert_refuses(env, "RRTN_TRUSTED_PROXY")

    def test_an_instance_folder_that_cant_be_written_exits_with_a_message_naming_it(self):
        # A folder "inside" a plain file can't be written to, even by root.
        blocker = pathlib.Path(self.tmp.name) / "a-file"
        blocker.write_text("")
        self.assert_refuses(dict(self.good, RRTN_DIR=str(blocker / "instance")), "RRTN_DIR")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write to any folder")
    def test_a_read_only_instance_folder_exits_with_a_message_naming_it(self):
        folder = pathlib.Path(self.tmp.name) / "read-only"
        folder.mkdir()
        folder.chmod(0o555)
        try:
            self.assert_refuses(dict(self.good, RRTN_DIR=str(folder)), "RRTN_DIR", str(folder))
        finally:
            folder.chmod(0o755)

    def test_a_port_that_isnt_a_number_exits_with_a_message_naming_it(self):
        self.assert_refuses(dict(self.good, RRTN_PORT="eighty"), "RRTN_PORT")

    def test_an_origin_with_a_path_exits_with_a_message_naming_it(self):
        self.assert_refuses(dict(self.good, RRTN_ORIGIN="https://permit.example.org/app"), "RRTN_ORIGIN")


ORIGIN = "https://permit.example.org"
SCRIPT_HASH = "sha256-dGVzdC1oYXNoLW5vdC1hLXJlYWwtb25lLWZvci10ZXN0cw=="
PAGE = b"<!doctype html><title>page</title><main id=stage></main>"
QUESTIONS = b'{"days": [], "qs": []}'


def make_dist(folder):
    """A small stand-in for dist/: the page, questions, CSP hash and one other file."""
    dist = pathlib.Path(folder) / "dist"
    dist.mkdir()
    (dist / "index.html").write_bytes(PAGE)
    (dist / "questions.json").write_bytes(QUESTIONS)
    (dist / "csp.json").write_text('{"script": "%s"}' % SCRIPT_HASH)
    return dist


class Response:
    def __init__(self, status, headers, body):
        self.status = int(status.split()[0])
        self.header_list = headers
        self.headers = {k.lower(): v for k, v in headers}
        self.body = body


def call(app, method="GET", path="/", headers=None, body=b""):
    """Call a WSGI app the way waitress would, and collect what it answers."""
    import io
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "", "SERVER_NAME": "localhost",
        "SERVER_PORT": "8080", "SERVER_PROTOCOL": "HTTP/1.1", "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body), "wsgi.errors": io.StringIO(), "CONTENT_LENGTH": str(len(body)),
    }
    for k, v in (headers or {}).items():
        key = k.upper().replace("-", "_")
        environ[key if key in ("CONTENT_TYPE", "CONTENT_LENGTH") else "HTTP_" + key] = v
    seen = {}

    def start_response(status, response_headers, exc_info=None):
        seen["status"], seen["headers"] = status, response_headers

    out = app(environ, start_response)
    try:
        data = b"".join(out)
    finally:
        getattr(out, "close", lambda: None)()
    return Response(seen["status"], seen["headers"], data)


class AppTestCase(unittest.TestCase):
    def setUp(self):
        from server import app, db
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = make_dist(self.tmp.name)
        self.instance = pathlib.Path(self.tmp.name) / "instance"
        self.instance.mkdir()
        db.migrate(self.instance)
        self.app = app.make_app(dist=self.dist, instance_dir=self.instance, origin=ORIGIN)

    def tearDown(self):
        self.tmp.cleanup()

    def signed_in(self, role="learner", name=None, password="a good password"):
        """Headers carrying a session cookie for a new account, made directly with server.auth."""
        import time
        from server import auth, db
        conn = db.connect(self.instance)
        try:
            account_id = auth.create_account(conn, role, name or f"{role} {time.time_ns()}", password, now=time.time())
            token = auth.start_session(conn, auth.get_account(conn, account_id), now=time.time())
        finally:
            conn.close()
        return {"Cookie": f"__Host-rrtn={token}"}


class StaticFiles(AppTestCase):
    def test_the_page_is_served_at_the_root_with_no_cache_and_an_etag(self):
        r = call(self.app, "GET", "/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, PAGE)
        self.assertTrue(r.headers["content-type"].startswith("text/html"))
        self.assertEqual(r.headers["cache-control"], "no-cache")
        self.assertTrue(r.headers.get("etag"))

    def test_the_page_is_also_served_as_index_html(self):
        r = call(self.app, "GET", "/index.html")
        self.assertEqual((r.status, r.body, r.headers["cache-control"]), (200, PAGE, "no-cache"))

    def test_questions_are_served_private_no_cache_with_an_etag(self):
        r = call(self.app, "GET", "/questions.json", self.signed_in())
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, QUESTIONS)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        self.assertEqual(r.headers["cache-control"], "private, no-cache")
        self.assertTrue(r.headers.get("etag"))

    def test_a_matching_if_none_match_gets_304_with_no_body(self):
        cookie = self.signed_in()
        for path in ("/", "/questions.json"):
            with self.subTest(path=path):
                tag = call(self.app, "GET", path, cookie).headers["etag"]
                r = call(self.app, "GET", path, {**cookie, "If-None-Match": tag})
                self.assertEqual(r.status, 304)
                self.assertEqual(r.body, b"")
                self.assertEqual(r.headers["etag"], tag)
                self.assertIn("no-cache", r.headers["cache-control"])

    def test_if_none_match_with_a_list_or_a_weak_tag_still_matches(self):
        tag = call(self.app, "GET", "/").headers["etag"]
        self.assertEqual(call(self.app, "GET", "/", {"If-None-Match": f'"other", W/{tag}'}).status, 304)

    def test_a_stale_if_none_match_gets_the_file(self):
        r = call(self.app, "GET", "/", {"If-None-Match": '"not-the-current-one"'})
        self.assertEqual((r.status, r.body), (200, PAGE))

    def test_files_are_read_fresh_so_a_new_page_needs_no_restart(self):
        before = call(self.app, "GET", "/")
        (self.dist / "index.html").write_bytes(b"<!doctype html><title>new page</title>")
        after = call(self.app, "GET", "/", {"If-None-Match": before.headers["etag"]})
        self.assertEqual((after.status, after.body), (200, b"<!doctype html><title>new page</title>"))
        self.assertNotEqual(after.headers["etag"], before.headers["etag"])

    def test_other_files_in_dist_get_their_content_type_no_cache_and_an_etag(self):
        (self.dist / "fonts").mkdir()
        (self.dist / "fonts" / "body.woff2").write_bytes(b"wOF2 font bytes")
        (self.dist / "icon.png").write_bytes(b"\x89PNG bytes")
        (self.dist / "app.webmanifest").write_text('{"name": "Road Ready"}')
        (self.dist / "sw.js").write_text("self.addEventListener('fetch', () => {});")
        expected = {
            "/fonts/body.woff2": "font/woff2",
            "/icon.png": "image/png",
            "/app.webmanifest": "application/manifest+json",
            "/sw.js": "text/javascript",
        }
        for path, ctype in expected.items():
            with self.subTest(path=path):
                r = call(self.app, "GET", path)
                self.assertEqual(r.status, 200)
                self.assertEqual(r.headers["content-type"].split(";")[0], ctype)
                self.assertEqual(r.headers["cache-control"], "no-cache")
                self.assertTrue(r.headers.get("etag"))

    def test_a_missing_file_is_404(self):
        self.assertEqual(call(self.app, "GET", "/nothing-here.js").status, 404)

    def test_a_folder_is_never_listed(self):
        (self.dist / "fonts").mkdir()
        (self.dist / "fonts" / "body.woff2").write_bytes(b"font")
        for path in ("/fonts", "/fonts/"):
            with self.subTest(path=path):
                r = call(self.app, "GET", path)
                self.assertEqual(r.status, 404)
                self.assertNotIn(b"body.woff2", r.body)

    def test_head_answers_the_headers_without_the_body(self):
        r = call(self.app, "HEAD", "/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, b"")
        self.assertEqual(r.headers["content-length"], str(len(PAGE)))

    def test_other_methods_on_a_file_get_405(self):
        r = call(self.app, "PUT", "/index.html", {"Origin": ORIGIN})
        self.assertEqual(r.status, 405)
        self.assertIn("GET", r.headers["allow"])


class PathTraversal(AppTestCase):
    def setUp(self):
        super().setUp()
        # A file beside dist/, standing in for build.py or the database.
        (self.dist.parent / "secret.py").write_bytes(b"SECRET = 1")

    def assert_not_served(self, path):
        r = call(self.app, "GET", path)
        self.assertIn(r.status, (400, 404), path)
        self.assertNotIn(b"SECRET", r.body, path)

    def test_dot_dot_paths_never_leave_dist(self):
        for path in ("/../secret.py", "/fonts/../../secret.py", "/./../secret.py", "/..", "/../",
                     "/..%2fsecret.py", "/%2e%2e/secret.py", "/..\\secret.py", "//secret.py",
                     "/" + str(self.dist.parent / "secret.py")):
            with self.subTest(path=path):
                self.assert_not_served(path)

    def test_the_real_build_script_is_never_served(self):
        from server import app
        real = app.make_app(dist=ROOT / "dist", instance_dir=self.instance, origin=ORIGIN)
        for path in ("/../build.py", "/../server/app.py", "/..%2fbuild.py"):
            with self.subTest(path=path):
                r = call(real, "GET", path)
                self.assertEqual(r.status, 404)
                self.assertNotIn(b"import", r.body)

    def test_a_link_inside_dist_that_points_outside_is_not_followed(self):
        try:
            (self.dist / "link.py").symlink_to(self.dist.parent / "secret.py")
        except OSError:
            self.skipTest("can't make symlinks here")
        self.assert_not_served("/link.py")

    def test_a_null_byte_in_the_path_is_refused(self):
        self.assert_not_served("/index.html\0.py")


def expected_csp(script_hash):
    return ("default-src 'none'; script-src '" + script_hash + "'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; connect-src 'self'; img-src 'self' data:; manifest-src 'self'; "
            "worker-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class HeadersOnEveryResponse(AppTestCase):
    REQUESTS = [
        ("GET", "/", {}, b""),
        ("GET", "/questions.json", {}, b""),
        ("HEAD", "/", {}, b""),
        ("GET", "/nothing-here", {}, b""),
        ("PUT", "/index.html", {"Origin": ORIGIN}, b""),
        ("GET", "/robots.txt", {}, b""),
        ("GET", "/healthz", {}, b""),
        ("POST", "/anything", {}, b"{}"),
        ("POST", "/anything", {"Origin": ORIGIN, "Content-Type": "application/json"}, b"x" * 70000),
    ]

    def responses(self):
        tag = call(self.app, "GET", "/").headers["etag"]
        yield "304", call(self.app, "GET", "/", {"If-None-Match": tag})
        for method, path, headers, body in self.REQUESTS:
            yield f"{method} {path}", call(self.app, method, path, headers, body)

    def test_every_response_carries_the_four_headers(self):
        for name, r in self.responses():
            with self.subTest(name, status=r.status):
                self.assertEqual(r.headers.get("x-robots-tag"), "noindex, nofollow")
                self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
                self.assertEqual(r.headers.get("referrer-policy"), "no-referrer")
                self.assertEqual(r.headers.get("content-security-policy"), expected_csp(SCRIPT_HASH))

    def test_no_header_is_sent_twice_and_there_is_no_hsts(self):
        for name, r in self.responses():
            with self.subTest(name):
                names = [k.lower() for k, _ in r.header_list]
                self.assertEqual(len(names), len(set(names)), names)
                self.assertNotIn("strict-transport-security", names)

    def test_the_csp_hash_is_read_fresh_from_csp_json(self):
        (self.dist / "csp.json").write_text('{"script": "sha256-bmV3LWhhc2g="}')
        csp = call(self.app, "GET", "/").headers["content-security-policy"]
        self.assertIn("script-src 'sha256-bmV3LWhhc2g='", csp)

    def test_a_missing_csp_json_allows_no_script_at_all(self):
        (self.dist / "csp.json").unlink()
        csp = call(self.app, "GET", "/").headers["content-security-policy"]
        self.assertIn("script-src 'none'", csp)

    def test_the_real_dist_csp_carries_the_hash_build_py_wrote(self):
        import json
        from server import app
        real = app.make_app(dist=ROOT / "dist", instance_dir=self.instance, origin=ORIGIN)
        written = json.loads((ROOT / "dist" / "csp.json").read_text())["script"]
        self.assertEqual(call(real, "GET", "/").headers["content-security-policy"], expected_csp(written))


class RobotsAndHealth(AppTestCase):
    def test_robots_txt_disallows_everything(self):
        r = call(self.app, "GET", "/robots.txt")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/plain"))
        self.assertEqual(r.body.decode().split(), ["User-agent:", "*", "Disallow:", "/"])

    def test_healthz_is_200_when_the_database_opens(self):
        r = call(self.app, "GET", "/healthz")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_healthz_is_503_when_the_database_cant_be_opened(self):
        from server import app
        broken = app.make_app(dist=self.dist, instance_dir=pathlib.Path(self.tmp.name) / "gone", origin=ORIGIN)
        r = call(broken, "GET", "/healthz")
        self.assertEqual(r.status, 503)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_healthz_is_503_when_the_database_file_has_gone(self):
        from server import db
        db.path(self.instance).unlink()
        self.assertEqual(call(self.app, "GET", "/healthz").status, 503)


JSON = {"Content-Type": "application/json"}


class PostsAndJson(AppTestCase):
    """POST routes: the Origin check, the size cap and the JSON helpers.

    No real POST route exists yet, so these tests add an echo route to a copy of the table.
    """

    def setUp(self):
        super().setUp()
        from server import app
        routes = dict(app.ROUTES)

        @app.route("POST", "/echo", table=routes)
        def echo(req):
            return app.json_response({"got": req.json()})

        self.app = app.make_app(dist=self.dist, instance_dir=self.instance, origin=ORIGIN, routes=routes)

    def post(self, body=b'{"a": 1}', **headers):
        return call(self.app, "POST", "/echo", {**JSON, **headers}, body)

    def test_a_post_from_the_instance_origin_reaches_the_route(self):
        r = self.post(Origin=ORIGIN)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["content-type"], "application/json")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.body, b'{"got": {"a": 1}}')

    def test_a_post_with_no_origin_is_403(self):
        self.assertEqual(self.post().status, 403)

    def test_a_post_from_another_origin_is_403(self):
        for other in ("https://evil.example.com", "http://permit.example.org", "https://permit.example.org:8443",
                      "null", ORIGIN + "/", ORIGIN.upper()):
            with self.subTest(origin=other):
                self.assertEqual(self.post(Origin=other).status, 403)

    def test_the_origin_is_compared_with_the_setting_not_the_host_header(self):
        self.assertEqual(self.post(Origin="https://localhost", Host="localhost").status, 403)

    def test_a_post_to_an_unknown_path_still_needs_the_origin(self):
        self.assertEqual(call(self.app, "POST", "/nope", JSON, b"{}").status, 403)
        self.assertEqual(call(self.app, "POST", "/nope", {**JSON, "Origin": ORIGIN}, b"{}").status, 404)

    def test_a_get_needs_no_origin(self):
        self.assertEqual(call(self.app, "GET", "/").status, 200)

    def test_a_body_over_64_kb_is_413(self):
        big = b'{"a": "' + b"x" * (64 * 1024) + b'"}'
        self.assertEqual(self.post(big, Origin=ORIGIN).status, 413)

    def test_a_body_of_exactly_64_kb_is_accepted(self):
        body = b'{"a": "' + b"x" * (64 * 1024 - 10) + b'"}'
        self.assertEqual(len(body), 64 * 1024 - 1)
        body += b" "
        self.assertEqual(self.post(body, Origin=ORIGIN).status, 200)

    def test_a_claimed_length_over_64_kb_is_413_before_reading(self):
        r = call(self.app, "POST", "/echo", {**JSON, "Origin": ORIGIN, "Content-Length": str(10**9)}, b"{}")
        self.assertEqual(r.status, 413)

    def test_a_body_that_isnt_json_is_400(self):
        r = self.post(b"{not json", Origin=ORIGIN)
        self.assertEqual(r.status, 400)
        self.assertEqual(r.headers["content-type"], "application/json")

    def test_a_body_sent_as_a_form_is_415(self):
        r = self.post(b"a=1", Origin=ORIGIN, **{"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 415)

    def test_a_get_to_a_post_route_is_405(self):
        r = call(self.app, "GET", "/echo")
        self.assertEqual(r.status, 405)
        self.assertEqual(r.headers["allow"], "POST")


class Database(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_migrate_creates_the_database_with_the_meta_table(self):
        from server import db
        self.assertEqual(db.migrate(self.dir), len(db.STEPS))
        self.assertTrue((self.dir / "rrtn.db").is_file())
        conn = db.connect(self.dir)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(db.STEPS))
            conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
            self.assertEqual(conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()[0], "v")
        finally:
            conn.close()

    def test_connections_use_wal_foreign_keys_and_a_busy_timeout(self):
        from server import db
        db.migrate(self.dir)
        conn = db.connect(self.dir)
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertGreater(conn.execute("PRAGMA busy_timeout").fetchone()[0], 0)
        finally:
            conn.close()

    def test_migrating_again_changes_nothing(self):
        from server import db
        db.migrate(self.dir)
        self.assertEqual(db.migrate(self.dir), len(db.STEPS))

    def test_only_steps_not_yet_run_are_run(self):
        from server import db
        db.migrate(self.dir)
        extra = "CREATE TABLE later (id INTEGER PRIMARY KEY);"
        db.STEPS.append(extra)
        try:
            self.assertEqual(db.migrate(self.dir), len(db.STEPS))
        finally:
            db.STEPS.remove(extra)
        conn = db.connect(self.dir)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
        self.assertLessEqual({"meta", "later"}, tables)

    def test_a_failing_step_leaves_the_version_where_it_was(self):
        from server import db
        db.migrate(self.dir)
        bad = "CREATE TABLE half (id INTEGER); THIS IS NOT SQL;"
        db.STEPS.append(bad)
        try:
            with self.assertRaises(Exception):
                db.migrate(self.dir)
        finally:
            db.STEPS.remove(bad)
        conn = db.connect(self.dir)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(db.STEPS))
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'")]
            self.assertEqual(names, [])
        finally:
            conn.close()

    def test_connect_refuses_a_database_that_was_never_made(self):
        import sqlite3
        from server import db
        with self.assertRaises(sqlite3.Error):
            db.connect(self.dir)
        self.assertFalse((self.dir / "rrtn.db").exists())


def run_manage(instance, *args, passwords=()):
    """Run `python -m server.manage <args>` in-process against an Instance folder, typing `passwords`."""
    import contextlib
    import io
    from unittest import mock
    from server import manage
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("getpass.getpass", side_effect=list(passwords)) as prompt, \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = manage.main(list(args), {"RRTN_DIR": str(instance)})
    return code, out.getvalue() + err.getvalue(), prompt.call_count


def cookie_from(r):
    """The __Host-rrtn token a response sets, or None."""
    value = r.headers.get("set-cookie", "")
    if not value.startswith("__Host-rrtn="):
        return None
    return value.split(";")[0].split("=", 1)[1]


def cookie_attributes(r):
    parts = [p.strip() for p in r.headers["set-cookie"].split(";")[1:]]
    return {p.split("=", 1)[0].lower(): (p.split("=", 1)[1] if "=" in p else True) for p in parts}


DAY = 86400
T0 = 1_800_000_000  # a fixed "now" for the fake clock


class AccountsTestCase(AppTestCase):
    """The real routes, with a fake clock the test moves with `self.now`."""

    def setUp(self):
        super().setUp()
        from server import app
        self.now = T0
        self.app = app.make_app(dist=self.dist, instance_dir=self.instance, origin=ORIGIN,
                                clock=lambda: self.now)

    def add_helper(self, name="Randy", password="correct horse"):
        code, out, _ = run_manage(self.instance, "add", name, passwords=[password, password])
        self.assertEqual(code, 0, out)

    def add_learner(self, name="Sam", password="learner pass"):
        from server import auth, db
        conn = db.connect(self.instance)
        try:
            return auth.create_account(conn, "learner", name, password, now=self.now)
        finally:
            conn.close()

    def sign_in(self, name, password):
        import json
        body = json.dumps({"name": name, "password": password}).encode()
        return call(self.app, "POST", "/api/sign-in", {**JSON, "Origin": ORIGIN}, body)

    def get(self, path, token=None):
        headers = {"Cookie": f"__Host-rrtn={token}"} if token else {}
        return call(self.app, "GET", path, headers)


class SigningIn(AccountsTestCase):
    def test_a_helper_made_with_manage_add_can_sign_in_and_is_a_helper(self):
        import json
        self.add_helper("Randy", "correct horse")
        r = self.sign_in("Randy", "correct horse")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(r.body), {"role": "helper", "name": "Randy"})
        me = self.get("/api/me", cookie_from(r))
        self.assertEqual(me.status, 200)
        body = json.loads(me.body)
        self.assertEqual((body["role"], body["name"]), ("helper", "Randy"))
        self.assertIsInstance(body["id"], int)

    def test_a_learner_can_sign_in_and_is_a_learner(self):
        import json
        self.add_learner("Sam", "learner pass")
        r = self.sign_in("Sam", "learner pass")
        self.assertEqual((r.status, json.loads(r.body)), (200, {"role": "learner", "name": "Sam"}))
        self.assertEqual(json.loads(self.get("/api/me", cookie_from(r)).body)["role"], "learner")

    def test_an_unknown_name_and_a_wrong_password_get_the_same_401(self):
        self.add_helper("Randy", "correct horse")
        unknown = self.sign_in("Nobody", "correct horse")
        wrong = self.sign_in("Randy", "wrong horse!")
        for r in (unknown, wrong):
            self.assertEqual(r.status, 401)
            self.assertEqual(r.body, b'{"error": "mismatch"}')
            self.assertEqual(r.headers["content-type"], "application/json")
            self.assertIsNone(cookie_from(r))

    def test_names_match_ignoring_capitals_and_outer_spaces(self):
        self.add_helper("Randy Willis", "correct horse")
        for typed in ("randy willis", "  RANDY WILLIS ", "Randy Willis\t"):
            with self.subTest(typed=typed):
                self.assertEqual(self.sign_in(typed, "correct horse").status, 200)
        self.assertEqual(self.sign_in("Randy  Willis", "correct horse").status, 401)

    def test_passwords_match_exactly(self):
        self.add_helper("Randy", "correct horse")
        for typed in ("Correct horse", "correct horse ", " correct horse", "correct hors"):
            with self.subTest(typed=typed):
                self.assertEqual(self.sign_in("Randy", typed).status, 401)

    def test_a_name_over_64_or_a_password_over_128_is_a_mismatch(self):
        self.add_helper("Randy", "correct horse")
        self.assertEqual(self.sign_in("R" * 65, "correct horse").body, b'{"error": "mismatch"}')
        self.assertEqual(self.sign_in("Randy", "x" * 129).body, b'{"error": "mismatch"}')

    def test_a_sign_in_without_a_name_or_password_is_400(self):
        import json
        for body in ({}, {"name": "Randy"}, {"name": "Randy", "password": 12345678}, ["Randy", "pw"]):
            with self.subTest(body=body):
                r = call(self.app, "POST", "/api/sign-in", {**JSON, "Origin": ORIGIN}, json.dumps(body).encode())
                self.assertEqual(r.status, 400)

    def test_sign_in_needs_the_instance_origin(self):
        self.add_helper("Randy", "correct horse")
        body = b'{"name": "Randy", "password": "correct horse"}'
        r = call(self.app, "POST", "/api/sign-in", {**JSON, "Origin": "https://evil.example.com"}, body)
        self.assertEqual(r.status, 403)
        self.assertIsNone(cookie_from(r))

    def test_account_answers_are_never_cached(self):
        self.add_helper("Randy", "correct horse")
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        for r in (self.sign_in("Randy", "correct horse"), self.sign_in("Randy", "nope nope"),
                  self.get("/api/me", token), self.get("/api/me")):
            self.assertEqual(r.headers["cache-control"], "no-store")


class SessionCookie(AccountsTestCase):
    def test_the_cookie_is_host_prefixed_http_only_secure_and_lax(self):
        self.add_helper("Randy", "correct horse")
        r = self.sign_in("Randy", "correct horse")
        self.assertTrue(r.headers["set-cookie"].startswith("__Host-rrtn="))
        attrs = cookie_attributes(r)
        self.assertIs(attrs["httponly"], True)
        self.assertIs(attrs["secure"], True)
        self.assertEqual(attrs["samesite"], "Lax")
        self.assertEqual(attrs["path"], "/")
        self.assertNotIn("domain", attrs)

    def test_max_age_is_400_days_for_a_learner_and_30_days_for_a_helper(self):
        self.add_helper("Randy", "correct horse")
        self.add_learner("Sam", "learner pass")
        self.assertEqual(cookie_attributes(self.sign_in("Sam", "learner pass"))["max-age"], "34560000")
        self.assertEqual(cookie_attributes(self.sign_in("Randy", "correct horse"))["max-age"], "2592000")

    def test_each_sign_in_gets_a_new_long_token(self):
        self.add_helper("Randy", "correct horse")
        a = cookie_from(self.sign_in("Randy", "correct horse"))
        b = cookie_from(self.sign_in("Randy", "correct horse"))
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 43)  # 32 random bytes in base64url


class SessionLifetime(AccountsTestCase):
    def setUp(self):
        super().setUp()
        self.add_helper("Randy", "correct horse")
        self.add_learner("Sam", "learner pass")

    def session_count(self):
        from server import db
        conn = db.connect(self.instance)
        try:
            return conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        finally:
            conn.close()

    def test_signed_out_and_unknown_tokens_get_401_signed_out(self):
        for token in (None, "not-a-real-token"):
            with self.subTest(token=token):
                r = self.get("/api/me", token)
                self.assertEqual((r.status, r.body), (401, b'{"error": "signed-out"}'))

    def test_a_helper_session_ends_after_30_days_and_is_deleted(self):
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        self.now = T0 + 29 * DAY
        self.assertEqual(self.get("/api/me", token).status, 200)  # moves the expiry to now + 30 days
        self.now += 30 * DAY - 1
        self.assertEqual(self.get("/api/me", token).status, 200)  # and again
        self.now += 30 * DAY
        r = self.get("/api/me", token)
        self.assertEqual(r.status, 401)
        self.assertEqual(cookie_attributes(r)["max-age"], "0")
        self.assertEqual(self.session_count(), 0)

    def test_a_session_not_used_for_its_whole_lifetime_ends(self):
        helper = cookie_from(self.sign_in("Randy", "correct horse"))
        learner = cookie_from(self.sign_in("Sam", "learner pass"))
        unused_learner = cookie_from(self.sign_in("Sam", "learner pass"))
        self.now = T0 + 30 * DAY
        self.assertEqual(self.get("/api/me", helper).status, 401)
        self.assertEqual(self.get("/api/me", learner).status, 200)
        self.now = T0 + 400 * DAY
        self.assertEqual(self.get("/api/me", unused_learner).status, 401)

    def test_the_expiry_moves_forward_at_most_once_a_day(self):
        token = cookie_from(self.sign_in("Sam", "learner pass"))
        self.now = T0 + DAY - 1
        self.assertNotIn("set-cookie", self.get("/api/me", token).headers)
        self.now = T0 + DAY
        renewed = self.get("/api/me", token)
        self.assertEqual(cookie_from(renewed), token)
        self.assertEqual(cookie_attributes(renewed)["max-age"], "34560000")
        self.now = T0 + DAY + 60
        self.assertNotIn("set-cookie", self.get("/api/me", token).headers)
        # The new expiry counts from the day it moved, not from sign-in.
        self.now = T0 + DAY + 400 * DAY - 1
        self.assertEqual(self.get("/api/me", token).status, 200)

    def test_a_session_used_only_within_a_day_keeps_its_first_expiry(self):
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        for hours in (1, 5, 23):
            self.now = T0 + hours * 3600
            self.assertEqual(self.get("/api/me", token).status, 200)
        self.now = T0 + 30 * DAY
        self.assertEqual(self.get("/api/me", token).status, 401)

    def test_sign_out_ends_that_session_and_clears_the_cookie(self):
        token = cookie_from(self.sign_in("Sam", "learner pass"))
        other = cookie_from(self.sign_in("Sam", "learner pass"))
        r = call(self.app, "POST", "/api/sign-out", {"Origin": ORIGIN, "Cookie": f"__Host-rrtn={token}"})
        self.assertEqual((r.status, r.body), (204, b""))
        self.assertTrue(r.headers["set-cookie"].startswith("__Host-rrtn=;"))
        self.assertEqual(cookie_attributes(r)["max-age"], "0")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(self.get("/api/me", token).status, 401)
        self.assertEqual(self.get("/api/me", other).status, 200)

    def test_sign_out_when_signed_out_still_answers_204(self):
        self.assertEqual(call(self.app, "POST", "/api/sign-out", {"Origin": ORIGIN}).status, 204)

    def test_sign_out_needs_the_instance_origin(self):
        token = cookie_from(self.sign_in("Sam", "learner pass"))
        r = call(self.app, "POST", "/api/sign-out", {"Cookie": f"__Host-rrtn={token}"})
        self.assertEqual(r.status, 403)
        self.assertEqual(self.get("/api/me", token).status, 200)

    def test_deleting_an_account_deletes_its_sessions(self):
        from server import auth, db
        token = cookie_from(self.sign_in("Sam", "learner pass"))
        self.sign_in("Randy", "correct horse")
        conn = db.connect(self.instance)
        try:
            auth.delete_account(conn, auth.find_account(conn, "Sam")["id"])
        finally:
            conn.close()
        self.assertEqual(self.get("/api/me", token).status, 401)
        self.assertEqual(self.session_count(), 1)


class QuestionsNeedSignIn(AccountsTestCase):
    def test_questions_are_401_signed_out_and_200_for_either_role(self):
        self.add_helper("Randy", "correct horse")
        self.add_learner("Sam", "learner pass")
        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                r = call(self.app, method, "/questions.json")
                self.assertEqual(r.status, 401)
        self.assertEqual(call(self.app, "GET", "/questions.json").body, b'{"error": "signed-out"}')
        for name, password in (("Randy", "correct horse"), ("Sam", "learner pass")):
            with self.subTest(name=name):
                r = self.get("/questions.json", cookie_from(self.sign_in(name, password)))
                self.assertEqual((r.status, r.body), (200, QUESTIONS))

    def test_an_ended_session_cannot_fetch_questions(self):
        self.add_helper("Randy", "correct horse")
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        self.now = T0 + 30 * DAY
        self.assertEqual(self.get("/questions.json", token).status, 401)

    def test_the_sign_in_page_and_its_files_stay_open(self):
        (self.dist / "fonts").mkdir()
        (self.dist / "fonts" / "body.woff2").write_bytes(b"font")
        (self.dist / "app.webmanifest").write_text("{}")
        for path in ("/", "/index.html", "/robots.txt", "/healthz", "/fonts/body.woff2", "/app.webmanifest",
                     "/csp.json"):
            with self.subTest(path=path):
                self.assertEqual(call(self.app, "GET", path).status, 200)


class WhatTheDatabaseHolds(AccountsTestCase):
    def all_values(self):
        from server import db
        conn = db.connect(self.instance)
        try:
            return "\n".join(conn.iterdump())
        finally:
            conn.close()

    def test_no_raw_token_and_no_raw_password_is_stored(self):
        self.add_helper("Randy", "correct horse")
        self.add_learner("Sam", "learner pass")
        tokens = [cookie_from(self.sign_in("Randy", "correct horse")),
                  cookie_from(self.sign_in("Sam", "learner pass"))]
        dump = self.all_values()
        self.assertIn("Randy", dump)
        for secret in ["correct horse", "learner pass", *tokens]:
            self.assertNotIn(secret, dump)
        for f in self.instance.iterdir():
            for secret in [b"correct horse", b"learner pass", *(t.encode() for t in tokens)]:
                self.assertNotIn(secret, f.read_bytes(), f.name)

    def test_each_hash_carries_its_scrypt_settings(self):
        self.add_helper("Randy", "correct horse")
        dump = self.all_values()
        self.assertIn("scrypt$32768$8$3$", dump)

    def test_a_hash_made_with_older_settings_is_redone_at_sign_in(self):
        from server import auth, db
        conn = db.connect(self.instance)
        try:
            conn.execute("INSERT INTO accounts (role, name, name_key, password_hash, created_at) "
                         "VALUES ('learner', 'Old', 'old', ?, ?)", (auth.hash_password("old password", n=2 ** 12), T0))
        finally:
            conn.close()
        self.assertNotIn("scrypt$32768$", self.all_values())
        self.assertEqual(self.sign_in("Old", "old password").status, 200)
        self.assertIn("scrypt$32768$8$3$", self.all_values())
        self.assertEqual(self.sign_in("Old", "old password").status, 200)


class NameAndPasswordRules(AccountsTestCase):
    def create(self, name, password="a good password", role="learner"):
        from server import auth, db
        conn = db.connect(self.instance)
        try:
            return auth.create_account(conn, role, name, password, now=self.now)
        finally:
            conn.close()

    def assert_refused(self, code, name, password="a good password"):
        from server import auth
        with self.assertRaises(auth.AccountError) as e:
            self.create(name, password)
        self.assertEqual(e.exception.code, code)

    def test_passwords_must_be_8_to_128_characters(self):
        self.assert_refused("password-length", "Seven", "x" * 7)
        self.assert_refused("password-length", "Long", "x" * 129)
        self.create("Eight", "x" * 8)
        self.create("Max", "x" * 128)

    def test_names_must_be_1_to_64_characters_after_trimming(self):
        self.assert_refused("name-length", "x" * 65)
        self.assert_refused("name-length", "")
        self.assert_refused("name-length", "   ")
        self.create("y" * 64)
        self.create("  " + "z" * 64 + "  ")

    def test_a_name_is_stored_trimmed(self):
        self.create("  Sam Jones  ", "learner pass")
        import json
        r = self.sign_in("sam jones", "learner pass")
        self.assertEqual(json.loads(r.body)["name"], "Sam Jones")

    def test_names_are_unique_ignoring_capitals_across_both_roles(self):
        self.create("Sam")
        self.assert_refused("name-taken", "sam")
        self.assert_refused("name-taken", " SAM ")
        from server import auth
        with self.assertRaises(auth.AccountError):
            self.create("SAM", role="helper")

    def test_a_new_password_follows_the_same_rules(self):
        from server import auth, db
        account_id = self.create("Sam")
        conn = db.connect(self.instance)
        try:
            for bad in ("x" * 7, "x" * 129):
                with self.assertRaises(auth.AccountError):
                    auth.set_password(conn, account_id, bad)
        finally:
            conn.close()


class Roles(AccountsTestCase):
    """auth.require, which later routes use to let in only one role."""

    def setUp(self):
        super().setUp()
        from server import app, auth
        routes = dict(app.ROUTES)

        @app.route("GET", "/helpers-only", table=routes)
        @auth.require("helper")
        def helpers_only(req):
            return app.json_response({"hello": req.account["name"]})

        self.app = app.make_app(dist=self.dist, instance_dir=self.instance, origin=ORIGIN, routes=routes,
                                clock=lambda: self.now)
        self.add_helper("Randy", "correct horse")
        self.add_learner("Sam", "learner pass")

    def test_the_role_gets_in_the_other_role_gets_403_and_signed_out_gets_401(self):
        helper = self.get("/helpers-only", cookie_from(self.sign_in("Randy", "correct horse")))
        self.assertEqual((helper.status, helper.body), (200, b'{"hello": "Randy"}'))
        learner = self.get("/helpers-only", cookie_from(self.sign_in("Sam", "learner pass")))
        self.assertEqual((learner.status, learner.body), (403, b'{"error": "wrong-role"}'))
        self.assertEqual(self.get("/helpers-only").status, 401)


class HelperCommand(AccountsTestCase):
    def manage(self, *args, passwords=()):
        return run_manage(self.instance, *args, passwords=passwords)

    def test_add_asks_for_the_password_twice_and_makes_a_helper(self):
        code, out, prompts = self.manage("add", "Randy", passwords=["correct horse", "correct horse"])
        self.assertEqual((code, prompts), (0, 2))
        self.assertIn("Randy", out)
        self.assertEqual(self.sign_in("randy", "correct horse").status, 200)

    def test_add_works_on_an_instance_folder_that_has_no_database_yet(self):
        fresh = pathlib.Path(self.tmp.name) / "fresh"
        fresh.mkdir()
        code, _, _ = run_manage(fresh, "add", "Randy", passwords=["correct horse"] * 2)
        self.assertEqual(code, 0)
        self.assertTrue((fresh / "rrtn.db").is_file())

    def test_add_refuses_two_different_passwords(self):
        code, out, _ = self.manage("add", "Randy", passwords=["correct horse", "correct house"])
        self.assertNotEqual(code, 0)
        self.assertIn("not the same", out)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 401)

    def test_add_refuses_a_password_of_7_or_129_characters(self):
        for bad in ("x" * 7, "x" * 129):
            with self.subTest(length=len(bad)):
                code, out, _ = self.manage("add", "Randy", passwords=[bad, bad])
                self.assertNotEqual(code, 0)
                self.assertIn("8 to 128", out)
        self.assertEqual(self.sign_in("Randy", "x" * 7).status, 401)

    def test_add_refuses_a_65_character_name_or_a_name_taken_ignoring_capitals(self):
        code, out, prompts = self.manage("add", "R" * 65, passwords=["correct horse"] * 2)
        self.assertNotEqual(code, 0)
        self.assertIn("1 to 64", out)
        self.add_learner("Sam", "learner pass")
        code, out, prompts = self.manage("add", "SAM", passwords=["correct horse"] * 2)
        self.assertNotEqual(code, 0)
        self.assertIn("taken", out)
        self.assertEqual(prompts, 0)  # refused before asking for a password

    def test_a_password_is_never_taken_as_an_argument(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
            self.manage("add", "Randy", "correct horse")
        self.assertNotEqual(e.exception.code, 0)

    def test_password_sets_a_new_one_and_ends_that_helpers_sessions(self):
        self.add_helper("Randy", "correct horse")
        self.add_helper("Alex", "another helper")
        randy = [cookie_from(self.sign_in("Randy", "correct horse")) for _ in range(2)]
        alex = cookie_from(self.sign_in("Alex", "another helper"))
        code, out, prompts = self.manage("password", "randy", passwords=["battery staple", "battery staple"])
        self.assertEqual((code, prompts), (0, 2))
        for token in randy:
            self.assertEqual(self.get("/api/me", token).status, 401)
        self.assertEqual(self.get("/api/me", alex).status, 200)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 401)
        self.assertEqual(self.sign_in("Randy", "battery staple").status, 200)

    def test_password_refuses_a_bad_new_password_and_keeps_the_old_one(self):
        self.add_helper("Randy", "correct horse")
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        code, _, _ = self.manage("password", "Randy", passwords=["short", "short"])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.get("/api/me", token).status, 200)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 200)

    def test_remove_deletes_the_helper_and_their_sessions(self):
        self.add_helper("Randy", "correct horse")
        token = cookie_from(self.sign_in("Randy", "correct horse"))
        code, out, prompts = self.manage("remove", "Randy")
        self.assertEqual((code, prompts), (0, 0))
        self.assertEqual(self.get("/api/me", token).status, 401)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 401)

    def test_the_command_never_touches_a_learner(self):
        self.add_learner("Sam", "learner pass")
        token = cookie_from(self.sign_in("Sam", "learner pass"))
        for args in (("password", "Sam"), ("remove", "sam")):
            with self.subTest(args=args):
                code, out, prompts = self.manage(*args, passwords=["new password"] * 2)
                self.assertNotEqual(code, 0)
                self.assertIn("Learner", out)
                self.assertEqual(prompts, 0)
        self.assertEqual(self.get("/api/me", token).status, 200)
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 200)

    def test_an_unknown_name_is_refused(self):
        for command in ("password", "remove"):
            with self.subTest(command=command):
                code, out, _ = self.manage(command, "Nobody", passwords=["new password"] * 2)
                self.assertNotEqual(code, 0)
                self.assertIn("no Helper", out)


NO_HELPER_LINE = "No Helper account exists. Run: python -m server.manage add <name>"


class NoHelperYet(unittest.TestCase):
    def test_the_log_names_the_command_only_while_no_helper_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RunningServer(tmp) as srv:
                pass
            self.assertEqual(srv.output.count(NO_HELPER_LINE), 1, srv.output)
            run_manage(tmp, "add", "Randy", passwords=["correct horse"] * 2)
            with RunningServer(tmp) as srv:
                pass
            self.assertNotIn("No Helper", srv.output)


if __name__ == "__main__":
    unittest.main()
