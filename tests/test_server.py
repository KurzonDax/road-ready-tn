"""Tests for the server: startup checks, the WSGI app, static files and headers,
accounts, sign-in sessions, the Helper command, Learner records, and the
Helper's routes for managing Learners.

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

    def test_password_stdin_reads_one_line_for_tests_and_asks_nothing(self):
        import contextlib
        import io
        from unittest import mock
        from server import manage
        with mock.patch("sys.stdin", io.StringIO("correct horse\n")), \
                mock.patch("getpass.getpass", side_effect=AssertionError("prompted")), \
                contextlib.redirect_stdout(io.StringIO()):
            code = manage.main(["add", "Randy", "--password-stdin"], {"RRTN_DIR": str(self.instance)})
        self.assertEqual(code, 0)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 200)

    def test_password_stdin_still_checks_the_length(self):
        import contextlib
        import io
        from unittest import mock
        from server import manage
        err = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("short\n")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = manage.main(["add", "Randy", "--password-stdin"], {"RRTN_DIR": str(self.instance)})
        self.assertNotEqual(code, 0)
        self.assertIn("8 to 128", err.getvalue())

    def test_the_command_runs_as_python_m_server_manage(self):
        # A fresh interpreter imports server.auth before server.app, unlike the tests above.
        env = {k: v for k, v in os.environ.items() if not k.startswith("RRTN_")}
        env["RRTN_DIR"] = str(self.instance)
        done = subprocess.run([sys.executable, "-m", "server.manage", "add", "Randy", "--password-stdin"],
                              cwd=ROOT, env=env, input="correct horse\n", capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.sign_in("Randy", "correct horse").status, 200)

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


def a_set(id="set-record-000001", set_id="set-000001", type="day", section=1, answers=None, **extra):
    """A finished-Set record that passes every shape rule. Tests change one field to break one rule."""
    record = {
        "id": id, "kind": "set", "reset": None, "at": "2026-10-16T14:05:00.000Z",
        "data": {
            "set_id": set_id, "type": type, "section": section, "started_at": "2026-10-16T14:00:00.000Z",
            "answers": answers if answers is not None else [
                {"q": "q-001", "chosen": "b", "right": True, "at": "2026-10-16T14:01:00.000Z"},
            ],
        },
    }
    record.update(extra)
    return record


def an_import(id="import-record-0001", state=None):
    return {"id": id, "kind": "imported", "reset": None, "at": "2026-10-16T13:00:00Z",
            "data": {"state": state if state is not None else {"day": 3, "scores": {}}}}


class RecordsTestCase(AccountsTestCase):
    """A Learner's records and unfinished Set, through the routes the page uses."""

    def setUp(self):
        super().setUp()
        self.sam = self.learner_token("Sam")

    def learner_token(self, name):
        self.add_learner(name, "learner pass")
        return cookie_from(self.sign_in(name, "learner pass"))

    def post(self, path, value, token=None):
        import json
        body = json.dumps(value).encode()
        return call(self.app, "POST", path,
                    {**JSON, "Origin": ORIGIN, "Cookie": f"__Host-rrtn={token or self.sam}"}, body)

    def send(self, *records, token=None):
        return self.post("/api/records", {"records": list(records)}, token)

    def save_unfinished(self, value, token=None):
        return self.post("/api/unfinished", {"set": value}, token)

    def fetch(self, token=None):
        import json
        r = self.get("/api/records", token or self.sam)
        self.assertEqual(r.status, 200, r.body)
        return json.loads(r.body)

    def ids(self, token=None):
        return [rec["id"] for rec in self.fetch(token)["records"]]

    def assert_bad_record(self, r, index=0):
        import json
        self.assertEqual(r.status, 400, r.body)
        self.assertEqual(json.loads(r.body), {"error": "bad-record", "index": index})


class RecordRoutesAreForLearners(RecordsTestCase):
    def test_a_new_learner_has_no_records_and_no_unfinished_set(self):
        self.assertEqual(self.fetch(), {"records": [], "unfinished": None})

    def test_a_helper_gets_403_and_signed_out_gets_401_on_every_route(self):
        import json
        self.add_helper("Randy", "correct horse")
        helper = cookie_from(self.sign_in("Randy", "correct horse"))
        for token, status, error in ((helper, 403, "wrong-role"), ("not-a-session", 401, "signed-out")):
            answers = [self.get("/api/records", token), self.send(a_set(), token=token),
                       self.save_unfinished({"set_id": "x"}, token=token)]
            for r in answers:
                self.assertEqual((r.status, json.loads(r.body)), (status, {"error": error}))
        self.assertEqual(self.fetch(), {"records": [], "unfinished": None})

    def test_record_answers_are_never_cached(self):
        for r in (self.get("/api/records", self.sam), self.send(a_set()), self.save_unfinished(None)):
            self.assertEqual(r.headers["cache-control"], "no-store")


