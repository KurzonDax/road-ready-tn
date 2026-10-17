#!/usr/bin/env python3
"""Write one lesson as a single page to review: every screen's prompt, drawing, choices and explanation,
top to bottom, so a lesson is read like a document instead of tapped through on a phone.

    python3 tools/lesson_sheet.py 3 reports/lessons/section-3.html

Needs Playwright with Chromium, like tests/test_app.py (set CHROMIUM_PATH to use an installed one), and a
built dist/. It starts a throwaway Instance, signs in a Learner moved to that Section, walks the lesson
answering every screen correctly, and captures each drawing before and after the action.
"""
import base64
import html
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright  # noqa: E402
from test_app import Instance, open_page, sign_in, store_for  # noqa: E402

STYLE = """
body { font: 18px/1.5 system-ui, sans-serif; background: #181715; color: #e4e0d9; margin: 0; padding: 24px; }
main { max-width: 760px; margin: 0 auto; }
h1 { font-size: 28px; } h2 { font-size: 22px; margin: 48px 0 8px; border-top: 1px solid #363330; padding-top: 24px; }
.prompt { font-size: 21px; font-weight: 700; }
.row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
.row img { width: 240px; background: #1f1e1c; border-radius: 12px; }
.cap { font-size: 14px; color: #ada79f; margin: 4px 0 0; }
ul { padding-left: 22px; } li.answer { font-weight: 700; } li.answer::after { content: "  ← the answer"; color: #62c27f; font-weight: 400; }
.say { font-size: 19px; margin: 8px 0; }
.not { color: #e8705f; } .ok { color: #62c27f; }
.meta { color: #ada79f; font-size: 15px; }
ul.wrongs { margin-top: 0; } ul.wrongs li { font-size: 16px; }
"""


def shot(el):
    return "data:image/png;base64," + base64.b64encode(el.screenshot()).decode()


def walk(browser, inst, section, name, pick):
    """Walk the lesson once as a fresh Learner, choosing with `pick(step)` (a target id or an option text),
    and return, per question, the drawing after acting (or None) and the result line shown."""
    lid = inst.add_learner(name, "review password")
    store_for(inst, lid, "move", {"to": section})
    pg = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    open_page(pg, inst.url)
    sign_in(pg, name, "review password")
    pg.wait_for_selector("#lessonBtn")
    pg.click("#lessonBtn")
    pg.wait_for_selector("#stepText")
    lesson = pg.evaluate("lesson.lesson")
    seen = []
    for st in lesson["steps"]:
        pg.wait_for_selector("#stepText")
        before = pg.query_selector(".scene")
        img_before = shot(before) if before else None
        choice = pick(st)
        if st["kind"] == "tap":
            pg.click(f".k-target[data-t='{choice}']")
        else:
            labels = [o.inner_text().split("\n", 1)[-1].strip() for o in pg.query_selector_all("button.opt")]
            pg.query_selector_all("button.opt")[labels.index(choice)].click()
        pg.wait_for_selector("#stepNextBtn")
        pg.wait_for_timeout(500)
        after = pg.query_selector(".scene")
        seen.append({"before": img_before, "after": shot(after) if after else None,
                     "lead": pg.inner_text("#stepHead"), "say": pg.inner_text("#stepText")})
        pg.click("#stepNextBtn")
    pg.close()
    return lesson, seen


def main():
    section, out = int(sys.argv[1]), pathlib.Path(sys.argv[2])
    with Instance() as inst, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        lesson, right = walk(browser, inst, section, "Review", lambda st: st["answer"])
        # A second walk picks a wrong target or option on every question, to show that path as he will see it.
        first_wrong = lambda st: next(t["id"] for t in st["targets"] if t["id"] != st["answer"]) if st["kind"] == "tap" \
            else next(o for o in st["options"] if o != st["answer"])
        _, wrong = walk(browser, inst, section, "Review two", first_wrong)
        browser.close()
    n = len(lesson["steps"])
    parts = [f"<h1>Lesson for Section {section}: {html.escape(lesson['title'])}</h1>",
             f"<p class='meta'>{n} questions. Each one is shown before acting, after the correct action, and after a wrong "
             "action. Every wrong pick is listed with the exact first line it gets; the explanation under it is the same for all of them.</p>"]
    for k, st in enumerate(lesson["steps"]):
        r, wr = right[k], wrong[k]
        parts.append(f"<h2>{k + 1} of {n}<span class='meta'> · {html.escape(st['id'])}"
                     f"{' · ' + html.escape(st['fact']) if st.get('fact') else ' · principle'}</span></h2>")
        parts.append(f"<p class='prompt'>{html.escape(st['prompt'])}</p>")
        if st["kind"] == "tap":
            items = [(t["label"], t["id"] == st["answer"]) for t in st["targets"]]
            parts.append("<ul>" + "".join(f"<li class='{'answer' if ok else ''}'>Tap target: {html.escape(label)}</li>" for label, ok in items) + "</ul>")
        else:
            items = [(o, o == st["answer"]) for o in st["options"]]
            parts.append("<ul>" + "".join(f"<li class='{'answer' if ok else ''}'>{html.escape(label)}</li>" for label, ok in items) + "</ul>")
        row = ""
        if r["before"]:
            row += f"<div><img src='{r['before']}' alt=''><p class='cap'>Before acting</p></div>"
        if r["after"]:
            row += f"<div><img src='{r['after']}' alt=''><p class='cap'>After the correct action</p></div>"
        if wr["after"]:
            row += f"<div><img src='{wr['after']}' alt=''><p class='cap'>After a wrong action</p></div>"
        if row:
            parts.append(f"<div class='row'>{row}</div>")
        parts.append(f"<p class='say'><span class='ok'>{html.escape(r['lead'])}</span> {html.escape(r['say'])}</p>")
        wrongs = [label for label, ok in items if not ok]
        lines = "".join(f"<li><span class='not'>Incorrect. You picked {html.escape(label)}.</span></li>" for label in wrongs)
        parts.append(f"<p class='meta'>Each wrong pick gets its own first line, then the same explanation:</p><ul class='wrongs'>{lines}</ul>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!doctype html><meta charset='utf-8'><title>Lesson for Section {section}</title><style>{STYLE}</style><main>{''.join(parts)}</main>\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
