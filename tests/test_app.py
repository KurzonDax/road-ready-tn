#!/usr/bin/env python3
"""Click through the built page in a real (headless) browser, served by the real server.

Needs Playwright with Chromium:  pip install playwright && playwright install chromium
Run after building:              python3 build.py && python3 tests/test_app.py
Before committing, also run:     python3 tests/check_dist.py  (fails if dist/ is out of date)

Starts `python -m server` with a temporary Instance folder, makes a Helper with
`python -m server.manage add --password-stdin` and a Learner straight into the
database, and signs in through the page like a person would.

Covers the sign-in screen (its wording, the mismatch and pause messages, each role
landing on its own screen, sign-out, and a sign-in that has ended) and the whole
path the Learner takes: all 12 sections, redoing a section, section scores,
review of missed questions, practice tests, the "ready" screen, saving progress
across a reload, picking up a half-finished section, and the phone layout. Progress
is worked out from the Learner's records on the server: progressFrom() on fixtures,
finished Sets stored as records and shown again in a fresh browser, a Reset and a
Move put straight into the database, a record that waits when the server can't be
reached, and #restart / #sectionN doing nothing. Offline (context.set_offline): a
Set finished offline sent once on reconnecting, a long wait sent in parts, an
unfinished Set continued on a second device (the newest wins), the one-time import
of the old tn-permit-daily-v1 state (once, never for a Helper, the old key left
alone), and sign-out refusing offline, sending waiting records first and deleting
that Learner's device copy. Also the Home Screen pieces: the
manifest, the icon sizes, the page head, the safe-area padding, and that the page
loads its fonts and everything else from its own origin. The service worker, on an
Instance run from a copy of the project so its dist/ can be rebuilt: opening the
app and answering a Set with no connection, no /api/ answer in any cache, a new
build reaching the next reload and replacing the old build's cache, and sign-out
dropping the kept questions.json. The server sends the
script-src hash from dist/csp.json, so a wrong hash stops the page, and one run
checks the sentence shown when questions.json can't be loaded.

Set CHROMIUM_PATH to use an installed Chromium instead of Playwright's download.
"""
import json
import os
import pathlib
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import auth, db, records as records_api  # noqa: E402

failures = []

HELPER = ("Randy", "helper password")
LEARNER = ("Sam", "learner password")


def check(cond, msg, got=None):
    """Print and count one check. `got`, when given, is shown only if the check fails."""
    if not cond and got is not None:
        msg += f" (got {got})"
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