class StoringRecords(RecordsTestCase):
    def test_a_finished_set_is_stored_and_handed_back_with_seq_and_received_at(self):
        import json
        r = self.send(a_set())
        self.assertEqual((r.status, json.loads(r.body)), (200, {"stored": 1, "skipped": 0}))
        [stored] = self.fetch()["records"]
        self.assertEqual(stored, {**a_set(), "seq": stored["seq"], "received_at": "2027-01-15T08:00:00Z"})
        self.assertIsInstance(stored["seq"], int)

    def test_a_finished_set_posted_twice_is_stored_once_and_the_second_is_skipped(self):
        import json
        self.send(a_set())
        self.now += 60
        r = self.send(a_set())
        self.assertEqual((r.status, json.loads(r.body)), (200, {"stored": 0, "skipped": 1}))
        [stored] = self.fetch()["records"]
        self.assertEqual(stored["received_at"], "2027-01-15T08:00:00Z")

    def test_the_same_id_twice_in_one_request_counts_once(self):
        import json
        r = self.send(a_set(), a_set())
        self.assertEqual(json.loads(r.body), {"stored": 1, "skipped": 1})
        self.assertEqual(len(self.fetch()["records"]), 1)

    def test_records_come_back_in_arrival_order_not_by_their_times(self):
        later = a_set(id="set-record-later01", at="2026-10-17T09:00:00Z")
        earlier = a_set(id="set-record-earlier", at="2026-10-01T09:00:00Z")
        self.send(later)
        self.send(earlier, an_import())
        records = self.fetch()["records"]
        self.assertEqual([rec["id"] for rec in records],
                         ["set-record-later01", "set-record-earlier", "import-record-0001"])
        seqs = [rec["seq"] for rec in records]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 3)

    def test_up_to_100_records_go_in_one_request_and_101_is_refused(self):
        import json
        many = [a_set(id=f"set-record-{n:06d}") for n in range(101)]
        r = self.send(*many)
        self.assertEqual(r.status, 400)
        self.assertEqual(self.ids(), [])
        r = self.send(*many[:100])
        self.assertEqual(json.loads(r.body), {"stored": 100, "skipped": 0})

    def test_an_empty_list_stores_nothing(self):
        import json
        self.assertEqual(json.loads(self.send().body), {"stored": 0, "skipped": 0})

    def test_a_body_without_a_list_of_records_is_400(self):
        for body in ({}, {"records": {}}, [], {"records": "x"}, None):
            self.assertEqual(self.post("/api/records", body).status, 400, body)

    def test_one_bad_record_refuses_the_whole_request_and_names_its_index(self):
        bad = a_set(id="short")
        r = self.send(a_set(id="set-record-good01"), an_import(), bad, a_set(id="set-record-good02"))
        self.assert_bad_record(r, index=2)
        self.assertEqual(self.ids(), [])

    def test_a_second_imported_record_is_skipped(self):
        import json
        self.send(an_import(id="import-record-0001"))
        r = self.send(an_import(id="import-record-0002"), a_set())
        self.assertEqual(json.loads(r.body), {"stored": 1, "skipped": 1})
        self.assertEqual(self.ids(), ["import-record-0001", "set-record-000001"])

    def test_two_imported_records_in_one_request_keep_only_the_first(self):
        import json
        r = self.send(an_import(id="import-record-0001"), an_import(id="import-record-0002"))
        self.assertEqual(json.loads(r.body), {"stored": 1, "skipped": 1})
        self.assertEqual(self.ids(), ["import-record-0001"])

    def test_a_learner_cannot_store_a_reset_or_a_move(self):
        reset = {"id": "reset-record-00001", "kind": "reset", "reset": None,
                 "at": "2026-10-16T14:05:00Z", "data": {}}
        move = {"id": "move-record-000001", "kind": "move", "reset": None,
                "at": "2026-10-16T14:05:00Z", "data": {"to": 5}}
        for record in (reset, move):
            self.assert_bad_record(self.send(record))
            self.assert_bad_record(self.send(a_set(), record), index=1)
        self.assertEqual(self.ids(), [])


def changed(record, **fields):
    """A copy of a record with fields set; a value of DROP removes the field. `data__x` reaches into data."""
    import copy
    record = copy.deepcopy(record)
    for key, value in fields.items():
        target, name = (record["data"], key[6:]) if key.startswith("data__") else (record, key)
        if value is DROP:
            del target[name]
        else:
            target[name] = value
    return record


DROP = object()
AN_ANSWER = {"q": "q-001", "chosen": "b", "right": True, "at": "2026-10-16T14:01:00.000Z"}


def answers_with(**fields):
    return [changed(AN_ANSWER, **fields)]


