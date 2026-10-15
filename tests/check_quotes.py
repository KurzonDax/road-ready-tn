#!/usr/bin/env python3
"""Check that every question's manual_quote appears in the manual text near its page.

A quote that can't be found usually means a wrong page number or a quote that
was retyped instead of copied. A few quotes come from tables that the PDF text
extraction scrambles into columns; those are listed in KNOWN_TABLE_QUOTES after
being checked by hand against the printed manual.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KNOWN_TABLE_QUOTES = {"a-022", "a-050", "a-084", "a-156", "a-157"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    pages, cur = {}, None
    for line in (ROOT / "data" / "manual" / "sections-b-c.txt").read_text().split("\n"):
        m = re.match(r"=====MANUAL PAGE (\d+)=====", line)
        if m:
            cur = int(m.group(1))
            pages[cur] = []
        elif cur is not None:
            pages[cur].append(line)
    text = {k: norm(" ".join(v)) for k, v in pages.items()}
    qs = json.loads((ROOT / "data" / "questions.json").read_text())["questions"]
    bad = []
    for q in qs:
        if q["id"] in KNOWN_TABLE_QUOTES:
            continue
        start = norm(q["manual_quote"].split("...")[0])[:40]
        near = "".join(text.get(q["page"] + d, "") for d in (-1, 0, 1))
        if start not in near:
            bad.append(q)
    for q in bad:
        print(f"- {q['id']} (page {q['page']}): quote not found: {q['manual_quote'][:80]!r}")
    print("OK" if not bad else f"{len(bad)} quote(s) not found")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
