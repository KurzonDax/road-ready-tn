#!/usr/bin/env python3
"""Build the study app.

Reads the question bank (data/questions.json) and the 12-section study plan
(data/sections.json), checks them, and writes one self-contained page to
dist/index.html. The page needs no server: open it in a browser.

Usage:
    python3 build.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))
from validate_data import validate  # noqa: E402


def compact(q, section):
    """Convert a bank question to the short field names the page uses."""
    item = {
        "id": q["id"],
        "q": q["question"],
        "a": q["answer"],
        "o": q["wrong"],
        "why": q["explanation"],
        "p": q["page"],
        "src": q["manual_quote"],
    }
    if q.get("manual_sample"):
        item["s"] = 1
    if q.get("sign"):
        item["sign"] = q["sign"]
    if q.get("color"):
        item["swatch"] = q["color"]
    item["day"] = section  # the page calls sections "days" internally
    return item


def build_data():
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    plan = json.loads((ROOT / "data" / "sections.json").read_text())
    by_id = {q["id"]: q for q in bank["questions"]}
    days, qs = [], []
    for sec in plan["sections"]:
        days.append({"day": sec["section"], "title": sec["title"]})
        qs.extend(compact(by_id[i], sec["section"]) for i in sec["questions"])
    return {"days": days, "qs": qs}


def main():
    errors = validate()
    if errors:
        print("Data check failed:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    data = build_data()
    template = (ROOT / "src" / "app.html").read_text()
    if template.count("__DATA__") != 1:
        sys.exit("src/app.html must contain exactly one __DATA__ placeholder")
    page = template.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = ROOT / "dist" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page)
    print(f"Wrote {out.relative_to(ROOT)}: {len(data['qs'])} questions in {len(data['days'])} sections")


if __name__ == "__main__":
    main()
