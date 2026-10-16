#!/usr/bin/env python3
"""Build the study app.

Reads the question bank (data/questions.json) and the 12-section study plan
(data/sections.json), checks them, and writes three files to dist/:

- index.html      the page, with no questions in it
- questions.json  the questions the page fetches when it starts
- csp.json        the SHA-256 hash of the page's one inline script, for the
                  server's Content-Security-Policy header

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
    page = opts.src.read_text(encoding="utf-8")
    csp = {"script": script_hash(page)}
    out = opts.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "questions.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / "csp.json").write_text(json.dumps(csp) + "\n", encoding="utf-8")
    print(f"Wrote {out}: index.html, csp.json, questions.json ({len(data['qs'])} questions in {len(data['days'])} sections)")


if __name__ == "__main__":
    main()
