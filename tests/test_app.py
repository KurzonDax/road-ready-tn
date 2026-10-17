#!/usr/bin/env python3
"""Click through the built page in a real (headless) browser, served by the real server.

Needs Playwright with Chromium:  pip install playwright && playwright install chromium
Run after building:              python3 build.py && python3 tests/test_app.py
Run some checks only:            python3 tests/test_app.py check_engine check_helper_view
Before committing, also run:     python3 tests/check_dist.py  (fails if dist/ is out of date)

Starts `python -m server` with a temporary Instance folder, makes a Helper with
`python -m server.manage add --password-stdin` and a Learner straight into the
database, and signs in through the page like a person would.

Covers the sign-in screen (its wording, the mismatch and pause messages, each role
landing on its own screen, sign-out, and a sign-in that has ended) and the path the
Learner takes (docs/specs/learning-engine.md): a new Learner's first Set of first looks,
rule screens and counted questions with the gap between them, a wrong answer's re-ask,
Set done, the next Set opening with the missed fact, a fact due again 13 hours later
but not a minute later, the line naming the question a wrong choice answers, every fact
learned, Practice tests up to the "ready" screen, saving a Set across a reload and picking
it up again, and every screen at 375 px wide. The learning engine runs on fixtures in the
page: standings, the due order, the Section cursor, old records, retention, and buildSet()'s
gap rule over 500 random histories. Progress is worked out from the Learner's records on
the server: finished Sets stored as records and shown again in a fresh browser, a Reset and a
Move put straight into the database, a record that waits when the server can't be
reached, and the removed #restart / #sectionN links doing nothing. Offline (context.set_offline): a
Set finished offline sent once on reconnecting, a long wait sent in parts, an
unfinished Set continued on a second device (the newest wins), the one-time import
of the old tn-permit-daily-v1 state (once, never for a Helper, the old key left
alone), and sign-out refusing offline, sending waiting records first and deleting
that Learner's device copy. The Helper's view: studySessions() and missedMost()
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

HELPER = ("Avery", "helper password")
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
            inst.add_helper("Avery", "helper password")
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


def screen_kind(pg):
    """The kind of screen on show in a Set (first_look, rule, counted, reask), or None outside one."""
    return pg.evaluate("run ? run.screens[run.i].kind : null")


def click_choice(pg, right=True):
    """Click the right answer to the question on screen, or the one after it in the list."""
    opts = pg.query_selector_all("button.opt")
    want = pg.evaluate("BY_ID[run.screens[run.i].id].a")
    k = [o.inner_text().split("\n", 1)[-1].strip() for o in opts].index(want)
    opts[k if right else (k + 1) % len(opts)].click()


def answer_set(pg, miss=0, stop=None):
    """Go through every screen of the Set on show to its end: each first look gets the right answer,
    each rule screen is gone on from, and every counted question and re-ask is answered right except
    the first `miss` counted ones. With `stop`, answer only that many counted questions and re-asks and
    leave the last one's feedback on screen. Returns how many counted questions and re-asks were answered."""
    n = missed = 0
    while (kind := screen_kind(pg)) is not None:
        if kind == "rule":
            pg.click("#ruleGoBtn")
            continue
        wrong = kind == "counted" and missed < miss
        missed += wrong
        click_choice(pg, right=not wrong)
        if kind == "first_look":
            continue
        if not pg.query_selector(".src"):
            failures.append(f"no manual quote shown after answering {pg.evaluate('run.screens[run.i].id')}")
        n += 1
        if n == stop:
            break
        pg.click("#nextBtn")
    return n


def answer_one(pg, right=True):
    """Go on past first looks and rule screens to the next counted question or re-ask, and answer it."""
    while screen_kind(pg) in ("first_look", "rule"):
        if screen_kind(pg) == "rule":
            pg.click("#ruleGoBtn")
        else:
            click_choice(pg)
    click_choice(pg, right)


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
    ctx.on("request", lambda r: requested.append(r.url))  # the context also sees the service worker's requests
    open_page(pg, url)
    check(stage_text(pg) == "Sign in Type the name and password you were given. Name Password Show password Sign in",
          f"signed out, the page shows only the sign-in screen, worded as decided (got {stage_text(pg)!r})")
    pg.wait_for_function("() => !!navigator.serviceWorker.controller", timeout=10000)
    time.sleep(1)  # time for the service worker to fetch anything it would after taking control
    check(any(u.endswith("/sw.js") for u in requested) and not any(u.endswith("questions.json") for u in requested),
          "signed out, neither the page nor its service worker asks for questions.json", requested)
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
    check(h1(pg) == "Set 1", "a Learner lands on the study path (the name matched ignoring capitals and spaces)")
    fine = pg.evaluate("""() => { const b = [...document.querySelectorAll('.home button')].find(b => b.textContent === 'Sign out');
        const fine = b && b.closest('.fine');
        return !!fine && fine.textContent.includes('This is a practice app.'); }""")
    check(fine, "the Learner's home screen has Sign out in the fine print beside the practice-app notice")
    pg.get_by_role("button", name="Sign out").click()
    check(stage_text(pg) == "Sign out? You will need your name and password to sign in again. Yes, sign out No, stay signed in",
          f"Sign out asks first (got {stage_text(pg)!r})")
    pg.get_by_role("button", name="No, stay signed in").click()
    check(h1(pg) == "Set 1" and me_status(pg) == 200, "No, stay signed in goes back home, still signed in")
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
    check(h1(pg) == "Set 2", "signing in again goes back to where the Learner was")
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
        check(h1(pg) == "Set 1", "online, the Learner signs in and sees Set 1")
        try:
            pg.wait_for_function("() => !!navigator.serviceWorker.controller", timeout=10000)
        except PlaywrightTimeout:
            check(False, "the page registers a service worker that takes control of it")
            return

        ctx.set_offline(True)
        reload(pg)
        check(h1(pg) == "Set 1", "with no connection, opening the app again shows the study path")
        pg.click("#startBtn")
        check(answer_set(pg, miss=1) == 6 and pg.inner_text(".home h2") == "Set done.",
              "with no connection, a whole Set can be answered")
        pg.click("#homeBtn")
        check(h1(pg) == "Set 2", "and the home screen moves on to Set 2")
        fonts = pg.evaluate("""document.fonts.check('800 18px Overpass')
                               && document.fonts.check('400 18px "Atkinson Hyperlegible"')""")
        check(fonts, "with no connection, the page still has its fonts")

        ctx.set_offline(False)
        reload(pg)
        pg.evaluate("fetch('/api/me').then(r => r.status)")
        pg.evaluate("fetch('/fonts/overpass/OFL.txt').then(r => r.status)")  # in fonts/, but not a file sw.js lists
        kept = cached(pg)
        static = sorted(k[1].lstrip("/") for k in kept if k[0] == f"rrtn-static-{v1}")
        listed = sorted(json.loads(re.search(r"const STATIC_FILES = (\[.*?\]);", (inst.root / "dist" / "sw.js").read_text()).group(1)))
        check(static == listed, "the static cache holds exactly the files build.py lists in sw.js", static)
        api = [k for k in kept if k[1].startswith("/api/")]
        check(kept and not api, f"no /api/ answer is in any cache (got {api})")
        pages = sorted(k[1] for k in kept if k[0] == "rrtn-pages")
        check(pages == ["/", "/questions.json"], f"rrtn-pages keeps only the page and questions.json (got {pages})")
        names = sorted({k[0] for k in kept})
        check(names == ["rrtn-pages", f"rrtn-static-{v1}"],
              f"the fonts, icons and manifest are kept under this build's version (got {names})")

        print("\n[signed in before the service worker takes control]")
        ctx2 = browser.new_context()
        held = []
        ctx2.route("**/sw.js", lambda route: held.append(route))  # the worker script waits until the Learner has signed in
        pg2 = ctx2.new_page()
        asked = []
        ctx2.on("request", lambda r: asked.append(r.url) if r.url.endswith("questions.json") else None)
        open_page(pg2, inst.url)
        sign_in(pg2, *LEARNER)
        check(held and len(asked) == 1 and not pg2.evaluate("!!navigator.serviceWorker.controller"),
              "the page got its questions before any service worker controlled it", asked)
        held[0].continue_()
        pg2.wait_for_function("() => !!navigator.serviceWorker.controller", timeout=10000)
        wait_until(lambda: ["rrtn-pages", "/questions.json"] in cached(pg2), 5)
        ctx2.set_offline(True)
        reload(pg2)
        check(stage_text(pg2).startswith("Set 2"), "with no connection, the next open still shows the study path",
              stage_text(pg2))
        ctx2.close()

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


def hours(h):
    """A record time `h` hours (a float) after a fixed start, in the page's toISOString() form."""
    t = datetime.datetime(2026, 10, 1, 12, tzinfo=datetime.UTC) + datetime.timedelta(hours=h)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def daily(n, answers, group=None, reset=None, seq=None):
    """A finished daily Set. `answers` is a list of (question id, right, hour) or (question id, right,
    hour, role); the role is counted unless given. The Set finishes at its last answer."""
    rows = [a if len(a) == 4 else (*a, "counted") for a in answers]
    last = max(h for _, _, h, _ in rows)
    return {"id": f"record-{n:012d}", "kind": "set", "reset": reset, "at": hours(last), "data": {
        "set_id": f"set-{n}", "type": "daily", "section": None, "group": group, "started_at": hours(rows[0][2]),
        "answers": [{"q": q, "chosen": "an answer", "right": right, "at": hours(h), "role": role, "format": "choice"}
                    for q, right, h, role in rows]}, **({} if seq is None else {"seq": seq})}