class RecordShape(RecordsTestCase):
    """Each rule in the record table, accepted and refused. A bad record is 400 bad-record."""

    def assert_accepted(self, *records):
        import json
        for n, record in enumerate(records):
            with self.subTest(record=record):
                r = self.send(changed(record, id=f"accepted-record-{n:04d}"))
                self.assertEqual((r.status, json.loads(r.body)), (200, {"stored": 1, "skipped": 0}))

    def assert_refused(self, *records):
        for record in records:
            with self.subTest(record=record):
                self.assert_bad_record(self.send(record))
        self.assertEqual(self.ids(), [])

    def test_a_record_is_an_object(self):
        self.assert_refused([], "set", None, 7)

    def test_id_is_16_to_64_characters_from_letters_digits_underscore_and_dash(self):
        self.assert_refused(changed(a_set(), id=DROP), changed(a_set(), id=None), changed(a_set(), id=12345678901234567),
                            changed(a_set(), id="a" * 15), changed(a_set(), id="a" * 65),
                            changed(a_set(), id="has a space in it!"), changed(a_set(), id="dots.are.not.allowed"),
                            changed(a_set(), id="accented-letter-é"), changed(a_set(), id="slash/is/not/allowed"))
        import json
        for good in ("a" * 16, "Z" * 64, "AZaz09_-AZaz09_-"):
            r = self.send(changed(a_set(), id=good))
            self.assertEqual(json.loads(r.body), {"stored": 1, "skipped": 0}, good)

    def test_kind_is_set_reset_move_or_imported(self):
        self.assert_refused(changed(a_set(), kind=DROP), changed(a_set(), kind="sets"),
                            changed(a_set(), kind="SET"), changed(a_set(), kind=None))

    def test_reset_is_a_record_id_or_null(self):
        self.assert_refused(changed(a_set(), reset=DROP), changed(a_set(), reset=7), changed(a_set(), reset=""),
                            changed(a_set(), reset="short"), changed(a_set(), reset={}))
        self.assert_accepted(changed(a_set(), reset="reset-record-00001"), changed(a_set(), reset=None))

    def test_at_is_an_iso_8601_utc_time(self):
        self.assert_refused(*(changed(a_set(), at=value) for value in (
            DROP, None, 1760623500, "", "yesterday", "2026-10-16", "2026-10-16T14:05:00",
            "2026-10-16T14:05:00+02:00", "2026-10-16 14:05:00Z", "2026-13-01T00:00:00Z",
            "2026-02-30T00:00:00Z", "2026-10-16T25:00:00Z", "2026-10-16T14:05:00.Z")))
        self.assert_accepted(changed(a_set(), at="2026-10-16T14:05:00Z"),
                             changed(a_set(), at="2026-10-16T14:05:00.123Z"),
                             changed(a_set(), at="2026-10-16T14:05:00+00:00"))

    def test_data_is_an_object(self):
        self.assert_refused(changed(a_set(), data=DROP), changed(a_set(), data=None),
                            changed(a_set(), data=[]), changed(a_set(), data="x"))

    def test_a_record_has_no_other_fields_so_seq_and_received_at_stay_the_servers(self):
        self.assert_refused(changed(a_set(), seq=1), changed(a_set(), received_at="2026-10-16T14:05:00Z"),
                            changed(a_set(), extra=True))

    def test_a_set_has_a_string_set_id(self):
        self.assert_refused(changed(a_set(), data__set_id=DROP), changed(a_set(), data__set_id=7),
                            changed(a_set(), data__set_id=None), changed(a_set(), data__set_id=""))

    def test_a_set_type_is_day_redo_review_or_test(self):
        self.assert_refused(changed(a_set(), data__type=DROP), changed(a_set(), data__type="practice"),
                            changed(a_set(), data__type="Day"), changed(a_set(), data__type=None))
        self.assert_accepted(a_set(type="day", section=1), a_set(type="redo", section=12),
                             a_set(type="review", section=None), a_set(type="test", section=None))

    def test_a_section_is_1_to_12_for_day_and_redo_and_null_otherwise(self):
        self.assert_refused(*(a_set(type=t, section=s) for t in ("day", "redo")
                              for s in (None, 0, 13, "3", 1.0, 1.5, True)),
                            changed(a_set(), data__section=DROP),
                            a_set(type="review", section=3), a_set(type="test", section=1))
        self.assert_accepted(*(a_set(type=t, section=s) for t in ("day", "redo") for s in (1, 6, 12)))

    def test_started_at_is_an_iso_8601_time(self):
        self.assert_refused(changed(a_set(), data__started_at=DROP), changed(a_set(), data__started_at=None),
                            changed(a_set(), data__started_at="this morning"),
                            changed(a_set(), data__started_at="2026-10-16T14:00:00"))

    def test_answers_are_a_list_of_1_to_50(self):
        self.assert_refused(changed(a_set(), data__answers=DROP), a_set(answers=[]),
                            a_set(answers=[AN_ANSWER] * 51), changed(a_set(), data__answers=AN_ANSWER),
                            changed(a_set(), data__answers=None))
        self.assert_accepted(a_set(answers=[AN_ANSWER] * 50), a_set(answers=[AN_ANSWER] * 30),
                             a_set(answers=[AN_ANSWER] * 10))

    def test_each_answer_has_a_string_q_and_chosen_a_boolean_right_and_an_iso_at(self):
        self.assert_refused(
            a_set(answers=["q-001"]), a_set(answers=[None]),
            a_set(answers=answers_with(q=DROP)), a_set(answers=answers_with(q=1)),
            a_set(answers=answers_with(chosen=DROP)), a_set(answers=answers_with(chosen=2)),
            a_set(answers=answers_with(right=DROP)), a_set(answers=answers_with(right=1)),
            a_set(answers=answers_with(right="true")), a_set(answers=answers_with(at=DROP)),
            a_set(answers=answers_with(at="14:01")), a_set(answers=answers_with(extra=1)),
            a_set(answers=[AN_ANSWER, changed(AN_ANSWER, right=None)]))
        self.assert_accepted(a_set(answers=answers_with(right=False, chosen="")))

    def test_set_data_has_no_other_fields(self):
        self.assert_refused(changed(a_set(), data__score=10))

    def test_an_imported_record_holds_a_state_object(self):
        self.assert_refused(changed(an_import(), data__state=DROP), changed(an_import(), data__state=None),
                            changed(an_import(), data__state=[]), changed(an_import(), data__state="{}"),
                            changed(an_import(), data__other=1))
        self.assert_accepted(an_import(state={"day": 5, "scores": {"1": 9}, "last": [], "tests": []}))


