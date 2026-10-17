# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is one specific learner preparing for the Tennessee Class D driver license knowledge test. They read literally, find tests stressful, and do best with one thing on screen at a time. They study on their own, without anyone helping, on a phone or a laptop.

After that learner, the app is for any Tennessee permit learner who wants a structured path instead of a question dump, especially those with similar needs. The repo is public so that others can run their own Instance. An Instance is private to the people its Helper gives access to.

A second, minor audience is the Helper, who sets the app up for a Learner and manages Learners from the Helper's view. There a Helper adds, renames and deletes Learners, gives a Learner a new password, follows each Learner's Progress and History, and makes a Reset or a Move. Nothing on the Learner's pages is addressed to the Helper.

## Product Purpose

Road Ready TN takes a learner from zero to ready for the knowledge test one small step at a time, and makes them recall each fact after a gap, several times, on separate days. A Section's facts are taught first in a lesson: on every step the learner acts, by tapping the car that goes or choosing, before the rule is stated, and the topic's principle is named after two or three cases. Then the learner sees one Set at a time: up to 10 counted questions, the facts that are due again and a few new ones. A new fact from a Section without a lesson starts with a first look (an unscored question), then its answer and a plain explanation, and its question comes back later in the Set. After each answer the app explains it in plain words. The manual's own sentences are kept in the data to check every question, not shown. The end of a Set says how many facts are learned, never a score.

New facts arrive in the order of the 12 Sections. Each fact is asked again after 12 hours, then 48 hours, then every 7 days once it is solid, and at once after a wrong answer. Practice tests of 30 questions unlock once every fact is learned. Success is "Ready for the test", meaning 27 or more of 30 on three practice tests in a row. That is a 90% bar against the real test's 80% (24 of 30), to leave room for nerves. The Helper's view shows each fact's standing and how often facts answered right are still right 12 or more hours later; that retention figure is how the app is checked.

## Positioning

A calm, guided path rather than a question bank. There's no menu, no topic list, and no pile of hundreds of questions. Every question is answerable from a verbatim, page-cited statement in the 2022 Tennessee Comprehensive Driver License Manual, checked by an independent review pass, and reworded to a standard written for literal readers. Where the manual is ambiguous or contradicts itself, the fact is left out instead of guessed (see `docs/DECISIONS.md`).

## Operating Context

- Short, self-directed Study sessions on a phone or laptop with no Helper present. The app has to explain itself without outside instruction.
- Served by an Instance: a small server (`python -m server`) in one container, behind HTTPS. The page can be installed as a Home Screen app, and after one visit online it opens and works offline. Finished Sets wait on the device and are sent when it is back online. Signing in and signing out need a connection.
- Each Learner and each Helper has an account with a name and a password. Progress is stored on the Instance, so it follows the Learner across devices. Each device keeps a working copy of the signed-in Learner's records.
- The source of truth is the manual PDF from tn.gov/safety (edition dated July 1, 2022). When the app and the current manual disagree, the manual is right.

## Capabilities and Constraints

- **Flow:** Sets, one after another. Each Set takes the facts that are due, then up to 5 new facts in Section order, with at least 4 screens for other facts between a new fact's rule and its question. A fact answered wrong is asked once more in the same Set and again in the next. Once a group of easily mixed-up facts is learned (`data/groups.json`), a later Set, at least 12 hours on, opens with a Compare screen that shows them side by side, then asks each one, some the other way round. Practice tests of 30 questions drawn from all 120 unlock once every fact is learned (`docs/specs/learning-engine.md`).
- **Scoring:** each fact has a standing (new, seen, learned, solid) worked out from its answers; standings only rise (`docs/adr/0002-standings-and-the-due-ladder.md`). A Section shows green on the progress track once its 10 facts are learned. The home screen and Set done show how many facts are learned and solid; only a Practice test shows how many were right.
- **Order:** new facts come easiest first within a Section; due facts are shuffled among them. Answer choices are shuffled every time.
- **Content:** 120 app questions chosen from a bank of 847 (`data/questions.json`, `data/sections.json`), including all 29 of the manual's sample questions. 73 other questions are other wordings of the 120, and the app asks each fact in its wordings in turn. Each has exactly one right answer and three wrong ones, an explanation, a page, and a quote under 25 words. Sign or color pictures appear only when they don't give the answer away.
- **Stack:** a single HTML page (`src/app.html`) with inline styles and script, used by both the Learner and the Helper. `build.py` validates the data and writes the page (`dist/index.html`), its questions (`dist/questions.json`, fetched when the page starts and served only to someone signed in), the inline script's CSP hash (`dist/csp.json`), the Home Screen files and the service worker (`dist/sw.js`). The server (`server/`) is the Python standard library plus waitress (vendored in `vendor/`), with SQLite in the Instance folder. It stores accounts and each Learner's records, and the page works out Progress from those records (`docs/adr/0001-server-stores-records-page-works-out-progress.md`). Tests are in Python (`tests/`), and the browser test uses Playwright.
- **Fixed:** question ids never change, because the Learner's records refer to them. The old progress key `tn-permit-daily-v1` is only read, once, to import progress saved before accounts.
- **Terminology:** "Set", "Section", "Lesson", "First look", "Rule screen", "Practice test", "Ready for the test". Standing words: new, seen, learned, solid.

## Brand Commitments

- Name: **Road Ready TN**.
- Voice: plain, calm, literal. Use "you", active voice, short words, and complete rules. Rules with conditions state both cases. No hedging, shorthand, or telegraphic fragments. The full standard is in `docs/QUESTIONS.md`.
- Every word on the Learner's pages is addressed to the Learner. The Helper's view speaks to the Helper in the same plain style. Instructions for running an Instance belong outside the app (`docs/self-hosting.md`).
- Not affiliated with the Tennessee Department of Safety and Homeland Security, and must never imply that it is.

## Evidence on Hand

- `data/questions.json`: 847 verified questions with manual quotes and pages.
- `data/manual/sections-b-c.txt`: the manual text for printed pages 24 to 121, marked by page.
- The manual says its information "is not copyrighted and may be reproduced."
- There are no testimonials, user counts, or pass-rate data, and none should be invented.

## Product Principles

1. **One step at a time.** Show only the current section and the current question. Never add menus, topic lists, or choices the learner doesn't need right now.
2. **Literal and complete.** Every sentence has to be correct read word for word. A clipped or hedged answer counts as a wrong answer.
3. **Calm over pressure.** No timers, streaks, or alarming feedback. Scores inform; they don't punish. The ready bar sits above the real test's to absorb nerves.
4. **The manual is the authority.** Every fact traces to a quoted, page-cited line. Ambiguous facts are left out, not guessed.
5. **Works alone, anywhere.** The Learner studies alone, online or offline, with nothing to set up. No Helper has to be present.

## Accessibility & Inclusion

The needs every change must protect:

- **Literal reading:** wording is exact, complete, and unambiguous. No idioms, no implied meanings, and NOT is capitalized when used.
- **Test anxiety:** no time pressure, gentle feedback, and a clear sense of how far along the learner is.
- **Attention and focus:** one task on screen, no distractions, and a predictable flow.

Baseline: readable, legible type at phone size; keyboard and screen reader support (the stage is an `aria-live` region); and one dark color scheme on every device, whatever its own setting.
