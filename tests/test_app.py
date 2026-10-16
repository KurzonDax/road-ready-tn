#!/usr/bin/env python3
"""Click through the built page in a real (headless) browser.

Needs Playwright with Chromium:  pip install playwright && playwright install chromium
Run after building:              python3 build.py && python3 tests/test_app.py
Before committing, also run:     python3 tests/check_dist.py  (fails if dist/ is out of date)

Covers the whole path the student takes: all 12 sections, redoing a section,
section scores, review of missed questions, practice tests, the "ready" screen,
the hidden #restart / #sectionN links, saving progress across a reload, picking
up a half-finished section, and the phone layout. Also the Home Screen pieces:
the manifest, the icon sizes, the page head, the safe-area padding, and that the
page loads its fonts and everything else from its own origin. The page is served over HTTP
with the script-src hash from dist/csp.json, so a wrong hash stops the page, and
one run checks the sentence shown when questions.json can't be loaded.

Set CHROMIUM_PATH to use an installed Chromium instead of Playwright's download.
"""
import functools
import http.server
import json
import os
import pathlib
import struct
import threading
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
failures = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serve dist/ with only the page's own inline script allowed, as the Instance does."""
    csp = "script-src '" + json.loads((DIST / "csp.json").read_text())["script"] + "'"

    def end_headers(self):
        self.send_header("Content-Security-Policy", self.csp)
        super().end_headers()

    def log_message(self, *a):
        pass


def serve():
    handler = functools.partial(Handler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/index.html"


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
    """Open the page and wait until it has its questions and shows something."""
    pg.goto(url)
    pg.wait_for_selector("#stage section")


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


def main():
    srv, url = serve()
    base = url.rsplit("/", 1)[0] + "/"
    errors = []
    print("\n[Home Screen files]")
    check_manifest(base)
    check_icons(base)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)

        print("\n[page head, fonts, own origin]")
        ctx = browser.new_context()
        pg = ctx.new_page()
        requested = []
        pg.on("request", lambda r: requested.append(r.url))
        open_page(pg, url)
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
        ctx = browser.new_context()
        ctx.route("**/questions.json", lambda route: route.fulfill(status=404, body="Not found"))
        pg = ctx.new_page()
        open_page(pg, url)
        check(pg.inner_text("#stage") ==
              "The questions could not be loaded. Check your connection and open the app again.",
              "with questions.json missing, the page says the questions could not be loaded")
        ctx.close()

        # A real phone lays the page out at its own width, not a shrunken desktop page.
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = phone.new_page()
        open_page(pg, url)
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
            open_page(pg, url)

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

            # Hidden links.
            pg.goto(url + "#section5")
            check(h1(pg) == "Section 5 of 12", "#section5 jumps to Section 5")
            open_page(pg, url + "?r=1#restart")
            check("Start over" in pg.inner_text("h2"), "#restart asks before erasing")
            pg.click("#yes")
            check(h1(pg) == "Section 1 of 12", "restart goes back to Section 1")
            ctx.close()
        browser.close()
    srv.shutdown()
    check(not errors, "no page errors" + (f": {errors}" if errors else ""))
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
