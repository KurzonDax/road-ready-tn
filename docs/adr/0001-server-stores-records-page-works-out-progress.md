# The server stores records; the page works out Progress

Each Learner's Progress is not saved as a state. The server keeps a list of records that only grows (finished Sets, Resets, Moves, one Imported record), and the page works out Progress from the records since the latest Reset, using the study rules it already has. The server checks only the shape and size of each record. It never applies the study rules, so those rules live in one place (the page's script), and the Helper's view uses that same code.

## Considered Options

- **Server holds the current state, as the device does today.** Two devices, or a device that was offline, overwrite each other. A reset can't keep the History.
- **Server works out Progress in Python.** The study rules would exist twice, once in the page and once on the server, and could drift apart.

## Consequences

- Records carry a unique id made on the device, so a Set sent twice counts once. That is what lets a device keep working offline.
- Combining records from two devices needs ordering rules: a finished Section moves the Learner forward only if it was their next Section, otherwise it counts as a redo. A record made before a Reset its device hadn't seen stays in the History but doesn't count toward Progress.
- Changing a study rule (for example the Ready for the test bar) changes Progress and the Helper's view for the past too, because both are worked out again from the records.
