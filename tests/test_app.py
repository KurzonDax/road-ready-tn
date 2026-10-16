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
reached, the old tn-permit-daily-v1 state left alone, and #restart / #sectionN
doing nothing. The Helper's view: studySessions(), missedMost() and sectionHistory()
on fixtures, the wording of where a Learner is, and, on a 375 px wide phone, the list of
Learners and one Learner's page with nothing scrolling sideways. Managing Learners: Add a Learner
and its errors, then signing in as them; Rename; Reset sign-in, after which the old password fails;
Reset progress and Move, which the Learner's next app open shows; Delete, turned off until the name
is typed; the paused line after 10 failed sign-ins; and each action asking first and doing nothing
on No. Also the Home Screen pieces: the
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
import datetime
import json
import math
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
import zoneinfo

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


def timed_set(n, kind, section, answers, reset=None, seq=None):
    """A finished Set whose answers each have their own time. `answers` is a list of
    (question id, chosen, right, minute); the Set starts at its first answer and finishes at its last."""
    minutes = [a[3] for a in answers]
    return record(n, "set", max(minutes), {
        "set_id": f"set-{n}", "type": kind, "section": section, "started_at": at(min(minutes)),
        "answers": [{"q": q, "chosen": chosen, "right": right, "at": at(m)} for q, chosen, right, m in answers]},
        reset, seq)