class Instance:
    """`python -m server` on a free port, with its own temporary Instance folder.

        with Instance() as inst:
            inst.add_helper("Randy", "helper password")
            page.goto(inst.url)
    """

    def __init__(self, root=ROOT):
        self.root = root  # the project folder the server runs from and serves dist/ of

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("RRTN_")}
        self.env.update(RRTN_DIR=str(self.dir), RRTN_PORT=str(self.port),
                        RRTN_ORIGIN=f"http://127.0.0.1:{self.port}", RRTN_TRUSTED_PROXY="127.0.0.1")
        self.log = open(self.dir / "server.log", "w+")
        self.proc = subprocess.Popen([sys.executable, "-m", "server"], cwd=self.root, env=self.env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while True:
            if self.proc.poll() is not None or time.monotonic() > deadline:
                self.__exit__()
                raise RuntimeError("the server did not start:\n" + self.output)
            try:
                urllib.request.urlopen(self.url + "healthz", timeout=1).close()
                return self
            except OSError:
                time.sleep(0.1)

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.seek(0)
        self.output = self.log.read()
        self.log.close()
        self.tmp.cleanup()

    def add_helper(self, name, password):
        """A Helper, made the way the self-host docs say: with server.manage."""
        subprocess.run([sys.executable, "-m", "server.manage", "add", name, "--password-stdin"],
                       cwd=self.root, env=self.env, input=password + "\n", text=True, check=True,
                       capture_output=True)

    def add_learner(self, name, password):
        """A Learner, put straight into the database with server.auth's own hashing."""
        conn = db.connect(self.dir)
        try:
            return auth.create_account(conn, "learner", name, password, now=time.time())
        finally:
            conn.close()

    def end_sessions(self, name):
        """End every sign-in of an account, as a Helper's Reset sign-in will."""
        conn = db.connect(self.dir)
        try:
            auth.end_all_sessions(conn, auth.find_account(conn, name)["id"])
        finally:
            conn.close()


def answer_set(pg, miss=0):
    """Answer every question in the current set, getting the first `miss` wrong."""
    n = 0
    while pg.query_selector(".opt"):
        opts = pg.query_selector_all(".opt")
        right = pg.evaluate("run.items[run.i].q.a")
        texts = [o.inner_text().split("\n", 1)[-1].strip() for o in opts]
        k = texts.index(right)
        if n < miss:
            k = (k + 1) % 4
        opts[k].click()
        if not pg.query_selector(".src"):
            failures.append(f"no manual quote shown after answering {pg.evaluate('run.items[run.i].q.id')}")
        pg.click("#nextBtn")
        n += 1
    return n


def answer_one(pg):
    """Click the right answer to the question on screen."""
    right = pg.evaluate("run.items[run.i].q.a")
    for o in pg.query_selector_all("button.opt"):
        if o.inner_text().split("\n", 1)[-1].strip() == right:
            o.click()
            return


def open_page(pg, url):
    """Open the page and wait until it shows something: the sign-in screen or, signed in, a screen."""
    pg.goto(url)
    pg.wait_for_selector("#stage section")


def fill_sign_in(pg, name, password):
    """Type into the sign-in screen and press Sign in, found by their labels as a person would."""
    pg.get_by_label("Name", exact=True).fill(name)
    pg.get_by_label("Password", exact=True).fill(password)
    pg.get_by_role("button", name="Sign in").click()


def sign_in(pg, name, password):
    """Sign in from the sign-in screen and wait for the screen that comes after it."""
    fill_sign_in(pg, name, password)
    pg.wait_for_selector("#signInForm", state="detached")
    pg.wait_for_selector("#stage section")


def stage_text(pg):
    """Everything #stage shows, with runs of white space as single spaces."""
    return " ".join(pg.inner_text("#stage").split())


def me_status(pg):
    """What GET /api/me answers for this browser's cookie."""
    return pg.evaluate("fetch('/api/me').then(r => r.status)")


def reload(pg):
    pg.reload()
    pg.wait_for_selector("#stage section")


def h1(pg):
    return pg.inner_text(".home h1")


def fetch(base, path):
    with urllib.request.urlopen(base + path) as r:
        return r.read()


def check_manifest(base):
    m = json.loads(fetch(base, "manifest.webmanifest"))
    want = {"name": "Road Ready TN", "short_name": "Road Ready", "id": "/", "start_url": "/", "scope": "/",
            "display": "standalone", "background_color": "#f3f5f2", "theme_color": "#f3f5f2", "lang": "en"}
    check({k: m.get(k) for k in want} == want, "the manifest names the app and opens it standalone at /")
    check("orientation" not in m, "the manifest doesn't lock the orientation")
    icons = sorted((i.get("src"), i.get("sizes"), i.get("purpose", "any")) for i in m.get("icons", []))
    check(icons == [("icon-192.png", "192x192", "any"), ("icon-512.png", "512x512", "any"),
                    ("icon-512.png", "512x512", "maskable")],
          f"the manifest lists the 192 and 512 icons, and the 512 again as maskable (got {icons})")


def png_header(data):
    """Width, height and color type from a PNG's IHDR chunk, or None if it isn't a PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height, _depth, color = struct.unpack(">IIBB", data[16:26])
    return width, height, color


def check_icons(base):
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        try:
            data = fetch(base, name)
        except OSError:
            data = b""
        head = png_header(data)
        check(head is not None and head[:2] == (size, size), f"{name} is a {size}x{size} PNG (got {head})")
        if name == "apple-touch-icon.png":
            # Color type 2 is RGB with no alpha channel; a tRNS chunk would add transparency back.
            check(head is not None and head[2] == 2 and b"tRNS" not in data,
                  "apple-touch-icon.png has no transparency")


def check_sign_in(browser, inst):
    url = inst.url
    print("\n[signed out]")
    ctx = browser.new_context()
    pg = ctx.new_page()
    requested = []
    pg.on("request", lambda r: requested.append(r.url))
    open_page(pg, url)
    check(stage_text(pg) == "Sign in Type the name and password you were given. Name Password Show password Sign in",
          f"signed out, the page shows only the sign-in screen, worded as decided (got {stage_text(pg)!r})")
    check(not any(u.endswith("questions.json") for u in requested), "signed out, the page never asks for questions.json")
    form = pg.evaluate("""() => { const f = document.querySelector('#stage form');
        return f && { method: f.getAttribute('method'),
                      fields: [...f.querySelectorAll('input:not([type=checkbox])')].map(i => [i.type, i.autocomplete]) }; }""")
    check(form == {"method": "post", "fields": [["text", "username"], ["password", "current-password"]]},
          f"the sign-in screen is a post form whose fields are marked for password managers (got {form})")
    show = pg.get_by_label("Show password", exact=True)
    show.check()
    shown = pg.get_by_label("Password", exact=True).get_attribute("type")
    show.uncheck()
    hidden = pg.get_by_label("Password", exact=True).get_attribute("type")
    check((shown, hidden) == ("text", "password"), "Show password shows the password, and unticking it hides it again")

    fill_sign_in(pg, LEARNER[0], "not the password")
    msg = pg.wait_for_selector("#signInMsg p")
    check(msg.inner_text() == "That name and password do not match. Check them and try again.",
          "wrong details show the mismatch message")
    check(pg.evaluate("document.activeElement === document.querySelector('#signInMsg p')"), "focus moves to the message")
    check(pg.evaluate("!!document.querySelector('#signInMsg p').closest('[aria-live]')"), "the message is in a live region")
    check(me_status(pg) == 401, "wrong details don't sign in")

    sign_in(pg, "  " + LEARNER[0].upper() + " ", LEARNER[1])
    check(h1(pg) == "Section 1 of 12", "a Learner lands on the study path (the name matched ignoring capitals and spaces)")
    fine = pg.evaluate("""() => { const b = [...document.querySelectorAll('.home button')].find(b => b.textContent === 'Sign out');
        const fine = b && b.closest('.fine');
        return !!fine && fine.textContent.includes('This is a practice app.'); }""")
    check(fine, "the Learner's home screen has Sign out in the fine print beside the practice-app notice")
    pg.get_by_role("button", name="Sign out").click()
    check(stage_text(pg) == "Sign out? You will need your name and password to sign in again. Yes, sign out No, stay signed in",
          f"Sign out asks first (got {stage_text(pg)!r})")
    pg.get_by_role("button", name="No, stay signed in").click()
    check(h1(pg) == "Section 1 of 12" and me_status(pg) == 200, "No, stay signed in goes back home, still signed in")
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")
    check(stage_text(pg).startswith("Sign in Type the name"), "Yes, sign out shows the sign-in screen")
    check(me_status(pg) == 401, "after sign-out, /api/me answers 401")
    reload(pg)
    check(pg.query_selector("#signInForm") is not None, "after sign-out, opening the app again shows the sign-in screen")

    print("\n[Helper]")
    sign_in(pg, *HELPER)
    check(pg.inner_text("#stage h1") == "Learners" and not pg.query_selector("#startBtn"),
          "a Helper lands on the Helper screen, not the study path")
    last = pg.evaluate("[...document.querySelectorAll('#stage button')].pop()?.textContent")
    check(last == "Sign out", "the Helper screen ends with Sign out")
    pg.get_by_role("button", name="Sign out").click()
    check(stage_text(pg) == "Sign out? You will need your name and password to sign in again. Yes, sign out No, stay signed in",
          "the Helper's Sign out asks the same question")
    pg.get_by_role("button", name="No, stay signed in").click()
    check(pg.inner_text("#stage h1") == "Learners", "No, stay signed in goes back to the Helper screen")
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")
    check(me_status(pg) == 401, "the Helper's sign-out ends the session")

    print("\n[a sign-in that has ended]")
    sign_in(pg, *LEARNER)
    pg.click("#startBtn")
    answer_set(pg)
    pg.click("#homeBtn")
    inst.end_sessions(LEARNER[0])
    requested.clear()
    reload(pg)
    check(pg.query_selector("#signInForm") is not None and stage_text(pg).startswith("Sign in Type the name"),
          "once the sign-in has ended, the app opens on the sign-in screen and says nothing else")
    check(not any(u.endswith("questions.json") for u in requested), "and it doesn't ask for questions.json")
    sign_in(pg, *LEARNER)
    check(h1(pg) == "Section 2 of 12", "signing in again goes back to where the Learner was")
    ctx.close()

    print("\n[sign-in paused]")
    ctx = browser.new_context(locale="en-US", timezone_id="America/Chicago")
    pg = ctx.new_page()
    pg.clock.set_fixed_time("2026-10-16T16:00:30-05:00")
    open_page(pg, url)
    # The server's answer during a pause, as "Sign-in limits" sends it.
    pg.evaluate("""() => { const real = window.fetch;
        window.fetch = (u, o) => String(u).includes('/api/sign-in')
            ? Promise.resolve(new Response(JSON.stringify({ error: 'paused', retry_after: window.retryAfter }),
                                           { status: 429, headers: { 'Content-Type': 'application/json' } }))
            : real(u, o); }""")
    for seconds, shown, why in ((870, "4:15 PM", "the clock time it ends"),
                                (871, "4:16 PM", "the time rounded up to the next minute")):
        pg.evaluate(f"window.retryAfter = {seconds}")
        fill_sign_in(pg, *LEARNER)
        pg.wait_for_selector("#signInBtn:not([disabled])")
        msg = pg.inner_text("#signInMsg p").replace("\u202f", " ")
        check(msg == f"Sign-in is paused because of too many tries. You can try again at {shown}.",
              f"a 429 shows the pause sentence with {why} (got {msg!r})")
        check(pg.evaluate("document.activeElement === document.querySelector('#signInMsg p')"),
              "focus moves to the pause message")
    ctx.close()


def copy_project(folder):
    """A copy of what the server and build.py need, to rebuild dist/ without touching the real one."""
    for name in ("build.py", "data", "dist", "server", "src", "tests", "vendor"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, folder / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, folder / name)
    return folder


def rebuild(project, change):
    """Rebuild project/dist/ from project/src/app.html with change(text) applied. Returns the new sw.js version."""
    app = project / "src" / "app.html"
    app.write_text(change(app.read_text(encoding="utf-8")), encoding="utf-8")
    subprocess.run([sys.executable, "build.py"], cwd=project, check=True, capture_output=True)
    return sw_version(project / "dist")


def sw_version(dist):
    return re.search(r"const VERSION = '([0-9a-f]{12})';", (dist / "sw.js").read_text()).group(1)


def cached(pg):
    """Every [cache name, path] that Cache Storage holds for the page's origin."""
    return pg.evaluate("""async () => { const all = [];
        for (const name of await caches.keys())
            for (const r of await (await caches.open(name)).keys()) all.push([name, new URL(r.url).pathname]);
        return all; }""")


def check_offline(browser):
    """The service worker, on its own Instance run from a copy of the project, so dist/ can be rebuilt."""
    print("\n[offline]")
    with tempfile.TemporaryDirectory() as t, Instance(copy_project(pathlib.Path(t))) as inst:
        inst.add_learner(*LEARNER)
        v1 = sw_version(inst.root / "dist")
        ctx = browser.new_context()
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        open_page(pg, inst.url)
        sign_in(pg, *LEARNER)
        check(h1(pg) == "Section 1 of 12", "online, the Learner signs in and sees Section 1")
        try:
            pg.wait_for_function("() => !!navigator.serviceWorker.controller", timeout=10000)
        except PlaywrightTimeout:
            check(False, "the page registers a service worker that takes control of it")
            return

        ctx.set_offline(True)
        reload(pg)
        check(h1(pg) == "Section 1 of 12", "with no connection, opening the app again shows the study path")
        pg.click("#startBtn")
        check(answer_set(pg, miss=1) == 10 and pg.inner_text(".score") == "9 of 10",
              "with no connection, a whole Set can be answered")
        pg.click("#homeBtn")
        check(h1(pg) == "Section 2 of 12", "and the home screen moves on to Section 2")
        fonts = pg.evaluate("""document.fonts.check('800 18px Overpass')
                               && document.fonts.check('400 18px "Atkinson Hyperlegible"')""")
        check(fonts, "with no connection, the page still has its fonts")

        ctx.set_offline(False)
        reload(pg)
        pg.evaluate("fetch('/api/me').then(r => r.status)")
        kept = cached(pg)
        api = [k for k in kept if k[1].startswith("/api/")]
        check(kept and not api, f"no /api/ answer is in any cache (got {api})")
        pages = sorted(k[1] for k in kept if k[0] == "rrtn-pages")
        check(pages == ["/", "/questions.json"], f"rrtn-pages keeps only the page and questions.json (got {pages})")
        names = sorted({k[0] for k in kept})
        check(names == ["rrtn-pages", f"rrtn-static-{v1}"],
              f"the fonts, icons and manifest are kept under this build's version (got {names})")

        print("\n[a new build]")
        v2 = rebuild(inst.root, lambda page: page.replace("This is a practice app.", "This is a practice app, new build."))
        check(v2 != v1, "the rebuild gives sw.js a new version")
        reload(pg)
        check("This is a practice app, new build." in stage_text(pg), "after a rebuild, the next reload online shows the change")
        deadline = time.monotonic() + 10
        while True:  # the new worker installs and activates in the background
            names = pg.evaluate("caches.keys()")
            if f"rrtn-static-{v1}" not in names or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        check(f"rrtn-static-{v1}" not in names and f"rrtn-static-{v2}" in names,
              f"the new build's service worker deletes the old version's cache (got {names})")

        print("\n[sign-out]")
        pg.get_by_role("button", name="Sign out").click()
        pg.get_by_role("button", name="Yes, sign out").click()
        pg.wait_for_selector("#signInForm")
        left = pg.evaluate("caches.open('rrtn-pages').then(c => c.match('/questions.json')).then(r => !!r)")
        check(not left, "after sign-out, questions.json is not kept in rrtn-pages")
        ctx.set_offline(True)
        reload(pg)
        check(not pg.query_selector("#startBtn") and not pg.evaluate("me"),
              "after sign-out, opening the app with no connection doesn't open the study path")
        check(not errors, "no page errors offline or across the new build" + (f": {errors}" if errors else ""))
        ctx.close()


def at(minute):
    """A record time, `minute` minutes after a fixed start, in the page's toISOString() form."""
    return f"2026-10-01T{12 + minute // 60:02d}:{minute % 60:02d}:00.000Z"


def record(n, kind, minute, data, reset=None, seq=None):
    """A record as the server hands it back (with seq), or as it waits on the device (seq None)."""
    r = {"id": f"record-{n:012d}", "kind": kind, "reset": reset, "at": at(minute), "data": data}
    if seq is not None:
        r["seq"] = seq
    return r


def set_record(n, kind, section, minute, answers, reset=None, seq=None):
    """A finished Set. `answers` is a list of (question id, right)."""
    return record(n, "set", minute, {
        "set_id": f"set-{n}", "type": kind, "section": section, "started_at": at(minute - 1),
        "answers": [{"q": q, "chosen": "an answer", "right": right, "at": at(minute)} for q, right in answers]},
        reset, seq)


def check_progress_from(browser, inst):
    """progressFrom(records) on fixtures, run in the page itself."""
    inst.add_learner("Fixtures", "fixtures password")
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, "Fixtures", "fixtures password")
    ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
    s1, s2, s3, s4 = ids["1"], ids["2"], ids["3"], ids["4"]

    def section(n, kind, number, minute, wrong=0, **kw):
        qs = ids[str(number)]
        return set_record(n, kind, number, minute, [(q, i >= wrong) for i, q in enumerate(qs)], **kw)

    def progress(records):
        return pg.evaluate("records => progressFrom(records)", records)

    def marks(qs, wrong=0):
        return {q: i >= wrong for i, q in enumerate(qs)}

    print("\n[progressFrom]")
    got = progress([section(1, "day", 1, 10, wrong=3, seq=1)])
    check(got == {"day": 2, "last": marks(s1, 3), "scores": {"1": 7}, "tests": []},
          "one Section Set moves the Learner on to Section 2 and keeps its score and answers", got)

    got = progress([])
    check(got == {"day": 1, "last": {}, "scores": {}, "tests": []}, "no records is the start of Section 1", got)

    # Two devices both finish Section 3. Device B's arrives first but finished later; and a
    # record still waiting on a device (no seq) sorts after a sent one with the same time.
    both = [section(1, "day", 1, 10, seq=1), section(2, "day", 2, 20, seq=2),
            section(4, "day", 3, 31, wrong=4, seq=3), section(3, "day", 3, 30, wrong=1, seq=4)]
    got = progress(both)
    check(got["day"] == 4 and got["scores"] == {"1": 10, "2": 10, "3": 6},
          "two devices finishing Section 3 move the Learner on once; the later one counts as a redo", got)
    got = progress(both + [section(5, "day", 3, 31, wrong=2)])
    check(got["day"] == 4 and got["scores"]["3"] == 8,
          "a record not yet sent sorts after a sent one with the same time", got)
    got = progress([section(1, "day", 1, 10, seq=1), section(2, "day", 3, 20, seq=2)])
    check(got["day"] == 2 and got["scores"] == {"1": 10, "3": 10},
          "a Section Set that isn't the next Section counts as a redo of it", got)

    # A Reset: only records after it that name it count. One still naming the older Reset, and
    # one naming none, stay in the History but don't count.
    old, new = "record-000000000003", "record-000000000005"
    got = progress([section(1, "day", 1, 10, seq=1), section(2, "day", 2, 20, seq=2),
                    record(3, "reset", 30, {}, seq=3), section(4, "day", 1, 40, wrong=5, reset=old, seq=4),
                    record(5, "reset", 50, {}, reset=old, seq=5), section(6, "day", 1, 60, wrong=2, reset=new, seq=6),
                    section(7, "day", 2, 70, reset=old, seq=7), set_record(8, "test", None, 80, [(s3[0], False)], seq=8)])
    check(got == {"day": 2, "last": marks(s1, 2), "scores": {"1": 8}, "tests": []},
          "after a Reset only records naming it count", got)

    # A Move to Section 4 keeps the scores, answers and Practice tests.
    got = progress([section(1, "day", 1, 10, wrong=1, seq=1), section(2, "day", 2, 20, seq=2),
                    record(3, "move", 30, {"to": 4}, seq=3)])
    check(got == {"day": 4, "last": {**marks(s1, 1), **marks(s2)}, "scores": {"1": 9, "2": 10}, "tests": []},
          "a Move to Section 4 makes Section 4 next and keeps the rest", got)
    got = progress([record(1, "move", 10, {"to": 4}, seq=1), section(2, "day", 4, 20, seq=2)])
    check(got["day"] == 5, "after a Move to Section 4, finishing Section 4 moves on to Section 5", got)

    # An Imported start: its state's fields are checked and anything else is dropped.
    state = {"day": 5, "last": {s1[0]: True, s1[1]: False, s1[2]: "yes"}, "scores": {"1": 10, "2": "8", "3": 7},
             "tests": [28, "29", 25], "run": {"kind": "day"}, "extra": 1}
    got = progress([record(1, "imported", 10, {"state": state}, seq=1), section(2, "day", 5, 20, wrong=1, seq=2)])
    check(got == {"day": 6, "last": {s1[0]: True, s1[1]: False, **marks(ids["5"], 1)},
                  "scores": {"1": 10, "3": 7, "5": 9}, "tests": [28, 25]},
          "an Imported record is the starting point, with its fields checked", got)
    got = progress([record(1, "imported", 10, {"state": {"day": "7", "last": [], "scores": None}}, seq=1)])
    check(got == {"day": 1, "last": {}, "scores": {}, "tests": []},
          "an Imported state with fields of the wrong type starts from Section 1", got)

    # Practice tests count in finish order, and the in-a-row count comes from them.
    def test_set(n, minute, right, seq):
        qs = s1 + s2 + s3
        return set_record(n, "test", None, minute, [(q, i < right) for i, q in enumerate(qs)], seq=seq)

    tests = [record(1, "move", 10, {"to": 13}, seq=1), test_set(2, 20, 28, 2), test_set(3, 30, 20, 3),
             test_set(5, 50, 29, 4), test_set(4, 40, 27, 5)]
    got = progress(tests)
    check(got["day"] == 13 and got["tests"] == [28, 20, 27, 29],
          "Practice tests count in finish order", got)
    check(pg.evaluate("records => streak(progressFrom(records))", tests) == 2,
          "the in-a-row count is 2 after 28, 20, 27, 29")
    check(pg.evaluate("records => streak(progressFrom(records))", tests + [test_set(6, 60, 30, 6)]) == 3,
          "a third test at 27 or more in a row reaches Ready for the test")
    got = progress([set_record(1, "review", None, 10, [(s4[0], True), (s4[1], False)], seq=1)])
    check(got == {"day": 1, "last": {s4[0]: True, s4[1]: False}, "scores": {}, "tests": []},
          "a Review Set changes only which questions are right or wrong", got)
    ctx.close()


