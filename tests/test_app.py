#!/usr/bin/env python3
"""Click through the built page in a real (headless) browser.

Needs Playwright with Chromium:  pip install playwright && playwright install chromium
Run after building:              python3 build.py && python3 tests/test_app.py

Covers the whole path the student takes: all 12 sections, redoing a section,
section scores, review of missed questions, practice tests, the "ready" screen,
the hidden #restart / #sectionN links, saving progress across a reload, picking
up a half-finished section, and the phone layout.

Set CHROMIUM_PATH to use an installed Chromium instead of Playwright's download.
"""
import functools
import http.server
import os
import pathlib
import threading

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
failures = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *a: None
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


def h1(pg):
    return pg.inner_text(".home h1")


def main():
    srv, url = serve()
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)

        # A real phone lays the page out at its own width, not a shrunken desktop page.
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = phone.new_page()
        pg.goto(url)
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
        phone.close()
        for scheme in ("light", "dark"):
            print(f"\n[{scheme} mode]")
            ctx = browser.new_context(viewport={"width": 400, "height": 900}, color_scheme=scheme)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)

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
            pg.reload()
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
            pg.reload()
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
            pg.goto(url + "?r=1#restart")
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
