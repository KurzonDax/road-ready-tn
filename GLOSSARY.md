# Road Ready TN

A study app that takes a learner, one small step at a time, from zero to ready for the Tennessee Class D knowledge test.

## People

**Learner**:
The person studying for the knowledge test with the app. Every word on the Learner's pages is addressed to them.
_Avoid_: Student, user, child

**Helper**:
The person who sets the app up for a Learner and follows their progress. Never addressed by anything on the Learner's pages; only the Helper's view speaks to them.
_Avoid_: Parent, guardian, admin, device manager

## Hosting

**Instance**:
One hosted copy of the app, run by a Helper and used only by the people that Helper gives access to. The repo itself is public so anyone can run their own Instance.
_Avoid_: Deployment, site, server

## Questions

**Fact**:
One rule from the manual that the app teaches, such as "stop between 15 and 50 feet from the tracks". Each of the app's 120 questions tests a different Fact, and a Fact is named by that question's id.
_Avoid_: Item, concept, skill

**Wording**:
One question that tests a Fact. Every Fact has the app's own question as one Wording, and some have other Wordings from the question bank. All Wordings of a Fact have the same right answer.
_Avoid_: Variant, version, paraphrase

## Study path

**Section**:
One of the 12 topic groups of 10 Facts, in the order new Facts arrive. Done when all 10 are learned.
_Avoid_: Day, lesson, chapter

**Set**:
One run of screens from Start the set to Set done, built from due Facts and new Facts, or a Practice test.
_Avoid_: Run, round, attempt

**Standing**:
How well a Fact is known, worked out from its counted questions: new, seen, learned or solid. A Standing only rises.
_Avoid_: Level, score, mastery

**Due**:
A Fact whose Standing says it should be asked again now: after a wrong answer at once, else after a wait that grows with each spaced success.
_Avoid_: Overdue, scheduled

**Counted question**:
A question whose answer changes a Fact's Standing. A First look and a re-ask are not counted.
_Avoid_: Scored question

**First look**:
An unscored question shown before a Fact's Rule screen, the first time the Learner meets the Fact.
_Avoid_: Pre-test, guess

**Rule screen**:
The screen with a Fact's answer and its explanation in plain words. It comes once, when the Learner first meets the Fact.
_Avoid_: Rule card, flashcard, hint

**Lesson**:
The screens that teach one Section's Facts before any question on them. On every step the Learner acts first, by tapping the car or person that goes or by choosing, and only then sees what the manual says happens, the rule, and the manual's sentence and page. The principle of the topic is named after two or three cases. Lessons are data (`data/lessons/`, `docs/specs/lessons.md`); a finished Lesson is a record of type `lesson`, and its answers change no Standing.
_Avoid_: Tutorial, reading, chapter

**Compare**:
One screen that shows a group of easily mixed-up Facts side by side, followed by questions on just that group.
_Avoid_: Contrast, review

**Review**:
No longer a stage. A Fact answered wrong comes back in the next Set instead.

**Redo**:
No longer a stage. A Section is not done again; its Facts come back when they are due.

**Practice test**:
30 questions drawn from all 120, like the real test. Unlocked once every Fact is learned.
_Avoid_: Mock exam, quiz

**Progress**:
Each Fact's Standing, the Section new Facts come from, and the Practice test scores.
_Avoid_: State, save

**History**:
Every Set a Learner has finished, with each answer and when it was given. Resetting Progress keeps the History.
_Avoid_: Log, activity

**Study session**:
A stretch of study with no break longer than 30 minutes between answers.
_Avoid_: Sitting, visit

**Ready for the test**:
27 or more right out of 30 on three Practice tests in a row.

## Helper's view

**Helper's view**:
The screens a Helper sees after signing in: every Learner, and each Learner's Progress and History.
_Avoid_: Dashboard, admin panel, parent view

**Reset**:
A Helper putting a Learner's Progress back to the start: every Fact new again, new Facts from Section 1. The History is kept.
_Avoid_: Restart, wipe

**Move**:
A Helper setting which Section new Facts come from next, or unlocking Practice tests before every Fact is learned.
_Avoid_: Jump, skip
