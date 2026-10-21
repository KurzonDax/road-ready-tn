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
    errors += check_lessons(secs)
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


STEP_KINDS = {"tap", "choose", "principle"}
# The drawing kit's part types (src/kit.json), which the page draws from the same list: whether each can be a tap
# target or a highlight, and which are roads.
KIT = json.loads((ROOT / "src" / "kit.json").read_text())["parts"]


def check_lessons(secs, lessons=None):
    """data/lessons/section-N.json (docs/specs/lessons.md): a lesson teaches every fact of its Section in 10 to 15
    steps the Learner acts on. Each step's answer must be one of what it offers, and every wrong pick has its own
    explanation. Every part is a type the kit draws, and every tap target and highlight is a part in that step's
    drawing whose type the kit lets be a target. `lessons` maps file names to their text; by default, the files in
    data/lessons."""
    errors = []
    by_section = {s["section"]: s["questions"] for s in secs}
    targetable = sorted(t for t, kind in KIT.items() if kind["target"])
    if lessons is None:
        lessons = {file.name: file.read_text() for file in (ROOT / "data" / "lessons").glob("section-*.json")}
    for name, text in sorted(lessons.items()):
        try:
            lesson = json.loads(text)
        except ValueError as e:
            errors.append(f"{name}: not valid JSON ({e})")
            continue
        number = lesson.get("section")
        if f"section-{number}.json" != name or number not in by_section:
            errors.append(f"{name}: its section must be the number in its file name, one of the sections")
            continue
        facts, steps, ids = set(by_section[number]), lesson.get("steps", []), set()
        if not lesson.get("title") or not steps:
            errors.append(f"{name}: needs a title and steps")
        elif not 10 <= len(steps) <= 15:
            errors.append(f"{name}: has {len(steps)} steps; a lesson has 10 to 15")
        covered = set()
        for step in steps:
            sid = step.get("id") or "?"
            if sid in ids:
                errors.append(f"{name}: step id {sid} is used twice")
            ids.add(sid)
            kind, fact = step.get("kind"), step.get("fact")
            if kind not in STEP_KINDS:
                errors.append(f"{name} {sid}: kind must be one of {sorted(STEP_KINDS)}")
            if fact is not None and fact not in facts:
                errors.append(f"{name} {sid}: fact {fact} is not in Section {number}")
            if fact:
                covered.add(fact)
                if not step.get("rule"):
                    errors.append(f"{name} {sid}: a step with a fact needs a rule")
            elif kind != "principle":
                errors.append(f"{name} {sid}: only a principle step has no fact")
            then = step.get("then") or {}
            if not step.get("prompt") or not then.get("say"):
                errors.append(f"{name} {sid}: needs a prompt and then.say")
            parts = (step.get("scene") or {}).get("parts", [])
            for p in parts + then.get("parts", []):
                if p.get("t") not in KIT:
                    errors.append(f"{name} {sid}: part type {p.get('t')!r} is not one the kit draws (src/kit.json)")
            part_ids = {p.get("id") for p in parts if p.get("t") in targetable and p.get("id")}
            after_ids = {p.get("id") for p in then.get("parts", []) if p.get("t") in targetable and p.get("id")}
            if kind == "tap":
                targets = step.get("targets", [])
                tids = [t.get("id") for t in targets]
                if len(targets) < 2 or not all(t.get("label") for t in targets):
                    errors.append(f"{name} {sid}: a tap step needs 2 or more targets, each with a label")
                for tid in tids:
                    if tid not in part_ids:
                        errors.append(f"{name} {sid}: target {tid!r} is not a part in the scene of a type that can be a target"
                                      f" ({', '.join(targetable)})")
                if step.get("answer") not in tids:
                    errors.append(f"{name} {sid}: answer must be one of the targets")
            else:
                options = step.get("options", [])
                if not 2 <= len(options) <= 4 or len(set(options)) != len(options):
                    errors.append(f"{name} {sid}: needs 2 to 4 different options")
                if step.get("answer") not in options:
                    errors.append(f"{name} {sid}: answer must be one of the options")
                # A principle step is left out: the closing principle question's options are questions (s3-12).
                for o in options if kind == "choose" else []:
                    if o not in ("Yes", "No") and not str(o).endswith("."):
                        errors.append(f"{name} {sid}: option {o!r} must be Yes, No, or a complete sentence ending in a period")
            # `then.wrong` holds an explanation for every wrong pick and nothing else.
            wrong = then.get("wrong")
            picks = [t.get("id") for t in step.get("targets", [])] if kind == "tap" else step.get("options", [])
            wrong_picks = {k for k in picks if k != step.get("answer")}
            if not isinstance(wrong, dict) or set(wrong) != wrong_picks or not all(isinstance(v, str) and v.strip() for v in wrong.values()):
                errors.append(f"{name} {sid}: then.wrong must give one non-empty explanation for each wrong pick, {sorted(wrong_picks)}")
            hi = then.get("highlight")
            if hi is not None and hi not in part_ids | after_ids:
                errors.append(f"{name} {sid}: then.highlight {hi!r} is not a part in the scene of a type that can be a target"
                              f" ({', '.join(targetable)})")
        missing = facts - covered
        if missing and steps:
            errors.append(f"{name}: no step teaches {sorted(missing)}")
        errors += check_lesson_wording(name, steps)
    return errors