# Checks buildSet's rules over `n` random histories, in both FIRST_LOOK modes; returns what broke.
BUILD_SET_PROPERTIES = """n => {
  const ids = QS.map(q => q.id), problems = [], H = 3600e3, t0 = Date.parse('2026-10-01T12:00:00Z');
  const rnd = Math.random;
  for (let k = 0; k < n; k++) {
    const answers = [], answered = k % 7 < 6 ? [0, 3, 40, 115, 118, 120][k % 7] : Math.floor(rnd() * 121);
    for (const id of shuffle(ids).slice(0, answered)) {
      for (let j = 0, times = 1 + Math.floor(rnd() * 5); j < times; j++)
        answers.push({ q: id, chosen: 'x', right: rnd() < 0.8, at: new Date(t0 + rnd() * 30 * 24 * H).toISOString() });
    }
    const records = answers.length ? [{ id: 'record-' + k, kind: 'set', reset: null, at: new Date(t0).toISOString(),
      data: { set_id: 's' + k, type: 'test', section: null, answers } }] : [];
    const p = progressFrom(records), now = t0 + rnd() * 40 * 24 * H, due = dueFacts(p, now).length;
    for (const firstLook of [true, false]) {
      const screens = buildSet(p, now, firstLook), say = what => problems.push(`history ${k}, FIRST_LOOK ${firstLook}: ${what}`);
      const counted = screens.filter(s => s.kind === 'counted'), rules = screens.filter(s => s.kind === 'rule');
      if (counted.length > COUNTED_TARGET) say(`${counted.length} counted questions`);
      if (counted.length < Math.min(MIN_SET, ids.length)) say(`only ${counted.length} counted questions`);
      if (new Set(counted.map(s => s.id)).size !== counted.length) say('a fact asked twice');
      if (rules.length > NEW_PER_SET) say(`${rules.length} new facts`);
      if (due >= 10 && rules.length) say(`${due} due and still ${rules.length} new facts`);
      if (screens.filter(s => s.kind === 'first_look').length !== (firstLook ? rules.length : 0)) say('first looks do not match rules');
      let least = Infinity;
      screens.forEach((s, i) => {
        if (s.kind !== 'rule') return;
        if (p.facts[s.id].asked) say(`a rule screen for ${s.id}, which is not new`);
        if (firstLook && (screens[i - 1] || {}).kind !== 'first_look') say(`no first look right before the rule for ${s.id}`);
        const j = screens.findIndex((c, x) => x > i && c.id === s.id);
        if (j < 0 || screens[j].kind !== 'counted') return say(`no counted question after the rule for ${s.id}`);
        least = Math.min(least, j - i - 1);
        if (j - i - 1 < GAP) say(`only ${j - i - 1} screens between the rule and counted question for ${s.id}`);
      });
      if (!due && answered <= ids.length - NEW_PER_SET && (rules.length !== NEW_PER_SET || least !== GAP))
        say(`nothing due: ${rules.length} new facts and a gap of ${least}`);
    }
  }
  return problems;
}"""