class HelperRecordShape(AccountsTestCase):
    """Reset and Move records go through the same store a Helper API will call (store_records)."""

    def store(self, *records):
        from server import db, records as rec
        conn = db.connect(self.instance)
        try:
            return rec.store_records(conn, self.learner, list(records), self.now, kinds=rec.KINDS)
        finally:
            conn.close()

    def setUp(self):
        super().setUp()
        self.learner = self.add_learner()

    def reset(self, **fields):
        return changed({"id": "reset-record-00001", "kind": "reset", "reset": None,
                        "at": "2026-10-16T14:05:00Z", "data": {}}, **fields)

    def move(self, to, **fields):
        return changed({"id": "move-record-" + str(to).rjust(6, "0"), "kind": "move",
                        "reset": None, "at": "2026-10-16T14:05:00Z", "data": {"to": to}}, **fields)

    def assert_refused(self, *records):
        from server import records as rec
        for record in records:
            with self.subTest(record=record), self.assertRaises(rec.RecordError):
                self.store(record)

    def test_a_reset_has_empty_data(self):
        self.assert_refused(self.reset(data={"to": 1}), self.reset(data=None), self.reset(data=[]))
        self.assertEqual(self.store(self.reset()), (1, 0))

    def test_a_move_goes_to_1_to_13(self):
        self.assert_refused(*(self.move(to) for to in (0, 14, "5", 5.0, True, None)),
                            self.move(5, data={}), self.move(5, data__extra=1))
        self.assertEqual(self.store(self.move(1), self.move(12), self.move(13)), (3, 0))


class UnfinishedSet(RecordsTestCase):
    PAGE_SHAPE = {"set_id": "set-000001", "kind": "day", "dayNum": 3, "i": 2, "answered": 2,
                  "items": [{"id": "q-001", "options": ["b", "a", "c"], "chosen": "b"}]}

    def unfinished(self, token=None):
        return self.fetch(token)["unfinished"]

    def test_it_is_handed_back_exactly_as_sent(self):
        r = self.save_unfinished(self.PAGE_SHAPE)
        self.assertEqual(r.status, 204)
        self.assertEqual(self.unfinished(), self.PAGE_SHAPE)

    def test_the_newest_one_wins(self):
        self.save_unfinished({"set_id": "set-000001", "i": 1})
        self.now += 60
        self.save_unfinished({"set_id": "set-000001", "i": 2})
        self.save_unfinished({"set_id": "set-000002", "i": 0})
        self.assertEqual(self.unfinished(), {"set_id": "set-000002", "i": 0})

    def test_null_clears_it(self):
        self.save_unfinished(self.PAGE_SHAPE)
        self.assertEqual(self.save_unfinished(None).status, 204)
        self.assertIsNone(self.unfinished())

    def test_it_must_be_an_object_with_a_string_set_id_or_null(self):
        import json
        self.save_unfinished(self.PAGE_SHAPE)
        for body in ({}, {"set": []}, {"set": "x"}, {"set": 1}, {"set": {}}, {"set": {"set_id": 7}},
                     {"set": {"set_id": None}}, [], None, {"unfinished": self.PAGE_SHAPE}):
            r = self.post("/api/unfinished", body)
            self.assertEqual((r.status, json.loads(r.body)), (400, {"error": "bad-set"}), body)
        self.assertEqual(self.unfinished(), self.PAGE_SHAPE)

    def test_its_json_may_be_16_kb_and_no_more(self):
        # {"set_id":"x","pad":""} is 23 bytes written compactly.
        self.assertEqual(self.save_unfinished({"set_id": "x", "pad": "a" * (16 * 1024 - 23)}).status, 204)
        r = self.save_unfinished({"set_id": "y", "pad": "a" * (16 * 1024 - 22)})
        self.assertEqual(r.status, 400)
        self.assertEqual(self.unfinished()["set_id"], "x")

    def test_it_is_dropped_when_its_finished_set_arrives(self):
        self.save_unfinished(dict(self.PAGE_SHAPE, set_id="set-000007"))
        self.send(a_set(set_id="set-000007"))
        self.assertIsNone(self.unfinished())

    def test_a_finished_set_with_another_set_id_leaves_it_in_place(self):
        self.save_unfinished(dict(self.PAGE_SHAPE, set_id="set-000008"))
        self.send(a_set(set_id="set-000007"), an_import())
        self.assertEqual(self.unfinished()["set_id"], "set-000008")

    def test_a_finished_set_sent_again_still_drops_an_unfinished_one_saved_since(self):
        self.send(a_set(set_id="set-000007"))
        self.save_unfinished(dict(self.PAGE_SHAPE, set_id="set-000007"))
        self.send(a_set(set_id="set-000007"))
        self.assertIsNone(self.unfinished())

    def test_a_bad_request_leaves_it_in_place(self):
        self.save_unfinished(dict(self.PAGE_SHAPE, set_id="set-000007"))
        self.assert_bad_record(self.send(a_set(set_id="set-000007"), a_set(id="short")), index=1)
        self.assertEqual(self.unfinished()["set_id"], "set-000007")


