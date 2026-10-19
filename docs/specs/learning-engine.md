# The learning engine

A build spec. Written 2026-10-17. It replaces the study loop in `src/app.html` with one that makes the Learner recall each fact after a gap, several times, on separate days, and that measures whether that is working. Every decision below is made. An agent building from this spec should not need to ask how anything works; where this spec is silent, keep the behavior the page has today.

This spec supersedes GitHub issues #33 (the rule card is reworked here), #34, #36, #37, and the "confusable pairs" and "why line" parts of #41. It defers #38, #39 and #40. Close or edit those issues in the PR that finishes each phase.

**Revised 2026-10-19** (`docs/adr/0003-lesson-answers-count.md`), after the owner used the app with lessons for every Section. Where this spec and that ADR differ, the ADR and the page win:

- A lesson's answers are counted answers. A fact is new only while it has no answer at all.
- `setPlan` walks the Sections in cursor order and stops at the first one with new facts whose lesson is not finished: that Section's lesson is what the home screen offers (`lesson` in the plan), and no new fact is taken from it or past it. New facts are asked cold, with the first look and rule screen below, only in a Section with no lesson file.
- Fill facts (step 4) are those last answered `SPACING_MS` or more ago, so nothing taught minutes ago is asked again. A Set with first looks may also fill with more recent facts, so "Why the gap always holds" still holds. A Set of fill facts alone is never offered: there is no "Nothing is due. This set goes over N facts you already know."
- On every Learner screen a Set is a "Practice quiz", with no number and no line saying what it holds. The record type stays `daily`; the Helper's History may still number them. The home screen shows one thing to do (the quiz when something is due, else the next lesson, else the practice tests, else "Nothing is due today.") and has no "See each section" block. The wording in "Screens" and "Home screen" below is the first draft from 2026-10-17; `src/app.html` and `docs/DECISIONS.md` have the current wording.

The reasoning behind it is in `reports/Making it a learning tool.md` and `reports/Autism friendly study app design.md` (both gitignored, in the working copy at `/opt/road-ready-tn/reports/`). You do not need them to build.

## Principles this spec keeps

From `PRODUCT.md`, unchanged:

- Progress is worked out on the page from append-only records (`docs/adr/0001-*`). Nothing new is stored as state. The server checks shapes and sizes only.
- Question ids never change.
- One thing on screen. Plain, literal, complete wording. "You", active voice. NOT in capitals. No idioms, no gesture words, no timers, no streaks, no verdicts. Counts are information.
- Every word on the Learner's pages is addressed to the Learner. Nothing on them mentions the Helper or tracking.
- The manual is the authority. Every question is checked against the manual's own sentence, which stays in the data; the Learner's screens do not quote the manual (changed 2026-10-17).
- Do not assume or document where an Instance is hosted.

## Vocabulary

Add to `GLOSSARY.md` in Phase 1 (full wording in "Docs to update"):

- **Standing**: how well a fact is known, worked out from the records: new, seen, learned, solid.
- **Due**: a fact whose standing says it should be asked again now.
- **Counted question**: a question whose answer changes a fact's standing.
- **First look**: an unscored question shown before a fact's rule, the first time the Learner meets it.
- **Rule screen**: the screen with a fact's answer and its explanation. Replaces "Rule card".
- **Set**: one run of screens from "Start the set" to "Set done". The page builds it from due facts and new facts.
- **Compare**: one screen that shows a group of easily mixed-up facts side by side, followed by questions on just that group.

"Review" stops being a stage. "Redo" goes away.

## Constants

All in one place near the top of the page's script, each with a one-line comment. Names are fixed so tests can refer to them.

| Name | Value | Meaning |
|---|---|---|
| `FIRST_LOOK` | `true` | A new fact's first encounter starts with an unscored question. `false` starts with the rule screen instead. |
| `COUNTED_TARGET` | 10 | Counted questions in a Set, at most. |
| `NEW_PER_SET` | 5 | New facts in a Set, at most. |
| `MIN_SET` | 5 | A Set with fewer counted questions than this is filled with not-yet-due facts. Equals `GAP + 1`; see "Why the gap always holds". |
| `GAP` | 4 | Screens for other facts between a fact's rule screen and its counted question, at least. |
| `RE_ASK_GAP` | 3 | Question screens for other facts between a wrong counted answer and the same fact asked once more. |
| `RE_ASK_CAP` | 4 | Re-asks in one Set, at most. |
| `SPACING_MS` | 12 hours | Two right answers count as separate successes only this far apart. |
| `LADDER_MS` | `[12 hours, 48 hours]` | After the first and second spaced success, how long before the fact is due again. |
| `MAINTENANCE_MS` | 7 days | A solid fact is due again after this long. |
| `LEECH_WRONG` | 6 | Wrong counted answers after which the Helper's view flags the fact. |
| `TEST_LEN`, `READY_SCORE`, `READY_STREAK`, `PASS_SCORE` | 30, 27, 3, 24 | Unchanged. |
| `SESSION_GAP` | 30 minutes | Unchanged. Used by the Helper's view only. |

