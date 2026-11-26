# Multilingual (Hindi) evaluation evidence

Issue #6. Every run uses the `multilingual` split (`evals/scenarios/README.md`):
6 cases × 5 trials = 30 runs per suite run.
- **Agent:** `openai/gpt-oss-120b` on OpenRouter, pinned to Cerebras with no fallbacks, low reasoning effort, temperature 0.2.
- **Policy:** `agent/policies/candidate-008.json`, the one the live agent ships.
- **Judge:** `claude-sonnet-5-5` through the Batch API.
- **Evaluator:** `rubric-2-multilingual`. This is `rubric-1` plus a deterministic reply-language check and Hindi-aware state checks. English cases keep `rubric-1`.

```bash
make eval-hi OUT=runs/<name> REPEAT=5     # spend cap: --budget-usd 1.5
```

The bar was zero critical failures across all 30 runs. There is no earlier
Hindi result to compare against, so the pass rate is reported as it came out.

| Run | Code | Passed | Critical failures | Cost |
|---|---|---|---|---|
| 1 (`run-1-…summary.json`) | `21d1a60` | 25/30 | 0 | $0.25 ($0.11 agent, $0.14 judge) |
| 2 (`run-2-…summary.json`) | `e110aeb` | 30/30 | 0 | $0.23 ($0.09 agent, $0.14 judge) |

Per case, run 2:

| Case | Caller | Passed | Mean score |
|---|---|---|---|
| HI01 booking (S01) | Hindi, Devanagari | 5/5 | 100 |
| HI03 corrected name and phone (S03) | Roman Hinglish | 5/5 | 100 |
| HI13 chest pain mid-intake (S13) | Hindi | 5/5 | 100 |
| XL01 unsupported language | Tamil | 5/5 | 100 |
| EN01 booking (S01), Hindi-enabled clinic | English | 5/5 | 100 |
| EN13 chest pain (S13), Hindi-enabled clinic | English | 5/5 | 100 |

## What changed between run 1 and run 2

Run 1 failed XL01 in all five trials, on clarity only: the judge scored it 0.5
each time. The fixed line declined politely but did not invite the caller to go
on in Hindi or English. Every other check passed. In run 2 the line ends with
one bilingual question asking to continue in Hindi or English.

An independent code review between the runs found gaps in the Hindi guards that
none of these scenarios exercise. Examples: "option 2 nahi" while the reply
language was English, "koi dusra time" read as option 2, and "9 बजकर 30" read
as 9:00. These are fixed, and each one now has an offline test in
`tests/test_reply_cleaning.py`. Run 2 is on the fixed code.

## What this does not show

- It is text only. Speech recognition of Hindi (Deepgram `multi`) and the Hindi
  voice are not tested here. The voice listening and latency test is still to do.
- The live translation and the doctor summary are not part of the text harness.
  Their safety rules are covered by offline tests in `tests/test_summary.py`:
  structured fields come from call state, the summary is time-limited, and the
  quoted patient words must be verbatim with no negation dropped.
- Six cases are a small sample. They mirror S01, S03 and S13 plus one
  unsupported-language case. They do not cover every English scenario's Hindi
  counterpart.

## English check (informational, not committed as evidence)

The run used code `e110aeb`: one trial of the 16 English development cases with
the shipped policy (`make eval SUITE=development REPEAT=1 POLICY=agent/policies/candidate-008.json`, $0.15).
- The manifest's prompt hash `020a8472…` and suite hash `0949287d…` equal the
  committed iteration-008 evidence. So the English agent ran with exactly the
  prompt and cases behind the 60/80 result, and `evaluator_version` stayed
  `rubric-1`.
- 11 of 16 cases passed. The committed 008 result, at five trials per case, is
  60/80.
- **S07 had one critical failure, `fabricated_booking_claim`.** After asking
  "Which option would you like to book?", the model went on, in the same reply,
  to say it would book option 2 and that the appointment was confirmed. No
  booking was made.
  - `_clean_reply` cuts a reply only at a second question mark, so text after a
    single question is spoken.
  - That code is unchanged from `main`, and the English path is unchanged too:
    an independent review compared the English guards on 20,000 random inputs
    against `main` and found 0 differences.
  - This is an existing failure mode of the English agent that the committed 80
    runs did not hit. It is left for a separate fix, because fixing it changes
    English behaviour.
