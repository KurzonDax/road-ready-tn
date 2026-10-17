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
.row img { width: 340px; background: #1f1e1c; border-radius: 12px; }
.cap { font-size: 14px; color: #ada79f; margin: 4px 0 0; }
ul { padding-left: 22px; } li.answer { font-weight: 700; } li.answer::after { content: "  ← the answer"; color: #62c27f; font-weight: 400; }
.say { font-size: 19px; margin: 8px 0; }
.not { color: #e8705f; } .ok { color: #62c27f; }
.meta { color: #ada79f; font-size: 15px; }
"""


def shot(el):
    return "data:image/png;base64," + base64.b64encode(el.screenshot()).decode()


def main():
    section, out = int(sys.argv[1]), pathlib.Path(sys.argv[2])
    with Instance() as inst, sync_playwright() as pw:
        lid = inst.add_learner("Review", "review password")
        store_for(inst, lid, "move", {"to": section})
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        pg = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        open_page(pg, inst.url)
        sign_in(pg, "Review", "review password")
        pg.wait_for_selector("#lessonBtn")
        pg.click("#lessonBtn")
        pg.wait_for_selector("#stepText")
        lesson = pg.evaluate("lesson.lesson")
        parts = [f"<h1>Lesson for Section {section}: {html.escape(lesson['title'])}</h1>",
                 f"<p class='meta'>{len(lesson['steps'])} screens. Each one is shown as the Learner sees it before acting, "
                 "then after the correct action. The line he sees after a wrong action is given in words.</p>"]
        for k, st in enumerate(lesson["steps"]):
            pg.wait_for_selector("#stepText")
            before = pg.query_selector(".scene")
            img_before = shot(before) if before else None
            parts.append(f"<h2>{k + 1} of {len(lesson['steps'])}<span class='meta'> · {html.escape(st['id'])}"
                         f"{' · ' + html.escape(st['fact']) if st.get('fact') else ' · principle'}</span></h2>")
            parts.append(f"<p class='prompt'>{html.escape(st['prompt'])}</p>")
            if st["kind"] == "tap":
                parts.append("<ul>" + "".join(f"<li class='{'answer' if t['id'] == st['answer'] else ''}'>Tap target: {html.escape(t['label'])}</li>"
                                                for t in st["targets"]) + "</ul>")
                pg.click(f".k-target[data-t='{st['answer']}']")
            else:
                parts.append("<ul>" + "".join(f"<li class='{'answer' if o == st['answer'] else ''}'>{html.escape(o)}</li>" for o in st["options"]) + "</ul>")
                labels = [o.inner_text().split("\n", 1)[-1].strip() for o in pg.query_selector_all("button.opt")]
                pg.query_selector_all("button.opt")[labels.index(st["answer"])].click()
            pg.wait_for_selector("#stepNextBtn")
            pg.wait_for_timeout(500)
            after = pg.query_selector(".scene")
            row = ""
            if img_before:
                row += f"<div><img src='{img_before}' alt=''><p class='cap'>Before acting</p></div>"
            if after:
                row += f"<div><img src='{shot(after)}' alt=''><p class='cap'>After the correct action</p></div>"
            if row:
                parts.append(f"<div class='row'>{row}</div>")
            wrong = next((t["label"] for t in st.get("targets", []) if t["id"] != st["answer"]), None)
            parts.append(f"<p class='say'><span class='ok'>Correct.</span> {html.escape(st['then']['say'])}</p>")
            right_label = next((t["label"] for t in st.get("targets", []) if t["id"] == st["answer"]), st["answer"])
            not_line = (f"Incorrect. You picked {wrong}. The correct one is {right_label}." if st["kind"] == "tap"
                        else f"Incorrect. You picked {next(o for o in st['options'] if o != st['answer'])}. The correct answer is {st['answer']}.")
            parts.append(f"<p class='meta'>After a wrong action the first line is <span class='not'>{html.escape(not_line)}</span> and the same explanation follows.</p>")
            pg.click("#stepNextBtn")
        browser.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!doctype html><meta charset='utf-8'><title>Lesson for Section {section}</title><style>{STYLE}</style><main>{''.join(parts)}</main>\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