# Words that read two ways to a literal reader, or point at nothing. Each rule came from a review of the
# first lesson, so none is a guess: "right" is a direction in a driving app, "yield" is a sign, "step" is
# the data word for a screen, "both cases" names no case, and a semicolon joins what should be two sentences.
BANNED = [
    # "right" is fine as a direction: your right, the right, to the right, right turn, right lane, right-of-way.
    (re.compile(r"(?<!your )(?<!the )(?<!a )(?<!turn )(?<!turns )(?<!turning )\bright\b(?![- ]of[- ]way|-hand| turn| lane| curb| side| edge| away| now)", re.I),
     "says right; in a driving app right is a direction, so say correct, or name the side"),
    (re.compile(r"\byield(ed|s|ing)?\b(?! sign)", re.I), "says yield; say what the driver does (wait, let it pass), unless it is a yield sign"),
    (re.compile(r"\bsteps?\b(?! (in|into|off|out|onto|back|forward)\b)", re.I), "says step; a Learner never sees that word"),
    (re.compile(r"\b(both|these|those|the above|the earlier|previous|the last) (cases?|ones?|screens?|examples?|questions?)\b", re.I),
     "points at earlier screens without naming them; say which situations"),
    (re.compile(r"\bcases?\b", re.I), "says case; say situation, and name it"),
    (re.compile(r"\bscreens?\b", re.I), "says screen; to the Learner these are questions"),
    (re.compile(r"\bround\b(?= (steady |flashing )?(red|yellow|green)? ?(light|arrow))", re.I), "calls a light round; there are no square lights, so name it by its color and whether it flashes"),
    (re.compile(r"\byour (traffic )?light\b", re.I), "says your light; the Learner does not own a light, he comes up to one (the light ahead of you, a steady yellow light)"),
    (re.compile(r"[;!]"), "has a semicolon or an exclamation mark"),
    (re.compile(r"\b(wrong(?! way)|incorrect|oops|nice|great|good job|well done)\b", re.I), "has a verdict or praise word (the wrong way, a direction, is allowed)"),
]
# A drawing with an intersection must say what controls it, or that nothing does.
CONTROL = re.compile(r"stop sign|yield sign|traffic light|the light|green light|red light|yellow light|signal|no sign|all-way stop|crosswalk|driveway|parking lot|roundabout", re.I)


def check_lesson_wording(name, steps):
    errors = []
    for step in steps:
        sid = step.get("id") or "?"
        texts = [("prompt", step.get("prompt", "")), ("say", (step.get("then") or {}).get("say", ""))]
        wrong = (step.get("then") or {}).get("wrong")
        texts += [("wrong", v) for v in (wrong.values() if isinstance(wrong, dict) else []) if isinstance(v, str)]
        texts += [("option", o) for o in step.get("options", [])]
        texts += [("target label", t.get("label", "")) for t in step.get("targets", [])]
        for field, text in texts:
            for pattern, why in BANNED:
                if pattern.search(text):
                    errors.append(f"{name} {sid} {field}: {why}: {text!r}")
        for field, text in [t for t in texts if t[0] in ("prompt", "say", "wrong")]:
            for sentence in re.split(r"(?<=[.?])\s+", text):
                if len(sentence.split()) > 30:
                    errors.append(f"{name} {sid} {field}: a sentence of more than 30 words: {sentence!r}")
            if field == "prompt" and len(text.split()) > 60:
                errors.append(f"{name} {sid} prompt: more than 60 words")
        for field, say in [t for t in texts if t[0] in ("say", "wrong")]:
            if len(re.findall(r"[.?](?!\d)", say)) > 3:  # a period inside a number (0.08 percent) ends no sentence
                errors.append(f"{name} {sid} {field}: more than three sentences: {say!r}")
        parts = (step.get("scene") or {}).get("parts", [])
        roads = [p for p in parts if KIT.get(p.get("t"), {}).get("road")]
        if len(roads) >= 2 and step.get("kind") == "tap" and not CONTROL.search(step.get("prompt", "")):
            errors.append(f"{name} {sid} prompt: draws an intersection but does not say what controls it (a sign, a light, or no sign)")
    return errors


if __name__ == "__main__":
    errs = validate()
    for e in errs:
        print("-", e)
    print("OK" if not errs else f"{len(errs)} problem(s)")
    sys.exit(1 if errs else 0)
