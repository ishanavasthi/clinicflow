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

Simulator v2 (after candidate 003): patients also answer date and timing
questions from an optional `patient.timing` preference (default: flexible,
asks for the real times) and open-ended symptom prompts such as "tell me a
bit about your knee pain". v1 left those turns unanswered, which ended booking
calls early and failed them for a simulator gap rather than an agent fault.
Every version compared under v2 was re-run under v2.