def check_engine(browser, inst):
    """Standings, due order, the Section cursor, buildSet and retention, on fixtures run in the page itself."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, *HELPER)
    ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
    s1, s2, s3 = ids["1"], ids["2"], ids["3"]
    a, b, c = s1[0], s1[1], s1[2]

    def fact(records, q, now=None):
        """A fact's standing, spaced successes and whether it is due `now` hours in."""
        return pg.evaluate("([r, q, now]) => { const p = progressFrom(r), f = p.facts[q]; return {standing: standing(f),"
                           " spaced: f.spacedRights, due: isDue(f, Date.parse(now))}; }", [records, q, hours(now or 0)])

    print("\n[standings]")
    check(fact([], a) == {"standing": "new", "spaced": 0, "due": False}, "a fact with no answers is new and not due",
          fact([], a))
    got = fact([daily(1, [(a, False, 0)])], a, 1)
    check(got == {"standing": "seen", "spaced": 0, "due": True}, "one wrong answer makes it seen, and due", got)
    one = [daily(1, [(a, True, 0)])]
    check(fact(one, a, 1) == {"standing": "learned", "spaced": 1, "due": False}, "one right answer makes it learned",
          fact(one, a, 1))
    check(fact(one, a, 11.9)["due"] is False and fact(one, a, 12)["due"] is True,
          "a fact right once is due again 12 hours later, not sooner")
    two = [daily(1, [(a, True, 0)]), daily(2, [(a, True, 11)])]
    got = fact(two, a, 12)
    check(got == {"standing": "learned", "spaced": 1, "due": False},
          "two right answers 11 hours apart count as one spaced success (and the ladder starts from the newer)", got)
    three = [daily(1, [(a, True, 0)]), daily(2, [(a, True, 13)]), daily(3, [(a, True, 26)])]
    check(fact(three[:2], a, 13 + 47.9)["due"] is False and fact(three[:2], a, 13 + 48)["due"] is True,
          "after two spaced successes the fact is due 48 hours later")
    got = fact(three, a, 27)
    check(got == {"standing": "solid", "spaced": 3, "due": False}, "three right answers 13 hours apart make it solid", got)
    check(fact(three, a, 26 + 167.9)["due"] is False and fact(three, a, 26 + 168)["due"] is True,
          "a solid fact is due again 7 days later")
    got = fact(one + [daily(2, [(a, False, 14)])], a, 15)
    check(got == {"standing": "learned", "spaced": 1, "due": True}, "a wrong answer after a right one keeps it learned "
          "and makes it due now", got)
    got = fact(three + [daily(4, [(a, False, 30)])], a, 31)
    check(got["standing"] == "solid" and got["due"], "a wrong answer never lowers a standing", got)
    got = fact([daily(1, [(a, False, 0, "first_look"), (a, True, 0.1, "counted"), (a, False, 0.2, "reask")])], a, 1)
    check(got == {"standing": "learned", "spaced": 1, "due": False}, "first looks and re-asks never change a standing", got)

    print("\n[due order]")
    recs = [daily(1, [(s2[0], True, 0), (s2[1], True, 0), (s2[1], True, 13), (s2[1], True, 26), (s2[2], True, 1)]),
            daily(2, [(s2[3], True, 2), (s2[3], False, 5), (s2[4], False, 3)])]
    got = pg.evaluate("([r, now]) => dueFacts(progressFrom(r), Date.parse(now))", [recs, hours(400)])
    check(got == [s2[4], s2[3], s2[0], s2[2], s2[1]],
          "wrong last first (oldest first), then learned facts, then solid ones (earliest due first)", got)

    print("\n[old records]")
    reset = "record-000000000005"
    old = [set_record(1, "day", 1, 10, [(q, q != a) for q in s1], seq=1),
           set_record(2, "redo", 1, 20, [(a, True)], seq=2),
           set_record(3, "review", None, 30, [(b, False)], seq=3),
           record(4, "move", 40, {"to": 6}, seq=4),
           record(7, "imported", 45, {"state": {"day": 9, "last": {s3[0]: True, s3[1]: False, s3[2]: "yes", "gone": True},
                                               "scores": {"1": 10}, "tests": [28, "29", 25]}}, seq=5),
           set_record(6, "test", None, 50, [(c, True)], seq=6)]
    got = pg.evaluate("r => { const p = progressFrom(r); return {cursor: p.cursor, unlock: p.unlockMove, tests: p.tests,"
                      " sets: p.sets, a: standing(p.facts[QS[0].id]), b: standing(p.facts[QS[1].id]),"
                      " s3: [0, 1, 2].map(k => standing(p.facts[QS[20 + k].id])), learned: learnedCount(p)}; }", old)
    check(got == {"cursor": 6, "unlock": False, "tests": [28, 25, 1], "sets": 0, "a": "learned", "b": "learned",
                  "s3": ["learned", "seen", "new"], "learned": 11},
          "day, redo, review, test, imported and move records give standings, test scores and the Section cursor", got)
    got = pg.evaluate("r => { const p = progressFrom(r); return [p.cursor, p.unlockMove, unlocked(p)]; }",
                      old + [record(8, "move", 60, {"to": 13}, seq=8)])
    check(got == [6, True, True], "a Move to 13 unlocks Practice tests and keeps the Section cursor", got)
    got = pg.evaluate("r => { const p = progressFrom(r); return [p.cursor, learnedCount(p), p.tests, p.sets]; }",
                      old + [record(5, "reset", 70, {}, seq=9), daily(9, [(a, True, 2)], reset=reset, seq=10)])
    check(got == [1, 1, [], 1], "after a Reset only the records naming it count, and the Set number starts again", got)

    print("\n[buildSet]")
    got = pg.evaluate("""() => buildSet(progressFrom([]), Date.now(), true).map(s => s.kind + ' ' + s.id)""")
    want = [f"{k} {q}" for q in s1[:5] for k in ("first_look", "rule")] + [f"counted {q}" for q in s1[:5]]
    check(got == want, "a new Learner's first Set: 5 first looks, each with its rule, then the 5 counted questions", got)
    got = pg.evaluate("""() => buildSet(progressFrom([]), Date.now(), false).map(s => s.kind + ' ' + s.id)""")
    check(got == [f"rule {q}" for q in s1[:5]] + [f"counted {q}" for q in s1[:5]],
          "with FIRST_LOOK false, 5 rule screens and then the 5 counted questions", got)
    moved = [record(1, "move", 0, {"to": 12}, seq=1), daily(2, [(q, True, 1) for q in ids["12"][:8]], seq=2)]
    got = pg.evaluate("r => setPlan(progressFrom(r), Date.parse('2026-10-01T14:00:00Z')).fresh", moved)
    check(got == ids["12"][8:] + s1[:3], "new facts come from the Section cursor on, then round to Section 1", got)
    got = pg.evaluate("r => setPlan(progressFrom(r), Date.parse('2026-10-01T14:00:00Z'))",
                      [daily(1, [(q, False, 1) for q in s1 + s2[:2]])])
    check(len(got["due"]) == 10 and got["fresh"] == [] and got["fill"] == [], "with 10 or more due, a Set is 10 due facts and no new ones", got)
    everything = [daily(1, [(q["id"], True, 1) for q in pg.evaluate("QS")])]
    got = pg.evaluate("r => setPlan(progressFrom(r), Date.parse('2026-10-01T14:00:00Z'))", everything)
    check(got["due"] == [] and got["fresh"] == [] and len(got["fill"]) == 5,
          "with nothing due and nothing new, a Set is 5 fill facts", got)
    problems = pg.evaluate(BUILD_SET_PROPERTIES, 500)
    check(problems == [], "over 500 random histories, in both FIRST_LOOK modes: at least GAP screens for other facts "
          "between each rule and its counted question, at most 5 new and 10 counted, never fewer than 5", problems[:5])

    print("\n[retention]")
    for answers, want, what in (
            ([(a, True, 0), (a, False, 13)], {"right": 0, "of": 1}, "a right answer followed by a wrong 13 hours later is 0 of 1"),
            ([(a, True, 0), (a, False, 11)], {"right": 0, "of": 0}, "followed 11 hours later it counts nothing"),
            ([(a, True, 0), (a, True, 12), (b, True, 0), (b, False, 0.5), (b, True, 20)], {"right": 1, "of": 1},
             "only pairs of consecutive answers on one fact count")):
        got = pg.evaluate("([r, now]) => retention(progressFrom(r), Date.parse(now)).all", [[daily(1, answers)], hours(30)])
        check(got == want, what, got)
    got = pg.evaluate("([r, now]) => retention(progressFrom(r), Date.parse(now))",
                      [[daily(1, [(a, True, 0), (a, True, 13), (b, True, 300), (b, False, 320)])], hours(400)])
    check(got == {"all": {"right": 1, "of": 2}, "recent": {"right": 0, "of": 1}},
          "the last 14 days count only pairs whose second answer is in them", got)
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
    missedMost(), and the wording of where a Learner is."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, *HELPER)
    ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
    qs = pg.evaluate("QS.map(q => q.id)")
    s1, s2, s4 = ids["1"], ids["2"], ids["4"]

    def run(fn, arg):
        return pg.evaluate(f"x => {fn}(x)", arg)

    def daily_set(n, answers, reset=None, seq=None):
        """A daily Set whose answers each have their own time: (question id, right, minute, role)."""
        return record(n, "set", max(a[2] for a in answers), {
            "set_id": f"set-{n}", "type": "daily", "section": None, "group": None, "started_at": at(answers[0][2]),
            "answers": [{"q": q, "chosen": "x", "right": right, "at": at(m), "role": role, "format": "choice"}
                        for q, right, m, role in answers]}, reset, seq)

    print("\n[Helper's view: Study sessions]")
    # A gap of 29 minutes keeps one Study session; a gap of 31 starts a new one. A Set whose
    # answers fall in two Study sessions counts as finished in the later one.
    got = run("studySessions", [
        timed_set(1, "day", 1, [(s1[0], "x", True, 0), (s1[1], "x", True, 1), (s1[2], "x", False, 2)], seq=1),
        timed_set(2, "day", 2, [(s2[0], "x", True, 31), (s2[1], "x", True, 32)], seq=2),
        timed_set(3, "redo", 1, [(s1[0], "x", True, 63)], seq=3),
        timed_set(4, "review", None, [(s1[2], "x", True, 100), (s1[2], "x", True, 200)], seq=4)])
    check(got == [
        {"kind": "session", "start": at(200), "end": at(200), "sets": [{"type": "review", "section": None, "number": None, "right": 2, "of": 2}]},
        {"kind": "session", "start": at(100), "end": at(100), "sets": []},
        {"kind": "session", "start": at(63), "end": at(63), "sets": [{"type": "redo", "section": 1, "number": None, "right": 1, "of": 1}]},
        {"kind": "session", "start": at(0), "end": at(32), "sets": [{"type": "day", "section": 1, "number": None, "right": 2, "of": 3},
                                                                    {"type": "day", "section": 2, "number": None, "right": 2, "of": 2}]}],
        "Study sessions, newest first, split by a 31-minute gap but not by a 29-minute one", got)
    check(run("studySessions", []) == [], "no records is no Study sessions")

    # A Reset and Moves are lines of their own; daily Sets are numbered from the latest Reset, and
    # count only their counted answers.
    reset = "record-000000000002"
    history = [daily_set(1, [(s1[0], True, 0, "counted")], seq=1), record(2, "reset", 40, {}, seq=2),
               record(3, "move", 50, {"to": 4}, reset=reset, seq=3),
               daily_set(4, [(s4[0], True, 79, "first_look"), (s4[0], False, 80, "counted"), (s4[0], True, 81, "reask"),
                             (s4[1], True, 82, "counted")], reset=reset, seq=4),
               record(5, "move", 90, {"to": 13}, reset=reset, seq=5)]
    got = run("studySessions", history)
    check(got == [{"kind": "move", "at": at(90), "to": 13},
                  {"kind": "session", "start": at(79), "end": at(82), "sets": [{"type": "daily", "section": None, "number": 1, "right": 1, "of": 2}]},
                  {"kind": "move", "at": at(50), "to": 4},
                  {"kind": "reset", "at": at(40)},
                  {"kind": "session", "start": at(0), "end": at(0), "sets": [{"type": "daily", "section": None, "number": 1, "right": 1, "of": 1}]}],
          "Study sessions keep the Sets from before a Reset, number daily Sets from each Reset, and count only counted answers", got)
    got = pg.evaluate("h => studySessions(h).map(historyLine)", history)
    check(got[0] == "Unlocked practice tests" and got[2] == "Started new facts from Section 4"
          and got[3] == "Progress reset by a Helper",
          "a Move and a Reset are worded as decided", got)
    got = [pg.evaluate("([t, s, n]) => setName(t, s, n)", x) for x in (("daily", None, 12), ("test", None, None),
                                                                      ("day", 3, None), ("redo", 3, None), ("review", None, None))]
    check(got == ["Set 12", "Practice test", "Section 3", "Section 3 again", "Review"], "Sets are named as decided", got)

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
    got = run("missedMost", [daily_set(1, [(qs[20], False, 0, "first_look"), (qs[20], False, 1, "counted"),
                                           (qs[20], False, 2, "reask")], seq=1)])
    check(got == [{"q": qs[20], "missed": 2, "answered": 2, "wrong": "x"}],
          "a first look is not a miss, but a counted answer and a re-ask are", got)

    print("\n[Helper's view: wording]")
    tests_all = s1 + s2 + ids["3"]

    def practice(n, minute, right):
        return timed_set(n, "test", None, [(q, "x", i < right, minute) for i, q in enumerate(tests_all)], seq=n)

    for records, want, next_set in (
            ([], "0 of 120 facts learned, 0 solid.", "Next set: 5 new."),
            ([daily_set(1, [(q, i > 1, 10, "counted") for i, q in enumerate(s1)], seq=1)],
             "8 of 120 facts learned, 0 solid.", "Next set: 2 come back, 5 new."),
            ([record(1, "move", 10, {"to": 13}, seq=1), practice(2, 20, 28), practice(3, 30, 27), practice(4, 40, 29)],
             "29 of 120 facts learned, 0 solid.", "Ready for the test: 3 practice tests in a row at 27 or more")):
        got = pg.evaluate("r => [whereNow(progressFrom(r)), nextSetLine(progressFrom(r), Date.parse('2026-10-01T13:00:00Z'))]", records)
        check(got == [want, next_set], f"where the Learner is reads {want!r} and {next_set!r}", got)

    def unfinished(kind, number, kinds, chosen):
        return {"kind": kind, "number": number, "i": 0, "answered": False, "set_id": "u", "started_at": at(0),
                "screens": [{"kind": k, "id": qs[n], "options": [], "chosen": "x" if n < chosen else None, "at": None}
                            for n, k in enumerate(kinds)]}

    old = {"kind": "day", "dayNum": 6, "i": 3, "answered": True, "set_id": "u", "started_at": at(0),
           "items": [{"id": q, "options": [], "chosen": None, "at": None} for q in qs[:10]]}
    for u, want in ((unfinished("daily", 4, ["first_look", "rule", "counted", "counted", "reask"], 3), "Unfinished: Set 4, 2 of 4 answered"),
                    (unfinished("test", 9, ["counted"] * 30, 4), "Unfinished: Practice test, 4 of 30 answered"),
                    (old, "Unfinished: Section 6, 4 of 10 answered")):
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
        # The next morning: s1[2] right again 20 hours later, s1[3] wrong, and s2[5] wrong six times.
        next_day = [(s1[2], True, 24), (s1[3], False, 24 + 1 / 60)] + [(s2[5], False, 24 + k / 60) for k in range(2, 8)]
        store_history(inst, casey, [
            section(1, "day", 1, 0),                                   # 7:00 AM, before the Reset
            record(2, "reset", 30, {}),                                # 7:30 AM
            section(3, "day", 1, 60, wrong=(0,), reset=reset),         # 8:00 AM
            section(4, "day", 2, 75, wrong=(0, 1), reset=reset),       # 8:15 AM, same Study session
            record(5, "move", 100, {"to": 4}, reset=reset),            # 8:40 AM
            section(6, "redo", 1, 200, wrong=(0, 1), reset=reset),     # 10:20 AM
            timed_set(7, "test", None, [(q, qs[q]["o"][1] if i >= 28 else qs[q]["a"], i < 28, 300)
                                        for i, q in enumerate(tests)], reset=reset),  # 12:00 PM
            daily(8, next_day, reset=reset)],                          # 7:00 AM the next day
            unfinished={"kind": "daily", "number": 2, "i": 4, "answered": True, "set_id": "unfinished-set",
                        "started_at": hours(30), "after": None, "group": None, "reasks": 0,
                        "screens": [{"kind": "counted", "id": q, "format": "choice", "options": [qs[q]["a"], *qs[q]["o"]],
                                     "chosen": qs[q]["a"] if i < 5 else None, "at": hours(30) if i < 5 else None}
                                    for i, q in enumerate(ids["4"])]})
        reload(pg)
        pg.wait_for_selector("#stage .learners")
        rows = texts(pg, ".learners li")
        check(rows == ["Casey 45 of 120 facts learned, 0 solid. Last studied October 2, 2026",
                       "Wolfeschlegelsteinhausenbergerdorffvoralternwarengewissenhaft 0 of 120 facts learned, 0 solid. "
                       "Has not answered any questions yet."],
              "one row per Learner: the name, how many facts are learned, and the date they last studied", rows)
        last = pg.evaluate("[...document.querySelectorAll('#stage button')].pop()?.textContent")
        check(last == "Sign out", "Sign out is still the last button on the list")
        check(no_sideways_scroll(pg), "at 375 px wide, nothing on the list scrolls sideways")

        pg.get_by_role("button", name="Casey").click()
        pg.wait_for_selector("#stage .part")
        check(pg.inner_text("#stage h1") == "Casey", "the Learner's page opens with the Learner's name")
        check(texts(pg, ".now p") == ["45 of 120 facts learned, 0 solid.", "Next set: 10 come back.",
                                      "Unfinished: Set 2, 5 of 10 answered"],
              "Now: the facts learned, what the next Set holds, and the unfinished Set", texts(pg, ".now p"))
        check(texts(pg, ".retention p") == ["Of 3 times a fact was answered right and asked again at least 12 hours later, "
                                            "it was right 1 time.", "In the last 14 days: 0 of 0."],
              "Retention counts each right answer asked again 12 or more hours later", texts(pg, ".retention p"))
        sections = texts(pg, ".facts > ul > li > details > summary")
        check(len(sections) == 12 and sections[:3] == [
            f"Section 1: {pg.evaluate('DAYS[0].title')}: 9 of 10 learned, 0 solid",
            f"Section 2: {pg.evaluate('DAYS[1].title')}: 8 of 10 learned, 0 solid",
            f"Section 3: {pg.evaluate('DAYS[2].title')}: 0 of 10 learned, 0 solid"],
              "Facts has a part per Section with how many of its facts are learned and solid, since the Reset", sections[:3])
        pg.click(".facts > ul > li:nth-child(1) summary")
        pg.click(".facts > ul > li:nth-child(2) summary")
        rows = texts(pg, ".facts .sets li")
        check(rows[0] == f"{qs[s1[0]]['q']} Seen Asked 2, right 0 Last asked October 1, 2026"
              and rows[2] == f"{qs[s1[2]]['q']} Learned Asked 3, right 3 Last asked October 2, 2026",
              "each fact shows its standing, how often it was asked and right, and when it was last asked", rows[:3])
        check(rows[15] == f"{qs[s2[5]]['q']} Learned Asked 7, right 1 Last asked October 2, 2026 Needs a different question"
              and sum("Needs a different question" in r for r in rows) == 1,
              "a fact answered wrong 6 times says it needs a different question", rows[15])
        pg.click(".facts > ul > li:nth-child(3) summary")
        check(texts(pg, ".facts > ul > li:nth-child(3) .sets li")[0].endswith("New Asked 0, right 0 Not asked yet"),
              "a fact never asked says so")
        check(texts(pg, ".tests p, .tests li") == ["In a row so far: 1 of 3", "October 1, 2026, 12:00 PM: 28 of 30"],
              "Practice tests lists each test with its date and score, and the count in a row", texts(pg, ".tests p, .tests li"))
        missed = texts(pg, ".missedmost li")
        q = qs[s1[0]]
        check(len(missed) == 2 and missed[0].startswith(qs[s2[5]]["q"]) and "Missed 6 of 7 times" in missed[0]
              and missed[1] == f"{q['q']} Right answer: {q['a']} Wrong answer chosen most often: {q['o'][0]} "
                               f"Missed 2 of 2 times Driver manual, page {q['p']}",
              "Questions missed most counts only since the Reset and shows the question, answers, count and page", missed)
        check(texts(pg, ".sessions > li") == [
            "October 2, 2026, 7:00 AM 7 minutes Set 1: 1 of 8",
            "October 1, 2026, 12:00 PM Less than 1 minute Practice test: 28 of 30",
            "October 1, 2026, 10:20 AM 9 minutes Section 1 again: 8 of 10",
            "October 1, 2026, 8:40 AM Started new facts from Section 4",
            "October 1, 2026, 8:00 AM 24 minutes Section 1: 9 of 10 Section 2: 8 of 10",
            "October 1, 2026, 7:30 AM Progress reset by a Helper",
            "October 1, 2026, 7:00 AM 9 minutes Section 1: 10 of 10"],
            "Study sessions, newest first, cover the whole History with the Reset and the Move as lines",
            texts(pg, ".sessions > li"))
        heads = texts(pg, "#stage h2")
        check(heads == ["Retention", "Facts", "Practice tests", "Questions missed most", "Study sessions", "Manage this Learner"],
              "the Learner's page is in the decided order", heads)
        pg.eval_on_selector_all("#stage details", "els => els.forEach(d => d.open = true)")
        check(no_sideways_scroll(pg), "at 375 px wide, nothing on the Learner's page scrolls sideways")

        pg.get_by_role("button", name="Back to Learners").last.click()
        pg.wait_for_selector("#stage .learners")
        check(pg.inner_text("#stage h1") == "Learners", "Back to Learners returns to the list")
        pg.get_by_role("button", name="Wolfeschlegel").click()
        pg.wait_for_selector("#stage .part")
        check(no_sideways_scroll(pg), "a long name doesn't make the Learner's page scroll sideways")
        check(texts(pg, ".now p") == ["0 of 120 facts learned, 0 solid.", "Next set: 5 new."]
              and texts(pg, ".retention p") == ["No fact has been asked again 12 or more hours after a right answer yet."]
              and texts(pg, ".history p") == ["No Study sessions yet."]
              and texts(pg, ".tests p") == ["No Practice tests yet."]
              and texts(pg, ".missedmost p") == ["No question has been missed two or more times."],
              "a Learner with no records has a page that says so",
              [texts(pg, ".now p"), texts(pg, ".retention p"), texts(pg, ".history p"), texts(pg, ".tests p"), texts(pg, ".missedmost p")])
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


