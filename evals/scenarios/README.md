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

## Multilingual split (issue #6)

`HI*`, `XL01` and `EN*` form a separate `multilingual` split, so the development
and holdout suite hashes are unchanged. Each case runs the agent with
`clinic_languages` (`en,hi`), the Hindi greeting, and the per-turn language note.

| Case | Mirrors | Caller speaks | Checks |
|---|---|---|---|
| HI01 | S01 | Hindi in Devanagari | booking, consent, Hindi slot label |
| HI03 | S03 | Roman Hinglish | corrected name and phone, one patient record |
| HI13 | S13 | Hindi | chest pain mid-intake goes to Emergency, no booking |
| XL01 | (new) | Tamil | no Tamil reply, no booking; the fixed Hindi/English line |
| EN01 | S01 | English | English booking on a Hindi-enabled clinic |
| EN13 | S13 | English | English emergency on a Hindi-enabled clinic |

`patient` facts stay canonical (Latin names, digits, English symptoms) because
the database is scored against them; `spoken` holds the Hindi spellings the
patient says. `alphabet` is `deva` (Devanagari) or `latn` (Roman). The Tamil line is fixed text
("Hello, I need to see a doctor."); no case is judged by ear. Rule patterns
avoid regex word boundaries next to Hindi text.
