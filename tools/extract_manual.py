#!/usr/bin/env python3
"""Pull the text of Sections B and C out of the Tennessee driver manual PDF.

The result (data/manual/sections-b-c.txt) is what every question was written
from and checked against. Each printed manual page starts with a line like
`=====MANUAL PAGE 47=====`, so a question's page number can be checked.

Needs pdftotext (poppler-utils).

Usage:
    python3 tools/extract_manual.py DL_Manual.pdf

The manual is free to download from tn.gov/safety. The edition used here is
dated July 1, 2022; in it the printed page number is the PDF page minus 14,
and Sections B and C are printed pages 24-121. A newer edition may shift
these, so check --offset against a page or two before trusting the output.
"""
import argparse
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def page_text(pdf, n):
    return subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), str(pdf), "-"],
                          capture_output=True, text=True, check=True).stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--offset", type=int, default=14, help="PDF page minus printed page (default 14)")
    ap.add_argument("--first", type=int, default=24, help="first printed page to keep (default 24)")
    ap.add_argument("--last", type=int, default=121, help="last printed page to keep (default 121)")
    ap.add_argument("--out", default=str(ROOT / "data" / "manual" / "sections-b-c.txt"))
    a = ap.parse_args()

    lines = []
    for printed in range(a.first, a.last + 1):
        lines.append(f"=====MANUAL PAGE {printed}=====")
        blank = False
        for raw in page_text(a.pdf, printed + a.offset).split("\n"):
            line = re.sub(r"\s+", " ", raw).strip()
            if line:
                lines.append(line)
                blank = False
            elif not blank:
                lines.append("")
                blank = True
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"Wrote {out} ({a.last - a.first + 1} pages)")


if __name__ == "__main__":
    main()
