# Decisions and manual quirks

Things found while building the question bank that are worth knowing before changing it.

## Where the manual differs from common belief

- **No school zone speed number.** Many study guides say 15 mph. The manual (p. 47) gives no number: school zone limits apply "when children are going to or from the school or during a school recess hour", and speeding there is reckless driving with 6 points. No question uses 15 mph.
- **No pentagon or "pennant".** The manual never says a school sign is a pentagon, and calls the no-passing sign "a triangular No Passing Zone sign" (p. 37), not a pennant. Neither word is used as a fact.
- **Train stopping distance** is "between 15 and 50 feet from the railroad tracks" (p. 50). Page 113 words it as from the nearest rail.
- **Move Over law** (pp. 55, 72): change to a lane not next to the stopped vehicle; slow down only when changing lanes is impossible or unsafe. It is not "move over or slow down" as equal choices.
- **Dimming high beams** (pp. 45, 74): within 500 feet of an oncoming vehicle, and also when meeting or overtaking within 500 feet.
- **Turn signal** is on p. 56 (at least 50 feet before the turn), not p. 55.

## Left out on purpose

- **Back-seat belt age.** Page 31 says back-seat passengers "under 17" must buckle up, and the next line says the rule stops at "18 years or older". The question was dropped rather than teach a number that may be wrong.
- **Facts that only appear in pictures** (flagger hand signals, lane-control symbols, route marker shields): the text extraction can't support them.
- **Statistics, fees, and licensing paperwork**: not test material.
- **The points table**: the PDF scrambles its columns, so only clearly aligned rows were used.

## Quotes from tables

Five quotes come from tables the PDF extracts out of order (a-022, a-050, a-084, a-156, a-157). They were checked by hand against the printed manual and are listed as exceptions in `tests/check_quotes.py`.

## App behavior

- **Old saved progress key.** Before accounts, the app saved progress in the browser under `tn-permit-daily-v1`. That key is now read only once, for the one-time import: the first time a Learner with no records signs in on a device that has it, the old progress becomes that Learner's Imported record. The app never writes or deletes the key. The device remembers that the import is done (under `rrtn-old-progress-imported`, which signing out leaves in place) and doesn't repeat it, so on a shared device only the first Learner to sign in there gets the import. A Helper signing in never triggers it.
- **Progress lives on the Instance.** The server stores each Learner's records, and the page works out Progress from them (`docs/adr/0001-server-stores-records-page-works-out-progress.md`). Each device keeps a copy of the signed-in Learner's records under `rrtn-learner-<account id>`, so the app opens quickly and works offline. Sets finished offline wait in that copy and are sent when the device is back online. Signing out needs a connection: it sends anything still waiting, then deletes that Learner's copy from the device.
- **Section scores** show the most recent attempt. They live behind "See your section scores" instead of coloring the progress track, so past low scores aren't the loudest thing on every screen for an anxious learner.
- **Half-finished Sets are saved** after each answer, in the device copy and on the Instance (question ids, the shown answer order, and answers so far), so a Learner can stop on one device and go on with the Set on another. Each Learner has at most one; the one saved most recently wins. A Reset or Move drops it, on the Instance and on every device, even one that was offline at the time. If the questions change so a saved Set no longer matches, it is dropped quietly.
- **"Go on to Section N"** is the main button after a Section or a redo while there is a next Section, and "I'm done for now" comes second. "Do Section N again" is the quiet choice, with a sentence saying the missed questions come back in review. A finished Section moves the Learner on whatever the score, and the screen used to read as "redo until 10 of 10" (#31). With no next Section, "I'm done for now" is the main button.
- **Wording is literal.** No idioms ("Not quite", "stay sharp"), no gesture words like "Tap", and the page says it is a practice app not made by the State of Tennessee.
- **Missed questions** go into review after Section 12. Getting one right on a redo removes it from review.
- **"Ready for the test"** means 27 or more of 30 on three practice tests in a row (90%). The real test passes at 24 of 30 (80%); the extra margin allows for test-day nerves.
- **Order.** The first time through, a section's questions run easiest first. Redos and review shuffle the order, and answer choices are shuffled every time.
- **Hidden links `#restart` and `#section<N>` were removed.** On an Instance they would change only one device's copy. Reset progress and Move, under "Manage this Learner" in the Helper's view, replace them.
- **Nothing on the Learner's pages is addressed to the Helper.** Every word there is addressed to the Learner. The Helper's view speaks to the Helper in the same plain, literal style. Instructions for running an Instance belong outside the app (`docs/self-hosting.md`).