class RecordsAreKeptApartPerLearner(RecordsTestCase):
    def test_each_learner_gets_back_only_their_own_records_and_unfinished_set(self):
        alex = self.learner_token("Alex")
        self.send(a_set(id="sams-record-000001"))
        self.send(a_set(id="alexs-record-00001"), token=alex)
        self.save_unfinished({"set_id": "sams-unfinished"})
        self.save_unfinished({"set_id": "alexs-unfinished"}, token=alex)
        self.assertEqual(self.ids(), ["sams-record-000001"])
        self.assertEqual(self.ids(alex), ["alexs-record-00001"])
        self.assertEqual(self.fetch()["unfinished"], {"set_id": "sams-unfinished"})
        self.assertEqual(self.fetch(alex)["unfinished"], {"set_id": "alexs-unfinished"})

    def test_one_learners_imported_record_does_not_block_anothers(self):
        alex = self.learner_token("Alex")
        self.send(an_import(id="sams-import-000001"))
        self.send(an_import(id="alexs-import-00001"), token=alex)
        self.assertEqual(self.ids(alex), ["alexs-import-00001"])

    def test_deleting_a_learner_leaves_no_records_or_unfinished_set_behind(self):
        from server import db
        alex = self.learner_token("Alex")
        self.send(a_set(), an_import())
        self.save_unfinished({"set_id": "set-000002"})
        self.send(a_set(id="alexs-record-00001"), token=alex)
        conn = db.connect(self.instance)
        try:
            conn.execute("DELETE FROM accounts WHERE name = 'Sam'")
            left = conn.execute("SELECT account_id FROM records UNION ALL "
                                "SELECT account_id FROM unfinished_sets").fetchall()
            alex_id = conn.execute("SELECT id FROM accounts WHERE name = 'Alex'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual([row[0] for row in left], [alex_id])


class HelperTestCase(RecordsTestCase):
    """The Helper's routes, called by a signed-in Helper (Randy) about a Learner (Sam)."""

    def setUp(self):
        super().setUp()
        self.add_helper("Randy", "correct horse")
        self.helper = cookie_from(self.sign_in("Randy", "correct horse"))
        self.sam_id = self.account_id("Sam")

    def account_id(self, name):
        from server import auth, db
        conn = db.connect(self.instance)
        try:
            account = auth.find_account(conn, name)
            return None if account is None else account["id"]
        finally:
            conn.close()

    def as_helper(self, method, path, value=None):
        """Call a route with the Helper's cookie. Returns (status, parsed JSON or None)."""
        import json
        if method == "GET":
            r = self.get(path, self.helper)
        else:
            r = self.post(path, {} if value is None else value, self.helper)
        return r.status, (json.loads(r.body) if r.body else None)


class HelperRoutesAreForHelpers(HelperTestCase):
    def requests(self):
        """(method, path, body) for every Helper route, each one valid for a Helper."""
        sam = f"/api/learners/{self.sam_id}"
        return [("GET", "/api/learners", None),
                ("GET", f"{sam}/records", None),
                ("POST", "/api/learners", {"name": "Alex", "password": "a good password"}),
                ("POST", f"{sam}/rename", {"name": "Samantha"}),
                ("POST", f"{sam}/reset-sign-in", {"password": "a new password"}),
                ("POST", f"{sam}/reset-progress", {}),
                ("POST", f"{sam}/move", {"to": 4}),
                ("POST", f"{sam}/delete", {"name": "Samantha"})]  # renamed two lines up

    def call_route(self, method, path, body, token, origin=ORIGIN):
        import json
        headers = {"Cookie": f"__Host-rrtn={token}"}
        if method == "GET":
            return call(self.app, "GET", path, headers)
        return call(self.app, "POST", path, {**JSON, **headers, "Origin": origin}, json.dumps(body).encode())

    def assert_nothing_changed(self):
        self.assertEqual(self.as_helper("GET", "/api/learners")[1]["learners"],
                         [{"id": self.sam_id, "name": "Sam", "created_at": "2027-01-15T08:00:00Z"}])
        self.assertEqual(self.as_helper("GET", f"/api/learners/{self.sam_id}/records")[1],
                         {"records": [], "unfinished": {"set_id": "set-000002"}})
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 200)

    def test_a_learner_gets_403_and_signed_out_gets_401_on_every_route_and_nothing_changes(self):
        import json
        self.save_unfinished({"set_id": "set-000002"})
        for token, status, error in ((self.sam, 403, "wrong-role"), ("not-a-session", 401, "signed-out")):
            for method, path, body in self.requests():
                with self.subTest(token=token, path=path, method=method):
                    r = self.call_route(method, path, body, token)
                    self.assertEqual((r.status, json.loads(r.body)), (status, {"error": error}))
        self.assert_nothing_changed()

    def test_every_post_needs_the_instance_origin(self):
        self.save_unfinished({"set_id": "set-000002"})
        for method, path, body in self.requests():
            if method == "POST":
                with self.subTest(path=path):
                    self.assertEqual(self.call_route(method, path, body, self.helper, "https://evil.example").status,
                                     403)
        self.assert_nothing_changed()

    def test_every_answer_is_never_cached(self):
        for method, path, body in self.requests():
            with self.subTest(path=path):
                r = self.call_route(method, path, body, self.helper)
                self.assertLess(r.status, 300, r.body)
                self.assertEqual(r.headers["cache-control"], "no-store")

    def test_nothing_stored_names_the_helper_who_acted(self):
        import json
        for method, path, body in self.requests()[:-1]:
            self.call_route(method, path, body, self.helper)
        from server import db
        conn = db.connect(self.instance)
        try:
            stored = [row[0] for row in conn.execute("SELECT record FROM records")]
        finally:
            conn.close()
        self.assertEqual(len(stored), 2)
        for text in stored:
            self.assertNotIn("Randy", text)
            self.assertEqual(set(json.loads(text)), {"id", "kind", "reset", "at", "data"})