def stop_partway(pg, inst, learner_id, stop=True):
    """The Learner answers 2 counted questions of the next Set (and stops); wait until the server has that unfinished Set."""
    pg.click("#startBtn")
    answer_one(pg)
    pg.click("#nextBtn")
    answer_one(pg)
    i = pg.evaluate("run.i")
    if stop:
        pg.click("#quitBtn")
        pg.wait_for_selector("#resumeBtn")
    wait_until(lambda: (db_state(inst, learner_id)[1] or {}).get("i") == i)


def check_set_dropped(pg, inst, learner_id, what):
    """After a Reset or Move, the Set the Learner's device stopped partway through is gone, there and on the server."""
    check(pg.query_selector("#resumeBtn") is None and "stopped partway" not in stage_text(pg),
          f"after {what}, the Learner's device no longer offers the Set it stopped partway through", stage_text(pg))
    time.sleep(0.5)
    reload(pg)
    check(pg.query_selector("#resumeBtn") is None, "not after another app open either")
    check(db_state(inst, learner_id)[1] is None, "and the server doesn't keep that Set",
          db_state(inst, learner_id)[1])


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
                ("avery", "new password", "Another account already uses that name. Choose a different name.")]:
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
        check(h1(lpg) == "Set 1", "the new Learner can sign in, and starts at Set 1", h1(lpg))

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
        check(paused == ["0 of 120 facts learned, 0 solid.", "Next set: 5 new.", want],
              "under where they are now, the paused line says until when", paused)

        pg.get_by_role("button", name="Reset sign-in").click()
        pg.get_by_label("New password", exact=True).fill("jordan new password")
        submit_form(pg, "Set the new password")
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(len(texts(pg, ".now p")) == 2, "after Reset sign-in, the paused line is gone", texts(pg, ".now p"))
        check(texts(pg, ".note") == ["Jordan's new password is set."], "the Learner's page says the new password is set",
              texts(pg, ".note"))
        check(me_status(lpg) == 401, "Reset sign-in signs the Learner out on their device")
        check(tpg.evaluate(sign_in_status, "jordan password") == 401, "after Reset sign-in, the old password fails")
        tries.close()
        open_page(lpg, inst.url)
        sign_in(lpg, "Jordan", "jordan new password")
        check(h1(lpg) == "Set 1", "the new password signs the Learner in", h1(lpg))
        lctx.close()

        # Reset progress. Casey Lee has finished Sections 1 and 2 and is signed in on a device of their own.
        ids = pg.evaluate("Object.fromEntries(DAYS.map(d => [d.day, QS.filter(q => q.day === d.day).map(q => q.id)]))")
        store_history(inst, casey, [set_record(1, "day", 1, 0, [(q, True) for q in ids["1"]]),
                                    set_record(2, "day", 2, 20, [(q, i > 0) for i, q in enumerate(ids["2"])])])
        cctx = browser.new_context()
        cpg = cctx.new_page()
        open_page(cpg, inst.url)
        sign_in(cpg, "Casey Lee", "casey password")
        check(texts(cpg, ".home .theme")[0] == "19 of 120 facts learned. 0 solid.", "Casey Lee has 19 facts learned",
              texts(cpg, ".home .theme"))
        stop_partway(cpg, inst, casey)
        pg.get_by_role("button", name="Back to Learners").first.click()
        open_learner(pg, "Casey Lee")
        pg.get_by_role("button", name="Reset progress").click()
        want = ("Put Casey Lee back at the start of Section 1? Every fact goes back to new, and Practice tests start over. "
                "The History of finished Sets is kept.")
        check(stage_text(pg).startswith(want), "Reset progress asks first, in the decided words", stage_text(pg))
        pg.click("#confirmNo")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["19 of 120 facts learned, 0 solid.", "Next set: 10 come back.",
                                      "Unfinished: Set 1, 2 of 10 answered"],
              "saying no to Reset progress changes nothing", texts(pg, ".now p"))
        pg.get_by_role("button", name="Reset progress").click()
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["0 of 120 facts learned, 0 solid.", "Next set: 5 new."],
              "after Reset progress, the Learner's page says no fact is learned", texts(pg, ".now p"))
        sessions = texts(pg, ".sessions > li")
        check(len(sessions) == 2 and sessions[0].endswith("Progress reset by a Helper")
              and sessions[1].endswith("Section 1: 10 of 10 Section 2: 9 of 10"),
              "Study sessions still shows the old Sets, under a Progress reset by a Helper line", sessions)
        reload(cpg)
        wait_for_stage_text(cpg, "0 of 120 facts learned.")
        check("5 new rules, one at a time." in stage_text(cpg), "the Learner's next app open starts from no facts learned",
              stage_text(cpg))
        check_set_dropped(cpg, inst, casey, "Reset progress")
        # This time the Set is still on the Learner's screen when the Helper moves them.
        stop_partway(cpg, inst, casey, stop=False)
        shown = cpg.evaluate("unfinishedLine(packRun(run))")

        # Move: where new facts come from, Section 1 to 12, or unlock Practice tests.
        pg.get_by_role("button", name="Move", exact=True).click()
        pg.wait_for_selector("#stage form")
        choices = texts(pg, "#fTo option")
        check(choices == [f"Start new facts from Section {n}" for n in range(1, 13)] + ["Unlock practice tests now"],
              "Move offers new facts from Section 1 to Section 12, and unlocking practice tests", choices)
        pg.get_by_label("What to change for Casey Lee").select_option(label="Start new facts from Section 4")
        submit_form(pg, "Move")
        want = ("Start new facts from Section 4 for Casey Lee? Every fact keeps its standing, and the History is kept. "
                "Any unfinished Set is dropped. Yes, start new facts from Section 4")
        check(stage_text(pg).startswith(want), "Move asks first, in the decided words", stage_text(pg))
        pg.click("#confirmNo")
        pg.get_by_role("button", name="Cancel").click()
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".now p") == ["0 of 120 facts learned, 0 solid.", "Next set: 5 new.", shown],
              "saying no to Move changes nothing", [texts(pg, ".now p"), shown])
        pg.get_by_role("button", name="Move", exact=True).click()
        pg.get_by_label("What to change for Casey Lee").select_option(label="Start new facts from Section 4")
        submit_form(pg, "Move")
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".note") == ["Casey Lee's new facts now come from Section 4."] and len(texts(pg, ".now p")) == 2,
              "after Move, the Learner's page says where new facts come from, and the unfinished Set is gone",
              [texts(pg, ".note"), texts(pg, ".now p")])
        check(texts(pg, ".sessions > li")[0].endswith("Started new facts from Section 4"),
              "Study sessions has a Started new facts from Section 4 line", texts(pg, ".sessions > li"))
        cpg.click("#nextBtn")
        answer_one(cpg)
        i = cpg.evaluate("run.i")
        check(wait_until(lambda: (db_state(inst, casey)[1] or {}).get("i") == i),
              "an answer given after the Move sends that Set to the server again")
        reload(cpg)
        wait_for_stage_text(cpg, "0 of 120 facts learned.")
        check(cpg.evaluate("setPlan(S, Date.now()).fresh") == ids["4"][:5] and texts(cpg, ".road .now") == ["4 Section 4, next"],
              "the Learner's next app open takes new facts from Section 4", texts(cpg, ".road .now"))
        check_set_dropped(cpg, inst, casey, "Move")
        pg.get_by_role("button", name="Move", exact=True).click()
        check(pg.eval_on_selector("#fTo", "s => s.selectedOptions[0].textContent") == "Start new facts from Section 4",
              "Move starts from where new facts come from now")
        pg.get_by_label("What to change for Casey Lee").select_option(label="Unlock practice tests now")
        submit_form(pg, "Move")
        check(stage_text(pg).startswith("Unlock practice tests now for Casey Lee?"), "unlocking asks first", stage_text(pg))
        pg.click("#confirmYes")
        pg.wait_for_selector("#stage .manage")
        check(texts(pg, ".note") == ["Practice tests are unlocked for Casey Lee."]
              and texts(pg, ".sessions > li")[0].endswith("Unlocked practice tests"),
              "after unlocking, the Learner's page says so", texts(pg, ".note"))
        reload(cpg)
        wait_for_stage_text(cpg, "Practice tests")
        check(cpg.query_selector("#testBtn") is not None, "and the Learner's home screen offers a Practice test")
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
    pg = ctx.new_page()
    open_page(pg, inst.url)
    sign_in(pg, name, password)
    check(h1(pg) == "Set 1", "a new Learner starts at Set 1")

    pg.click("#startBtn")
    answer_set(pg, miss=2)
    check(pg.inner_text(".home h2") == "Set done.", "the Set ends on the Set done screen")
    got = wait_for_records(pg, 1)
    rec = got[0] if len(got) == 1 else {}
    data = rec.get("data", {})
    check(len(got) == 1 and rec["kind"] == "set" and rec["reset"] is None
          and (data["type"], data["section"], data["group"]) == ("daily", None, None),
          "finishing a Set stores one daily Set record on the server", got)
    answers = data.get("answers", [])
    roles = [a["role"] for a in answers]
    check(sorted(roles) == ["counted"] * 5 + ["first_look"] * 5 + ["reask"] * 2,
          "the record holds the 5 first looks, the 5 counted answers and the 2 re-asks", roles)
    check(len(answers) == 12 and sum(a["right"] for a in answers if a["role"] == "counted") == 3
          and all(a["format"] == "choice" for a in answers)
          and all(a["at"] >= data["started_at"] and a["at"] <= rec["at"] for a in answers),
          "each answer says whether it was right, its role and format, and when it was chosen", data)
    pg.click("#homeBtn")
    check(h1(pg) == "Set 2", "home then shows Set 2")
    reload(pg)
    check(h1(pg) == "Set 2" and "3 of 120 facts learned." in stage_text(pg), "reloading keeps Progress", stage_text(pg))

    other = browser.new_context()
    pg2 = other.new_page()
    open_page(pg2, inst.url)
    sign_in(pg2, name, password)
    check(h1(pg2) == "Set 2" and "3 of 120 facts learned." in stage_text(pg2), "signing in on a fresh browser shows the same")
    other.close()

    reset = store_for(inst, learner, "reset", {})
    reload(pg)
    check(wait_for_h1(pg, "Set 1") == "Set 1" and "0 of 120 facts learned." in stage_text(pg),
          "a Reset put into the database shows on the Learner's next app open")
    store_for(inst, learner, "move", {"to": 4})
    reload(pg)
    wait_for_stage_text(pg, "Section 4, next")
    check(texts(pg, ".road .now") == ["4 Section 4, next"],
          "a Move to Section 4 put into the database shows on the Learner's next app open", texts(pg, ".road .now"))
    pg.click("#startBtn")
    check(pg.evaluate("run.screens.filter(s => s.kind === 'rule').map(s => BY_ID[s.id].day)") == [4] * 5,
          "and the next Set's new facts come from Section 4")
    answer_set(pg)
    got = wait_for_records(pg, 4)
    check(len(got) == 4 and got[-1]["reset"] == reset and got[-1]["data"]["type"] == "daily",
          "a Set finished after the Reset names that Reset", got[-1:])
    pg.click("#homeBtn")
    check(h1(pg) == "Set 2", "and the Set number counts from the Reset")

    # The server can't be reached when a Set finishes: the record waits and is sent next time.
    ctx.route("**/api/records", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
    pg.click("#startBtn")
    answer_set(pg)
    check(pg.inner_text(".home h2") == "Set done.", "with the server out of reach, the Set still finishes")
    pg.click("#homeBtn")
    check(h1(pg) == "Set 3", "and the home screen shows Set 3")
    check(len(server_records(pg)) == 4, "the record hasn't reached the server yet")
    reload(pg)
    check(h1(pg) == "Set 3", "the waiting record still counts after a reload")
    ctx.unroute("**/api/records")
    reload(pg)
    got = wait_for_records(pg, 5)
    check(len(got) == 5 and got[-1]["data"]["type"] == "daily", "the waiting record is sent on the next app open", got)
    reload(pg)
    check(len(server_records(pg)) == 5, "and it is stored only once")
    pg.goto(inst.url + "#section9")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Set 3", "#section9 does nothing")
    pg.goto(inst.url + "?r=1#restart")
    pg.wait_for_selector("#stage section")
    check(h1(pg) == "Set 3" and not pg.query_selector("#yes"), "#restart does nothing")
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
    check(pg.inner_text(".home h2") == "Set done.", "with no connection the Learner keeps answering to the end of a Set")
    pg.click("#homeBtn")
    check(h1(pg) == "Set 2", "and the home screen moves on to Set 2")
    shown = stage_text(pg).lower()
    check("offline" not in shown and "connection" not in shown, "nothing on the page says the device is offline", shown)
    check(db_state(inst, kit)[0] == [], "the server doesn't have the Set yet")
    ctx.set_offline(False)
    got = wait_until(lambda: db_state(inst, kit)[0])
    check(len(got) == 1 and got[0]["data"]["type"] == "daily",
          "going back online sends the waiting Set without reopening the app", got)
    reload(pg)
    check(len(server_records(pg)) == 1 and h1(pg) == "Set 2", "and the server holds it exactly once")
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
    check(left, "a record the server refuses no longer waits, so it doesn't hold back the others")
    kept = json.loads(local_item(pg, copy_key(kit))).get("rejected")
    check(kept == [bad], "but it is kept aside in the device copy, not deleted", kept)
    reload(pg)
    kept = json.loads(local_item(pg, copy_key(kit))).get("rejected")
    check(kept == [bad] and h1(pg) == "Set 2", "and stays kept aside when the app opens again", kept)
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
    i = pg.evaluate("run.i")  # 5 first looks and 3 counted questions answered, on the 4th counted question
    unfinished = wait_until(lambda: (db_state(inst, lee)[1] or {}).get("i") == i and db_state(inst, lee)[1])
    check(bool(unfinished) and isinstance(unfinished.get("saved_at"), str),
          "after each answer the unfinished Set is on the server, with saved_at", unfinished)
    open_page(pg2, inst.url)
    sign_in(pg2, name, password)
    check(pg2.query_selector("#resumeBtn") is not None and "Set 1. You answered 8 of 10 questions" in stage_text(pg2),
          "the second device offers the Set the first one stopped partway through", stage_text(pg2))
    pg2.click("#resumeBtn")
    check(pg2.evaluate("run.i") == i and pg2.evaluate("run.set_id") == pg.evaluate("run.set_id"),
          "and continues it at the next question")
    answer_one(pg2)
    pg2.click("#nextBtn")
    wait_until(lambda: (db_state(inst, lee)[1] or {}).get("i") == i + 1)
    reload(pg)
    wait_for_stage_text(pg, "You answered 9 of 10 questions")
    check("You answered 9 of 10 questions" in stage_text(pg),
          "the first device, opened again, takes the newer unfinished Set from the server", stage_text(pg))
    answer_set(pg2)
    pg2.click("#homeBtn")
    got = wait_until(lambda: db_state(inst, lee)[0])
    check(len(got) == 1 and wait_until(lambda: db_state(inst, lee)[1] is None, 5),
          "finishing it stores the Set and the server drops the unfinished one", db_state(inst, lee))
    reload(pg)
    check(wait_for_h1(pg, "Set 2") == "Set 2" and not pg.query_selector("#resumeBtn"),
          "the first device then shows Set 2 and nothing to continue")
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
    first = json.loads((ROOT / "data" / "sections.json").read_text())["sections"][0]["questions"]
    old_state = {"day": 5, "last": {first[0]: True, first[1]: True, first[2]: True, first[3]: False}, "tests": [],
                 "scores": {"1": 9, "2": 7, "3": 10, "4": 8}}
    old = json.dumps(old_state)
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [OLD_KEY, old])
    pg.evaluate("localStorage.setItem('rrtn-learner-someone-else', '{}')")

    sign_in(pg, *HELPER)
    check(pg.inner_text("#stage h1") == "Learners" and posts == [], "a Helper signing in on that device imports nothing")
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")

    sign_in(pg, name, password)
    wait_for_stage_text(pg, "3 of 120 facts learned.")
    check("3 of 120 facts learned." in stage_text(pg), "the Learner's first sign-in picks up the old progress",
          stage_text(pg))
    got = wait_until(lambda: db_state(inst, ash)[0])
    check(len(got) == 1 and got[0]["kind"] == "imported" and got[0]["data"] == {"state": old_state},
          "the old progress becomes one imported record holding the old saved state", got)
    reload(pg)
    check("3 of 120 facts learned." in stage_text(pg), "the imported progress stays after a reload")

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
    check(len(got) == 2 and got[1]["data"]["type"] == "daily", "signing out online sends the waiting Set first", got)
    check(local_item(pg, copy_key(ash)) is None, "and then deletes that Learner's device copy")
    check(local_item(pg, "rrtn-learner-someone-else") == "{}", "but leaves other copies alone")

    sign_in(pg, name, password)
    check(wait_for_h1(pg, "Set 2") == "Set 2", "signing in again shows Set 2")
    imports = [r for body in posts for r in body["records"] if r["kind"] == "imported"]
    check(len(imports) == 1 and len(db_state(inst, ash)[0]) == 2, "and doesn't import the old progress again", imports)
    calls = [c for c in pg.evaluate("window.oldKeyCalls") if c != "getItem"]
    check(calls == [], f"the page never writes or deletes tn-permit-daily-v1 (calls: {calls})")
    check(local_item(pg, OLD_KEY) == old, "the old saved state under tn-permit-daily-v1 is unchanged")

    # The device remembers the import is done, so a second Learner with no records gets none.
    pg.get_by_role("button", name="Sign out").click()
    pg.get_by_role("button", name="Yes, sign out").click()
    pg.wait_for_selector("#signInForm")
    cy = inst.add_learner("Cy", "second import password")
    sign_in(pg, "Cy", "second import password")
    check(h1(pg) == "Set 1" and "0 of 120 facts learned." in stage_text(pg),
          "a second Learner signing in on that device starts from nothing", h1(pg))
    time.sleep(0.5)
    imports = [r for body in posts for r in body["records"] if r["kind"] == "imported"]
    check(len(imports) == 1 and db_state(inst, cy)[0] == [], "and the old progress is not imported for them", imports)
    ctx.close()

    print("\n[an import that has to wait]")
    name, password = "Bo", "waiting import password"
    bo = inst.add_learner(name, password)
    ctx = browser.new_context()
    pg = ctx.new_page()
    open_page(pg, inst.url)
    pg.evaluate("([k, v]) => localStorage.setItem(k, v)", [OLD_KEY, json.dumps({"day": 3, "last": {first[0]: True}, "tests": [], "scores": {}})])
    block_record_posts(ctx)
    sign_in(pg, name, password)
    wait_for_stage_text(pg, "1 of 120 facts learned.")
    check("1 of 120 facts learned." in stage_text(pg), "the import counts at once, before the server has it")
    reload(pg)
    pending = json.loads(local_item(pg, copy_key(bo)))["pending"]
    check([r["kind"] for r in pending] == ["imported"], "opening the app again doesn't make a second imported record", pending)
    ctx.unroute("**/api/records")
    reload(pg)
    got = wait_until(lambda: db_state(inst, bo)[0])
    check(len(got) == 1 and got[0]["kind"] == "imported" and "1 of 120 facts learned." in stage_text(pg),
          "it is sent on the next app open", got)
    ctx.close()


