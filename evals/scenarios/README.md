# Frozen scenario data

The 16 `S*.json` cases are development cases. The four `H*.json` cases are
held out until candidate selection. Patient messages contain only facts and
intent; `expected` contains evaluator assertions and is never sent to the
patient agent. Each case runs with a fresh seeded database and the fixed
clinic-local clock defined by the runner fixture.

Rules are checked in order against the latest assistant message. A rule can
answer once. An unmatched turn is a visible patient-policy failure. The
`__FIRST_OFFERED_TIME__` reply is expanded by the runner from an actual
availability result, never from evaluator expectations.