OLD_KEY = "tn-permit-daily-v1"  # the saved state from before accounts; this page must leave it alone
# Logs every localStorage call that names the old key, from before the page's own script runs.
WATCH_OLD_KEY = """(() => { window.oldKeyCalls = [];
    for (const name of ['getItem', 'setItem', 'removeItem']) {
        const real = Storage.prototype[name];
        Storage.prototype[name] = function (key, ...rest) {
            if (key === '%s') window.oldKeyCalls.push(name);
            return real.call(this, key, ...rest);
        };
    } })()""" % OLD_KEY


def server_records(pg):
    """The signed-in Learner's records, as GET /api/records hands them back."""
    return pg.evaluate("fetch('/api/records').then(r => r.json()).then(b => b.records)")


def wait_for_records(pg, n):
    """Wait until the server holds `n` records for the signed-in Learner, and return them."""
    deadline = time.monotonic() + 10
    while True:
        records = server_records(pg)
        if len(records) >= n or time.monotonic() > deadline:
            return records
        time.sleep(0.1)


def wait_for_h1(pg, text):
    """Wait (up to 5 seconds) for the home screen's heading to read `text`; return what it reads."""
    try:
        pg.wait_for_function("t => document.querySelector('.home h1')?.textContent === t", arg=text, timeout=5000)
    except Exception:
        pass
    return h1(pg)