def screens(pg):
    """The Set on show as [kind, fact id] pairs."""
    return pg.evaluate("run.screens.map(s => [s.kind, s.id])")


def gap_problems(list_):
    """Rule screens whose counted question comes sooner than GAP screens for other facts later."""
    out = []
    for i, (kind, fact) in enumerate(list_):
        if kind == "rule":
            j = next((j for j in range(i + 1, len(list_)) if list_[j] == ["counted", fact]), None)
            if j is None or j - i - 1 < 4 or any(f == fact for _, f in list_[i + 1:j]):
                out.append((fact, i, j))
    return out


def ago(hours_back):
    """A record time `hours_back` hours before now, in the page's toISOString() form."""
    t = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours_back)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def daily_at(n, answers):
    """A daily Set finished in the past: `answers` is a list of (question id, right, hours ago). Record ids are
    unique across the whole Instance, so each Learner's fixtures need their own `n`."""
    oldest = max(h for _, _, h in answers)
    return {"id": f"record-{n:012d}", "kind": "set", "reset": None, "at": ago(min(h for _, _, h in answers)), "data": {
        "set_id": f"set-{n}", "type": "daily", "section": None, "group": None, "started_at": ago(oldest),
        "answers": [{"q": q, "chosen": "an answer", "right": right, "at": ago(h), "role": "counted", "format": "choice"}
                    for q, right, h in answers]}}


