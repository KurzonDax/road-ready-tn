#!/usr/bin/env python3
"""Check what build.py writes and what it refuses, and that check_dist.py catches a stale dist/.

Runs build.py and check_dist.py as programs, the way a person runs them, into temporary folders.

Usage:
    python3 tests/test_build.py
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
failures = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)


def build_into(out, src=None):
    args = ["build.py", "--out", out]
    if src:
        args += ["--src", src]
    return run(*args)


def test_build_writes_page_questions_and_csp(tmp):
    out = tmp / "out"
    r = build_into(out)
    check(r.returncode == 0, "build succeeds" + (f": {r.stderr}" if r.returncode else ""))
    names = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) if out.exists() else []
    want = ["apple-touch-icon.png", "csp.json",
            "fonts/atkinson-hyperlegible/OFL.txt", "fonts/atkinson-hyperlegible/atkinson-hyperlegible-400.woff2",
            "fonts/atkinson-hyperlegible/atkinson-hyperlegible-700.woff2",
            "fonts/overpass/OFL.txt", "fonts/overpass/overpass-variable.woff2",
            "icon-192.png", "icon-512.png", "index.html", "manifest.webmanifest", "questions.json", "sw.js"]
    check(names == want, "build writes the page, questions, CSP hash, manifest, icons, fonts with their licenses,"
          " and the service worker"
          + (f" (got {names})" if names != want else ""))
    if not {"csp.json", "index.html", "questions.json"} <= set(names):
        return
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    page = (out / "index.html").read_text()
    leaked = [q["id"] for q in bank["questions"] if q["question"] in page or q["manual_quote"] in page]
    check(not leaked, f"the page has no question text in it (found {leaked[:3]})")
    data = json.loads((out / "questions.json").read_text())
    check(sorted(data) == ["days", "groups", "lessons", "qs", "wordings"] and len(data["days"]) == 12 and len(data["qs"]) == 120,
          "questions.json holds the 12 sections, 120 questions, the groups, the other wordings and the lessons")
    lessons = {l["section"]: l for l in data["lessons"]}
    check(3 in lessons and not any("src" in st or "p" in st for st in lessons[3]["steps"]),
          "the Section 3 lesson is shipped, with no manual sentence or page in any step")
    tagged = [q for q in bank["questions"] if q.get("fact") and q["fact"] != q["id"]]
    wordings = data.get("wordings", [])
    check(sorted(w["id"] for w in wordings) == sorted(q["id"] for q in tagged)
          and all(w["fact"] == next(q["fact"] for q in tagged if q["id"] == w["id"]) and "day" not in w for w in wordings),
          f"every other wording in the bank ships with its fact, and no Section (got {len(wordings)} of {len(tagged)})")
    check(all(q["fact"] == q["id"] for q in data["qs"]), "each of the 120 questions is its own fact")
    d165 = next((w for w in wordings if w["id"] == "d-165"), {})
    check(d165.get("fact") == "b-077" and d165.get("q") and d165.get("a") and len(d165.get("o", [])) == 3,
          f"a wording has the page's short fields: question, answer, wrong choices (got {d165})")
    groups = json.loads((ROOT / "data" / "groups.json").read_text())["groups"]
    check(data.get("groups") == groups, "the groups are data/groups.json's, as they are")
    grouped = {q["id"]: q["group"] for q in data["qs"] if "group" in q}
    check(len(grouped) == 56 and grouped.get("b-250") == "parking-distances" and grouped.get("a-084") == "sign-colors",
          f"the 56 grouped questions name their group (got {len(grouped)})")
    check("__DATA__" not in page, "the page has no __DATA__ placeholder left")
    by_id = {q["id"]: q for q in data["qs"]}
    also = {q["id"]: q["also"] for q in data["qs"] if "also" in q}
    check(sum(len(a) for a in also.values()) == 15 and len(also) == 12,
          f"15 wrong choices across 12 questions name the question they answer (got {also})")
    check(also.get("b-250") == {"30 feet": "b-253"} and also.get("b-253") == {"15 feet": "b-250", "50 feet": "b-251"},
          "a wrong choice that is another question's answer names that question")
    check(all(w in by_id[q]["o"] and by_id[r]["a"] == w for q, a in also.items() for w, r in a.items()),
          "every also entry is a wrong choice of its question and the right answer of the one it names")


def test_build_refuses_pages_that_break_the_csp(tmp):
    page = (ROOT / "src" / "app.html").read_text()
    cases = {
        "a second inline <script>": page.replace("</body>", "<script>console.log(1)</script>\n</body>"),
        "an on...= handler in the markup": page.replace('<main id="stage">', '<main id="stage" onclick="go()">'),
        "an on...= handler in HTML the script writes": page.replace(
            'id="homeBtn">', 'id="homeBtn" onclick="renderHome()">'),
    }
    for name, bad in cases.items():
        check(bad != page, f"test setup: {name} was added to the copy")
        src = tmp / "bad.html"
        src.write_text(bad)
        out = tmp / "refused"
        r = build_into(out, src)
        check(r.returncode != 0 and not (out / "index.html").exists(), f"build refuses a page with {name}")
    r = build_into(tmp / "fine", ROOT / "src" / "app.html")
    check(r.returncode == 0, "build accepts the real page")


def sw_version(folder):
    """The build version written into folder/sw.js, or None."""
    try:
        m = re.search(r"const VERSION = '([^']*)';", (folder / "sw.js").read_text())
    except OSError:
        return None
    return m and m.group(1)


def test_sw_carries_a_build_version(tmp):
    first, again = tmp / "v1", tmp / "v1-again"
    build_into(first)
    build_into(again)
    v1 = sw_version(first)
    check(v1 is not None and re.fullmatch(r"[0-9a-f]{12}", v1) is not None,
          f"sw.js carries a 12-hex-character build version (got {v1!r})")
    check("__" not in (first / "sw.js").read_text(), "sw.js has no placeholder left")
    check(sw_version(again) == v1, "building the same sources again gives the same version")
    static = re.search(r"const STATIC_FILES = (\[.*?\]);", (first / "sw.js").read_text(), re.S)
    listed = sorted(json.loads(static.group(1))) if static else None
    want = ["apple-touch-icon.png", "fonts/atkinson-hyperlegible/atkinson-hyperlegible-400.woff2",
            "fonts/atkinson-hyperlegible/atkinson-hyperlegible-700.woff2", "fonts/overpass/overpass-variable.woff2",
            "icon-192.png", "icon-512.png", "manifest.webmanifest"]
    check(listed == want, "sw.js lists the fonts, icons and manifest to keep" + ("" if listed == want else f" (got {listed})"))

    repo = copy_repo(tmp, "sw-repo")
    changes = {
        "a page change": (repo / "src" / "app.html", lambda b: b.replace(b"Road Ready TN", b"Road Ready Tennessee")),
        "a font change": (repo / "src" / "fonts" / "overpass" / "overpass-variable.woff2", lambda b: b + b"\0"),
        "a question change": (repo / "data" / "sections.json", lambda b: b.replace(b'"title": "', b'"title": "The ', 1)),
    }
    seen = {v1}
    for name, (file, change) in changes.items():
        file.write_bytes(change(file.read_bytes()))
        out = tmp / ("after " + name)
        r = run("build.py", "--out", out, cwd=repo)
        v = sw_version(out)
        check(r.returncode == 0 and v not in seen, f"{name} gives sw.js a new version" + (f": {r.stderr}" if r.returncode else ""))
        seen.add(v)


def copy_repo(tmp, name="repo"):
    """A copy of the project to build and change without touching the real one."""
    repo = tmp / name
    for name in ("build.py", "data", "src", "tests", "dist"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, repo / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            repo.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, repo / name)
    return repo


def test_check_dist_catches_a_stale_dist(tmp):
    repo = copy_repo(tmp)
    r = run("build.py", cwd=repo)
    check(r.returncode == 0, "build into the copy's dist/ succeeds")
    r = run("tests/check_dist.py", cwd=repo)
    check(r.returncode == 0, "check_dist passes on a fresh build" + (f": {r.stdout}{r.stderr}" if r.returncode else ""))

    app = repo / "src" / "app.html"
    app.write_text(app.read_text().replace("Road Ready TN", "Road Ready Tennessee"))
    r = run("tests/check_dist.py", cwd=repo)
    check(r.returncode != 0 and "index.html" in r.stdout + r.stderr,
          "check_dist fails, naming index.html, after src/app.html changes without a rebuild")

    run("build.py", cwd=repo)
    font = repo / "src" / "fonts" / "overpass" / "overpass-variable.woff2"
    font.write_bytes(font.read_bytes() + b"\0")
    r = run("tests/check_dist.py", cwd=repo)
    check(r.returncode != 0 and "dist/fonts/overpass/overpass-variable.woff2 is out of date" in r.stdout,
          "check_dist fails, naming the font, after a font in src/fonts/ changes without a rebuild")

    run("build.py", cwd=repo)
    csp = repo / "dist" / "csp.json"
    csp.write_text(json.dumps({"script": "sha256-" + "A" * 43 + "="}) + "\n")
    r = run("tests/check_dist.py", cwd=repo)
    check(r.returncode != 0 and "does not match the page's inline script" in r.stdout,
          "check_dist fails, saying the hash does not match, when csp.json's hash is wrong")


def test_group_rules_catch_each_mistake():
    """The rules validate_data.py checks data/groups.json against, each shown catching its mistake."""
    sys.path.insert(0, str(ROOT / "tests"))
    from validate_data import check_groups
    used = {"q-1", "q-2", "q-3", "q-4", "q-5"}

    def group(gid="g", facts=("q-1", "q-2"), reverse=None, **extra):
        return {"id": gid, "title": "A title", "reverse": reverse,
                "facts": [{"id": f, "label": f"Label {f}"} for f in facts], **extra}

    check(check_groups([group(), group("h", ("q-3", "q-4", "q-5"))], used) == [],
          "groups of facts in the sections, each in one group, pass")
    four = ("q-1", "q-2", "q-3", "q-4")
    for groups, want, what in (
            ([group(facts=("q-1", "x-9"))], "x-9", "a fact not in the sections"),
            ([group(), group("h", ("q-2", "q-3"))], "q-2", "a fact in two groups"),
            ([group(facts=("q-1",))], "2 or more", "a group of one fact"),
            ([dict(group(), facts=[{"id": "q-1", "label": ""}, {"id": "q-2", "label": "B"}])], "label", "an empty label"),
            ([dict(group(), facts=[{"id": "q-1", "label": "Same"}, {"id": "q-2", "label": "Same"}])], "label",
             "two facts with one label"),
            ([group(facts=four, reverse="Which one: {answer} or {answer}?")], "{answer}", "a stem with {answer} twice"),
            ([group(facts=four, reverse="Which one?")], "{answer}", "a stem with no {answer}"),
            ([group(facts=("q-1", "q-2", "q-3"), reverse="Which one: {answer}?")], "4 or more",
             "a reverse stem on a group of 3"),
            ([group(), group()], "id", "two groups with one id"),
            ([group(facts=four, reverse=7)], "{answer}", "a stem that is not text")):
        errors = check_groups(groups, used)
        check(any(want in e for e in errors), f"check_groups catches {what} (got {errors})")
    check(check_groups([group(facts=four, reverse="Which one: {answer}?")], used) == [],
          "a reverse stem with {answer} once, on 4 facts, passes")


def main():
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        print("[build]")
        test_build_writes_page_questions_and_csp(tmp)
        print("\n[service worker]")
        test_sw_carries_a_build_version(tmp)
        print("\n[refusals]")
        test_build_refuses_pages_that_break_the_csp(tmp)
        print("\n[check_dist]")
        test_check_dist_catches_a_stale_dist(tmp)
        print("\n[groups.json rules]")
        test_group_rules_catch_each_mistake()
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
