# A lesson's answers count, and the practice quiz follows the ladder

Decided 2026-10-19. An answer given in a Lesson, on a step that teaches a Fact, is that Fact's first counted answer, at its time, right or wrong. The record keeps `role: "lesson"` so the Helper's History can tell a Lesson from a Practice quiz, but `progressFrom` counts it like any other answer. A Fact taught today therefore comes back only when the due ladder says (ADR 0002): 12 hours later, then 48, then never on its own (ADR 0002 as amended the same day), and at once if the lesson answer was wrong. A Fact is new only while it has no answer at all, which now happens only in a Section whose Lesson has not been taken; the home screen offers that Lesson instead of asking its Facts cold, and the Set that used to follow a Lesson is gone. What remains is called a Practice quiz on every Learner screen, with no number and no sentence explaining it, and a Lesson is named there only as its Section ("Section 4", "Start Section 4"): the owner struck the word "lesson" from the Learner's screens the same day, since it is not a lesson in the way people think of one and there is exactly one per Section.

## The problem it fixes

The owner used the app on his phone on 2026-10-19 and found it confusing. The Lesson asked a Fact, and the Set minutes later asked the same Fact again in the test's wording, so the two read as the same questions twice under two names. Sets were numbered although each is built fresh and never revisited, and the home screen explained in sentences what a Set, a Lesson and a Section were instead of naming them. Lesson answers were stored but changed no Standing, which is what made the Set after a Lesson necessary.

## Considered Options

- **Keep Lesson answers uncounted and drop the Set after a Lesson anyway.** The taught Facts would stay new, so the next Set would ask them cold with a first look and a rule screen: the same duplicate, one screen later.
- **Count a Lesson answer as a counted answer only when it is correct.** A wrong Lesson answer would leave the Fact new and it would be met cold in a Set. Counting it as a wrong answer instead makes the Fact due at once, which is what the ladder already does for a wrong answer anywhere.
- **Store a "taught" flag per Fact.** Breaks ADR 0001: nothing new is stored as state.

## Consequences

- Standings for existing Learners change, because past Lesson answers now count. A Learner who took Lessons before this change sees those Facts as learned (or seen, when the Lesson answer was wrong) and due by the ladder from the Lesson's time, and the Helper's view shows the same. Nothing is migrated: Progress is worked out from the records as always.
- A Lesson taken again from the Lessons panel adds answers like any other quiz: a correct answer 12 or more hours after the last counts as a spaced success, a wrong one makes the Fact due.
- A Practice quiz is offered only when something is due: a group to compare, a Fact whose due time has come, or a new Fact in a Section with no Lesson file. There is no fill-only quiz. A quiz is filled to five questions only with Facts last answered 12 or more hours ago, so nothing taught minutes ago is asked again; a quiz with first looks may fill with more recent Facts so that the gap rule in `docs/specs/learning-engine.md` still holds.
- The first look and rule screen remain for a Section with no Lesson file. With a Lesson for every Section they are never shown; the engine keeps them and the tests cover them with the Lesson files set aside.
- The record type stays `daily` and the server is unchanged. The Helper's History may still number Practice quizzes; the Learner never sees a number.