def check_study_path(browser, inst, scheme="light"):
    """A new Learner's first Sets, in light or dark mode: first looks, rule screens, the gap, re-asks,
    Set done, the next Set, and a Set stopped partway through."""
    print(f"\n[{scheme} mode: the study path]")
    errors = []
    ctx = browser.new_context(viewport={"width": 400, "height": 900}, color_scheme=scheme)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if "Content Security Policy" in m.text else None)
    learner = (f"{scheme.title()} Learner", "path password")
    inst.add_learner(*learner)
    open_page(pg, inst.url)
    sign_in(pg, *learner)

    check(h1(pg) == "Set 1" and "5 new rules, one at a time. There is no time limit." in stage_text(pg)
          and "0 of 120 facts learned. 0 solid." in stage_text(pg),
          "a new Learner's home screen: Set 1, 5 new rules, 0 of 120 facts learned", stage_text(pg))
    check(not pg.query_selector("#testBtn") and "Practice tests" not in texts(pg, ".home h2"),
          "no Practice test until every fact is learned")
    check("parent" not in pg.inner_text("body").lower() and "helper" not in pg.inner_text("body").lower(),
          "nothing on the page is addressed to anyone but the Learner")
    check("score" not in stage_text(pg).lower(), "the home screen shows no Section score", stage_text(pg))

    # Set 1: five first looks, each followed by its rule screen, then the counted questions.
    pg.click("#startBtn")
    first = screens(pg)
    check([k for k, _ in first] == ["first_look", "rule"] * 5 + ["counted"] * 5 and not gap_problems(first),
          "the first Set is 5 first looks, each with its rule screen, then 5 counted questions, none right after its rule",
          first)
    check(stage_text(pg).startswith("Set 1: first look First look. You have not seen this rule yet. Pick what you think it is."),
          "a first look says so above the question", stage_text(pg))
    click_choice(pg, right=False)
    picked = pg.evaluate("run.screens[0].chosen")
    q = pg.evaluate("BY_ID[run.screens[1].id]")
    check(pg.inner_text("#ruleHead") == "Here is the rule." and pg.inner_text(".rule") == q["why"]
          and texts(pg, ".picked") == [f"You picked: {picked}.", f"The answer is: {q['a']}."]
          and pg.text_content(".src figcaption") == f"Driver manual, page {q['p']}"
          and "This question comes back later in this set." in stage_text(pg),
          "choosing goes straight to the rule screen: the rule, the manual's words, what was picked and the answer",
          stage_text(pg))
    check(not pg.query_selector(".opt.right, .opt.wrong, .verdict") and "Correct" not in stage_text(pg),
          "a first look is not scored: no colors and no Correct")
    check(pg.inner_text(".progress") == "Set 1" and pg.inner_text("#ruleGoBtn") == "Go on",
          "the rule screen's progress line is just the Set, and its button is Go on")
    answer_set(pg)
    done = stage_text(pg)
    check(done.startswith("Set done. 5 new facts learned. 5 of 120 facts learned. 0 solid."),
          "with every answer right, Set done says 5 new facts learned", done)
    check("right" not in done and "score" not in done.lower(), "Set done shows no score", done)
    check(pg.get_attribute("#moreBtn", "class") == "btn primary" and pg.inner_text("#homeBtn") == "I'm done for now",
          "with more to do, Another set is the main button and I'm done for now comes after it")

    # Set 2: the first counted question is answered wrong; it comes back once in this Set.
    pg.click("#moreBtn")
    second = screens(pg)
    check(not {f for _, f in second} & {f for _, f in first},
          "a fact answered right is not in the next Set started a minute later", second)
    while screen_kind(pg) != "counted":
        pg.click("#ruleGoBtn") if screen_kind(pg) == "rule" else click_choice(pg)
    p = pg.evaluate("run.i")
    check(pg.inner_text(".progress") == "Set 2: question 1 of 5", "a counted question says which of the Set's counted questions it is",
          pg.inner_text(".progress"))
    click_choice(pg, right=False)
    feedback = " ".join(pg.inner_text("#feedback").split())
    right = pg.evaluate("BY_ID[run.screens[run.i].id].a")
    check(feedback.startswith(f"The right answer is: {right}.") and "Not correct" not in feedback
          and feedback.endswith("This question comes back later in this set, and in your next set."),
          "after a wrong answer, the screen gives the right answer and says the question comes back, with no verdict", feedback)
    shown = pg.evaluate("BY_ID[run.screens[run.i].id]")
    said = pg.text_content("#announce")
    check(said.startswith(f"The right answer is: {right}. {shown['why']} Driver manual, page {shown['p']}: “{shown['src']}”")
          and said.endswith("This question comes back later in this set, and in your next set."),
          "and the screen reader hears the same sentences, in the same order", said)
    now = screens(pg)
    r = next(i for i, s in enumerate(now) if s[0] == "reask")
    between = [s for s in now[p + 1:r] if s[0] != "rule"]
    check(now[r][1] == now[p][1] and len(between) == 3 and all(f != now[p][1] for _, f in between),
          "a wrong counted answer puts the fact in once more, after 3 question screens for other facts", now)
    pg.click("#nextBtn")
    while screen_kind(pg) != "reask":
        answer_one(pg) if screen_kind(pg) != "counted" else click_choice(pg)
        if pg.query_selector("#nextBtn"):
            pg.click("#nextBtn")
    check(stage_text(pg).startswith("Set 2: one more time One more time."), "a re-ask says One more time.", stage_text(pg))
    click_choice(pg, right=False)
    check(" ".join(pg.inner_text("#feedback").split()).endswith("This question comes back in your next set.")
          and len([s for s in screens(pg) if s[0] == "reask"]) == 1,
          "a wrong re-ask puts nothing more in, and says the question comes back in the next Set")
    missed = pg.evaluate("run.screens[run.i].id")
    pg.click("#nextBtn")
    answer_set(pg)
    done = stage_text(pg)
    check(done.startswith("Set done. 4 new facts learned. 1 fact comes back in your next set. 9 of 120 facts learned. 0 solid."),
          "Set done counts the new facts learned and the one that comes back", done)
    check("See the 1 question you missed" in done, "and lists the missed question once", done)
    pg.click("#homeBtn")

    # Set 3 opens with the missed fact. Stopping partway keeps the answers.
    check(h1(pg) == "Set 3" and "1 question comes back. 5 new." in stage_text(pg),
          "the home screen says what the next Set holds", stage_text(pg))
    pg.click("#startBtn")
    third = screens(pg)
    check([s for s in third if s[0] == "counted"][0] == ["counted", missed] and not gap_problems(third),
          "the next Set opens with the fact answered wrong", third)
    answer_one(pg)
    pg.click("#nextBtn")
    answer_one(pg)
    pg.click("#quitBtn")
    check(pg.query_selector("#resumeBtn") is not None and "You stopped partway through Set 3. You answered 7 of 11 questions." in stage_text(pg)
          and not pg.query_selector("#startBtn") and h1(pg) == "Set 3",
          "stopping partway goes home, where Continue takes the place of Start the set", stage_text(pg))
    reload(pg)
    check(pg.query_selector("#resumeBtn") is not None, "a Set stopped partway through survives a reload")
    at = pg.evaluate("S.run.i")
    pg.click("#resumeBtn")
    check(pg.evaluate("run.i") == at and pg.query_selector("#nextBtn") is not None, "continuing picks up at the same screen")
    pg.click("#nextBtn")
    answer_set(pg)
    check(pg.inner_text(".home h2") == "Set done.", "a continued Set finishes normally")
    pg.click("#homeBtn")
    reload(pg)
    check(h1(pg) == "Set 4", "progress is kept across a reload")
    check(texts(pg, ".road .done") == ["1 Section 1, finished"] and texts(pg, ".road .now") == ["2 Section 2, next"],
          "once all 10 of its facts are learned, Section 1 is finished on the track and Section 2 is next", texts(pg, ".road li"))
    check(not errors, f"no page errors in {scheme} mode" + (f": {errors}" if errors else ""))
    ctx.close()