class LearnerList(HelperTestCase):
    def test_the_helper_gets_every_learner_sorted_by_name_ignoring_capitals(self):
        self.add_learner("alex", "learner pass")
        self.add_learner("Zoe", "learner pass")
        status, body = self.as_helper("GET", "/api/learners")
        self.assertEqual(status, 200)
        self.assertEqual([l["name"] for l in body["learners"]], ["alex", "Sam", "Zoe"])
        self.assertEqual(body["learners"][1], {"id": self.sam_id, "name": "Sam",
                                               "created_at": "2027-01-15T08:00:00Z"})


class AddingALearner(HelperTestCase):
    def test_a_learner_added_by_the_helper_can_sign_in_with_that_password(self):
        status, body = self.as_helper("POST", "/api/learners", {"name": "  Alex ", "password": "alex pass 1"})
        self.assertEqual(status, 201)
        self.assertEqual(body, {"id": self.account_id("Alex"), "name": "Alex"})
        r = self.sign_in("alex", "alex pass 1")
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(r.body, b'{"role": "learner", "name": "Alex"}')

    def test_a_name_in_use_by_a_learner_or_a_helper_ignoring_capitals_is_409(self):
        for name in ("sam", "RANDY"):
            with self.subTest(name=name):
                self.assertEqual(self.as_helper("POST", "/api/learners", {"name": name, "password": "a good password"}),
                                 (409, {"error": "name-taken"}))

    def test_a_broken_name_or_password_rule_is_400(self):
        cases = [({"name": "", "password": "a good password"}, "bad-name"),
                 ({"name": "x" * 65, "password": "a good password"}, "bad-name"),
                 ({"name": 7, "password": "a good password"}, "bad-name"),
                 ({"password": "a good password"}, "bad-name"),
                 ({"name": "Alex", "password": "7 chars"}, "bad-password"),
                 ({"name": "Alex", "password": "x" * 129}, "bad-password"),
                 ({"name": "Alex"}, "bad-password")]
        for value, error in cases:
            with self.subTest(value=value):
                self.assertEqual(self.as_helper("POST", "/api/learners", value), (400, {"error": error}))
        self.assertIsNone(self.account_id("Alex"))


