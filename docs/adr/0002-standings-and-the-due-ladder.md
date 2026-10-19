# Standings and due times are worked out from counted answers with fixed constants

A Fact's Standing (new, seen, learned, solid) and when it is due again are worked out on the page from the Learner's counted answers, by one fixed rule: two right answers count as separate successes only 12 hours apart, and after the first and second spaced success the Fact is due again after 12 hours and 48 hours; after the third it is solid and finished, never due again on its own; a wrong answer makes it due at once and never lowers its Standing. The constants live in one place at the top of the page's script (`src/app.html`), and the full rule is in `docs/specs/learning-engine.md`. This keeps the decision in ADR 0001: nothing new is stored as state, and the server checks only shapes.

## Considered Options

- **A stored schedule.** The page would save each Fact's next due time. Two devices, or one that was offline, would overwrite each other's schedule, and a Reset could not keep the History. It also breaks ADR 0001.
- **A full spaced-repetition algorithm with per-item intervals** (an ease factor per Fact, as SM-2 and its descendants do). It needs months of answers per Fact to tune itself, while this Learner has weeks before the test and 120 Facts. A fixed ladder is enough to make every Fact come back after a gap, several times, on separate days, and a Helper can read it.

**Amended 2026-10-19.** The third and later returns (every 7 days once solid) are gone, at the owner's decision: a Fact answered correctly in its Section, again 12 hours later, and again 48 hours after that is done. A solid Fact comes back only after a wrong answer, once, and is finished again after the next correct one. `MAINTENANCE_MS` is removed from the page.

## Consequences

- Changing a constant changes every Learner's Progress for the past too, because Standings are worked out again from the records. That is how a constant can be corrected after the retention check (the spec's Phase 4).
- First looks and re-asks are stored with every other answer, with a `role` saying so, but never change a Standing. The server accepts answers with or without `role` and `format`; answers from before the learning engine have neither and all count.
- ADR 0001's ordering rule for Sections ("a finished Section moves the Learner forward only if it was their next Section") no longer applies: Sets name no Section, and a Section is done when its Facts are learned, whichever Sets that took.