## Data

### `data/groups.json`: 15 groups of easily mixed-up facts

New file. Used by Phase 2. Each fact is in at most one group. `label` is the left column of the Compare screen and an answer choice in the reverse format. `means`, when present, replaces the fact's answer in the right column of the Compare screen (used where the answer is itself a name, not a meaning). `reverse` is the stem of the reverse format with `{answer}` where the fact's answer goes, or `null` when the group has none. A fact with `"reverse": false` is never the subject of a reverse question but its label still serves as a wrong choice.

```json
{
  "groups": [
    {"id": "sign-colors", "title": "What each sign color means",
     "reverse": "Which sign means: {answer}?",
     "facts": [
       {"id": "a-084", "label": "A yellow sign"},
       {"id": "a-085", "label": "An orange sign"},
       {"id": "a-086", "label": "A green sign"},
       {"id": "a-087", "label": "A blue sign"},
       {"id": "a-089", "label": "A fluorescent yellow-green sign"}]},
    {"id": "sign-shapes", "title": "What each sign shape means",
     "reverse": "Which sign means: {answer}?",
     "facts": [
       {"id": "a-095", "label": "An eight-sided sign (octagon)"},
       {"id": "a-099", "label": "A triangle pointing down"},
       {"id": "a-101", "label": "A round sign"},
       {"id": "a-108", "label": "A diamond-shaped sign"},
       {"id": "a-109", "label": "A rectangle", "means": "Regulatory signs, like speed limits and lane use", "reverse": false}]},
    {"id": "line-colors", "title": "Yellow lines and white lines",
     "reverse": "Which lines mean: {answer}?",
     "facts": [
       {"id": "a-168", "label": "Lines that separate traffic going in opposite directions", "reverse": false},
       {"id": "a-175", "label": "Lines that separate lanes going the same direction", "reverse": false},
       {"id": "a-176", "label": "Broken white lines between lanes", "reverse": false},
       {"id": "a-170", "label": "Two solid yellow lines between lanes"},
       {"id": "a-172", "label": "A solid yellow line and a broken yellow line, with the broken line on your side", "reverse": false},
       {"id": "a-166", "label": "A yellow line on your right and a white line on your left"}]},
    {"id": "lights", "title": "Red and yellow lights",
     "reverse": null,
     "facts": [
       {"id": "a-156", "label": "A flashing red light"},
       {"id": "a-157", "label": "A flashing yellow light"},
       {"id": "a-147", "label": "A steady yellow light"}]},
    {"id": "arrows", "title": "Turn arrows",
     "reverse": "Which arrow means: {answer}?",
     "facts": [
       {"id": "a-152", "label": "A green arrow"},
       {"id": "a-153", "label": "A yellow arrow"},
       {"id": "a-155", "label": "A flashing yellow arrow"},
       {"id": "a-154", "label": "A red arrow", "means": "All turns are prohibited", "reverse": false}]},
    {"id": "parking-distances", "title": "No-parking distances",
     "reverse": "Which of these has a no-parking distance of {answer}?",
     "facts": [
       {"id": "b-250", "label": "A fire hydrant"},
       {"id": "b-252", "label": "A crosswalk"},
       {"id": "b-253", "label": "A stop sign or traffic signal"},
       {"id": "b-251", "label": "A railroad crossing"}]},
    {"id": "hill-parking", "title": "Which way to turn your wheels when you park on a hill",
     "reverse": null,
     "facts": [
       {"id": "b-260", "label": "Facing downhill, next to a curb"},
       {"id": "b-261", "label": "Facing uphill, next to a curb"},
       {"id": "b-262", "label": "On a hill with NO curb"}]},
    {"id": "feet-rules", "title": "Distances measured in feet",
     "reverse": "Which of these distances is {answer}?",
     "facts": [
       {"id": "b-077", "label": "How far from the tracks you stop for a train"},
       {"id": "b-147", "label": "How far before a turn you turn on your signal"},
       {"id": "b-228", "label": "How much space you leave when you pass a bicycle"},
       {"id": "c-050", "label": "How close another vehicle is when you dim your high beams"},
       {"id": "d-116", "label": "How far behind a truck its blind spot reaches", "means": "Up to 200 feet", "reverse": false}]},
    {"id": "speed-limits", "title": "Speed limits set by law",
     "reverse": null,
     "facts": [
       {"id": "b-031", "label": "Interstate highways"},
       {"id": "b-030", "label": "Primary and secondary state and federal highways, unless another speed is posted"}]},
    {"id": "following-distance", "title": "Following distance",
     "reverse": null,
     "facts": [
       {"id": "b-054", "label": "Under normal conditions"},
       {"id": "b-056", "label": "In bad weather, at night, at higher interstate speeds, or behind a motorcycle"},
       {"id": "b-055", "label": "The speeds at which the two-second rule holds true"}]},
    {"id": "bac", "title": "Blood alcohol limits",
     "reverse": null,
     "facts": [
       {"id": "c-097", "label": "Drivers 21 and older"},
       {"id": "c-121", "label": "Drivers 16 to 20"}]},
    {"id": "school-bus", "title": "School bus lights",
     "reverse": null,
     "facts": [
       {"id": "b-084", "label": "Yellow lights flashing"},
       {"id": "b-085", "label": "Red lights flashing and the stop arm out: when you may go"},
       {"id": "b-086", "label": "Stopped at an intersection: who must stop"},
       {"id": "b-089", "label": "Stopped on the other side of a median you cannot drive on"}]},
    {"id": "turn-lanes", "title": "Which lane to use for a turn",
     "reverse": null,
     "facts": [
       {"id": "b-169", "label": "A right turn: the lane to turn into"},
       {"id": "b-159", "label": "A left turn from a two-way street onto a two-way street: the lane to turn into"},
       {"id": "b-163", "label": "A left turn from a one-way street: the lane to be in before the turn"}]},
    {"id": "who-goes-first", "title": "Who goes first",
     "reverse": null,
     "facts": [
       {"id": "b-118", "label": "At an all-way stop"},
       {"id": "b-119", "label": "Two vehicles reach an all-way stop at the same time"},
       {"id": "a-159", "label": "A traffic signal is not working at all"}]},
    {"id": "emergency-vehicles", "title": "Emergency vehicles",
     "reverse": null,
     "facts": [
       {"id": "b-124", "label": "One with a siren is approaching"},
       {"id": "b-126", "label": "You are in the middle of an intersection when one approaches"},
       {"id": "b-136", "label": "One is stopped on the roadside with its lights flashing"}]}
  ]
}
```

