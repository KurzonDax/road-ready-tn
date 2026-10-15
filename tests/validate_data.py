#!/usr/bin/env python3
"""Check the question bank and study plan for mistakes.

Run on its own (python3 tests/validate_data.py) or automatically from build.py.
Every rule here exists because the mistake it catches actually happened.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIGNS = {"octagon", "triangle", "circle", "crossbuck", "diamond", "rectangle"}
GIVEAWAY = re.compile(r"\b(what|which) (shape|colou?rs?)\b|\blook like\b|\bwhich sign\b", re.I)
SECTIONS = 12
PER_SECTION = 10


def validate():
    errors = []
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    plan = json.loads((ROOT / "data" / "sections.json").read_text())
    topics = bank["topics"]
    qs = bank["questions"]
    ids = [q["id"] for q in qs]

    if len(ids) != len(set(ids)):
        errors.append("duplicate question ids in questions.json")
    for q in qs:
        i = q["id"]
        for f in ("question", "answer", "wrong", "explanation", "page", "manual_quote", "topic"):
            if not q.get(f):
                errors.append(f"{i}: missing {f}")
        wrong = q.get("wrong", [])
        if len(wrong) != 3 or len(set(wrong)) != 3:
            errors.append(f"{i}: needs exactly 3 different wrong answers")
        if q.get("answer") in wrong:
            errors.append(f"{i}: the right answer also appears as a wrong answer")
        if q.get("topic") not in topics:
            errors.append(f"{i}: unknown topic {q.get('topic')!r}")
        if not 25 <= q.get("page", 0) <= 118:
            errors.append(f"{i}: page {q.get('page')} is outside Sections B and C (pages 25-118)")
        if ";" in q.get("answer", "") or any(";" in w for w in wrong):
            errors.append(f"{i}: answer choices should be plain phrases, not clauses joined by a semicolon")
        if q.get("sign") and q["sign"] not in SIGNS:
            errors.append(f"{i}: unknown sign picture {q['sign']!r}")
        if (q.get("sign") or q.get("color")) and GIVEAWAY.search(q.get("question", "")):
            errors.append(f"{i}: the picture would give away the answer to {q['question']!r}")

    by_id = {q["id"]: q for q in qs}
    secs = plan["sections"]
    if len(secs) != SECTIONS:
        errors.append(f"sections.json has {len(secs)} sections, expected {SECTIONS}")
    used = []
    for s in secs:
        if len(s["questions"]) != PER_SECTION:
            errors.append(f"section {s['section']} has {len(s['questions'])} questions, expected {PER_SECTION}")
        for i in s["questions"]:
            if i not in by_id:
                errors.append(f"section {s['section']}: {i} is not in questions.json")
        used += s["questions"]
    if len(used) != len(set(used)):
        errors.append("a question appears in more than one section")
    samples = {q["id"] for q in qs if q.get("manual_sample")}
    missing = samples - set(used)
    if missing:
        errors.append(f"the manual's own sample questions are missing from the sections: {sorted(missing)}")
    return errors


if __name__ == "__main__":
    errs = validate()
    for e in errs:
        print("-", e)
    print("OK" if not errs else f"{len(errs)} problem(s)")
    sys.exit(1 if errs else 0)
