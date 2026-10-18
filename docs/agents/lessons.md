# Building a lesson

How a Section's lesson (`data/lessons/section-N.json`) gets written, checked and handed over. The format and the drawing kit are in `docs/specs/lessons.md`; this document is the judgement that the format cannot hold. Every rule here was set by the owner while reviewing the first lesson, Section 3, one question at a time. The Learner is his son: 18, autistic, fully intelligent, reads every word literally, preparing for the Tennessee knowledge test. Write for an intelligent adult who takes each sentence at its exact meaning.

## Steps

1. **Read** `docs/specs/lessons.md`, this document, the Section's ten facts in `data/sections.json` and `data/questions.json` (their `explanation` and `manual_quote` are the truth each question must match), and the manual passage they come from in `data/manual/sections-b-c.txt`. Then read `data/lessons/section-3.json` as the worked example.
2. **Write** the lesson as an Opus subagent with this document and the spec in its brief. Ten to fifteen questions: two or three cases that share the Section's principle, the principle named, the remaining facts, a closing principle.
3. **Lint**: `python3 tests/validate_data.py` prints `OK`. The lint (`check_lesson_wording`) is the enforced form of the language rules below; a lesson that fails it does not build.
4. **Audit** with a second Opus subagent that reads every question as the Learner will, against the checklists under Questions and Language, and edits the file. Then lint again.
5. **Build and check**: `python3 build.py`, then `tests/test_app.py check_lessons` passes (run with a Python that has Playwright; `CHROMIUM_PATH` picks an installed Chromium).
6. **Sheet**: `python3 tools/lesson_sheet.py N reports/lessons/section-N.html` writes the lesson as one page. Read the whole page yourself, every wrong path included, and fix what you find. Regenerate.
7. **Hand over the sheet** to the owner. A lesson is reviewed as that page, never by tapping through the app. Done when he has the page and nothing on it breaks a rule below.

## Questions

A lesson is a sequence of situations the Learner decides, not text he reads. Each question is one decision.

- **One question form, so the marks mean one thing.** Every tap question asks "Who goes first? Tap the car." (or "Tap the person or your car."). The green check marks the one that goes. When a scene has two that go first, redesign the scene until exactly one does; put the wider rule in the explanation. Section 3's question 2 is the worked example: one car on the main road, and "both directions" in the explanation.
- **The prompt states every fact the decision needs.** What controls the intersection, in words, every time: the sign, the light and its color, or "There is no stop sign and no yield sign." Who arrived first. Which way each vehicle is going, and which way the Learner wants to go. How close the other vehicle is when it matters. The drawing shows the same facts; it never carries one alone.
- **Targets are named from the driver's seat.** "your car", "the car on your left", "the car coming toward you", "the person". Never a color, a position on the page, or a letter.
- **Every wrong path is audited.** For each wrong target or option, read "Incorrect. You picked X." followed by the explanation, and confirm the explanation answers that pick. A question with two wrong targets has two paths; check both.
- **A choose question asks about the scene drawn.** "May you drive into the intersection now?" with the cars stopped past it in the drawing, never "if you cannot get all the way through".
- **A principle question names its cases.** "When you drove out of the driveway onto the main road, and when your road ended at the main road with no sign, who waited each time?" The closing question is short and exact: "Every question in this lesson came down to one thing. What was it?"
- **The options of a choose or principle question** are complete sentences or a plain Yes or No, and exactly one is defensible on the facts stated.

## Language

Precise means exact, never exhaustive. A sentence that lists eight situations is as wrong as one that names none.

- **Correct and incorrect.** "Correct." and "Incorrect. You picked your car." In a driving app "right" is a direction and nothing else.
- **What the driver does, in his words.** "You wait and let it pass." "You stay stopped until it has gone across." "You stop before the crosswalk and wait until the person has crossed." The word "yield" belongs to a yield sign only. The questions in `data/questions.json` keep the test's own wording, because that is what the test says.
- **They are questions.** "This lesson has 12 questions." The button is "Go on". The count is "1 of 12".
- **Name what you refer to.** A situation is named by what happened in it, never pointed at as "both cases", "these", or "the one above".
- **Short sentences, few of them.** A sentence is at most 30 words; a prompt at most 60. An explanation is at most three sentences: what happens, then why. It names the correct one once; the lead never repeats it.
- **Tennessee roads, plainly.** "the main road", "a stop sign with an ALL WAY sign under it", "a traffic light that is not working". No idioms, no hedges, no exclamation marks, no semicolons, no praise.
- **The manual stays in the data.** Its sentences and page numbers verify every fact and never appear on a Learner screen.

The lint refuses: yield (except "yield sign"), right for correct, step, screen, case, unnamed references, semicolons, exclamation marks, verdict and praise words, sentences and prompts over the caps, and a tap question that draws an intersection without saying what controls it.

## Drawings

Top-down, schematic, from the kit in `docs/specs/lessons.md`, drawn as Tennessee roads are.

- **The traffic signal is a vertical head, red on top, on a span across the road**, over the far side of the intersection, centered on the lanes it controls. On the standard intersection with the Learner heading north that is `x` 160, `y` 121. A signal on a corner post belongs downtown in a city, not here.
- **All-way stops have a stop sign with an ALL WAY plate at every corner**, and the prompt says so.
- **Every car sits in the correct lane for its heading** (right-hand traffic: northbound in the east lane, southbound in the west lane, eastbound in the south lane, westbound in the north lane), turned toward its heading.
- **The Learner's car is marked `you`** and a `path` arrow shows where he wants to go whenever the prompt says it.
- **At most three vehicles and one person.** Roads get a label when the prompt names them ("Main road", "Driveway").
- **After acting, the player marks the drawing**: the correct one gets a green ring and a check, a wrong tap a red ring and a cross. A lesson never draws its own marks.

## What the Learner sees after acting

Fixed by the player; a lesson supplies only `then.say` and, when the scene changes, `then.parts`.

1. One line: "Correct." in green, or "Incorrect. You picked your car." in red. A wrong choice reads "Incorrect." alone, because the list under it marks the pick.
2. The drawing, marked.
3. The explanation, once.

Nothing else: no repeated prompt, no rule paragraph, no quote, no hint.

## Rejected, so it is not proposed again

Each of these was built and taken out: the manual's sentence and page on a Learner screen; a rule paragraph under the explanation; "Next step" and "step" anywhere; "screens" for questions; "Not your car." as the whole result; "Right." for correct; "yield" for waiting; "In both cases"; a prompt listing every situation in the lesson; dashed rings as marks; a horizontal signal head; a signal on a corner post; a drawing with no sign and a prompt that does not say so; a rule shown and then its own question asked immediately; a lesson as text with a Next button; a Section framed as a story or a trip; physics the test does not ask (stopping distance, feet per second); asking the owner to proofread one question at a time.

## Done when

- `python3 tests/validate_data.py` prints `OK` and `tests/test_app.py check_lessons` passes on the built page.
- Every one of the Section's ten facts is taught by a question whose answer agrees with the fact's `explanation`.
- Every tap question asks who goes first and has exactly one target that does.
- Every wrong path has been read in the sheet and its explanation answers the pick.
- The owner has the sheet for the Section.