def store_for(inst, learner_id, kind, data):
    """Put a reset or move record straight into the database, as the Helper API does. Returns its id."""
    conn = db.connect(inst.dir)
    try:
        return records_api.helper_record(conn, learner_id, kind, data, time.time())["id"]
    finally:
        conn.close()


def check_records_on_server(browser, inst):
    """Finished Sets become records on the server, and Progress comes back from them anywhere."""
    name, password = "Robin", "records password"
    learner = inst.add_learner(name, password)
    print("\n[Progress from the server's records]")
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, name, password)
    check(h1(pg) == "Section 1 of 12", "a new Learner starts at Section 1")

    pg.click("#startBtn")
    answer_set(pg, miss=2)
    check(pg.inner_text(".score") == "8 of 10" and pg.inner_text(".home h2") == "Section 1 done.",
          "the results screen is the same as before")
    got = wait_for_records(pg, 1)
    rec = got[0] if len(got) == 1 else {}
    data = rec.get("data", {})
    check(len(got) == 1 and rec["kind"] == "set" and rec["reset"] is None
          and (data["type"], data["section"]) == ("day", 1),
          "finishing Section 1 stores one Section Set record on the server", got)
    answers = data.get("answers", [])
    check(len(answers) == 10 and sum(a["right"] for a in answers) == 8
          and all(a["at"] >= data["started_at"] and a["at"] <= rec["at"] for a in answers),
          "the record holds every answer, which were right, and when each was chosen", data)
    pg.click("#homeBtn")
    check(h1(pg) == "Section 2 of 12", "home then shows Section 2")
    reload(pg)
    check(h1(pg) == "Section 2 of 12", "reloading keeps Progress")

    other = browser.new_context()
    pg2 = other.new_page()
    open_page(pg2, inst.url)
    sign_in(pg2, name, password)
    check(h1(pg2) == "Section 2 of 12", "signing in on a fresh browser shows the same Section")
    other.close()

    reset = store_for(inst, learner, "reset", {})
    reload(pg)
    check(wait_for_h1(pg, "Section 1 of 12") == "Section 1 of 12",
          "a Reset put into the database shows on the Learner's next app open")
    check(not pg.query_selector(".scores"), "after the Reset no Section scores are left")
    store_for(inst, learner, "move", {"to": 4})
    reload(pg)
    check(wait_for_h1(pg, "Section 4 of 12") == "Section 4 of 12",
          "a Move to Section 4 put into the database shows on the Learner's next app open")
    pg.click("#startBtn")
    answer_set(pg)
    got = wait_for_records(pg, 4)
    check(len(got) == 4 and got[-1]["reset"] == reset and got[-1]["data"]["section"] == 4,
          "a Set finished after the Reset names that Reset", got[-1:])
    pg.click("#homeBtn")
    check(h1(pg) == "Section 5 of 12", "finishing Section 4 after the Move moves on to Section 5")

    # The server can't be reached when a Set finishes: the record waits and is sent next time.
    ctx.route("**/api/records", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
    pg.click("#startBtn")
    answer_set(pg)
    check(pg.inner_text(".home h2") == "Section 5 done.", "with the server out of reach, the Set still finishes")
    pg.click("#homeBtn")
    check(h1(pg) == "Section 6 of 12", "and the home screen shows Section 6")
    check(len(server_records(pg)) == 4, "the record hasn't reached the server yet")
    reload(pg)
    check(h1(pg) == "Section 6 of 12", "the waiting record still counts after a reload")
    ctx.unroute("**/api/records")
    reload(pg)
    got = wait_for_records(pg, 5)
    check(len(got) == 5 and got[-1]["data"]["section"] == 5, "the waiting record is sent on the next app open", got)
    reload(pg)
    check(len(server_records(pg)) == 5, "and it is stored only once")
    pg.goto(inst.url + "#section9")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Section 6 of 12", "#section9 does nothing")
    pg.goto(inst.url + "?r=1#restart")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Section 6 of 12" and not pg.query_selector("#yes"), "#restart does nothing")
    ctx.close()


def db_state(inst, learner_id):
    """What the server holds for a Learner, read straight from the database: (records, unfinished Set)."""
    conn = db.connect(inst.dir)
    try:
        return records_api.learner_records(conn, learner_id), records_api.unfinished_set(conn, learner_id)
    finally:
        conn.close()


def wait_until(test, timeout=10):
    """Call `test` until it returns something true (or the time runs out); return its last answer."""
    deadline = time.monotonic() + timeout
    while True:
        got = test()
        if got or time.monotonic() > deadline:
            return got
        time.sleep(0.1)


def record_posts(pg):
    """A list that fills with the body of each POST /api/records the page sends."""
    posts = []
    pg.on("request", lambda r: posts.append(json.loads(r.post_data))
          if r.method == "POST" and r.url.endswith("/api/records") else None)
    return posts


def wait_for_stage_text(pg, text):
    """Wait (up to 5 seconds) for #stage to show `text` somewhere."""
    try:
        pg.wait_for_function("t => document.querySelector('#stage').textContent.includes(t)", arg=text, timeout=5000)
    except Exception:
        pass


def copy_key(learner_id):
    return f"rrtn-learner-{learner_id}"


def local_item(pg, key):
    return pg.evaluate("k => localStorage.getItem(k)", key)


def block_record_posts(ctx):
    """Make POST /api/records fail as if the server can't be reached (GETs still work)."""
    ctx.route("**/api/records", lambda route: route.abort() if route.request.method == "POST" else route.continue_())


OFFLINE_SIGN_OUT = "You are offline. Sign out needs a connection, so that your answers are saved first."


def check_offline_and_sync(browser, inst):
    """Waiting records are sent later, the unfinished Set follows the Learner, and old progress comes in once."""
    print("\n[a Set finished offline]")
    name, password = "Kit", "offline password"
    kit = inst.add_learner(name, password)
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, name, password)
    ctx.set_offline(True)
    pg.click("#startBtn")
    answer_set(pg, miss=1)
    check(pg.inner_text(".home h2") == "Section 1 done.", "with no connection the Learner keeps answering to the end of a Set")
    pg.click("#homeBtn")
    check(h1(pg) == "Section 2 of 12", "and the home screen moves on to Section 2")
    shown = stage_text(pg).lower()
    check("offline" not in shown and "connection" not in shown, "nothing on the page says the device is offline", shown)
    check(db_state(inst, kit)[0] == [], "the server doesn't have the Set yet")
    ctx.set_offline(False)
    got = wait_until(lambda: db_state(inst, kit)[0])
    check(len(got) == 1 and got[0]["data"]["section"] == 1,
          "going back online sends the waiting Set without reopening the app", got)
    reload(pg)
    check(len(server_records(pg)) == 1 and h1(pg) == "Section 2 of 12", "and the server holds it exactly once")
    check(json.loads(local_item(pg, copy_key(kit)))["pending"] == [], "the device copy has nothing left waiting")

    # A long wait: 40 Practice tests (well over the server's 64 KB body limit in all), with one
    # record among them the server will never take.
    qs = pg.evaluate("QS.map(q => q.id)")[:30]
    tests = [set_record(100 + n, "test", None, 100 + n, [(q, True) for q in qs]) for n in range(40)]
    for t in tests:
        t["id"] = f"long-wait-{t['id']}"
        for a in t["data"]["answers"]:
            a["chosen"] = "an answer chosen from four, about as long as the real ones are"
    bad = dict(tests[5], id="long-wait-bad-record-0", kind="move", data={"to": 99})
    saved = json.loads(local_item(pg, copy_key(kit)))
    saved["pending"] = tests[:5] + [bad] + tests[5:]
    check(len(json.dumps(saved["pending"])) > 64 * 1024, "the waiting records are over 64 KB together")
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [copy_key(kit), json.dumps(saved)])
    reload(pg)
    got = wait_until(lambda: len(db_state(inst, kit)[0]) == 41 and db_state(inst, kit)[0])
    check(got and [r["id"] for r in got[1:]] == [t["id"] for t in tests],
          "a long wait is sent in several requests, all stored once and in order", len(got or []))
    left = wait_until(lambda: json.loads(local_item(pg, copy_key(kit)))["pending"] == [], 5)
    check(left, "a record the server refuses is dropped, so it doesn't hold back the others")
    ctx.close()

    print("\n[an unfinished Set on two devices]")
    name, password = "Lee", "two devices password"
    lee = inst.add_learner(name, password)
    phone, laptop = browser.new_context(), browser.new_context()
    pg, pg2 = phone.new_page(), laptop.new_page()
    open_page(pg, inst.url)
    sign_in(pg, name, password)
    pg.click("#startBtn")
    for _ in range(3):
        answer_one(pg)
        pg.click("#nextBtn")
    unfinished = wait_until(lambda: (db_state(inst, lee)[1] or {}).get("i") == 3 and db_state(inst, lee)[1])
    check(bool(unfinished) and isinstance(unfinished.get("saved_at"), str),
          "after each answer the unfinished Set is on the server, with saved_at", unfinished)
    open_page(pg2, inst.url)
    sign_in(pg2, name, password)
    check(pg2.query_selector("#resumeBtn") is not None and "You answered 3 of 10 questions" in stage_text(pg2),
          "the second device offers the Set the first one stopped partway through", stage_text(pg2))
    pg2.click("#resumeBtn")
    check(pg2.evaluate("run.i") == 3 and pg2.evaluate("run.set_id") == pg.evaluate("run.set_id"),
          "and continues it at the next question")
    answer_one(pg2)
    pg2.click("#nextBtn")
    wait_until(lambda: (db_state(inst, lee)[1] or {}).get("i") == 4)
    reload(pg)
    wait_for_stage_text(pg, "You answered 4 of 10 questions")
    check("You answered 4 of 10 questions" in stage_text(pg),
          "the first device, opened again, takes the newer unfinished Set from the server", stage_text(pg))
    answer_set(pg2)
    pg2.click("#homeBtn")
    got = wait_until(lambda: db_state(inst, lee)[0])
    check(len(got) == 1 and wait_until(lambda: db_state(inst, lee)[1] is None, 5),
          "finishing it stores the Set and the server drops the unfinished one", db_state(inst, lee))
    reload(pg)
    check(wait_for_h1(pg, "Section 2 of 12") == "Section 2 of 12" and not pg.query_selector("#resumeBtn"),
          "the first device then shows Section 2 and nothing to continue")
    phone.close()
    laptop.close()

    print("\n[old progress from before accounts]")
    name, password = "Ash", "import password"
    ash = inst.add_learner(name, password)
    ctx = browser.new_context()
    ctx.add_init_script(WATCH_OLD_KEY)
    pg = ctx.new_page()
    posts = record_posts(pg)
    open_page(pg, inst.url)
    old_state = {"day": 5, "last": {}, "tests": [], "scores": {"1": 9, "2": 7, "3": 10, "4": 8}}
    old = json.dumps(old_state)
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [OLD_KEY, old])
    pg.evaluate("localStorage.setItem('rrtn-learner-someone-else', '{}')")

    sign_in(pg, *HELPER)
    check(pg.inner_text("#stage h1") == "Learners" and posts == [], "a Helper signing in on that device imports nothing")
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")

    sign_in(pg, name, password)
    check(wait_for_h1(pg, "Section 5 of 12") == "Section 5 of 12",
          "the Learner's first sign-in picks up the old progress at Section 5")
    got = wait_until(lambda: db_state(inst, ash)[0])
    check(len(got) == 1 and got[0]["kind"] == "imported" and got[0]["data"] == {"state": old_state},
          "the old progress becomes one imported record holding the old saved state", got)
    check(json.loads(local_item(pg, copy_key(ash))).get("imported_done") is True,
          "the device copy remembers that the import is done")
    reload(pg)
    check(h1(pg) == "Section 5 of 12", "the imported progress stays after a reload")

    # Sign-out sends what is waiting first. The record can't be sent when the Set finishes...
    block_record_posts(ctx)
    pg.click("#startBtn")
    answer_set(pg)
    pg.click("#homeBtn")
    ctx.unroute("**/api/records")
    check(len(db_state(inst, ash)[0]) == 1, "a Set waits on the device when the server can't take it")
    # ...and offline, sign-out refuses and stays signed in.
    ctx.set_offline(True)
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    msg = pg.wait_for_selector("#signOutMsg")
    check(msg.inner_text() == OFFLINE_SIGN_OUT, "signing out offline says it needs a connection", msg.inner_text())
    check(pg.evaluate("document.activeElement?.id") == "signOutMsg", "focus moves to that sentence")
    # Back online, with the server still not taking records, so only sign-out can send the waiting Set.
    block_record_posts(ctx)
    ctx.set_offline(False)
    check(me_status(pg) == 200 and local_item(pg, copy_key(ash)) is not None,
          "the Learner is still signed in and the device copy is kept")
    time.sleep(0.5)  # let the send the online event starts fail
    check(len(db_state(inst, ash)[0]) == 1, "the Set is still waiting")
    ctx.unroute("**/api/records")
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")
    got = db_state(inst, ash)[0]
    check(len(got) == 2 and got[1]["data"]["section"] == 5, "signing out online sends the waiting Set first", got)
    check(local_item(pg, copy_key(ash)) is None, "and then deletes that Learner's device copy")
    check(local_item(pg, "rrtn-learner-someone-else") == "{}", "but leaves other copies alone")

    sign_in(pg, name, password)
    check(wait_for_h1(pg, "Section 6 of 12") == "Section 6 of 12", "signing in again shows Section 6")
    imports = [r for body in posts for r in body["records"] if r["kind"] == "imported"]
    check(len(imports) == 1 and len(db_state(inst, ash)[0]) == 2, "and doesn't import the old progress again", imports)
    calls = [c for c in pg.evaluate("window.oldKeyCalls") if c != "getItem"]
    check(calls == [], f"the page never writes or deletes tn-permit-daily-v1 (calls: {calls})")
    check(local_item(pg, OLD_KEY) == old, "the old saved state under tn-permit-daily-v1 is unchanged")
    ctx.close()

    print("\n[an import that has to wait]")
    name, password = "Bo", "waiting import password"
    bo = inst.add_learner(name, password)
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [OLD_KEY, json.dumps({"day": 3, "last": {}, "tests": [], "scores": {}})])
    block_record_posts(ctx)
    sign_in(pg, name, password)
    check(wait_for_h1(pg, "Section 3 of 12") == "Section 3 of 12", "the import counts at once, before the server has it")
    reload(pg)
    pending = json.loads(local_item(pg, copy_key(bo)))["pending"]
    check([r["kind"] for r in pending] == ["imported"], "opening the app again doesn't make a second imported record", pending)
    ctx.unroute("**/api/records")
    reload(pg)
    got = wait_until(lambda: db_state(inst, bo)[0])
    check(len(got) == 1 and got[0]["kind"] == "imported" and h1(pg) == "Section 3 of 12",
          "it is sent on the next app open", got)
    ctx.close()


