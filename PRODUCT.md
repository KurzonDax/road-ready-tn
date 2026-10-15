# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is one specific learner preparing for the Tennessee Class D driver license knowledge test. They read literally, find tests stressful, and do best with one thing on screen at a time. They study on their own, without anyone helping, on a phone or a laptop.

After that learner, the app is meant to be shared publicly with any Tennessee permit learner who wants a structured path instead of a question dump, especially those with similar needs.

A second, minor audience is whoever manages the device. They have hidden URL controls (`#restart`, `#sectionN`) but are never addressed by anything on the page.

## Product Purpose

Road Ready TN takes a learner from zero to ready for the knowledge test one small step at a time. The learner sees only the section they're on: 10 questions on one topic, an explanation after each answer with the manual's own words and page number, and a short score at the end.

The path is fixed: Sections 1 to 12, then Review (only missed questions), then Practice tests of 30 questions. Success is "Ready for the test", meaning 27 or more of 30 on three practice tests in a row. That is a 90% bar against the real test's 80% (24 of 30), to leave room for nerves.

## Positioning

A calm, guided path rather than a question bank. There's no menu, no topic list, and no pile of hundreds of questions. Every question is answerable from a verbatim, page-cited statement in the 2022 Tennessee Comprehensive Driver License Manual, checked by an independent review pass, and reworded to a standard written for literal readers. Where the manual is ambiguous or contradicts itself, the fact is left out instead of guessed (see `docs/DECISIONS.md`).

## Operating Context

- Short, self-directed study sittings on a phone or laptop with no helper present. The app has to explain itself without outside instruction.
- Distributed as one self-contained file (`dist/index.html`) that works offline and needs no server. It can also be served from any static host.
- Progress is saved in the browser on that device only, under the key `tn-permit-daily-v1`. There are no accounts and no sync, so switching devices starts over.
- The source of truth is the manual PDF from tn.gov/safety (edition dated July 1, 2022). When the app and the current manual disagree, the manual is right.

## Capabilities and Constraints

- **Flow:** 12 sections of 10 questions each, easiest first the first time through. Then Review, 10 missed questions at a time. Then Practice tests of 30 questions drawn from all 120.
- **Scoring:** a finished section is colored by its latest score: green for 10 of 10, yellow for 7 to 9, red for under 7. Tapping a finished section redoes it in a new order. Getting a missed question right on a redo removes it from review.
- **Order:** redos and review shuffle the questions. Answer choices are shuffled every time.
- **Content:** 120 app questions chosen from a bank of 803 (`data/questions.json`, `data/sections.json`), including all 29 of the manual's sample questions. Each has exactly one right answer and three wrong ones, an explanation, a page, and a quote under 25 words. Sign or color pictures appear only when they don't give the answer away.
- **Stack:** a single HTML page (`src/app.html`) with inline styles and script. `build.py` validates the data and inlines it into `dist/index.html`. Tests are in Python (`tests/`), and the browser test uses Playwright.
- **Fixed:** question ids and the saved progress key never change, because progress is keyed by them.
- **Terminology:** "Section", "Review", "Practice test", "Ready for the test".

## Brand Commitments

- Name: **Road Ready TN**.
- Voice: plain, calm, literal. Use "you", active voice, short words, and complete rules. Rules with conditions state both cases. No hedging, shorthand, or telegraphic fragments. The full standard is in `docs/QUESTIONS.md`.
- Every word on the page is addressed to the learner. Instructions for helpers belong outside the app.
- Not affiliated with the Tennessee Department of Safety and Homeland Security, and must never imply that it is.

## Evidence on Hand

- `data/questions.json`: 803 verified questions with manual quotes and pages.
- `data/manual/sections-b-c.txt`: the manual text for printed pages 24 to 121, marked by page.
- The manual says its information "is not copyrighted and may be reproduced."
- There are no testimonials, user counts, or pass-rate data, and none should be invented.

## Product Principles

1. **One step at a time.** Show only the current section and the current question. Never add menus, topic lists, or choices the learner doesn't need right now.
2. **Literal and complete.** Every sentence has to be correct read word for word. A clipped or hedged answer counts as a wrong answer.
3. **Calm over pressure.** No timers, streaks, or alarming feedback. Scores inform; they don't punish. The ready bar sits above the real test's to absorb nerves.
4. **The manual is the authority.** Every fact traces to a quoted, page-cited line. Ambiguous facts are left out, not guessed.
5. **Works alone, anywhere.** One offline file, no account, no helper required.

## Accessibility & Inclusion

The needs every change must protect:

- **Literal reading:** wording is exact, complete, and unambiguous. No idioms, no implied meanings, and NOT is capitalized when used.
- **Test anxiety:** no time pressure, gentle feedback, and a clear sense of how far along the learner is.
- **Attention and focus:** one task on screen, no distractions, and a predictable flow.

Baseline: readable, legible type at phone size; keyboard and screen reader support (the stage is an `aria-live` region); and both light and dark color schemes.