class ALearnersRecords(HelperTestCase):
    def test_the_helper_gets_the_same_answer_the_learner_gets(self):
        self.send(a_set(), an_import())
        self.save_unfinished({"set_id": "set-000002"})
        status, body = self.as_helper("GET", f"/api/learners/{self.sam_id}/records")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.fetch())
        self.assertEqual(body["unfinished"], {"set_id": "set-000002"})
        self.assertEqual([r["id"] for r in body["records"]], ["set-record-000001", "import-record-0001"])

    def test_an_unknown_id_a_helpers_id_or_a_word_is_404(self):
        arabic_one = "١".encode().decode("latin-1")  # as WSGI hands a UTF-8 path over
        for learner in (self.sam_id + 100, self.account_id("Randy"), "sam", "0", "-1", "1.0", arabic_one):
            with self.subTest(learner=learner):
                self.assertEqual(self.as_helper("GET", f"/api/learners/{learner}/records")[0], 404)

    def test_a_post_to_the_records_of_a_learner_is_405(self):
        r = self.post(f"/api/learners/{self.sam_id}/records", {"records": []}, self.helper)
        self.assertEqual((r.status, r.headers["allow"]), (405, "GET, HEAD"))


class RenamingALearner(HelperTestCase):
    def rename(self, name, learner=None):
        return self.as_helper("POST", f"/api/learners/{learner or self.sam_id}/rename", {"name": name})

    def test_the_learner_signs_in_with_the_new_name_and_keeps_their_session(self):
        self.assertEqual(self.rename(" Samantha "), (200, {"id": self.sam_id, "name": "Samantha"}))
        self.assertEqual(self.sign_in("samantha", "learner pass").status, 200)
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 401)
        self.assertEqual(self.get("/api/me", self.sam).status, 200)

    def test_changing_only_the_capitals_of_their_own_name_is_allowed(self):
        self.assertEqual(self.rename("SAM"), (200, {"id": self.sam_id, "name": "SAM"}))

    def test_the_same_name_rules_apply(self):
        self.add_learner("Alex", "learner pass")
        self.assertEqual(self.rename("alex"), (409, {"error": "name-taken"}))
        self.assertEqual(self.rename("randy"), (409, {"error": "name-taken"}))
        for name in ("  ", "x" * 65, None):
            with self.subTest(name=name):
                self.assertEqual(self.rename(name), (400, {"error": "bad-name"}))
        self.assertEqual(self.as_helper("GET", "/api/learners")[1]["learners"][1]["name"], "Sam")

    def test_an_unknown_learner_is_404(self):
        self.assertEqual(self.rename("Zed", self.sam_id + 100)[0], 404)


class ResettingSignIn(HelperTestCase):
    def reset_sign_in(self, password, learner=None):
        return self.as_helper("POST", f"/api/learners/{learner or self.sam_id}/reset-sign-in",
                              {"password": password})

    def test_every_old_session_ends_and_only_the_new_password_works(self):
        laptop = cookie_from(self.sign_in("Sam", "learner pass"))
        self.assertEqual(self.reset_sign_in("a new password")[0], 200)
        for token in (self.sam, laptop):
            self.assertEqual(self.get("/api/me", token).status, 401)
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 401)
        self.assertEqual(self.sign_in("Sam", "a new password").status, 200)

    def test_the_helpers_own_session_is_untouched(self):
        self.reset_sign_in("a new password")
        self.assertEqual(self.get("/api/me", self.helper).status, 200)

    def test_a_bad_password_is_400_and_changes_nothing(self):
        for password in ("7 chars", "x" * 129, None):
            with self.subTest(password=password):
                self.assertEqual(self.reset_sign_in(password), (400, {"error": "bad-password"}))
        self.assertEqual(self.get("/api/me", self.sam).status, 200)
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 200)

    def test_an_unknown_learner_is_404(self):
        self.assertEqual(self.reset_sign_in("a new password", self.sam_id + 100)[0], 404)


class ResettingProgress(HelperTestCase):
    def reset_progress(self, learner=None):
        return self.as_helper("POST", f"/api/learners/{learner or self.sam_id}/reset-progress", {})

    def test_it_adds_a_reset_record_the_learner_sees_and_keeps_the_history(self):
        import re
        self.send(a_set())
        self.now = T0 + 90.5
        status, body = self.reset_progress()
        self.assertEqual(status, 200)
        record = body["record"]
        self.assertRegex(record.pop("id"), r"^[A-Za-z0-9_-]{16,64}$")
        self.assertEqual(record, {"kind": "reset", "reset": None, "at": "2027-01-15T08:01:30.500Z", "data": {},
                                  "seq": 2, "received_at": "2027-01-15T08:01:30Z"})
        mine = self.fetch()["records"]
        self.assertEqual([r["kind"] for r in mine], ["set", "reset"])
        self.assertEqual(mine[1], {**record, "id": mine[1]["id"]})
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{16,64}", mine[1]["id"]))

    def test_a_later_reset_names_the_latest_reset_before_it(self):
        first = self.reset_progress()[1]["record"]["id"]
        second = self.reset_progress()[1]["record"]
        third = self.reset_progress()[1]["record"]
        self.assertEqual((second["reset"], third["reset"]), (first, second["id"]))
        self.assertEqual(len({first, second["id"], third["id"]}), 3)

    def test_it_drops_the_unfinished_set(self):
        self.save_unfinished({"set_id": "set-000002"})
        self.reset_progress()
        self.assertIsNone(self.fetch()["unfinished"])

    def test_an_unknown_learner_is_404(self):
        self.assertEqual(self.reset_progress(self.sam_id + 100)[0], 404)