def main():
    errors = []
    with Instance() as inst, sync_playwright() as p:
        inst.add_helper(*HELPER)
        inst.add_learner(*LEARNER)
        url = base = inst.url
        print("\n[Home Screen files]")
        check_manifest(base)
        check_icons(base)
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        check_sign_in(browser, inst)
        check_offline(browser)
        check_progress_from(browser, inst)
        check_records_on_server(browser, inst)
        check_offline_and_sync(browser, inst)

        print("\n[page head, fonts, own origin]")
        ctx = browser.new_context()
        pg = ctx.new_page()
        requested = []
        pg.on("request", lambda r: requested.append(r.url))
        open_page(pg, url)
        sign_in(pg, *LEARNER)
        pg.evaluate("document.fonts.ready")
        outside = [u for u in requested if not u.startswith(base)]
        check(requested and not outside, f"the page loads nothing from another origin (got {outside})")
        for face in ('400 18px "Atkinson Hyperlegible"', '700 18px "Atkinson Hyperlegible"',
                     '600 18px "Overpass"', '800 18px "Overpass"'):
            loaded = pg.evaluate("async f => (await document.fonts.load(f)).length > 0 && document.fonts.check(f)", face)
            check(loaded, f"text can render in {face}")
        head = pg.evaluate("""() => ({
            viewport: document.querySelector('meta[name=viewport]')?.content,
            themes: [...document.querySelectorAll('meta[name=theme-color]')].map(m => [m.media, m.content]),
            title: document.querySelector('meta[name=apple-mobile-web-app-title]')?.content,
            links: [...document.querySelectorAll('link')].map(l => [l.rel, l.getAttribute('href')]),
            odd: [...document.querySelectorAll('meta[name^="claude:"], meta[name=apple-mobile-web-app-status-bar-style]')].length,
        })""")
        check(head["viewport"] == "width=device-width, initial-scale=1, viewport-fit=cover",
              "the viewport covers the whole screen, with zoom left on")
        check(sorted(head["themes"]) == [["(prefers-color-scheme: dark)", "#111814"],
                                         ["(prefers-color-scheme: light)", "#f3f5f2"]],
              f"theme-color is set for light and dark (got {head['themes']})")
        check(head["title"] == "Road Ready", "the Home Screen label is Road Ready")
        check(sorted(head["links"]) == [["apple-touch-icon", "apple-touch-icon.png"], ["icon", "icon-192.png"],
                                        ["manifest", "manifest.webmanifest"]],
              f"the head links the manifest and icons, and nothing else (got {head['links']})")
        check(head["odd"] == 0, "no claude: meta and no status-bar-style meta")
        fonts = sorted(u[len(base):] for u in requested if u.endswith(".woff2"))
        check(fonts and all(f.startswith("fonts/") for f in fonts), f"the fonts come from the Instance's fonts/ (got {fonts})")
        ctx.close()

        print("\n[questions.json missing]")
        # Requests a service worker makes are not routed, so this one runs without it.
        ctx = browser.new_context(service_workers="block")
        ctx.route("**/questions.json", lambda route: route.fulfill(status=404, body="Not found"))
        pg = ctx.new_page()
        open_page(pg, url)
        sign_in(pg, *LEARNER)
        check(pg.inner_text("#stage") ==
              "The questions could not be loaded. Check your connection and open the app again.",
              "with questions.json missing, the page says the questions could not be loaded")
        ctx.close()

        # A real phone lays the page out at its own width, not a shrunken desktop page.
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = phone.new_page()
        open_page(pg, url)
        sign_in(pg, *LEARNER)
        print("\n[phone]")
        check(pg.evaluate("document.compatMode") == "CSS1Compat", "page runs in standards mode")
        check(pg.evaluate("innerWidth") == 390, "phone lays the page out at the phone's width")
        check(pg.evaluate("document.documentElement.lang") == "en", "page language is set")
        pg.click("#startBtn")
        pg.query_selector_all(".opt")[0].click()
        box = pg.query_selector("#feedback .verdict").bounding_box()
        check(box is not None and 0 <= box["y"] < 844, "after answering, the verdict is on screen")
        nb = pg.query_selector("#nextBtn").bounding_box()
        check(nb is not None and nb["y"] + nb["height"] <= 844, "after answering, Next is on screen")

        # An iPhone with a notch reports a 44px top inset and a 34px bottom one in standalone mode.
        def padding():
            return pg.evaluate("[getComputedStyle(document.body).paddingTop, getComputedStyle(document.body).paddingBottom]"
                               ".map(parseFloat)")
        check(padding() == [24, 48], "with no insets the page keeps its 24px top and 48px bottom padding")
        cdp = phone.new_cdp_session(pg)
        cdp.send("Emulation.setSafeAreaInsetsOverride", {"insets": {"top": 44, "bottom": 60}})
        top, bottom = padding()
        check(top >= 44, f"with a 44px top inset, the top of the page is padded at least 44px (got {top})")
        check(bottom >= 60, f"with a 60px bottom inset, the bottom of the page is padded at least 60px (got {bottom})")
        phone.close()
        for scheme in ("light", "dark"):
            print(f"\n[{scheme} mode]")
            ctx = browser.new_context(viewport={"width": 400, "height": 900}, color_scheme=scheme)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if "Content Security Policy" in m.text else None)
            # Progress lives on the server now, so each run of the whole path needs its own Learner.
            learner = (f"{scheme.title()} Learner", "path password")
            inst.add_learner(*learner)
            open_page(pg, url)
            sign_in(pg, *learner)

            check(h1(pg) == "Section 1 of 12", "starts at Section 1 of 12")
            check(not pg.query_selector("details") and "parent" not in pg.inner_text("body").lower(),
                  "nothing on the page is addressed to the parent")

            # Section 1 with 3 misses: results, redo button, then redo perfectly.
            pg.click("#startBtn")
            first = pg.evaluate("run.items.map(i => i.q.id)")
            check(answer_set(pg, miss=3) == 10, "a section is exactly 10 questions")
            check(pg.inner_text(".score") == "7 of 10", "results show 7 of 10")
            check(pg.query_selector("#againBtn") is not None, "results offer to try the section again")
            pg.click("#againBtn")
            redo = pg.evaluate("run.items.map(i => i.q.id)")
            check(sorted(redo) == sorted(first), "a redo uses the same 10 questions")
            answer_set(pg)
            check(pg.inner_text(".home h2") == "Section 1 done." and pg.evaluate("S.day") == 2,
                  "a redo doesn't move his place forward")
            pg.click("#homeBtn")

            # Sections 2 and 3 at 8 and 5. Scores are shown on request, not as colors.
            for miss in (2, 5):
                pg.click("#startBtn"); answer_set(pg, miss); pg.click("#homeBtn")
            check(len(pg.query_selector_all(".road .stop.done")) == 3, "finished sections show as finished")
            check(not pg.query_selector(".road .g-low, .road .g-mid"), "finished sections are not colored by score")
            pg.click(".scores summary")
            scores = [e.inner_text() for e in pg.query_selector_all(".scores .sscore")]
            check(scores == ["Last time: 10 of 10 right", "Last time: 8 of 10 right", "Last time: 5 of 10 right"],
                  "section scores list the latest score for each section")

            # Doing a finished section again updates its score.
            pg.click('.redo[data-day="3"]'); answer_set(pg); pg.click("#homeBtn")
            pg.click(".scores summary")
            check(pg.inner_text('.scores li:nth-child(3) .sscore') == "Last time: 10 of 10 right",
                  "redoing a section updates its score")

            # A half-finished section is saved: stopping, or closing the page, keeps the answers.
            pg.click("#startBtn")
            answer_one(pg); pg.click("#nextBtn")
            answer_one(pg)
            pg.click("#quitBtn")
            check(pg.query_selector("#resumeBtn") is not None and "answered 2 of 10" in pg.inner_text(".home"),
                  "stopping partway shows how far you got")
            reload(pg)
            check(pg.query_selector("#resumeBtn") is not None, "a half-finished section survives a reload")
            pg.click("#resumeBtn")
            check(pg.evaluate("run.i") == 1 and pg.query_selector("#nextBtn") is not None,
                  "continuing picks up at the same question")
            pg.click("#nextBtn")
            answer_set(pg)
            check(pg.inner_text(".score") == "10 of 10" and pg.query_selector("details.missed") is None,
                  "a resumed section finishes normally")
            pg.click("#homeBtn")

            # Progress survives a reload.
            reload(pg)
            check(h1(pg) == "Section 5 of 12", "progress is saved across a reload")

            # Finish the rest, missing 2 in each.
            for _ in range(5, 13):
                pg.click("#startBtn"); answer_set(pg, 2); pg.click("#homeBtn")
            check(h1(pg) == "Review", "after Section 12 comes review of missed questions")
            rounds = 0
            while h1(pg) == "Review" and rounds < 10:
                pg.click("#startBtn"); answer_set(pg); pg.click("#homeBtn"); rounds += 1
            check(h1(pg).startswith("Practice test"), "after review come practice tests")

            # Three practice tests at 28/30 reach "ready".
            for _ in range(3):
                pg.click("#startBtn")
                check(answer_set(pg, 2) == 30, "a practice test is 30 questions")
                pg.click("#homeBtn")
                if h1(pg) == "Review":
                    pg.click("#startBtn"); answer_set(pg); pg.click("#homeBtn")
            check(h1(pg) == "Ready for the test", "three tests in a row at 27+ shows the ready screen")
            reload(pg)
            check(h1(pg) == "Ready for the test", "Ready for the test is still shown after a reload")
            ctx.close()
        browser.close()
    check(not errors, "no page errors" + (f": {errors}" if errors else ""))
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
