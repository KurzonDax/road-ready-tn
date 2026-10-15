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

- **Saved progress key.** The app saves progress in the browser under `tn-permit-daily-v1`. Don't rename it; doing so would erase progress on devices already using the app.
- **Section scores** show the most recent attempt, so redoing a red section at 10 of 10 turns it green.
- **Missed questions** go into review after Section 12. Getting one right on a redo removes it from review.
- **"Ready for the test"** means 27 or more of 30 on three practice tests in a row (90%). The real test passes at 24 of 30 (80%); the extra margin allows for test-day nerves.
- **Order.** The first time through, a section's questions run easiest first. Redos and review shuffle the order, and answer choices are shuffled every time.
- **Hidden links**, for whoever manages the device: add `#restart` (asks before erasing progress) or `#section5` (any number; 13 jumps to review and tests) to the end of the page's address. Nothing on the page points to these.
- **Nothing on the page is addressed to anyone but the learner.** Instructions for helpers belong outside the app.
