#!/usr/bin/env python3
"""Check what build.py writes and what it refuses, and that check_dist.py catches a stale dist/.

Runs build.py and check_dist.py as programs, the way a person runs them, into temporary folders.

Usage:
    python3 tests/test_build.py
"""
import json
import pathlib
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
            "icon-192.png", "icon-512.png", "index.html", "manifest.webmanifest", "questions.json"]
    check(names == want, "build writes the page, questions, CSP hash, manifest, icons, and fonts with their licenses"
          + (f" (got {names})" if names != want else ""))
    if not {"csp.json", "index.html", "questions.json"} <= set(names):
        return
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    page = (out / "index.html").read_text()
    leaked = [q["id"] for q in bank["questions"] if q["question"] in page or q["manual_quote"] in page]
    check(not leaked, f"the page has no question text in it (found {leaked[:3]})")
    data = json.loads((out / "questions.json").read_text())
    check(sorted(data) == ["days", "qs"] and len(data["days"]) == 12 and len(data["qs"]) == 120,
          "questions.json holds the 12 sections and 120 questions")
    check("__DATA__" not in page, "the page has no __DATA__ placeholder left")


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


def copy_repo(tmp):
    """A copy of the project to build and change without touching the real one."""
    repo = tmp / "repo"
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


def main():
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        print("[build]")
        test_build_writes_page_questions_and_csp(tmp)
        print("\n[refusals]")
        test_build_refuses_pages_that_break_the_csp(tmp)
        print("\n[check_dist]")
        test_check_dist_catches_a_stale_dist(tmp)
    print("\nAll checks passed." if not failures else f"\n{len(failures)} check(s) failed.")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
