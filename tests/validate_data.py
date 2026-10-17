#!/usr/bin/env python3
"""Check the question bank and study plan for mistakes.

Run on its own (python3 tests/validate_data.py) or automatically from build.py.
Every rule here exists because the mistake it catches actually happened, except the
fact and group rules, which guard groupings done by hand (see check_facts and check_groups).
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
    errors += check_facts(qs, set(used))
    groups = json.loads((ROOT / "data" / "groups.json").read_text())["groups"]
    errors += check_groups(groups, set(used))
    return errors


NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}


def numbers(text):
    """The numbers in an answer, whether written as digits or words: "No closer than two seconds" -> {"2"}."""
    digits = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?|\.\d+", text)}
    return digits | {NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in NUMBER_WORDS}


def plain(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def check_facts(qs, used):
    """Each of the app's questions is its own fact. Other wordings of a fact must have the same right answer.

    Whether two questions test the same rule is a person's judgment, recorded in `fact`. What can be
    checked here: no wording's right answer is a wrong choice in another wording of the same fact, and
    every wording's right answer has the same numbers ("15 and 50 feet", never "15 and 30 feet").
    """
    errors = []
    by_id = {q["id"]: q for q in qs}
    wordings = {}
    for q in qs:
        f = q.get("fact")
        if q["id"] in used and f != q["id"]:
            errors.append(f"{q['id']}: is in the sections, so its fact must be its own id, not {f!r}")
        elif f is not None and f not in used:
            errors.append(f"{q['id']}: fact {f!r} is not a question in the sections")
        elif f is not None:
            wordings.setdefault(f, []).append(q)
    for f, group in wordings.items():
        want = numbers(by_id[f]["answer"])
        for q in group:
            if numbers(q["answer"]) != want:
                errors.append(f"{q['id']}: its answer {q['answer']!r} has different numbers from fact {f}'s"
                              f" answer {by_id[f]['answer']!r}")
            for other in group:
                if plain(q["answer"]) in {plain(w) for w in other["wrong"]}:
                    errors.append(f"{q['id']}: its right answer is a wrong choice in {other['id']}, another"
                                  f" wording of fact {f}")
    return errors


def check_groups(groups, used):
    """data/groups.json: groups of easily mixed-up facts, shown side by side on a Compare screen.

    Every fact is in the sections and in at most one group, a group has 2 or more facts, each with
    its own label (the labels are the answer choices of a reverse question), and a `reverse` stem
    has {answer} exactly once and is only on a group of 4 or more, so it always has 3 wrong choices.
    """
    errors, seen, ids = [], {}, set()
    for g in groups:
        gid = g.get("id")
        if not gid or gid in ids:
            errors.append(f"group {gid!r}: needs an id of its own")
        ids.add(gid)
        facts = g.get("facts", [])
        if len(facts) < 2:
            errors.append(f"group {gid}: needs 2 or more facts")
        labels = [f.get("label", "") for f in facts]
        if not all(labels) or len(set(labels)) != len(labels):
            errors.append(f"group {gid}: every fact needs a label of its own")
        for f in facts:
            if f["id"] not in used:
                errors.append(f"group {gid}: {f['id']} is not a question in the sections")
            elif f["id"] in seen:
                errors.append(f"group {gid}: {f['id']} is already in group {seen[f['id']]}")
            seen[f["id"]] = gid
        stem = g.get("reverse")
        if stem is not None:
            if not isinstance(stem, str) or stem.count("{answer}") != 1:
                errors.append(f"group {gid}: its reverse stem needs {{answer}} exactly once")
            if len(facts) < 4:
                errors.append(f"group {gid}: a reverse stem needs a group of 4 or more facts")
    return errors


if __name__ == "__main__":
    errs = validate()
    for e in errs:
        print("-", e)
    print("OK" if not errs else f"{len(errs)} problem(s)")
    sys.exit(1 if errs else 0)