a-172 and a-176 are never reversed because each one's answer is also true of the other's label ("You may pass when it is safe", "You may change lanes or pass if it is safe"), and a-154's `means` replaces an answer that only reads as a reply to its own yes-or-no question (both changed 2026-10-17 in review of Phase 2).

`tests/validate_data.py` checks: every fact id is in `data/sections.json`; no fact is in two groups; every group has 2 or more facts; every `label` is non-empty; a `reverse` stem contains `{answer}` exactly once; a group with a `reverse` stem has at least 4 facts.

### What `build.py` ships

`compact()` adds to each question, when present: `group` (the group id) and `also`. `also` is computed: for each wrong choice whose text, normalized by the existing `plain()` helper, equals the normalized answer of another question in the sections, `also[wrongText] = thatQuestionId`. Today that yields 15 entries across 12 questions.

`questions.json` gains a top-level `groups` array, copied from `data/groups.json`. In Phase 5 it also gains the other wordings of each fact (see Phase 5).

## Records

### The server (`server/records.py`)

- `SET_TYPES` becomes `("daily", "test", "day", "redo", "review")`. The last three are accepted so that stored History still passes `check_record` in tests, and so the page can read them. The page never makes them again.
- `_check_set`: for type `daily`, `section` must be `null` and the data has one more field, `group`, which is `null` or a string of 1 to 64 characters. For `test`, the fields are as today. For the old three types, as today.
- An answer has either exactly the four fields it has today (`q`, `chosen`, `right`, `at`) or exactly six: those plus `role` in `("counted", "first_look", "reask")` and `format` in `("choice", "reverse")`. Both shapes are accepted for every type. The page writes six fields for every new Set.
- `MAX_ANSWERS` stays 50. A daily Set has at most 5 first looks, 10 counted, 4 re-asks: 19.
- `MOVE_TO` stays 13. A Move "to 13" now means "Unlock practice tests"; 1 to 12 means "Start new facts from Section N".
- `tests/test_server.py`: a daily Set with six-field answers and a group is stored; a daily Set with a `section` is refused; an answer with `role` but no `format` is refused; a four-field answer is still accepted; a Practice test with six-field answers is accepted.

### How the page reads records

A **counted answer** is an answer in a `set` record counted by `countedRecords()` whose `role` is `counted` or missing. First looks and re-asks are stored but never change a standing. An `imported` record's `state.last` becomes one synthetic counted answer per entry, at the record's `at` time, right or wrong as the entry says.

Each counted answer belongs to a fact. In Phases 1 to 4 a fact is the question id. In Phase 5 it is `BY_ID[q].fact`, so other wordings of a fact count toward it.

## Standings and when a fact is due

For each of the 120 facts, from its counted answers in time order:

