# How the questions were made

Every question comes from Sections B and C of the *Tennessee Comprehensive Driver License Manual* (edition dated July 1, 2022), the sections the Class D knowledge test is drawn from. The bank was built in four passes, and each pass followed the rules below.

1. **Extract.** `tools/extract_manual.py` pulls the text of printed pages 24-121 into `data/manual/sections-b-c.txt`, with a `=====MANUAL PAGE N=====` line at the top of each page.
2. **Write.** Each chapter was read in full and turned into questions, one per testable rule, number, distance, required action, or sign meaning. All of the manual's own end-of-chapter sample questions are included (`manual_sample: true`) and match its answer key on page 90.
3. **Verify.** A separate review, done without seeing how the questions were written, checked every question against the manual text: the answer is what the manual says, every wrong answer really is wrong, there is one clear best answer, and the page is right.
4. **Reword.** Every question was brought up to the wording standard below.

The 120 questions the app uses (`data/sections.json`) were then picked from the 803: all 29 manual sample questions, plus the clearest question for each core rule. No two of the 120 test the same fact, and some of the other 683 test a fact again in other words (see `fact` under Data format).

## Audience

The app is written for learners who read literally, do best with explicit rules, and find tests stressful. A clipped or hedged answer reads as wrong to them even when the fact is right, so wording matters as much as accuracy.

## Rules for every question

**Source**
- Answerable from a statement in the manual. No outside knowledge. If the manual is ambiguous or contradicts itself, leave the fact out (see [DECISIONS.md](DECISIONS.md)).
- `page` is the printed manual page of the supporting statement.
- `manual_quote` is a short verbatim quote (under 25 words) that supports the answer. The app shows it after each answer, and `tests/check_quotes.py` checks it.
- Skip statistics, licensing paperwork, and fees.

**Wording**
- Questions and choices read as normal sentences or phrases a person would say. No telegraphic fragments ("After lights go off, arm goes in, bus moves"), no semicolons joining clauses, no shorthand.
- State a rule completely. When a rule has a condition, say what to do in both cases ("Slow down and stop, unless you are too close to stop safely"), not a hedge that makes it sound optional.
- Use "you", active voice, and short words. Avoid NOT questions unless the rule really is a prohibition, and capitalize NOT when it's used.

**Answer choices**
- One right answer and exactly three wrong answers.
- Wrong answers are plausible mistakes and clearly wrong according to the manual. A wrong answer that is also true, or arguably true, is a serious error. Watch "at least" thresholds: if the rule is "at least 200 feet", "at least 100 feet" is also technically true.
- Keep choices similar in length and style. The right answer should be the longest choice in no more than about 30% of questions, or length gives it away.
- No "all of the above", "none of the above", or "both A and B".

**Pictures**
- `sign` (octagon, triangle, circle, crossbuck, diamond, rectangle) or `color` (a hex color) only shows the sign or sign color the question is about.
- Never when the question asks for that shape or color ("What shape...", "What color...", "What does it look like...", "Which sign..."): the picture would give the answer away. `tests/validate_data.py` checks this.
- Plain color boxes never stand in for traffic lights, vehicle lights, lane signals, or painted lines.

## Data format

`data/questions.json`:

```json
{
  "id": "b-077",
  "fact": "b-077",
  "topic": "road",
  "question": "A train is coming. How far from the railroad tracks must you stop?",
  "answer": "Between 15 and 50 feet",
  "wrong": ["Between 5 and 10 feet", "Between 50 and 100 feet", "At least 100 feet"],
  "explanation": "Stop between 15 and 50 feet from the tracks. Never stop on the tracks.",
  "page": 50,
  "manual_quote": "...",
  "manual_sample": false
}
```

Ids are grouped by manual range: `a-` pages 25-44 (vehicle, seat belts, signs, signals), `b-` pages 45-67 (rules of the road), `c-` pages 68-90 (interstate, weather, alcohol, your record), `d-` pages 91-118 (defensive driving, sharing the road). Ids never change, because the app saves progress by id.

`fact` says which of the app's questions this one tests the same fact as. Each of the 120 questions in `data/sections.json` is its own fact, so its `fact` is its own id. Another question in the bank gets that id as its `fact` when it is another wording of the same fact:

- it rests on the same rule in the manual, and its right answer says what that rule says;
- it tests the whole rule, not one part of it (b-045 "ease off the brake and steer in the direction of the skid" has no other wording, because c-067 asks only about the brake and c-068 only about steering);
- a Learner who knows the app question's answer can pick its right answer without learning anything new (d-073, "on your half of the road", is not a wording of a-178, "in or about to enter the crosswalk").

d-165 ("Within 50 feet but no closer than 15 feet from the nearest rail") is a wording of b-077. A question with no `fact` tests something the app does not use. A fact may have just one wording, the app's own question. `tests/validate_data.py` checks that every question in the sections is its own fact, that every `fact` names one of them, and that the wordings of a fact share one answer: none gives another's right answer as a wrong choice, and all of their right answers have the same numbers. The app does not use `fact` yet, and `build.py` leaves it out.

`data/sections.json` lists the 12 study sections, 10 question ids each, in the order the app presents them the first time through (easiest first).

`data/groups.json` lists groups of easily mixed-up facts, such as the four distances you may not park within. Once every fact in a group is learned, the app shows the group on one Compare screen, side by side, then asks one question on each of its facts:

```json
{"id": "parking-distances", "title": "How close you may park",
 "reverse": "You may NOT park within {answer} of which of these?",
 "facts": [
   {"id": "b-250", "label": "A fire hydrant"},
   {"id": "b-252", "label": "A crosswalk"}, ...]}
```

- `title` follows "Compare:" on the screen.
- `label` names a fact in the Compare screen's left column. Its answer goes in the right column, or `means` instead, when the answer is itself a name and not a meaning (a-109's answer is "Rectangle"; its `means` says what a rectangle sign is for).
- `reverse` is the stem of a reverse question, with `{answer}` where a fact's answer goes. Its choices are the group's labels, and the right one is the fact's own label. `null` when the group has none. A fact with `"reverse": false` is never asked the reverse way, but its label is still a wrong choice.

`tests/validate_data.py` checks that every fact is a question in the sections and in at most one group, that a group has 2 or more facts with a label of its own each, and that a `reverse` stem has `{answer}` exactly once and is only on a group of 4 or more. `build.py` adds each fact's `group` to it and ships the groups as they are.
