#!/usr/bin/env python3
"""Check that the committed dist/ is what build.py makes from the current sources.

Builds into a temporary folder and fails if any file differs from dist/, or if
csp.json's hash is not the SHA-256 of the page's inline script. Run it before
committing, after `python3 build.py`.

Usage:
    python3 tests/check_dist.py
"""
import base64
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def hash_problem(folder):
    """Say what's wrong with folder's csp.json, or return None if its hash matches the page's script."""
    try:
        page = (folder / "index.html").read_text(encoding="utf-8")
        want = json.loads((folder / "csp.json").read_text(encoding="utf-8"))["script"]
    except (OSError, ValueError, KeyError) as e:
        return f"can't read index.html and csp.json: {e}"
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page, re.S)
    if len(scripts) != 1:
        return f"index.html has {len(scripts)} inline <script> elements, not 1"
    got = "sha256-" + base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode("ascii")
    if got != want:
        return f"csp.json's hash {want} does not match the page's inline script ({got})"
    return None


def main():
    problems = []
    with tempfile.TemporaryDirectory() as t:
        fresh = pathlib.Path(t)
        r = subprocess.run([sys.executable, str(ROOT / "build.py"), "--out", str(fresh)], capture_output=True, text=True)
        if r.returncode:
            print("build.py failed:\n" + r.stdout + r.stderr)
            raise SystemExit(1)
        names = sorted({str(p.relative_to(folder)) for folder in (fresh, DIST)
                        for p in folder.rglob("*") if p.is_file()})
        for name in names:
            built, committed = fresh / name, DIST / name
            if not committed.exists():
                problems.append(f"dist/{name} is missing")
            elif not built.exists():
                problems.append(f"dist/{name} is not made by build.py any more")
            elif built.read_bytes() != committed.read_bytes():
                problems.append(f"dist/{name} is out of date")
        for label, folder in (("fresh build", fresh), ("dist/", DIST)):
            problem = hash_problem(folder)
            if problem:
                problems.append(f"{label}: {problem}")
    if problems:
        print("dist/ is not up to date. Run `python3 build.py` and commit dist/.")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("dist/ is up to date.")


if __name__ == "__main__":
    main()
