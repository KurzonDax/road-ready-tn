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

**Practice quiz**:
One run of up to 10 counted questions, built fresh each time from the Facts that are due: a group to compare, Facts whose due time has come, and, in a Section with no Lesson file, new Facts met cold. Offered only when something is due; never numbered or explained on a Learner screen. Its record type is still `daily`, and the Helper's History may number them.
_Avoid_: Set, run, round, attempt, quiz on its own

**Standing**:
How well a Fact is known, worked out from its counted questions: new, seen, learned or solid. A Standing only rises.
_Avoid_: Level, score, mastery

**Due**:
A Fact whose Standing says it should be asked again now: after a wrong answer at once, else 12 hours after its first spaced success and 48 hours after its second. A solid Fact is finished and never Due on its own.
_Avoid_: Overdue, scheduled

**Counted question**:
A question whose answer changes a Fact's Standing: every Lesson question with a Fact, every Practice quiz question and every Practice test question. A First look and a re-ask are not counted.
_Avoid_: Scored question

**First look**:
An unscored question shown before a Fact's Rule screen, the first time the Learner meets a Fact from a Section that has no Lesson file. With a Lesson for every Section it is never shown.
_Avoid_: Pre-test, guess

**Rule screen**:
The screen with a Fact's answer and its explanation in plain words, after its First look. Only for a Section with no Lesson file.
_Avoid_: Rule card, flashcard, hint

**Lesson**:
The project's word, never the Learner's, for the questions that teach one Section's Facts, and where the Learner meets them. On the Learner's screens it is simply the Section: "Section 4", "Start Section 4", "You finished Section 4.". On every question the Learner acts first, by tapping the car or person that goes or by choosing, and only then sees what happens and the rule. The principle of the topic is named after two or three cases. Lessons are data (`data/lessons/`, `docs/specs/lessons.md`); a finished Lesson is a record of type `lesson`, and each answer in it is the Fact's first counted answer (`docs/adr/0003-lesson-answers-count.md`), so the Fact comes back in a Practice quiz only when it is Due. The home screen offers the next Lesson, as its Section, whenever nothing is due.
_Avoid_ on Learner screens: Lesson. _Avoid_: Tutorial, reading, chapter

**Compare**:
One screen that shows a group of easily mixed-up Facts side by side, followed by questions on just that group.
_Avoid_: Contrast, review

**Practice test**:
30 questions drawn from all 120, like the real test. Unlocked once every Fact is learned.
_Avoid_: Mock exam, quiz

**Progress**:
Each Fact's Standing, the Lessons finished, the Section new Facts come from, and the Practice test scores. Worked out on the page from the records, never stored.
_Avoid_: State, save

**History**:
Every Lesson, Practice quiz and Practice test a Learner has finished, with each answer and when it was given. Resetting Progress keeps the History.
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