def check_known_facts(browser, inst):
    """Learners whose records are put straight into the database with times: due again after 13 hours,
    the wrong-choice line, every fact learned, and Practice tests up to Ready for the test."""
    print("\n[due again after 13 hours]")
    ctx = browser.new_context(viewport={"width": 400, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    sections = json.loads((ROOT / "data" / "sections.json").read_text())["sections"]
    all_ids = [i for s in sections for i in s["questions"]]
    s1 = sections[0]["questions"]
    a = inst.add_learner("Dana", "timed password")
    store_history(inst, a, [daily_at(1, [(s1[0], True, 13)]), daily_at(2, [(s1[1], True, 1 / 60)])])
    open_page(pg, inst.url)
    sign_in(pg, "Dana", "timed password")
    check("1 question comes back. 5 new." in stage_text(pg), "a fact answered right 13 hours ago comes back", stage_text(pg))
    pg.click("#startBtn")
    ids = {f for _, f in screens(pg)}
    check(s1[0] in ids and s1[1] not in ids, "it is in the Set; one answered right a minute ago is not", screens(pg))
    pg.click("#quitBtn")
    ctx.close()

    print("\n[a wrong choice that answers a different question]")
    b = inst.add_learner("Eli", "also password")
    store_history(inst, b, [daily_at(11, [("b-250", False, 2)])])
    ctx = browser.new_context(viewport={"width": 400, "height": 900})
    pg2 = ctx.new_page()
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    open_page(pg2, inst.url)
    sign_in(pg2, "Eli", "also password")
    pg2.click("#startBtn")
    while pg2.evaluate("run.screens[run.i].id") != "b-250" or screen_kind(pg2) != "counted":
        if screen_kind(pg2) == "rule":
            pg2.click("#ruleGoBtn")
        else:
            click_choice(pg2)
            if pg2.query_selector("#nextBtn"):
                pg2.click("#nextBtn")
    k = [o.inner_text().split("\n", 1)[-1].strip() for o in pg2.query_selector_all("button.opt")].index("30 feet")
    pg2.query_selector_all("button.opt")[k].click()
    other = pg2.evaluate("BY_ID['b-253'].q")
    check(pg2.inner_text(".also") == f"30 feet answers a different question: {other}",
          "choosing 30 feet for the fire hydrant says which question 30 feet answers", pg2.inner_text(".also"))
    ctx.close()

    print("\n[every fact learned]")
    c = inst.add_learner("Finn", "known password")
    store_history(inst, c, [daily_at(21, [(q, True, 1) for q in all_ids[:50]]),
                            daily_at(22, [(q, True, 1) for q in all_ids[50:100]]),
                            daily_at(23, [(q, True, 1) for q in all_ids[100:]])])
    ctx = browser.new_context(viewport={"width": 400, "height": 900})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    open_page(pg, inst.url)
    sign_in(pg, "Finn", "known password")
    home = stage_text(pg)
    check(h1(pg) == "Set 4" and "Nothing is due. This set goes over 5 facts you already know." in home
          and "120 of 120 facts learned. 0 solid." in home,
          "with every fact learned and nothing due, the home screen says the Set goes over known facts", home)
    check("Practice tests The real test passes at 24 of 30. The app's goal is 27 of 30 on three practice tests in a row." in home
          and pg.get_attribute("#testBtn", "class") == "btn primary" and pg.get_attribute("#startBtn", "class") == "btn",
          "Practice tests appear, and Start a practice test is the main button", home)
    check(len(pg.query_selector_all(".road .stop.done")) == 12 and texts(pg, ".road .now") == ["Practice tests Practice tests, next"],
          "every Section is done on the track and Practice tests are next", texts(pg, ".road li"))
    pg.click("#startBtn")
    check([k for k, _ in screens(pg)] == ["counted"] * 5, "the fill Set is 5 counted questions")
    answer_set(pg)
    check("Nothing is due. The next set goes over 5 facts you already know." in stage_text(pg)
          and pg.get_attribute("#homeBtn", "class") == "btn primary" and pg.get_attribute("#moreBtn", "class") == "link"
          and pg.get_attribute("#testBtn", "class") == "btn",
          "after it, I'm done for now is the main button, with Start a practice test and a quiet Another set", stage_text(pg))
    pg.click("#homeBtn")

    # A Practice test: 30 questions, no rule screens; its wrong answers come back in the next Set.
    pg.click("#testBtn")
    check(pg.inner_text(".progress") == "Practice test: question 1 of 30" and [k for k, _ in screens(pg)] == ["counted"] * 30,
          "a Practice test is 30 counted questions with no rule screens")
    answer_one(pg)
    pg.click("#quitBtn")
    check("You stopped partway through a practice test." in stage_text(pg) and pg.get_attribute("#startBtn", "class") == "btn",
          "a Practice test stopped partway is one line, with Start the set as a plain button", stage_text(pg))
    pg.click("#startBtn")
    check(pg.inner_text(".home h2") == "Start the set?" and "the 1 answer you gave there will be cleared" in stage_text(pg),
          "starting a Set instead asks first", stage_text(pg))
    pg.click("#newSetNo")
    pg.click("#resumeBtn")
    pg.click("#nextBtn")
    check(answer_set(pg, miss=5) == 29, "the rest of the Practice test is answered")
    end = stage_text(pg)
    check(pg.inner_text(".score") == "25 of 30 right" and "This practice test is done." in end
          and "The questions you missed come back in your next set." in end and "pass" not in end,
          "a Practice test with 25 right says so, says the missed ones come back, with no pass or fail", end)
    pg.click("#homeBtn")
    check("Your last practice tests: 25" in stage_text(pg) and "5 questions come back." in stage_text(pg)
          and pg.get_attribute("#startBtn", "class") == "btn primary",
          "the home screen lists the Practice test score, and the missed questions come back in the next Set", stage_text(pg))
    for n in range(3):
        pg.click("#testBtn")
        answer_set(pg, 2)
        pg.click("#homeBtn")
    check(texts(pg, ".sign h2") == ["Ready for the test"] and pg.inner_text("#testBtn") == "Take another practice test"
          and "Your last practice tests: 25, 28, 28, 28" in stage_text(pg),
          "three Practice tests in a row at 27 or more shows Ready for the test", stage_text(pg))
    reload(pg)
    check(texts(pg, ".sign h2") == ["Ready for the test"], "Ready for the test is still shown after a reload")
    check(texts(pg, ".road .done")[-1] == "Practice tests Practice tests, ready", "and the track shows it")
    check(not errors, "no page errors" + (f": {errors}" if errors else ""))
    ctx.close()


def check_phone_screens(browser, inst):
    """At 375 px wide, nothing on any screen of a Set scrolls sideways."""
    print("\n[every screen at 375 px wide]")
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    inst.add_learner("Gray", "phone password")
    open_page(pg, inst.url)
    sign_in(pg, "Gray", "phone password")
    seen, wide = set(), []

    def look(what):
        seen.add(what)
        if not no_sideways_scroll(pg):
            wide.append(what)

    look("home")
    pg.click("#startBtn")
    missed = 0
    while (kind := screen_kind(pg)) is not None:
        look(kind)
        if kind == "rule":
            pg.click("#ruleGoBtn")
            continue
        wrong = kind in ("counted", "reask") and missed < 2
        missed += wrong
        click_choice(pg, right=not wrong)
        if kind != "first_look":
            look(f"{kind} feedback")
            pg.click("#nextBtn")
    look("Set done")
    pg.eval_on_selector_all("details", "els => els.forEach(d => d.open = true)")
    look("Set done, missed questions open")
    check(seen >= {"home", "first_look", "rule", "counted", "counted feedback", "reask", "reask feedback", "Set done"} and not wide,
          "first look, rule, counted, re-ask and Set done screens fit 375 px", [sorted(seen), wide])
    ctx.close()


def run_only(names):
    """Run only the named check functions (python3 tests/test_app.py check_engine check_helper_view)."""
    with Instance() as inst, sync_playwright() as p:
        inst.add_helper(*HELPER)
        inst.add_learner(*LEARNER)
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        for name in names:
            fn = globals()[name]
            fn(*(browser, inst)[:fn.__code__.co_argcount])
        browser.close()
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


def main():
    if sys.argv[1:]:
        run_only(sys.argv[1:])
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
        check_engine(browser, inst)
        check_records_on_server(browser, inst)
        check_offline_and_sync(browser, inst)
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
        answer_one(pg, right=False)
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
            check_study_path(browser, inst, scheme)
        check_known_facts(browser, inst)
        check_phone_screens(browser, inst)
        browser.close()
    check(not errors, "no page errors" + (f": {errors}" if errors else ""))
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
