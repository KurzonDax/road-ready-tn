# Road Ready TN

A calm, one-step-at-a-time study app for the Tennessee Class D driver license knowledge test.

I am developing this specifically for my son who is on the autism spectrum and struggles with normal study methods, and with taking tests.

I am not an educator by trade or training.  In fact, I'm pretty terrible at trying to teach anything, so I'm trying to build a tool that will help my son learn what he needs to pass the test.

This app is mainly geared toward mobile first, but also supports a desktop browser.  The learner sees only the section they're on: 10 questions, an explanation after each answer with the manual's own words and page number, and a short score at the end. There's no menu, no topic list, and no pile of hundreds of questions. It was built for a learner who reads literally and finds tests stressful, and it works for anyone who wants a structured path instead of a question dump.

Since this app is in active development, the content of this README may not always be up to date.  

## How it works

| Step | What the learner does | Done when |
| --- | --- | --- |
| Sections 1 to 12 | 10 questions on one topic per sitting, easiest first | All 12 sections finished |
| Review | Only the questions they missed, 10 at a time | Nothing left to review |
| Practice tests | 30 questions drawn from all 120, like the real test | 27 or more right, three times in a row |

- Finished sections show as finished, whatever the score. "See your section scores" on the home screen lists each section's latest score and lets the learner do it again in a new order.
- Stopping partway, or closing the page, keeps the answers so far. The home screen offers to continue where the learner stopped.
- The real test is 30 questions and needs 24 right (80%). "Ready" asks for 27 (90%) to leave room for nerves.
- Progress is saved in the browser on the device being used.

The 120 questions cover the rules the test asks about, including all 29 of the manual's own end-of-chapter sample questions. They come from a bank of 803 questions written from and checked against the manual. See [docs/QUESTIONS.md](docs/QUESTIONS.md).

## Using it

Open `dist/index.html` in any browser. It's one self-contained file that needs no server, and it works offline (fonts fall back to system fonts). To put it online, serve `dist/` from any static host, such as GitHub Pages.

## Project layout

```
data/
  questions.json         803 questions: answer, wrong answers, explanation, manual page and quote
  sections.json          the 12 study sections (10 question ids each)
  manual/sections-b-c.txt  text of manual Sections B and C, marked by printed page
src/app.html             the page (styles and script), with a __DATA__ placeholder
build.py                 checks the data, then writes dist/index.html
dist/index.html          the built app
tests/
  validate_data.py       data rules (also run by build.py)
  check_quotes.py        every manual_quote appears on its page
  test_app.py            clicks through the whole app in a headless browser
tools/extract_manual.py  rebuilds the manual text from the PDF
docs/
  QUESTIONS.md           how questions are written, checked, and worded
  DECISIONS.md           manual quirks and app behavior choices
```

## Changing questions

1. Edit `data/questions.json` or `data/sections.json`. Keep ids unchanged, since saved progress is keyed by id.
2. Run `python3 build.py`. It refuses to build if a rule in `tests/validate_data.py` is broken.
3. Run `python3 tests/check_quotes.py` and `python3 tests/test_app.py`.

The browser test needs Playwright: `pip install playwright && playwright install chromium`. To use an installed Chromium instead, set `CHROMIUM_PATH` (for example `CHROMIUM_PATH=/usr/bin/chromium`). Rebuilding the manual text needs `pdftotext` (poppler-utils) and the manual PDF from [tn.gov/safety](https://www.tn.gov/safety).

## Source and disclaimer

Questions are based on the [Tennessee Comprehensive Driver License Manual](https://www.tn.gov/content/dam/tn/safety/documents/DL_Manual.pdf), edition dated July 1, 2022. The manual states that its information "is not copyrighted and may be reproduced." This project is not affiliated with the Tennessee Department of Safety and Homeland Security. Laws change: when this app and the current manual disagree, the manual is right.
