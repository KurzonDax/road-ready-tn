# Road Ready TN

A calm, one-step-at-a-time study app for the Tennessee Class D driver license knowledge test.

I am developing this specifically for my son who is on the autism spectrum and struggles with normal study methods, and with taking tests.

I am not an educator by trade or training.  In fact, I'm pretty terrible at trying to teach anything, so I'm trying to build a tool that will help my son learn what he needs to pass the test.

This app is mainly geared toward mobile first, but also supports a desktop browser.  The learner sees one short Set at a time: the facts due again and a few new ones, each new fact's rule before its question, a plain explanation after each answer, and at the end how many facts are learned. There's no menu, no topic list, and no pile of hundreds of questions. It was built for a learner who reads literally and finds tests stressful, and it works for anyone who wants a structured path instead of a question dump.

Since this app is in active development, the content of this README may not always be up to date.  

## How it works

| Step | What the learner does | Done when |
| --- | --- | --- |
| Lessons | One per Section, before its first Set: on each step the learner acts on a drawing or a choice first, then sees the rule and the manual's sentence | The Section's facts are taught |
| Sets | Up to 10 counted questions: facts due again, then up to 5 new facts in Section order. Each new fact gets a first look, its rule, and its question a few screens later | Every fact is learned |
| Practice tests | 30 questions drawn from all 120, like the real test | 27 or more right, three times in a row |

- A fact answered right comes back after 12 hours, then 48 hours, then every 7 days. A fact answered wrong comes back once more in the same Set and again in the next one. The home screen shows how many of the 120 facts are learned, never a score, and a Section shows as finished once its 10 facts are learned. The full design is in [docs/specs/learning-engine.md](docs/specs/learning-engine.md).
- Stopping partway, or closing the page, keeps the answers so far. The home screen offers to continue where the learner stopped.
- The real test is 30 questions and needs 24 right (80%). "Ready" asks for 27 (90%) to leave room for nerves.
- Progress is stored on the Instance, so it follows the learner from one device to another. With no connection the app still works, and finished sets wait on the device until it is back online.

The 120 questions cover the rules the test asks about, including all 29 of the manual's own end-of-chapter sample questions. They come from a bank of 847 questions written from and checked against the manual, and the app asks many of them in more than one wording. See [docs/QUESTIONS.md](docs/QUESTIONS.md).

## Run your own Instance

An Instance is one hosted copy of Road Ready TN. A Helper runs it, and only the Learners and Helpers who have an account on it can sign in. It is one Docker container on a stock Python image with the repo mounted in, so there is nothing to build. An HTTPS reverse proxy in front of the container is required. [docs/self-hosting.md](docs/self-hosting.md) covers setting it up, making the first Helper, updating, backups and the settings.

## Project layout

```
data/
  questions.json         847 questions: answer, wrong answers, explanation, manual page and quote
  sections.json          the 12 study sections (10 question ids each)
  manual/sections-b-c.txt  text of manual Sections B and C, marked by printed page
src/
  app.html               the page (styles and script) for Learners and Helpers; it fetches questions.json when it starts
  sw.js                  the service worker; build.py fills in its version and file list
  manifest.webmanifest   the Home Screen app manifest
  icons/                 the Home Screen icons, drawn by tools/make_icons.py
  fonts/                 Atkinson Hyperlegible and Overpass as WOFF2, with their licenses
build.py                 checks the data, then writes dist/
dist/                    what build.py writes, committed; the server serves it
  index.html             the built page, with no questions in it
  questions.json         the 120 app questions and 12 sections the page loads, sent only when signed in
  csp.json               SHA-256 hash of the page's one inline script, for the server's CSP header
  sw.js                  the service worker, with the build version filled in
server/                  the Instance's server: python -m server
  __main__.py            reads the settings, updates the database, starts waitress
  app.py                 routes, response headers and the files from dist/
  auth.py                accounts, passwords, sign-in and sessions
  limits.py              the pauses after too many failed sign-ins
  records.py             each Learner's records and unfinished Set
  helpers.py             what the Helper's view reads and changes
  db.py                  the SQLite database in the Instance folder and its schema steps
  manage.py              python -m server.manage: Helper accounts, unlock, backup
vendor/                  waitress, the only package not in the standard library (see vendor/README.md)
compose.yaml             runs an Instance with Docker Compose
.env.example             the settings compose.yaml reads; copy it to .env
tests/
  validate_data.py       data rules (also run by build.py)
  check_quotes.py        every manual_quote appears on its page
  test_app.py            clicks through the whole app in a headless browser, on the real server
  test_server.py         the server: headers, sign-in, records, the Helper's routes, server.manage
  test_build.py          what build.py writes and refuses
  check_dist.py          fails if the committed dist/ is out of date
  check_compose.py       compose.yaml still runs the Instance the way docs/self-hosting.md says
tools/
  extract_manual.py      rebuilds the manual text from the PDF
  make_icons.py          draws the Home Screen icons (needs Pillow)
docs/
  QUESTIONS.md           how questions are written, checked, and worded
  DECISIONS.md           manual quirks and app behavior choices
  self-hosting.md        how to run your own Instance
  adr/                   records of decisions that are hard to reverse
GLOSSARY.md              the words this project uses, and what they mean
```

## Changing questions

1. Edit `data/questions.json` or `data/sections.json`. Keep ids unchanged, since each Learner's records refer to questions by id.
2. Run `python3 build.py`. It refuses to build if a rule in `tests/validate_data.py` is broken.
3. Run `python3 tests/check_quotes.py`, `python3 tests/test_build.py` and `python3 tests/test_app.py`.
4. Before committing, run `python3 tests/check_dist.py`. It fails if `dist/` doesn't match a fresh build.

The browser test needs Playwright: `pip install playwright && playwright install chromium`. To use an installed Chromium instead, set `CHROMIUM_PATH` (for example `CHROMIUM_PATH=/usr/bin/chromium`). Rebuilding the manual text needs `pdftotext` (poppler-utils) and the manual PDF from [tn.gov/safety](https://www.tn.gov/safety).

## Source and disclaimer

Questions are based on the [Tennessee Comprehensive Driver License Manual](https://www.tn.gov/content/dam/tn/safety/documents/DL_Manual.pdf), edition dated July 1, 2022. The manual states that its information "is not copyrighted and may be reproduced." This project is not affiliated with the Tennessee Department of Safety and Homeland Security. Laws change: when this app and the current manual disagree, the manual is right.