- `spacedRights`: walk the answers; keep `lastCounted = -infinity`; for each right answer whose time is at least `SPACING_MS` after `lastCounted`, add one and set `lastCounted` to its time. Two right answers eleven hours apart count once.
- `standing`: no answers: **new**. `spacedRights` 0: **seen**. 1 or 2: **learned**. 3 or more: **solid**.
- `lastAt`, `lastRight`: the time and result of the newest answer.
- `wrong`: the number of wrong answers.

A wrong answer never lowers a standing. Standings only rise.

**Due** at time `now`, for a fact that is not new:

- `lastRight` false: due now. (A seen fact is always due, since it has no right answer.)
- otherwise `spacedRights` 1: due at `lastAt + LADDER_MS[0]`.
- `spacedRights` 2: due at `lastAt + LADDER_MS[1]`.
- `spacedRights` 3 or more: due at `lastAt + MAINTENANCE_MS`.

Due facts are ordered: first those with `lastRight` false, oldest `lastAt` first; then learned facts, earliest due time first; then solid facts, earliest due time first. Ties in `sections.json` order.

**Learned count** for the home screen and the Helper's view is the number of facts whose standing is learned or solid. **Solid count** is the number that are solid.

**Section done**: all 10 of its facts are learned or solid.

**Practice tests unlocked**: every fact is learned or solid, or the latest Move since the latest Reset is to 13.

**Ready for the test**: unchanged. `tests` is the list of right counts of `test` records plus the imported `state.tests`, in order; ready when the last `READY_STREAK` are all at least `READY_SCORE`.

**Section cursor**: the latest Move to 1..12 since the latest Reset, else 1. New facts are drawn from Sections in the order cursor, cursor+1, ..., 12, 1, ..., cursor−1.

**Set number**: the count of `daily` records since the latest Reset, plus one. Shown as "Set 12".

## Building a Set

`buildSet(now)` is a pure function of the records and `now`. The home screen calls it to preview the next Set; "Start the set" calls it again and starts the result. It returns a list of screens.

