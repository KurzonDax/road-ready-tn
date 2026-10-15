# Road Ready TN

A study app that takes a learner, one small step at a time, from zero to ready for the Tennessee Class D knowledge test.

## People

**Learner**:
The person studying for the knowledge test with the app. Every word on the page is addressed to them.
_Avoid_: Student, user, child

**Helper**:
The person who sets the app up for a Learner and follows their progress. Never addressed by anything on the page.
_Avoid_: Parent, guardian, admin, device manager

## Hosting

**Instance**:
One hosted copy of the app, run by a Helper and used only by the people that Helper gives access to. The repo itself is public so anyone can run their own Instance.
_Avoid_: Deployment, site, server

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

**Ready for the test**:
27 or more right out of 30 on three Practice tests in a row.
