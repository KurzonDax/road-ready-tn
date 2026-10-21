#!/usr/bin/env python3
"""Build the study app.

Reads the question bank (data/questions.json), the 12-section study plan
(data/sections.json) and the groups of easily mixed-up facts (data/groups.json),
checks them, and writes to dist/:

- index.html      the page (src/app.html), with no questions in it and the drawing
                  kit's part types (src/kit.json) written in
- questions.json  the questions the page fetches when it starts
- csp.json        the SHA-256 hash of the page's one inline script, for the
                  server's Content-Security-Policy header

and copies the Home Screen files from src/ as they are:

- manifest.webmanifest                 from src/manifest.webmanifest
- apple-touch-icon.png, icon-192.png,  from src/icons/, drawn by
  icon-512.png                         tools/make_icons.py
- fonts/                               from src/fonts/, without its README

and last writes sw.js, the service worker (src/sw.js), with two things filled in:
the build version, the first 12 hex characters of a SHA-256 over every other
file in the output folder (each one's path and contents), and the list of fonts,
icons and the manifest it keeps on install. Any change to any other file gives
the service worker a new version, which is how a new build replaces the old one's
kept files.

The page needs a web server: opened as a file it can't fetch questions.json
and shows "The questions could not be loaded." There is no guest mode.

Usage:
    python3 build.py [--src src/app.html] [--out dist]
"""
import argparse
import base64
import hashlib
import html.parser
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT / "tests"))
from validate_data import plain, validate  # noqa: E402


def compact(q, section=None, group=None):
    """Convert a bank question to the short field names the page uses. `section` is the Section of one
    of the app's 120 questions (None for another wording of a fact); `group` is the id of the
    data/groups.json group its fact is in, if any."""
    item = {
        "id": q["id"],
        "q": q["question"],
        "a": q["answer"],
        "o": q["wrong"],
        "why": q["explanation"],
        "p": q["page"],
    }
    if q.get("manual_sample"):
        item["s"] = 1
    if q.get("sign"):
        item["sign"] = q["sign"]
    if q.get("color"):
        item["swatch"] = q["color"]
    if group:
        item["group"] = group
    item["fact"] = q.get("fact") or q["id"]
    if section is not None:
        item["day"] = section  # the page calls sections "days" internally
    return item


def build_data():
    bank = json.loads((ROOT / "data" / "questions.json").read_text())
    plan = json.loads((ROOT / "data" / "sections.json").read_text())
    groups = json.loads((ROOT / "data" / "groups.json").read_text())["groups"]
    by_id = {q["id"]: q for q in bank["questions"]}
    group_of = {f["id"]: g["id"] for g in groups for f in g["facts"]}
    days, qs = [], []
    for sec in plan["sections"]:
        days.append({"day": sec["section"], "title": sec["title"]})
        qs.extend(compact(by_id[i], sec["section"], group_of.get(i)) for i in sec["questions"])
    app = {q["id"] for q in qs}
    # Other wordings of the app's facts (docs/QUESTIONS.md, `fact`): the page asks a fact in each of them in turn.
    wordings = [compact(q) for q in bank["questions"] if q.get("fact") in app and q["id"] not in app]
    add_also(qs, qs + wordings)
    return {"days": days, "qs": qs, "groups": groups, "wordings": wordings, "lessons": build_lessons()}


def build_lessons():
    """The lessons (data/lessons/section-N.json, docs/specs/lessons.md), in Section order. The manual's
    sentences stay in the data to check each step's fact; the page never shows them."""
    return [json.loads(file.read_text())
            for file in sorted((ROOT / "data" / "lessons").glob("section-*.json"), key=lambda f: int(f.stem.split("-")[1]))]


def add_also(facts, qs):
    """Give a question `also` when a wrong choice is the right answer to another fact: {wrong text: that
    fact's question id}. The page says so after that choice ("30 feet answers a different question: ...").
    `facts` are the app's 120 questions; `qs` every question shipped, wordings included."""
    answers = {plain(q["a"]): q["id"] for q in facts}
    for q in qs:
        also = {w: answers[plain(w)] for w in q["o"] if answers.get(plain(w), q["fact"]) != q["fact"]}
        if also:
            q["also"] = also


