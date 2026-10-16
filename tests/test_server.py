"""Tests for the server core: startup checks, the WSGI app, static files and headers.

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
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.proc.stdout.close()


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
        r = call(self.app, "GET", "/questions.json")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, QUESTIONS)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        self.assertEqual(r.headers["cache-control"], "private, no-cache")
        self.assertTrue(r.headers.get("etag"))

    def test_a_matching_if_none_match_gets_304_with_no_body(self):
        for path in ("/", "/questions.json"):
            with self.subTest(path=path):
                tag = call(self.app, "GET", path).headers["etag"]
                r = call(self.app, "GET", path, {"If-None-Match": tag})
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


if __name__ == "__main__":
    unittest.main()