class MovingALearner(HelperTestCase):
    def move(self, value, learner=None):
        return self.as_helper("POST", f"/api/learners/{learner or self.sam_id}/move", value)

    def test_it_adds_a_move_record_the_learner_sees_and_drops_the_unfinished_set(self):
        self.send(a_set())
        self.save_unfinished({"set_id": "set-000002"})
        status, body = self.move({"to": 4})
        self.assertEqual(status, 200)
        record = body["record"]
        self.assertEqual((record["kind"], record["reset"], record["at"], record["data"]),
                         ("move", None, "2027-01-15T08:00:00.000Z", {"to": 4}))
        self.assertEqual(self.fetch(), {"records": [self.fetch()["records"][0], record], "unfinished": None})

    def test_a_move_names_the_latest_reset(self):
        reset = self.as_helper("POST", f"/api/learners/{self.sam_id}/reset-progress", {})[1]["record"]
        self.assertEqual(self.move({"to": 13})[1]["record"]["reset"], reset["id"])

    def test_to_must_be_1_to_13_and_a_bad_one_changes_nothing(self):
        self.save_unfinished({"set_id": "set-000002"})
        for value in ({"to": 0}, {"to": 14}, {"to": "5"}, {"to": 5.0}, {"to": True}, {"to": None}, {}):
            with self.subTest(value=value):
                self.assertEqual(self.move(value), (400, {"error": "bad-move"}))
        self.assertEqual(self.fetch(), {"records": [], "unfinished": {"set_id": "set-000002"}})
        self.assertEqual([self.move({"to": to})[0] for to in (1, 12, 13)], [200, 200, 200])

    def test_an_unknown_learner_is_404(self):
        self.assertEqual(self.move({"to": 4}, self.sam_id + 100)[0], 404)


class DeletingALearner(HelperTestCase):
    def setUp(self):
        super().setUp()
        self.alex = self.learner_token("Alex")
        self.send(a_set(), an_import())
        self.as_helper("POST", f"/api/learners/{self.sam_id}/move", {"to": 3})
        self.save_unfinished({"set_id": "set-000002"})
        self.send(a_set(id="alexs-record-00001"), token=self.alex)

    def delete(self, value, learner=None):
        return self.as_helper("POST", f"/api/learners/{learner or self.sam_id}/delete", value)

    def rows_for(self, account_id):
        """How many rows each table holds for this account."""
        from server import db
        conn = db.connect(self.instance)
        try:
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                                        (account_id,)).fetchone()[0]
                    for table, column in (("accounts", "id"), ("sessions", "account_id"),
                                          ("records", "account_id"), ("unfinished_sets", "account_id"))}
        finally:
            conn.close()

    def test_a_name_that_does_not_match_changes_nothing(self):
        before = self.rows_for(self.sam_id)
        for value in ({"name": "Samuel"}, {"name": "S am"}, {"name": ""}, {"name": None}, {}):
            with self.subTest(value=value):
                self.assertEqual(self.delete(value), (400, {"error": "name-mismatch"}))
        self.assertEqual(self.rows_for(self.sam_id), before)
        self.assertEqual(before, {"accounts": 1, "sessions": 1, "records": 3, "unfinished_sets": 1})
        self.assertEqual(self.get("/api/me", self.sam).status, 200)

    def test_the_matching_name_ignoring_capitals_and_outer_spaces_removes_every_row(self):
        self.assertEqual(self.delete({"name": "  sAM "}), (204, None))
        self.assertEqual(self.rows_for(self.sam_id),
                         {"accounts": 0, "sessions": 0, "records": 0, "unfinished_sets": 0})
        self.assertEqual(self.get("/api/me", self.sam).status, 401)
        self.assertEqual(self.sign_in("Sam", "learner pass").status, 401)
        self.assertEqual(self.as_helper("GET", f"/api/learners/{self.sam_id}/records")[0], 404)

    def test_other_learners_are_untouched(self):
        self.delete({"name": "Sam"})
        self.assertEqual(self.ids(self.alex), ["alexs-record-00001"])
        self.assertEqual([l["name"] for l in self.as_helper("GET", "/api/learners")[1]["learners"]], ["Alex"])

    def test_an_unknown_learner_is_404(self):
        self.assertEqual(self.delete({"name": "Sam"}, self.sam_id + 100)[0], 404)


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