def with_kit(page):
    """The page with the drawing kit's part types (src/kit.json) written in place of its one __KIT__."""
    if page.count("__KIT__") != 1:
        sys.exit("The page must have __KIT__ exactly once, where the drawing kit's part types go.")
    kit = json.loads((SRC / "kit.json").read_text(encoding="utf-8"))["parts"]
    return page.replace("__KIT__", json.dumps(kit, separators=(",", ":")))


# An on...= attribute inside a tag the script writes as a string, such as `<button onclick="...">`.
HANDLER_IN_SCRIPT = re.compile(r"<[a-zA-Z][^<>]*?\son[a-z]+\s*=")


class _Scripts(html.parser.HTMLParser):
    """Collect the text of each inline <script> and any on...= handler attributes."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inline, self.handlers, self._in = [], [], False

    def handle_starttag(self, tag, attrs):
        self.handlers += [f"<{tag} {k}=...>" for k, _ in attrs if k.startswith("on")]
        if tag == "script" and not dict(attrs).get("src"):
            self.inline.append("")
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.inline[-1] += data


def script_hash(page):
    """Return the CSP hash of the page's one inline script, or stop if the page breaks the CSP rules."""
    parser = _Scripts()
    parser.feed(page)
    parser.close()
    if len(parser.inline) != 1:
        sys.exit(f"The page must have exactly one inline <script>; it has {len(parser.inline)}.")
    parser.handlers += HANDLER_IN_SCRIPT.findall(parser.inline[0])
    if parser.handlers:
        sys.exit("The page must not use inline on...= handler attributes: " + ", ".join(parser.handlers))
    digest = hashlib.sha256(parser.inline[0].encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def build_version(out):
    """The first 12 hex characters of a SHA-256 over every file in out/ but sw.js, path and contents."""
    digest = hashlib.sha256()
    for file in sorted(p for p in out.rglob("*") if p.is_file() and p.relative_to(out).as_posix() != "sw.js"):
        name = file.relative_to(out).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(4, "big") + name)
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    return digest.hexdigest()[:12]


def static_files(out):
    """The files sw.js keeps on install: the fonts, the icons and the manifest."""
    names = [p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()]
    return sorted(n for n in names if (n.startswith("fonts/") and n.endswith(".woff2"))
                  or re.fullmatch(r"icon-[^/]+\.png|apple-touch-icon\.png|manifest\.webmanifest", n))


def write_service_worker(out):
    sw = (SRC / "sw.js").read_text(encoding="utf-8")
    for placeholder in ("'__VERSION__'", "__STATIC_FILES__"):
        if sw.count(placeholder) != 1:
            sys.exit(f"src/sw.js must have {placeholder} exactly once.")
    version = build_version(out)
    sw = sw.replace("'__VERSION__'", f"'{version}'").replace("__STATIC_FILES__", json.dumps(static_files(out)))
    (out / "sw.js").write_text(sw, encoding="utf-8")
    return version


def main():
    args = argparse.ArgumentParser(description="Build the study app into dist/.")
    args.add_argument("--src", type=pathlib.Path, default=ROOT / "src" / "app.html", help="page source")
    args.add_argument("--out", type=pathlib.Path, default=ROOT / "dist", help="folder to write into")
    opts = args.parse_args()
    errors = validate()
    if errors:
        print("Data check failed:")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    data = build_data()
    page = with_kit(opts.src.read_text(encoding="utf-8"))
    csp = {"script": script_hash(page)}
    out = opts.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "questions.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / "csp.json").write_text(json.dumps(csp) + "\n", encoding="utf-8")
    shutil.copyfile(SRC / "manifest.webmanifest", out / "manifest.webmanifest")
    for icon in sorted((SRC / "icons").glob("*.png")):
        shutil.copyfile(icon, out / icon.name)
    shutil.rmtree(out / "fonts", ignore_errors=True)
    shutil.copytree(SRC / "fonts", out / "fonts", ignore=shutil.ignore_patterns("README.md"))
    version = write_service_worker(out)
    print(f"Wrote {out}: index.html, csp.json, questions.json ({len(data['qs'])} questions in {len(data['days'])} sections, {len(data['lessons'])} lessons),"
          f" manifest.webmanifest, icons, fonts/, sw.js (version {version})")


if __name__ == "__main__":
    main()