Screen kinds: `contrast` (a group's Compare screen), `first_look`, `rule`, `counted`, `reask`. A "question screen" is any kind but `contrast` and `rule`. A "screen for another fact" is any screen whose fact is not the one in question; a `contrast` screen counts as a screen for another fact.

1. **Group block** (Phase 2; before Phase 2 this step yields nothing). Take the first group in `groups.json` order that is due. A group is due when all its facts are learned or solid, the newest counted answer on any of them is at least `SPACING_MS` old (so the Compare is a recall after a gap, not a re-ask minutes after the facts were taught; added 2026-10-17 in review of Phase 2), and either no daily record has that group id since the latest Reset, or a fact in the group has a wrong counted answer whose `at` is later than the `at` of the newest daily record with that group id. If there is one, the block is: `contrast` for the group, then one `counted` question per fact in the group, shuffled. These facts are excluded from steps 2 to 4. A Set with a group block takes no new facts (step 3 is skipped), so the gap rule below never has to hold across the block.
2. **Due facts**: `room = COUNTED_TARGET − (group block size)`. Take the first `room` due facts in due order.
3. **New facts**: skipped when there is a group block. Otherwise `room2 = room − (due taken)`. Take up to `min(NEW_PER_SET, room2)` new facts in Section-cursor order, within a Section in the order listed in `sections.json`.
4. **Fill**: if the counted questions so far (group block, due and new) are fewer than `MIN_SET`, add not-yet-due facts (learned or solid, not due) with the oldest `lastAt` first, ties in `sections.json` order, until `MIN_SET` or none are left. These are counted questions. They are called fill facts on the home screen.
5. **Order the rest** (everything after the group block). Let `W` be the new facts in the order taken (`k` of them) and `D` the due and fill facts, shuffled (`m` of them).
   - If `k` is 0: the `D` questions in their shuffled order.
   - Otherwise `h = max(0, GAP − (k − 1))`. Hold back the first `min(h, m)` of `D`. Spread the remaining `D` as evenly as possible over `k` slots, earlier slots getting the extra ones. Then emit, for each new fact in order: its `first_look` (only when `FIRST_LOOK` is true), its `rule`, then that slot's `D` questions. After the last slot, the held-back `D` questions, then the `counted` question of each new fact in the order they were introduced.
6. Every question screen for a fact other than its first look and rule is `counted`. Counted questions in a daily Set use the format rules in "Formats". The first look always uses the `choice` format on the fact's own question.

**Why the gap always holds.** The gap is counted in screens for other facts. For new fact number `i` (0-based), between its rule and its counted question lie the `D` questions in slots `i` and after, at least one screen (the rule, plus the first look when `FIRST_LOOK` is true) for each of the `k − 1 − i` later new facts, the held-back questions, and the counted questions of the `i` earlier new facts. That is at least `(k − 1) + min(h, m)`. With `k = NEW_PER_SET = 5`, `h` is 0 and the gap is at least 4 with no due facts at all, in either `FIRST_LOOK` mode. With fewer than 5 new facts and no group block, step 4 fills to `MIN_SET = 5`, so `m ≥ 5 − k = h` and the gap is at least `GAP`; fill facts always exist then, because fewer than 5 new facts means at least 115 facts are not new, and a fact that is not new is either due (and so in `D`) or not yet due (and so a fill fact). A Set with a group block has no new facts. A fact's counted question therefore never follows its own rule screen directly, in any Set. With `FIRST_LOOK` false and nothing due, the first new fact's gap is four rule screens of other facts and no question; that is the weakest case the spec allows. Tests must prove the invariant over random records.

**Re-asks** are inserted while the Set runs. A wrong re-ask never inserts another. After a wrong counted answer at screen index `p`, if fewer than `RE_ASK_CAP` re-asks have been inserted in this Set, insert a `reask` for that fact right after the `RE_ASK_GAP`th question screen for another fact that follows `p`; if fewer remain, append it at the end. A re-ask uses the same format and, for `choice`, a fresh shuffle of the same options.

**There is always a Set.** `buildSet(now)` never yields fewer than `min(MIN_SET, 120)` counted questions, except a Set with a group block when too few other facts are learned to fill it (four parking facts learned and nothing else gives four questions): without a block, new facts are always taken when they exist, and a fact that is not new is either due or a fill fact. When nothing is due and nothing is new, the Set is made of fill facts only; the home screen and the Set done screen say so (see those screens) and do not push it.

## Formats

- `choice`: the fact's own question (or, in Phase 5, a wording of it), four choices shuffled. Used for every first look, every re-ask of a `choice` question, every Practice test question, and counted questions not covered below.
- `reverse` (Phase 2): only inside a group block, only in groups with a `reverse` stem and at least 4 facts, only for facts without `"reverse": false`. Within the block, eligible facts alternate: the first eligible fact in shuffled order gets `choice`, the second `reverse`, the third `choice`, and so on. The stem is the group's `reverse` with `{answer}` replaced by the fact's answer. The choices are the fact's label and the labels of 3 other facts in the group, shuffled. The right choice is the fact's label.

Every question is multiple choice, as on the real test. In a group block a counted question is `reverse` where assigned, else `choice`.

## Screens

**Revised 2026-10-17 in a design review (#55).** The wording below is the first draft. The page (`src/app.html`) now has the revised wording, and it wins where the two differ. After any answer, the result comes first on the card: "You picked the right answer: {answer}." in green, or "The answer is: {answer}." with "You picked: {chosen}." under it. The question, its choices (tagged "Your answer" and "The answer"), the explanation and the comes-back line follow. Every Learner line is a full sentence: "You finished Set N.", "You learned N new facts.", "This set has … new facts.", and so on. The app is dark mode only and never quotes the manual.

Wording is exact. Everything else (type, spacing, the pinned button, the A to D keys for choices, "Stop for now and save my place") follows the page as it is. The `aria-live` announcement after an answer reads the same sentences the screen shows, in the same order.

**Progress line.** On a `counted` screen: "Set 12: question 3 of 10", where the number counts counted questions and the bar shows counted answered over counted total. On a `first_look` screen: "Set 12: first look". On a `reask` screen: "Set 12: one more time". On a `rule` or `contrast` screen: "Set 12". In a Practice test: "Practice test: question 3 of 30" as today. The bar does not move on first looks, re-asks, rules or Compare screens.

**First look** (`FIRST_LOOK` true). Above the question, one line in the muted style: "You have not had this question before. Pick the answer you think is right. This answer does not count." Then the question and four choices. Choosing one goes straight to the rule screen; no coloring, no "Correct", no "right answer" on this screen.

**Rule screen.** After a first look, the result is the heading, at the top in the question's size: "You picked the right answer: {answer}." (in green) after a right pick; "The answer is: {answer}." followed by the line "You picked: {chosen}." after a wrong one. Without a first look the heading is "Read this first." Then the sign or color picture if the fact has one, and the explanation (`why`). No manual quote. Then: "This question comes back later in this set." Button: "Go on".

**Counted question, `choice`.** As today before answering. After a right answer: "Correct." then `why`. After a wrong answer: "The right answer is: {answer}." then, when `also[chosen]` exists, one line: "{chosen} answers a different question: {that question's text}" (this line appears wherever `choice` feedback is shown, Practice tests included). Then `why`. Then one line: "This question comes back later in this set, and in your next set." when a re-ask was inserted, otherwise "This question comes back in your next set." Button: "Next question", or "See how it went" on the last screen.

**Counted question, `reverse`.** The stem, four label choices. Feedback as for `choice`, with "The right answer is: {label}." after a wrong answer, and `why`.

**Re-ask.** Above the question: "One more time." Otherwise as the counted question of the same format, except the comes-back line after a wrong answer is always "This question comes back in your next set."

**Compare.** Heading: "Compare: {title}". One line: "These {n} rules are easy to mix up. Here they are side by side." Then a two-column list, one row per fact in `groups.json` order: the fact's picture if it has one, then the label, then the answer (or `means`). Button: "Go on to the questions".

**Set done.** Heading: "Set done." Then, each line only when its number is more than 0:
- "{n} new {fact | facts} learned." (facts whose standing rose from new or seen to learned in this Set)
- "{n} {fact | facts} now solid." (facts that became solid in this Set)
- "{n} {fact | facts} come back in your next set." (facts in this Set with a wrong newest counted answer)
Then: "{L} of 120 facts learned. {S} solid." Then the existing "See the questions you missed" details, listing each fact with a wrong counted or re-ask answer once. Buttons: "Another set" is the primary button when the next Set (`buildSet(now)` with this Set's record included) has a group block, a due fact or a new fact; otherwise "I'm done for now" is primary, "Start a practice test" is a plain button when Practice tests are unlocked, and "Another set" is the quiet link under them with the line "Nothing is due. The next set goes over {n} facts you already know." No score, no "right out of".

**Practice test done.** As today (#35 wording), plus "The questions you missed come back in your next set." when any were missed. The streak sentence stays.

## Home screen

Top to bottom:

1. If a Set is saved partway through: the stopped line and "Continue where I stopped" as today, for daily Sets and Practice tests alike. The Set number is shown: "You stopped partway through Set 12."
2. Otherwise, with `preview = buildSet(now)`:
   - Heading "Set {number}". Under it one line built from the parts that are not zero, in this order: "Compare: {title}." "{d} {question | questions} come back." "{f} to keep fresh." "{k} new." (`f` counts fill facts.) When the Learner has no counted answers at all, the line is "{k} new rules, one at a time. There is no time limit." When the Set is fill facts only, the line is "Nothing is due. This set goes over {f} facts you already know." Button: "Start the set" (primary, except when the Set is fill facts only and Practice tests are unlocked; then "Start a practice test" is primary and "Start the set" is a plain button).
3. One line: "{L} of 120 facts learned. {S} solid."
4. Practice tests, only when unlocked: heading "Practice tests". Line: "The real test passes at 24 of 30. The app's goal is 27 of 30 on three practice tests in a row." Then, when there are scores: "Your last practice tests: 22, 25, 28" (up to 5, oldest first). Button: "Start a practice test", primary only as in 2. When ready: the existing "Ready for the test" sign replaces the heading and line, and the button reads "Take another practice test", primary only as in 2.
5. The progress track: 12 Section markers, then one wide "Practice tests" marker. A Section marker is done when its 10 facts are learned or solid; the first Section in cursor order that still has a new fact is "next" (none is, once no Section has one); the Practice tests marker is done when ready, "next" when unlocked. The "Review" marker goes away. Legend as today.
6. A details block "See each section": one row per Section, "Section N: {title}" and "{x} of 10 learned, {y} solid". No buttons. "See your section scores" and "Do Section N again" go away.
7. The fine print and Sign out, as today.

## Practice tests

Unchanged in length and draw (30 of the 120, shuffled, `choice`, fresh option shuffle). Every answer is a counted answer with `role` `counted` and `format` `choice`, so a wrong Practice test answer makes the fact due and a right one counts toward spacing. The gate is "Practice tests unlocked" above. The streak rule and the ready screen stay.

## The unfinished Set

`packRun`/`unpackRun` carry the whole screen list: `{kind, id, format, options, chosen, at, group}` per screen, plus `set_id`, `started_at`, `after`, `number`, `group`, `i`, `answered`, `reasks` (count inserted). `unpackRun` drops the Set when a question is missing, when a `choice` screen's options no longer match the question's answer and wrong choices, or when a `reverse` screen's options are not labels of its group. Re-asks already inserted are kept. The size stays well under the server's 16 KB limit (25 screens at under 200 bytes each).

## Moves, Resets, Imports and old records

- **Reset**: unchanged. Records after the latest Reset count.
- **Move to 1..12**: sets the Section cursor. In the Helper's view the action reads "Start new facts from Section N". It no longer changes any standing.
- **Move to 13**: unlocks Practice tests. The action reads "Unlock practice tests now".
- **Imported**: `state.last` becomes synthetic counted answers at the record's time; `state.tests` joins the test scores; `state.day` and `state.scores` are ignored.
- **Old `day`, `redo`, `review` records**: their answers are counted answers. They name no Set number; the Helper's History shows them as "Section N", "Section N again" and "Review" as today.

## Helper's view

The Learner's page (`learnerPage`) becomes, top to bottom:

1. **Now**: "{L} of 120 facts learned, {S} solid." then "Next set: {d} come back, {f} to keep fresh, {k} new." (parts that are zero left out), or "Ready for the test" with the streak. The unfinished and paused lines as today.
2. **Retention**: over counted answers since the latest Reset, take every pair of consecutive counted answers on one fact where the first is right and the second is at least `SPACING_MS` later. "Of {Y} times a fact was answered right and asked again at least 12 hours later, it was right {X} times." When `Y` is 0: "No fact has been asked again 12 or more hours after a right answer yet." A second sentence for pairs whose second answer is in the last 14 days: "In the last 14 days: {X} of {Y}." This is the number that says whether the app is working.
3. **Facts**: one details block per Section, summary "Section N: {title}: {x} of 10 learned, {y} solid". Inside, one row per fact: the question text, the standing word, "Asked {n}, right {m}" (counted answers only), "Last asked {date}" (the existing `dayText`) or "Not asked yet", and the line "Needs a different question" when `wrong ≥ LEECH_WRONG`.
4. **Practice tests**: as today, oldest to newest.
5. **Questions missed most**: as today.
6. **Study sessions**: as today; a daily Set reads "Set 12: 7 of 10" counting counted answers only.
7. **Manage this Learner**: as today, with the Move wording above.

The "Sections" scores part and the "Review" part go away. `whereNow` returns the Now line's first sentence.

## Docs to update in Phase 1

- `GLOSSARY.md`: add Standing, Due, Counted question, First look, Compare; rename Rule card to Rule screen; rewrite Set ("One run of screens from Start the set to Set done, built from due facts and new facts, or a Practice test"), Progress ("Each fact's standing, the Section new facts come from, and the Practice test scores"), Section ("One of the 12 topic groups of 10 facts, in the order new facts arrive; done when all 10 are learned"); remove Review and Redo or mark them "no longer a stage".
- `docs/adr/0002-standings-and-the-due-ladder.md`: the decision that standings and due times are worked out from counted answers with fixed constants, the options considered (a stored schedule; a full spaced-repetition algorithm with per-item intervals), and the consequences (changing a constant changes every Learner's Progress for the past too; first looks and re-asks are stored but never counted).
- `docs/DECISIONS.md` "App behavior": replace the Rule first, Section scores, Missed questions, Go on to Section N and Order bullets with the engine's behavior in the same style.
- `PRODUCT.md`: Product Purpose, Flow, Scoring, Order and Terminology.
- `README.md`: the table and the two paragraphs that describe Sections, Review and scores.
- `docs/QUESTIONS.md`: `data/groups.json` (Phase 2), and the note that the app now uses `fact` (Phase 5).

## Tests

`tests/test_app.py` already runs page functions on fixtures (`check_progress_from`) and clicks through the app in Chromium. Add, at minimum:

Fixtures (page functions on made-up records):
- Standings: new with no answers; seen after one wrong; learned after one right; two rights 11 hours apart stay learned with `spacedRights` 1; three rights 13 hours apart are solid; a wrong after a right keeps learned and makes the fact due now.
- Due order: wrong-last before learned-due before solid-maintenance.
- `buildSet`: over 500 random record histories and times, in both `FIRST_LOOK` modes, no counted question ever follows its own rule screen directly, and between a fact's rule and its counted question there are at least `GAP` screens for other facts; at most `NEW_PER_SET` new facts; at most `COUNTED_TARGET` counted questions; never fewer than `MIN_SET` counted questions; with 10 or more due, no new facts; with a group block, no new facts; with nothing due and no block, 5 new facts and the gap is exactly 4.
- Old records (`day`, `redo`, `review`, `test`, `imported`, `move`, `reset`) produce standings and a Section cursor without errors.
- Retention pairs: a right answer followed by a wrong 13 hours later counts 0 of 1; followed 11 hours later counts nothing.

Browser:
- A new Learner's first Set: 5 first looks, each followed by its rule screen with "You picked:" and "The answer is:", then counted questions, none directly after its rule; the Set done screen says "5 new facts learned." when all are right.
- A wrong counted answer inserts "One more time." after 3 question screens for other facts, a wrong re-ask inserts nothing, and the done screen says "1 fact comes back in your next set."; the next Set opens with that fact.
- A fact answered right is not in the next Set started a minute later, and is in a Set started 13 hours later (records written straight into the database with timestamps).
- The home screen shows "{L} of 120 facts learned." and no Practice test button until every fact is learned; a Learner with 120 learned facts (fixtures) sees it, and with nothing due sees "Nothing is due. This set goes over 5 facts you already know."
- Compare (Phase 2): a Learner with all four parking-distance facts learned sees "Compare: How close you may park" at the start of the next Set, then four questions, two of them reverse; choosing "30 feet" for the hydrant shows "30 feet answers a different question: It is illegal to park within how many feet of a traffic signal or stop sign?"
- Helper's view: the Facts block shows standings; the Retention sentence matches the fixture; "Needs a different question" appears after 6 wrong answers.
- The phone layout (375 px) still scrolls nothing sideways on every new screen.

`tests/test_server.py`: the record shapes in "The server". `tests/validate_data.py` rules: as in "Data". `tests/check_dist.py` passes.

## Phases

Each phase is one PR to `main`, in this order; a phase builds on the merged one before it. Each PR updates the docs listed for it, passes every test, and includes `python3 build.py` output in `dist/`.

**Phase 1: the engine.** Constants; standings, due order, Section cursor, Set number; `buildSet` with first look, rule, gap and re-asks; the `choice` format with the `also` line; the Set done, home and progress track screens; Practice test gate and trend; the unfinished Set changes; server `daily` type and six-field answers; the Helper's Now, Retention and Facts blocks; ADR 0002 and the docs. Closes #33 (reworked), #34, #37. Group blocks and reverse are not built yet; `buildSet` step 1 yields nothing.

**Phase 2: Compare.** `data/groups.json` and its validation; `group` and `groups` in the build; the group block in `buildSet`; the Compare screen; the `reverse` format. Closes the confusable-pairs part of #41.

**Phase 3: dropped.** It was typed-number answers for 22 numeric facts. It was built (#46) and removed the same day: the real knowledge test is multiple choice, and the app practices the test as it is. Every question stays multiple choice. Do not bring typed answers back.

**Phase 4: the retention check.** Nothing to build or wait for: the Helper's view shows the Retention figure at all times, updated as the Learner studies. Whenever it is below 70 percent over a fair number of answers, open an issue with the Facts block's standings attached.

**Phase 5: other wordings (#36).** Page half: standings key by `BY_ID[q].fact`; a counted `choice` question for a fact uses the wording with the fewest counted answers (ties: the app's own question first, then id order); the first look and Practice tests use the app's own question; `build.py` ships every bank question that has a `fact`, with `fact` on each, and computes `also` for every shipped question against the 120 facts' answers. Data half: for every fact in `data/groups.json` that has exactly one wording (44 facts as of 2026-10-17), write one more wording into `data/questions.json` following every rule in `docs/QUESTIONS.md` (one right answer, three wrong and clearly wrong, under-25-word verbatim quote, page, `fact` set), so `validate_data.py` and `check_quotes.py` pass. Each new id is the next unused number in the fact's own prefix series (as of 2026-10-17 the highest are a-184, b-276, c-162, d-182). Nothing else in the bank changes.

## Done when

- A Learner who starts from nothing meets each fact as first look, rule, then a counted question with at least four screens for other facts in between, never sooner.
- A fact answered right is asked again only after 12 hours, then 48, then is solid after three spaced successes and returns every 7 days.
- A fact answered wrong is asked once more in the same Set and again in the next.
- The home screen and the Set done screen show standings and never a Section score.
- Practice tests appear only when every fact is learned, and their wrong answers feed the next Set.
- The Helper's view shows every fact's standing and the retention figure.
- Compare screens and reverse questions appear once a group is learned. Every question is multiple choice, as on the real test.
- Every test listed above passes; `check_dist.py` passes; the docs describe only the new flow.

## Verified against (2026-10-17, commit 5bedba0)

- The rule gate: `renderQuestion` returns `renderRule(false)` for any fact with no entry in `S.last` (`src/app.html:584-587`).
- One boolean per fact, dropped after one right answer: `progressFrom` sets `p.last[a.q] = a.right` (`src/app.html:303-318`); `reviewPile` filters `last === false` (`:249`); `phase()` (`:252-257`).
- Set building today: `start()` (`src/app.html:548-560`); the record shape: `setRecord` (`:344-349`).
- The unfinished Set shape: `packRun`/`unpackRun` (`src/app.html:320-335`); server limit 16 KB (`server/records.py`, `MAX_UNFINISHED`).
- Server shapes: `SET_TYPES`, `_check_set`, `MAX_ANSWERS = 50`, `MOVE_TO = 13` (`server/records.py`).
- Study session rule: `SESSION_GAP`, `studySessions` (`src/app.html:979-1000`).
- Build output fields: `compact()` (`build.py:48-65`).
- `numbers()` and `plain()` helpers, and `check_facts` (`tests/validate_data.py:73-115`).
- Counts: 120 app facts in 12 Sections; 803 bank questions; 149 tagged with `fact`; 96 app facts with one wording, 21 with two, 2 with three, 1 with five; 22 app facts whose answer is a number (19 as digits, 3 as words); 15 wrong choices across 12 facts equal another fact's answer (Python over `data/`, 2026-10-17).
- The 15 groups name 55 distinct facts, all in the sections (checked 2026-10-17; 56 until d-138, the school-bus distance, left the bank on 2026-10-18).

## Not verified

- No study data from this Learner exists yet. The local Instance holds five click-through test runs from 2026-10-16.
- The constants (12 hours, 48 hours, 7 days, three spaced successes) are a reading of the successive-relearning literature for a test weeks away, not a measured fit to this Learner. Phase 4 is where they get checked.
- All the evidence behind the design comes from non-autistic samples.
