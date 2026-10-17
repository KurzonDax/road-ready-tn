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
One of the 12 topic sets of 10 questions, done in order.
_Avoid_: Day, lesson, chapter

**Review**:
The step after Section 12 that repeats only the questions the Learner missed, 10 at a time.

**Practice test**:
30 questions drawn from all 120, like the real test.
_Avoid_: Mock exam, quiz

**Set**:
One run of questions from the first to the last: a Section (first time or redone), 10 Review questions, or a Practice test.
_Avoid_: Run, round, attempt

**Progress**:
Where a Learner is on the study path now: the next Section, Section scores, what is left to Review, and the Practice test streak.
_Avoid_: State, save

**History**:
Every Set a Learner has finished, with each answer and when it was given. Resetting Progress keeps the History.
_Avoid_: Log, activity

**Rule card**:
The screen before a question the Learner has never answered: the rule in plain words, the manual's own words, and the page. During a Section it can be opened again before answering.
_Avoid_: Flashcard, hint

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
A Helper putting a Learner's Progress back to the start of Section 1. The History is kept.
_Avoid_: Restart, wipe

**Move**:
A Helper setting which Section a Learner does next, or sending them on to Review and Practice tests.
_Avoid_: Jump, skip