def check_helper_helpers(browser, inst):
    """The Helper's view's pure helpers on fixtures, run in the page itself: studySessions(),
    missedMost(), sectionHistory(), and the wording of where a Learner is."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, *HELPER)
    ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
    qs = pg.evaluate("QS.map(q => q.id)")
    s1, s2, s4 = ids["1"], ids["2"], ids["4"]

    def run(fn, arg):
        return pg.evaluate(f"x => {fn}(x)", arg)

    print("\n[Helper's view: Study sessions]")
    # A gap of 29 minutes keeps one Study session; a gap of 31 starts a new one. A Set whose
    # answers fall in two Study sessions counts as finished in the later one.
    got = run("studySessions", [
        timed_set(1, "day", 1, [(s1[0], "x", True, 0), (s1[1], "x", True, 1), (s1[2], "x", False, 2)], seq=1),
        timed_set(2, "day", 2, [(s2[0], "x", True, 31), (s2[1], "x", True, 32)], seq=2),
        timed_set(3, "redo", 1, [(s1[0], "x", True, 63)], seq=3),
        timed_set(4, "review", None, [(s1[2], "x", True, 100), (s1[2], "x", True, 200)], seq=4)])
    check(got == [
        {"kind": "session", "start": at(200), "end": at(200), "sets": [{"type": "review", "section": None, "right": 2, "of": 2}]},
        {"kind": "session", "start": at(100), "end": at(100), "sets": []},
        {"kind": "session", "start": at(63), "end": at(63), "sets": [{"type": "redo", "section": 1, "right": 1, "of": 1}]},
        {"kind": "session", "start": at(0), "end": at(32), "sets": [{"type": "day", "section": 1, "right": 2, "of": 3},
                                                                    {"type": "day", "section": 2, "right": 2, "of": 2}]}],
        "Study sessions, newest first, split by a 31-minute gap but not by a 29-minute one", got)
    check(run("studySessions", []) == [], "no records is no Study sessions")

    # A Reset and Moves are lines of their own; Study sessions cover the whole History while
    # Progress counts only from after the Reset.
    reset = "record-000000000002"
    history = [timed_set(1, "day", 1, [(s1[0], "x", True, 0)], seq=1), record(2, "reset", 40, {}, seq=2),
               record(3, "move", 50, {"to": 4}, reset=reset, seq=3),
               timed_set(4, "day", 4, [(s4[0], "x", False, 80)], reset=reset, seq=4),
               record(5, "move", 90, {"to": 13}, reset=reset, seq=5)]
    got = run("studySessions", history)
    check(got == [{"kind": "move", "at": at(90), "to": 13},
                  {"kind": "session", "start": at(80), "end": at(80), "sets": [{"type": "day", "section": 4, "right": 0, "of": 1}]},
                  {"kind": "move", "at": at(50), "to": 4},
                  {"kind": "reset", "at": at(40)},
                  {"kind": "session", "start": at(0), "end": at(0), "sets": [{"type": "day", "section": 1, "right": 1, "of": 1}]}],
          "Study sessions keep the Sets from before a Reset, with the Reset and each Move as its own line", got)
    got = run("progressFrom", history)
    check(got == {"day": 13, "last": {s4[0]: False}, "scores": {"4": 0}, "tests": []},
          "while Progress counts only the records after the Reset", got)
    got = pg.evaluate("h => studySessions(h).map(historyLine)", history)
    check(got[0] == "Moved to Review and Practice tests" and got[2] == "Moved to Section 4"
          and got[3] == "Progress reset by a Helper",
          "a Move and a Reset are worded as decided", got)

    print("\n[Helper's view: Questions missed most]")
    # Since the Reset: qs[0] missed 4 of 5, qs[1] 3 of 3, qs[2] 3 of 6, qs[3] to qs[10] 2 of 2,
    # qs[11] once. Before it, qs[11] and qs[12] were missed many times.
    reset = "record-000000000001"
    plan = {qs[0]: ["W1", "W1", "W2", "W1", None], qs[1]: ["W3"] * 3, qs[2]: ["W4", "W5", "W5", None, None, None],
            **{q: ["X", "X"] for q in qs[3:11]}, qs[11]: ["Y", None]}
    recs = [timed_set(90, "review", None, [(qs[11], "Y", False, m) for m in range(5)]
                      + [(qs[12], "Z", False, m) for m in range(3)], seq=0),
            record(1, "reset", 10, {}, seq=1)]
    for n, (q, picks) in enumerate(plan.items(), start=2):
        recs.append(timed_set(n, "review", None, [(q, c or "right", c is None, 20 + n + i) for i, c in enumerate(picks)],
                              reset=reset, seq=n))
    got = run("missedMost", recs)
    want = [{"q": qs[0], "missed": 4, "answered": 5, "wrong": "W1"},
            {"q": qs[1], "missed": 3, "answered": 3, "wrong": "W3"},
            {"q": qs[2], "missed": 3, "answered": 6, "wrong": "W5"}] + \
           [{"q": q, "missed": 2, "answered": 2, "wrong": "X"} for q in qs[3:10]]
    check(got == want, "Questions missed most: most misses first, then fewer answers, then path order; "
                       "at most 10; only since the latest Reset; none missed only once", got)
    check(run("missedMost", recs[:2]) == [], "with only answers from before the Reset, nothing is listed")

    print("\n[Helper's view: Section history]")
    reset = "record-000000000002"
    got = run("sectionHistory", [
        timed_set(1, "day", 1, [(s1[0], "x", True, 0), (s1[1], "x", False, 1)], seq=1), record(2, "reset", 5, {}, seq=2),
        timed_set(3, "day", 1, [(s1[0], "x", False, 10), (s1[1], "x", True, 11)], reset=reset, seq=3),
        timed_set(4, "redo", 1, [(s1[0], "x", True, 20), (s1[1], "x", True, 21)], reset=reset, seq=4),
        timed_set(5, "review", None, [(s1[0], "x", True, 30)], reset=reset, seq=5),
        timed_set(6, "day", 2, [(s2[0], "x", True, 40)], reset=reset, seq=6)])
    want = [{"section": 1, "sets": [{"at": at(21), "right": 2, "of": 2}, {"at": at(11), "right": 1, "of": 2}]},
            {"section": 2, "sets": [{"at": at(40), "right": 1, "of": 1}]}] + \
           [{"section": n, "sets": []} for n in range(3, 13)]
    check(got == want, "sectionHistory lists every Section's Sets since the Reset, newest first", got)

    print("\n[Helper's view: wording]")
    review = [(q, "x", False, 20) for q in s1 + ids["2"][:4]]
    tests_all = s1 + s2 + ids["3"]

    def practice(n, minute, right):
        return timed_set(n, "test", None, [(q, "x", i < right, minute) for i, q in enumerate(tests_all)], seq=n)

    for records, want in (
            ([record(1, "move", 10, {"to": 5}, seq=1)], "Section 5 of 12"),
            ([record(1, "move", 10, {"to": 13}, seq=1), timed_set(2, "review", None, review, seq=2)],
             "Review: 14 questions left"),
            ([record(1, "move", 10, {"to": 13}, seq=1), timed_set(2, "review", None, review[:1], seq=2)],
             "Review: 1 question left"),
            ([record(1, "move", 10, {"to": 13}, seq=1), practice(2, 20, 30), practice(3, 30, 30)],
             "Practice tests: 2 of 3 in a row"),
            ([record(1, "move", 10, {"to": 13}, seq=1), practice(2, 20, 28), practice(3, 30, 27), practice(4, 40, 29)],
             "Ready for the test")):
        got = pg.evaluate("r => whereNow(progressFrom(r))", records)
        check(got == want, f"where the Learner is reads {want!r}", got)

    def unfinished(kind, day, n, i, answered):
        return {"kind": kind, "dayNum": day, "i": i, "answered": answered, "set_id": "u", "started_at": at(0),
                "items": [{"id": qs[k], "options": [], "chosen": "x" if k < i + answered else None, "at": None}
                          for k in range(n)]}

    for u, want in ((unfinished("day", 6, 10, 3, True), "Unfinished: Section 6, 4 of 10 answered"),
                    (unfinished("redo", 2, 10, 0, False), "Unfinished: Section 2, 0 of 10 answered"),
                    (unfinished("review", 13, 10, 3, True), "Unfinished: Review, 4 of 10 answered"),
                    (unfinished("test", 13, 30, 4, False), "Unfinished: Practice test, 4 of 30 answered")):
        got = run("unfinishedLine", u)
        check(got == want, f"an unfinished Set reads {want!r}", got)
    ctx.close()


def store_history(inst, learner_id, recs, unfinished=None):
    """Put records (any kind) and an unfinished Set straight into the database for a Learner."""
    conn = db.connect(inst.dir)
    try:
        records_api.store_records(conn, learner_id, recs, time.time(), kinds=records_api.KINDS)
        if unfinished is not None:
            with db.transaction(conn):
                records_api.save_unfinished(conn, learner_id, unfinished, time.time())
    finally:
        conn.close()


def no_sideways_scroll(pg, width=375):
    """True when nothing on the page is wider than `width`. (On a phone, innerWidth itself grows
    to fit content that is too wide, so the width is given rather than read.)"""
    return pg.evaluate("w => document.documentElement.scrollWidth <= w && innerWidth === w", width)


def texts(pg, selector):
    return [" ".join(t.replace(" ", " ").split()) for t in pg.eval_on_selector_all(selector, "els => els.map(e => e.innerText)")]


def check_helper_view(browser):
    """A Helper sees the list of Learners and opens one Learner's page, on a 375 px wide phone."""
    print("\n[Helper's view]")
    with Instance() as inst:
        inst.add_helper(*HELPER)
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
                                  locale="en-US", timezone_id="America/Chicago")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: failures.append(f"page error on the Helper's view: {e}"))
        open_page(pg, inst.url)
        sign_in(pg, *HELPER)
        pg.wait_for_selector("#stage .learners, #stage .none")
        check(stage_text(pg) == "Learners No Learners yet. Add a Learner Sign out",
              "with no Learners, the list says No Learners yet., with Add a Learner and Sign out below", stage_text(pg))

        qs = {q["id"]: q for q in pg.evaluate("QS")}
        ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
        s1, s2 = ids["1"], ids["2"]
        casey = inst.add_learner("Casey", "casey password")
        inst.add_learner("Wolfeschlegelsteinhausenbergerdorffvoralternwarengewissenhaft", "long name password")

        def section(n, kind, number, start, wrong=(), reset=None):
            """A Section Set with one answer a minute from `start`; questions at the `wrong` places get a wrong answer."""
            return timed_set(n, kind, number, [(q, qs[q]["o"][0] if i in wrong else qs[q]["a"], i not in wrong, start + i)
                                               for i, q in enumerate(ids[str(number)])], reset=reset)

        reset = "record-000000000002"
        tests = ids["5"] + ids["6"] + ids["7"]
        store_history(inst, casey, [
            section(1, "day", 1, 0),                                   # 7:00 AM, before the Reset
            record(2, "reset", 30, {}),                                # 7:30 AM
            section(3, "day", 1, 60, wrong=(0,), reset=reset),         # 8:00 AM
            section(4, "day", 2, 75, wrong=(0, 1), reset=reset),       # 8:15 AM, same Study session
            record(5, "move", 100, {"to": 4}, reset=reset),            # 8:40 AM
            section(6, "redo", 1, 200, wrong=(0, 1), reset=reset),     # 10:20 AM
            timed_set(7, "test", None, [(q, qs[q]["o"][1] if i >= 28 else qs[q]["a"], i < 28, 300)
                                        for i, q in enumerate(tests)], reset=reset)],  # 12:00 PM
            unfinished={"kind": "day", "dayNum": 4, "i": 3, "answered": True, "set_id": "unfinished-set",
                        "started_at": at(400),
                        "items": [{"id": q, "options": [qs[q]["a"], *qs[q]["o"]], "chosen": qs[q]["a"] if i < 4 else None,
                                   "at": at(400) if i < 4 else None} for i, q in enumerate(ids["4"])]})
        reload(pg)
        pg.wait_for_selector("#stage .learners")
        rows = texts(pg, ".learners li")
        check(rows == ["Casey Section 4 of 12 Last studied October 1, 2026",
                       "Wolfeschlegelsteinhausenbergerdorffvoralternwarengewissenhaft Section 1 of 12 Has not answered any questions yet."],
              "one row per Learner: the name, where they are, and the date they last studied", rows)
        last = pg.evaluate("[...document.querySelectorAll('#stage button')].pop()?.textContent")
        check(last == "Sign out", "Sign out is still the last button on the list")
        check(no_sideways_scroll(pg), "at 375 px wide, nothing on the list scrolls sideways")

        pg.get_by_role("button", name="Casey").click()
        pg.wait_for_selector("#stage .part")
        check(pg.inner_text("#stage h1") == "Casey", "the Learner's page opens with the Learner's name")
        check(texts(pg, ".now p") == ["Section 4 of 12", "Unfinished: Section 4, 4 of 10 answered"],
              "where they are now, and the unfinished Set", texts(pg, ".now p"))
        sections = texts(pg, ".sections > li")
        check(len(sections) == 12, "Sections has 12 rows", len(sections))
        check(sections[:3] == [f"Section 1: {pg.evaluate('DAYS[0].title')} Last score: 8 of 10. Done 2 times.",
                               f"Section 2: {pg.evaluate('DAYS[1].title')} Last score: 8 of 10. Done 1 time.",
                               f"Section 3: {pg.evaluate('DAYS[2].title')} Not done yet."],
              "each Section row has its latest score and how many times it was done, since the Reset", sections[:3])
        pg.click(".sections > li:first-child summary")
        check(texts(pg, ".sections > li:first-child .sets li") == ["October 1, 2026, 10:29 AM: 8 of 10",
                                                                    "October 1, 2026, 8:09 AM: 9 of 10"],
              "opening a Section row lists each Set with its date and score", texts(pg, ".sections > li:first-child .sets li"))
        check(texts(pg, ".review p") == ["6 questions left. Review starts after Section 12."],
              "Review says how many questions are left", texts(pg, ".review p"))
        check(texts(pg, ".tests p, .tests li") == ["In a row so far: 1 of 3", "October 1, 2026, 12:00 PM: 28 of 30"],
              "Practice tests lists each test with its date and score, and the count in a row", texts(pg, ".tests p, .tests li"))
        q = qs[s1[0]]
        check(texts(pg, ".missedmost li") == [f"{q['q']} Right answer: {q['a']} Wrong answer chosen most often: {q['o'][0]} "
                                              f"Missed 2 of 2 times Driver manual, page {q['p']}"],
              "Questions missed most counts only since the Reset and shows the question, answers, count and page",
              texts(pg, ".missedmost li"))
        check(texts(pg, ".sessions > li") == [
            "October 1, 2026, 12:00 PM Less than 1 minute Practice test: 28 of 30",
            "October 1, 2026, 10:20 AM 9 minutes Section 1: 8 of 10",
            "October 1, 2026, 8:40 AM Moved to Section 4",
            "October 1, 2026, 8:00 AM 24 minutes Section 1: 9 of 10 Section 2: 8 of 10",
            "October 1, 2026, 7:30 AM Progress reset by a Helper",
            "October 1, 2026, 7:00 AM 9 minutes Section 1: 10 of 10"],
            "Study sessions, newest first, cover the whole History with the Reset and the Move as lines",
            texts(pg, ".sessions > li"))
        heads = texts(pg, "#stage h2")
        check(heads == ["Sections", "Review", "Practice tests", "Questions missed most", "Study sessions", "Manage this Learner"],
              "the Learner's page is in the decided order", heads)
        pg.eval_on_selector_all("#stage details", "els => els.forEach(d => d.open = true)")
        check(no_sideways_scroll(pg), "at 375 px wide, nothing on the Learner's page scrolls sideways")

        pg.get_by_role("button", name="Back to Learners").last.click()
        pg.wait_for_selector("#stage .learners")
        check(pg.inner_text("#stage h1") == "Learners", "Back to Learners returns to the list")
        pg.get_by_role("button", name="Wolfeschlegel").click()
        pg.wait_for_selector("#stage .part")
        check(no_sideways_scroll(pg), "a long name doesn't make the Learner's page scroll sideways")
        check(texts(pg, ".now p") == ["Section 1 of 12"] and texts(pg, ".history p") == ["No Study sessions yet."]
              and texts(pg, ".tests p") == ["No Practice tests yet."]
              and texts(pg, ".missedmost p") == ["No question has been missed two or more times."],
              "a Learner with no records has a page that says so",
              [texts(pg, ".now p"), texts(pg, ".history p"), texts(pg, ".tests p"), texts(pg, ".missedmost p")])
        pg.get_by_role("button", name="Back to Learners").first.click()
        pg.wait_for_selector("#stage .learners")
        ctx.close()


