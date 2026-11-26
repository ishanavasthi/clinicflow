# Hindi and Hinglish patient calls (issue #6)

Status: approved approaches 2026-11-25. Hindi only; second language deferred.

## Intent

A patient phones a small clinic and speaks Hindi, Hinglish or English, switching
mid-sentence. ClinicFlow takes intake, books a real slot, answers FAQs and stops
for emergencies in the caller's language. The doctor gets an English summary,
with the patient's own words kept alongside. It backs the team's entry for the
Scaler × Wispr Flow "India Runs on Voice" hackathon (Healthcare track) and is
the base for the 13 Dec finale demo.

Why Hindi only: nobody on the team can judge another Indian language by ear, so
a second language could not be checked for mistranslated symptoms. It moves to a
follow-up issue that requires a native-speaker reviewer.

## Goals

- Full call in Hindi or Hinglish: intake, booking, FAQ, routing, live dashboard.
- The reply language follows the caller, including switches mid-call.
- Chest pain and other red flags in Hindi reach the existing emergency path.
- Live dashboard shows each Hindi line with an English translation; every call
  ends with an English doctor summary.
- Hindi versions of S01, S03 and S13, plus an unsupported-language case, run
  through the existing harness with no critical failures; results committed under
  `docs/evidence/multilingual/`.
- README section.

## Non-goals

- Languages other than Hindi, Hinglish and English.
- Phone numbers / PSTN (web call only; nothing here may block it later).
- Outbound calls. Diagnosis or medical advice (unchanged: none).
- Changing the agent model. It stays `openai/gpt-oss-120b` (Groq live; OpenRouter
  pinned to Cerebras in evals), per the locked eval decision.

## Anti-goals (failure even if it runs)

- Any guardrail weaker in Hindi than in English: invented times, booking without
  a clear choice, fake handoffs, a missed emergency.
- The agent replying in a language nobody on the team can verify.
- A doctor summary that drops or changes what the patient said.
- Replies slow enough to stop feeling like a phone call.
- English calls behaving differently from today.

## Constraints

- Reuse first: extend the existing agent, tools, server, dashboard and harness.
- English-only configuration must stay byte-identical in prompt and greeting, so
  the committed 60/80 English evidence remains valid.
- The eval harness is text-only, so every language decision must work from the
  caller's text, not from STT metadata.
- LiveKit agents 1.8.5: the Deepgram plugin accepts `language="multi"` but does
  not expose `language_hint`.
- Spend caps unchanged: `--budget-usd 1.5` per suite run.
- Public repo: no personal details in code, docs or evidence.

## Approaches considered

| Decision | Options | Picked | Why |
|---|---|---|---|
| STT | Deepgram nova-3 `multi`; Sarvam saaras | Deepgram `multi` | Existing vendor and key; documented mid-sentence code-switching; Sarvam needs a new account for no clear Hindi gain |
| TTS | Rumik mulberry (Devanagari); Rumik muga (Roman Hinglish only, mis-speaks English); Cartesia sonic-3 | Deferred to a listening test; build ships mulberry | Speed and Hindi quality are unmeasured. The owner will run the test later; the TTS choice stays a config switch |
| Language tracking | Model decides each turn; code tracks it | Code tracks it | Tool results are English, so a model-only rule drifts back to English; code is testable offline |
| Guardrails | Per-language copies of each check; one canonical form plus localised speech | Canonical form | One check per guardrail, not one per language |
| Translation and summary | Post-call only; live per-turn translation plus post-call summary | Live plus post-call | The live dashboard is the demo moment; translation runs off the caller's wait |
| Eval patient | Scripted Hindi patient; LLM-played patient | Scripted | Deterministic and cheap, matching the existing harness design |

## Design

### Configuration

`CLINIC_LANGUAGES` in `agent/.env`: `en` (default, today's behaviour exactly) or
`en,hi`. With `en,hi`:

- STT is `deepgram.STT(model="nova-3", language="multi")`.
- The greeting is bilingual (Hindi first, offering English), from its own cached
  audio file; `GREETING_TEXT` for `en` is unchanged.
- The persona's "speak English" sentence is replaced by a language rule.
- `main.py:_pipeline_config` records the real STT language, TTS model and
  `languages`, so `make latency` groups Hindi calls separately.

### Language tracking (`agent/language.py`, new)

`classify(text) -> "en" | "hi" | "other"`:

- Devanagari letters dominate, or Roman text carries enough common Hindi words
  (a short lexicon: hai, mujhe, nahi, kya, haan, ...), → `hi`. Hinglish is `hi`:
  the agent answers a Hinglish caller in natural Hinglish.
- Another Indic script (Tamil, Bengali, Telugu, ...) dominates → `other`.
- Otherwise `en`.

`CallState.language` starts as `hi` when Hindi is enabled. It switches only when
a caller turn of three or more words classifies as the other supported language,
so "appointment", "yes" or a phone number never flips it. `other` never becomes
the reply language.

One shared method, `Receptionist.language_note(caller_text)`, updates the state
and returns a short system note for the next reply (or nothing for an English
call in an English-only clinic). Live, `on_user_turn_completed` adds it to the
turn context; the eval runner appends it as a system message after each patient
turn. Same code, both paths.

Reply script for Hindi: Hindi words in Devanagari, English clinic words in Latin
(Rumik's documented format for mulberry). If the listening test picks muga, a
Roman-script mode is a later switch.

### Unsupported languages

When a caller turn is `other`, the note tells the model to reply only with one
fixed line, in Hindi and English, saying the clinic can help in Hindi or English,
and still to call `route_to_department("Emergency")` if a red flag is described.
As a code backstop, `speakable()` replaces any reply containing a non-Devanagari
Indic script with that fixed line. No booking is possible without the usual
intake and explicit choice.

### Guardrails in Hindi

Everything the code checks stays canonical: English department names, ASCII
digits, `H:MM` times, names in Latin script. Only speech is localised.

- **Emergency stop:** `tools/routing.py:_canonical` (and the availability
  department lookup) maps Hindi variants (आपातकालीन, इमरजेंसी, "emergency
  ward", "हृदय रोग" and the other departments) to the English names. The tool
  schemas themselves do not change, so the English tool payload stays identical.
- **Invented times:** `receptionist.py:_unsupported_times` reads Hindi time
  expressions too: digits with बजे/baje, `H:MM`, Devanagari digits, Hindi hour
  words, and साढ़े/सवा/पौने/डेढ़/ढाई. In Hindi mode it fails closed: every time
  in a reply is checked whether or not an English offer word appears.
- **Slot labels:** `tools/appointments.py` adds `format_slot_time_hi` (for
  example "शनिवार, 18 जुलाई, सुबह 9:30 बजे"). In Hindi mode the availability and
  booking results give the model this label to copy, so it never translates a
  time itself.
- **Consent:** in Hindi mode only, `_explicit_choice` learns Hindi refusals and hedges (नहीं/nahi,
  मत/mat, रुको/ruko, शायद/shayad, या/ya) and Hindi ordinals (पहला/pehla,
  दूसरा/doosra, तीसरा/teesra), with Devanagari digits normalised.
- **Phone and age:** `_spoken_digits` and `tools/intake.py:_normalize` accept
  Devanagari numerals and Hindi digit words.
- **Speech:** `_normalize_times` spells times in English only for English
  replies; Hindi replies keep the Hindi label.
- **Intake values:** names in Latin script, symptoms as a short English phrase.
  The Hindi language note says so; tool descriptions stay unchanged. The patient's original words live in the transcript
  and the summary quote.

The policy texts (`agent/policies/candidate-008.json`) stay as they are: they are
instructions to the model, not speech.

### What stays identical for English

Every change above is gated. With `CLINIC_LANGUAGES=en` the prompt, greeting,
tool schemas and descriptions, and every guard behave exactly as today. With
`en,hi`, the Hindi-only branches (Hindi time parsing, Hindi consent words, Hindi
slot labels) run only while `CallState.language == "hi"`; an English caller on a
bilingual clinic gets today's English checks after the bilingual greeting.
`VOICE_MODE=realtime` with Hindi enabled is refused at startup, because realtime
replies never pass through `tts_node` and so would skip the Hindi guards.

### Live translation and doctor summary (`agent/summary.py`, new)

- **Live:** in Hindi mode, after each exchange (caller turn plus agent reply),
  one background request asks the configured LLM for English translations of
  both lines, then
  publishes a `translation` event (`{index, role, text_en}`) and keeps it in
  `CallState`. It never delays a reply; a failure leaves that line untranslated.
- **End of call:** one LLM call returns the summary as JSON: chief complaint,
  duration, key answers, and `patient_words` (one verbatim quote of the
  complaint). Name, age, phone, booking, routing and red flags come straight from
  call state, not from the model. `patient_words` is dropped unless it appears
  verbatim in a caller turn. Summary failure shows "summary unavailable"; the
  structured fields still show.
- **Storage:** `call_log.build_record` adds `language`, `text_en` per transcript
  line and `doctor_summary`; `summary_of` carries `language` and
  `doctor_summary`. `Call.summary` and `Call.transcript` are JSON columns, so no
  migration.
- **Model and limits:** translation and summary use the configured LLM provider.
  The Groq free tier's tokens-per-minute cap is too tight for the extra calls, so
  the Hindi demo runs on OpenRouter (the existing public-demo setup). A 429 on a
  translation is dropped, never retried into the caller's turn.
- Summary and translation run only when Hindi is enabled, so English-only calls
  are unchanged.

### Dashboard (`web/`)

`lib/types.ts` gains the `translation` event and the new fields.
`TranscriptFeed` shows the English line under each Hindi line, live.
`PostCallView` and `history/CallDetail` show a doctor-summary card and a language
badge. Layout details are left to the builder, following the existing panels.

### Evals

- Scenarios carry `"language": "hi"` and live in a new `multilingual` split, so
  the development and holdout hashes do not change. `runner.py` and `compare.py`
  accept the split; a `make eval-hi` target runs it.
- `evals/patients.py:ScriptedPatient` becomes language-aware: Hindi and Hinglish
  question patterns, Hindi answer templates, and a Hindi slot choice ("पहला वाला,
  {when}, book kar dijiye").
- Cases: `HI01` (S01 booking, Devanagari Hindi), `HI03` (S03 corrections, Roman
  Hinglish), `HI13` (S13 chest pain mid-intake, Hindi), `XL01` (a caller speaking
  Tamil with no red flag: no Tamil reply, no booking), and `EN01`/`EN13` (the
  English S01 and S13 under the bilingual `en,hi` setup, which is what the demo
  runs). The Tamil line is fixed text from a translation we can check, not judged
  by ear. For XL01 a Tamil reply fails the scenario's outcome; what counts is what
  would be spoken, so a reply the `speakable()` backstop replaced is not a Tamil
  reply (the `reply_guarded` event stays visible in the trace).
- Policy: the split runs with `agent/policies/candidate-008.json`, the policy the
  live agent ships.
- The runner uses the Hindi greeting and passes `CLINIC_LANGUAGES=en,hi` for this
  split.
- `scoring.py` adds a deterministic, non-critical language check: after the
  caller's first Hindi turn, every agent reply classifies as `hi`. Its two
  English-only checks are extended so they cannot silently skip Hindi runs: the
  booking-after-emergency check learns Hindi red-flag words (सीने में दर्द, साँस,
  ...), and `_selected_slot` learns Hindi ordinals and the Hindi slot label.
  `EVALUATOR_VERSION` is bumped.
- Bar: zero critical failures across every run of the split, and the pass rate
  reported as is. There is no Hindi baseline to compare against. Name matching
  for `language: hi` scenarios tolerates common transliteration variants (for
  example aa/a, ee/i).
- Run with the default 5 trials (30 runs) and the existing judge, within the
  $1.50 cap; if the cap stops it, resume with `--resume` in a second command.

### Tests (offline, `make test`)

Extend `tests/test_reply_cleaning.py` (Hindi times, consent, unsupported script),
`tests/test_patients.py` (Hindi patient), `tests/test_scoring.py` (language
check), and add `tests/test_language.py` (classifier and switching rule).
`tests/test_booking_backend.py` covers the Hindi slot label.

## Left to the builder

Exact word lists and regexes, prompt wording, the translation and summary
prompts, dashboard layout, and how many English regression runs fit the budget
(at minimum the offline tests, plus an English development-suite run if spend
allows).

## Deferred

- TTS listening test (mulberry vs muga vs Cartesia) and its latency numbers: the
  owner runs it later; until then Hindi uses mulberry.
- Demo video: recorded by the owner.
- Second Indian language: follow-up issue, needs a native-speaker reviewer.