def learner_names(pg):
    """The names on the Learner list, once it has loaded."""
    pg.wait_for_selector("#stage .learners, #stage .none")
    return texts(pg, ".lrow .lname")


def form_message(pg):
    """The error shown on a Helper's form, or None."""
    el = pg.query_selector("#formMsg .warn")
    return " ".join(el.inner_text().split()) if el else None


def submit_form(pg, button):
    """Press a form's button, then wait for the confirm question or an error."""
    pg.get_by_role("button", name=button, exact=True).click()
    pg.wait_for_selector("#confirmYes, #formMsg .warn")


def open_learner(pg, name):
    """From the Learner list, open one Learner's page and wait for it to load."""
    pg.wait_for_selector("#stage .learners")
    pg.locator(".lrow", has=pg.locator(".lname", has_text=name)).click()
    pg.wait_for_selector("#stage .manage")


def check_manage_learner(browser):
    """The Helper adds a Learner and manages one: each action asks first, in literal words."""
    print("\n[Manage Learners]")
    with Instance() as inst:
        inst.add_helper(*HELPER)
        casey = inst.add_learner("Casey", "casey password")
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
                                  locale="en-US", timezone_id="America/Chicago")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: failures.append(f"page error while managing Learners: {e}"))
        open_page(pg, inst.url)
        sign_in(pg, *HELPER)
        check(learner_names(pg) == ["Casey"], "the list starts with one Learner", learner_names(pg))
        buttons = texts(pg, "#stage button:not(.lrow)")
        check(buttons == ["Add a Learner", "Sign out"], "Add a Learner sits between the list and Sign out", buttons)

        # Add a Learner: a name and a password, with Show password.
        pg.get_by_role("button", name="Add a Learner").click()
        pg.wait_for_selector("#stage form")
        check(h1(pg) == "Add a Learner", "Add a Learner opens its own screen", h1(pg))
        check(no_sideways_scroll(pg), "at 375 px wide, the Add a Learner screen doesn't scroll sideways")
        pw = pg.get_by_label("Password", exact=True)
        check(pw.get_attribute("type") == "password", "the password is hidden at first")
        pg.get_by_label("Show password").check()
        check(pw.get_attribute("type") == "text", "Show password shows it")
        for name, password, want in [
                ("", "new password", "The name must be 1 to 64 characters."),
                ("   ", "new password", "The name must be 1 to 64 characters."),
                ("x" * 65, "new password", "The name must be 1 to 64 characters."),
                ("Jordan", "short", "The password must be 8 to 128 characters."),
                ("Jordan", "p" * 129, "The password must be 8 to 128 characters."),
                (" casey ", "new password", "Another account already uses that name. Choose a different name."),
                ("randy", "new password", "Another account already uses that name. Choose a different name.")]:
            pg.get_by_label("Name", exact=True).fill(name)
            pw.fill(password)
            submit_form(pg, "Add this Learner")
            if pg.query_selector("#confirmYes"):
                pg.click("#confirmYes")
                pg.wait_for_selector("#formMsg .warn, #stage .learners")
            check(form_message(pg) == want, f"adding {name[:12]!r} with a {len(password)}-character password says {want!r}",
                  form_message(pg))
        pg.get_by_label("Name", exact=True).fill("Jordan")
        pw.fill("jordan password")
        submit_form(pg, "Add this Learner")
        check(stage_text(pg).startswith("Add a Learner named Jordan?"), "Add asks first", stage_text(pg))
        pg.click("#confirmNo")
        pg.wait_for_selector("#stage form")
        check(pg.get_by_label("Name", exact=True).input_value() == "Jordan",
              "saying no goes back to the form with what was typed")
        pg.get_by_role("button", name="Cancel").click()
        check(learner_names(pg) == ["Casey"], "saying no adds nobody", learner_names(pg))

        pg.get_by_role("button", name="Add a Learner").click()
        pg.get_by_label("Name", exact=True).fill("Jordan")
        pg.get_by_label("Password", exact=True).fill("jordan password")
        submit_form(pg, "Add this Learner")
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .learners")
        check(learner_names(pg) == ["Casey", "Jordan"], "after Add, the list is loaded again with the new Learner",
              learner_names(pg))
        lctx = browser.new_context()
        lpg = lctx.new_page()
        open_page(lpg, inst.url)
        sign_in(lpg, "Jordan", "jordan password")
        check(h1(lpg) == "Section 1 of 12", "the new Learner can sign in, and starts at Section 1", h1(lpg))

        # Manage this Learner: its own part at the bottom of the Learner's page.
        open_learner(pg, "Casey")
        heads = texts(pg, "#stage h2")
        check(heads[-2:] == ["Study sessions", "Manage this Learner"], "Manage this Learner comes after Study sessions", heads)
        manage = texts(pg, ".manage button")
        check(manage == ["Rename", "Reset sign-in", "Reset progress", "Move", "Delete"],
              "Manage this Learner has Rename, Reset sign-in, Reset progress, Move and Delete", manage)
        last = pg.evaluate("[...document.querySelectorAll('#stage button')].pop()?.textContent")
        check(last == "Back to Learners", "Back to Learners is still the last button on the Learner's page", last)
        check(no_sideways_scroll(pg), "at 375 px wide, Manage this Learner doesn't scroll sideways")

        # Rename, with the same errors as Add a Learner.
        pg.get_by_role("button", name="Rename", exact=True).click()
        pg.wait_for_selector("#stage form")
        check(pg.get_by_label("New name").input_value() == "Casey", "Rename starts from the Learner's name")
        for name, want in [("", "The name must be 1 to 64 characters."),
                           ("y" * 65, "The name must be 1 to 64 characters."),
                           ("JORDAN", "Another account already uses that name. Choose a different name.")]:
            pg.get_by_label("New name").fill(name)
            submit_form(pg, "Rename")
            if pg.query_selector("#confirmYes"):
                pg.click("#confirmYes")
                pg.wait_for_selector("#formMsg .warn, #stage .manage")
            check(form_message(pg) == want, f"renaming to {name[:12]!r} says {want!r}", form_message(pg))
        pg.get_by_label("New name").fill(" Casey Lee ")
        submit_form(pg, "Rename")
        check(stage_text(pg).startswith("Rename Casey to Casey Lee?"), "Rename asks first", stage_text(pg))
        pg.click("#confirmNo")
        pg.get_by_role("button", name="Cancel").click()
        pg.wait_for_selector("#stage .manage")
        check(h1(pg) == "Casey", "saying no keeps the name", h1(pg))
        pg.get_by_role("button", name="Rename", exact=True).click()
        pg.get_by_label("New name").fill(" Casey Lee ")
        submit_form(pg, "Rename")
        pg.click("#confirmYes")
        pg.wait_for_function("() => document.querySelector('.home h1')?.textContent === 'Casey Lee' && document.querySelector('#stage .manage')")
        check(h1(pg) == "Casey Lee", "after Rename, the Learner's page loads again with the new name", h1(pg))
        pg.get_by_role("button", name="Back to Learners").first.click()
        check(learner_names(pg) == ["Casey Lee", "Jordan"], "the list has the new name", learner_names(pg))

        # Reset sign-in, and the paused line. Jordan is signed in on a device of their own.
        open_learner(pg, "Jordan")
        check(not pg.query_selector(".now .paused"), "with no pause, there is no paused line")
        pg.get_by_role("button", name="Reset sign-in").click()
        pg.wait_for_selector("#stage form")
        new_pw = pg.get_by_label("New password", exact=True)
        new_pw.fill("short")
        submit_form(pg, "Set the new password")
        check(form_message(pg) == "The password must be 8 to 128 characters.",
              "a new password that is too short says so", form_message(pg))
        new_pw.fill("jordan new password")
        submit_form(pg, "Set the new password")
        want = ("Set a new password for Jordan? Jordan will be signed out on every device and will need "
                "the new password to sign in.")
        check(stage_text(pg).startswith(want), "Reset sign-in asks first, in the decided words", stage_text(pg))
        pg.click("#confirmNo")
        pg.get_by_role("button", name="Cancel").click()
        pg.wait_for_selector("#stage .manage")
        check(me_status(lpg) == 200, "saying no to Reset sign-in leaves the Learner signed in")

        tries = browser.new_context()
        tpg = tries.new_page()
        open_page(tpg, inst.url)
        sign_in_status = "pw => fetch('/api/sign-in', {method: 'POST', headers: {'Content-Type': 'application/json'}, " \
                         "body: JSON.stringify({name: 'Jordan', password: pw})}).then(r => r.status)"
        statuses = [tpg.evaluate(sign_in_status, "wrong password") for _ in range(10)]
        check(statuses == [401] * 10, "ten failed sign-ins for Jordan through the API", statuses)
        conn = db.connect(inst.dir)
        try:
            until = conn.execute("SELECT paused_until FROM sign_in_limits WHERE key = 'name:jordan'").fetchone()[0]
        finally:
            conn.close()
        shown = datetime.datetime.fromtimestamp(math.ceil(until / 60) * 60, zoneinfo.ZoneInfo("America/Chicago"))
        want = f"Sign-in is paused until {shown.strftime('%I:%M %p').lstrip('0')} after too many tries."
        pg.get_by_role("button", name="Back to Learners").first.click()
        open_learner(pg, "Jordan")
        paused = texts(pg, ".now p")
        check(paused == ["Section 1 of 12", want], "under where they are now, the paused line says until when", paused)

        pg.get_by_role("button", name="Reset sign-in").click()
        pg.get_by_label("New password", exact=True).fill("jordan new password")
        submit_form(pg, "Set the new password")
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["Section 1 of 12"], "after Reset sign-in, the paused line is gone", texts(pg, ".now p"))
        check(texts(pg, ".note") == ["Jordan's new password is set."], "the Learner's page says the new password is set",
              texts(pg, ".note"))
        check(me_status(lpg) == 401, "Reset sign-in signs the Learner out on their device")
        check(tpg.evaluate(sign_in_status, "jordan password") == 401, "after Reset sign-in, the old password fails")
        tries.close()
        open_page(lpg, inst.url)
        sign_in(lpg, "Jordan", "jordan new password")
        check(h1(lpg) == "Section 1 of 12", "the new password signs the Learner in", h1(lpg))
        lctx.close()

        # Reset progress. Casey Lee has finished Sections 1 and 2 and is signed in on a device of their own.
        ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
        store_history(inst, casey, [set_record(1, "day", 1, 0, [(q, True) for q in ids["1"]]),
                                    set_record(2, "day", 2, 20, [(q, i > 0) for i, q in enumerate(ids["2"])])])
        cctx = browser.new_context()
        cpg = cctx.new_page()
        open_page(cpg, inst.url)
        sign_in(cpg, "Casey Lee", "casey password")
        check(h1(cpg) == "Section 3 of 12", "Casey Lee's study path is at Section 3", h1(cpg))
        pg.get_by_role("button", name="Back to Learners").first.click()
        open_learner(pg, "Casey Lee")
        pg.get_by_role("button", name="Reset progress").click()
        want = ("Put Casey Lee back at the start of Section 1? Scores, Review and Practice tests start over. "
                "The History of finished Sets is kept.")
        check(stage_text(pg).startswith(want), "Reset progress asks first, in the decided words", stage_text(pg))
        pg.click("#confirmNo")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["Section 3 of 12"], "saying no to Reset progress changes nothing", texts(pg, ".now p"))
        pg.get_by_role("button", name="Reset progress").click()
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["Section 1 of 12"], "after Reset progress, the Learner's page says Section 1",
              texts(pg, ".now p"))
        sessions = texts(pg, ".sessions > li")
        check(len(sessions) == 2 and sessions[0].endswith("Progress reset by a Helper")
              and sessions[1].endswith("Section 1: 10 of 10 Section 2: 9 of 10"),
              "Study sessions still shows the old Sets, under a Progress reset by a Helper line", sessions)
        reload(cpg)
        check(wait_for_h1(cpg, "Section 1 of 12") == "Section 1 of 12",
              "the Learner's next app open shows Section 1", h1(cpg))

        # Move: Section 1 to 12, or Review and Practice tests.
        pg.get_by_role("button", name="Move", exact=True).click()
        pg.wait_for_selector("#stage form")
        choices = texts(pg, "#fTo option")
        check(choices == [f"Section {n}" for n in range(1, 13)] + ["Review and Practice tests"],
              "Move offers Section 1 to Section 12, and Review and Practice tests", choices)
        pg.get_by_label("Move Casey Lee to").select_option(label="Section 4")
        submit_form(pg, "Move")
        want = ("Move Casey Lee to Section 4? Scores and History are kept. Questions in skipped Sections are not added "
                "to Review. Any unfinished Set is dropped.")
        check(stage_text(pg).startswith(want), "Move asks first, in the decided words", stage_text(pg))
        pg.click("#confirmNo")
        pg.get_by_role("button", name="Cancel").click()
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["Section 1 of 12"], "saying no to Move changes nothing", texts(pg, ".now p"))
        pg.get_by_role("button", name="Move", exact=True).click()
        pg.get_by_label("Move Casey Lee to").select_option(label="Section 4")
        submit_form(pg, "Move")
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["Section 4 of 12"], "after Move, the Learner's page says Section 4", texts(pg, ".now p"))
        check(texts(pg, ".sessions > li")[0].endswith("Moved to Section 4"), "Study sessions has a Moved to Section 4 line",
              texts(pg, ".sessions > li"))
        reload(cpg)
        check(wait_for_h1(cpg, "Section 4 of 12") == "Section 4 of 12", "the Learner's next app open shows Section 4", h1(cpg))
        cctx.close()

        # Delete: the Helper types the Learner's name to turn on the button.
        pg.get_by_role("button", name="Delete", exact=True).click()
        pg.wait_for_selector("#deleteBtn")
        want = "Delete Casey Lee and all of Casey Lee's progress and History? This cannot be undone."
        check(want in stage_text(pg), "Delete asks first, in the decided words", stage_text(pg))
        delete = pg.get_by_role("button", name="Delete Casey Lee")
        check(delete.is_disabled(), "Delete is turned off until the name is typed")
        typed = pg.get_by_label("Type Casey Lee to delete")
        for wrong in ("Casey", "Casey Le", "Jordan", "CaseyLee"):
            typed.fill(wrong)
            check(delete.is_disabled(), f"typing {wrong!r} leaves Delete turned off")
        typed.fill("  casey LEE ")
        check(delete.is_enabled(), "the name typed with other capitals and spaces at the start and end turns Delete on")
        pg.get_by_role("button", name="No, keep Casey Lee").click()
        pg.wait_for_selector("#stage .manage")
        check(h1(pg) == "Casey Lee", "saying no keeps the Learner", h1(pg))
        pg.get_by_role("button", name="Delete", exact=True).click()
        pg.get_by_label("Type Casey Lee to delete").fill("Casey Lee")
        pg.get_by_role("button", name="Delete Casey Lee").click()
        check(learner_names(pg) == ["Jordan"], "after Delete, the list loads again without the Learner", learner_names(pg))
        check(texts(pg, ".note") == ["Casey Lee is deleted."], "the list says the Learner is deleted", texts(pg, ".note"))
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
    ctx.add_init_script(WATCH_OLD_KEY)
    pg = ctx.new_page()
    open_page(pg, inst.url)
    old = json.dumps({"day": 7, "last": {}, "tests": [], "scores": {}})
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [OLD_KEY, old])
    sign_in(pg, name, password)
    check(h1(pg) == "Section 1 of 12", "a new Learner starts at Section 1, whatever the old saved state says")

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
    calls = pg.evaluate("window.oldKeyCalls")
    check(calls == ["setItem"], f"signing in and finishing a Set don't touch tn-permit-daily-v1 (calls: {calls})")
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

    calls = pg.evaluate("window.oldKeyCalls")
    check(calls == [], f"opening the app doesn't touch tn-permit-daily-v1 (calls: {calls})")
    check(pg.evaluate("([k]) => localStorage.getItem(k)", [OLD_KEY]) == old,
          "the old saved state under tn-permit-daily-v1 is untouched")
    pg.goto(inst.url + "#section9")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Section 6 of 12", "#section9 does nothing")
    pg.goto(inst.url + "?r=1#restart")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Section 6 of 12" and not pg.query_selector("#yes"), "#restart does nothing")
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
        check_helper_helpers(browser, inst)
        check_helper_view(browser)
        check_manage_learner(browser)

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
