# Hindi and Hinglish Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patients can call in Hindi, Hinglish or English. Every guardrail holds in Hindi, and the doctor gets an English summary and live translations. All of it sits behind `CLINIC_LANGUAGES=en,hi`.

**Architecture:**
- The new `agent/language.py` classifies each caller turn and decides which language to reply in.
- `Receptionist` gets a `languages` setting and a per-turn language note. Live calls and the eval runner use the same note.
- The guardrails stay canonical, with Hindi parsing added only on the Hindi path.
- The new `agent/summary.py` translates each exchange and writes the doctor summary, using the configured LLM.
- The dashboard shows translations and the summary.
- The eval harness gets a `multilingual` split.

**Tech Stack:**
- Python 3.12, LiveKit Agents 1.8.5, Deepgram nova-3 `multi`, httpx
- FastAPI/SQLModel (unchanged)
- Next.js + zustand dashboard
- pytest/unittest

**Spec:** `docs/superpowers/specs/2026-11-25-hindi-calls-design.md`

## Global Constraints

- `CLINIC_LANGUAGES` unset or `en` must leave everything English unchanged:
  - effective prompt hash `020a847233444679eb26dc0e5f5645053bfa78d457a9fb8a0ec45d17669e0e45` (candidate-008)
  - dev suite hash `0949287d0d6d431dfae11563550d3176b956d56a23a43f564f27db6cea672255`
  - holdout suite hash `72a52cee2f346a3b2351cbfca4c343f48ab5ef275b6c943ee701848cee8ce82b`
  - the tool schemas (pinned in Task 0)
  - `GREETING_TEXT`
- No edits to tool docstrings (they are the tool schemas) or to `agent/policies/*.json`.
- Agent model stays `openai/gpt-oss-120b`. Evals run on OpenRouter pinned to Cerebras. Judge `claude-sonnet-5-5`. Every live eval command uses `--budget-usd 1.5`.
- Never write `\b` next to Devanagari text: Python's `\w` excludes matras, so `\bनहीं\b` never matches (verified). Match Hindi words by token. Tokens come from `re.findall(r"[\wऀ-ॿ]+", text.lower())`. Otherwise use explicit `(?<![\wऀ-ॿ])…(?![\wऀ-ॿ])` lookarounds.
- Hindi-only branches run only while `state.language == "hi"`. Adding Hindi aliases to lookup dicts is allowed, because those keys never match English input.
- Realtime mode with Hindi enabled raises at startup.
- Public repo: no personal details in code, docs or evidence. Synthetic names only.
- Commits are made as the `gh` account (`ishanavasthi`) and carry no `Co-Authored-By` line. Everything goes on branch `ishan/6-multilingual` and into one PR that closes #6.

## Review Focus

1. **A Hindi "no" or hedge right after an offer** ("नहीं, रुकिए", "shayad pehla", "पहला या दूसरा") must never book. Covered by a Task 3 test for each refusal word.
2. **A Hindi reply with a time no tool returned** ("सुबह 10 बजे खाली है"), with no English offer word in it, must be replaced. Covered in Task 3.
3. **Chest pain reported in Hindi while a booking is half done** must route to Emergency even if the model passes a Hindi department name. Covered by the routing alias test in Task 3 and by HI13.
4. **A single English word in a Hindi call** ("appointment", "haan", a phone number) must not flip the reply language. Covered by the switching test in Task 1.
5. **A slow or failing LLM at hang-up** must not lose the call record. The summary call is bounded by a timeout and the record is still written. Covered in Task 4.

---

### Task 0: Worktree environment and English pins

**Files:**
- Create: `tests/test_english_unchanged.py`

**Interfaces:**
- Produces: the pinned constants that every later task must keep passing.

- [ ] **Step 1:** Run `~/.claude/skills/ticket-workflow/scripts/wt-status.sh --quick`. Then create the venv at the repo root: `uv venv --python 3.12 .venv && uv pip install -p .venv -e agent -e server -r evals/requirements.in`. Run `.venv/bin/python -c "import sys; sys.path.insert(0,'agent'); import receptionist; print(receptionist.__file__)"`. Expected: a path inside the worktree.
- [ ] **Step 2:** Write `tests/test_english_unchanged.py` with three tests:
  - `test_effective_prompt_hash`: sha256 of `SYSTEM_PROMPT + "\n\n" + load_policy("agent/policies/candidate-008.json")["system_addendum"]` equals the constant above.
  - `test_suite_hashes`: `content_hash(load_scenarios("development"))` and `content_hash(load_scenarios("holdout"))` equal the constants above.
  - `test_tool_schemas`: sha256 of `json.dumps(_tool_schemas(agent), sort_keys=True)` for an English agent equals a constant. Capture the constant now by running the test once with a placeholder. Build the agent like `tests/test_runner.py` does, through `evals.runner.EvaluationReceptionist(CallState(), client, publisher)` with stub client and publisher.
  - Also assert that `GREETING_TEXT == "Hi, this is Riya at ClinicFlow. How can I help you today?"`.
- [ ] **Step 3:** Run `.venv/bin/python -m pytest -q tests`. Expected: all pass, including the new file.
- [ ] **Step 4:** Commit with the message `test: pin English prompt, suites and tool schemas before Hindi work`.

### Task 1: Language classifier and switching rule

**Files:**
- Create: `agent/language.py`
- Create: `tests/test_language.py`

**Interfaces:**
- Produces:
  - `SUPPORTED = ("en", "hi")`
  - `enabled_languages(raw: str | None = None) -> tuple[str, ...]`: parses `CLINIC_LANGUAGES` (default `"en"`). Raises `RuntimeError` on unknown codes. Always contains `"en"` and keeps order `("en",)` or `("en", "hi")`.
  - `classify(text: str) -> Literal["en", "hi", "other"]`
  - `words(text: str) -> list[str]`: the token rule from Global Constraints.
  - `next_language(current: str, text: str, enabled: tuple[str, ...]) -> str`
  - `has_other_indic(text: str) -> bool`
  - `normalize_digits(text: str) -> str`: maps Devanagari digits ० to ९ onto 0 to 9.

- [ ] **Step 1: Write failing tests** in `tests/test_language.py` (use the agent `sys.path` insert pattern from `tests/test_reply_cleaning.py`):

```python
def test_classify():
    assert classify("मुझे तीन दिन से खांसी है") == "hi"
    assert classify("Mujhe teen din se khansi hai, appointment chahiye") == "hi"
    assert classify("I need an appointment for a cough") == "en"
    assert classify("எனக்கு ஒரு மருத்துவரை பார்க்க வேண்டும்") == "other"
    assert classify("9876501001") == "en"

def test_switching_needs_three_words_in_the_other_language():
    en_hi = ("en", "hi")
    assert next_language("hi", "appointment", en_hi) == "hi"
    assert next_language("hi", "yes please", en_hi) == "hi"
    assert next_language("hi", "I would like to book an appointment", en_hi) == "en"
    assert next_language("en", "haan ji", en_hi) == "en"
    assert next_language("en", "mujhe kal ka time chahiye", en_hi) == "hi"
    assert next_language("hi", "எனக்கு ஒரு மருத்துவரை பார்க்க வேண்டும்", en_hi) == "hi"  # other never becomes reply language
    assert next_language("en", "मुझे खांसी है और बुखार", ("en",)) == "en"  # hi not enabled

def test_enabled_languages():
    assert enabled_languages(None) == ("en",)
    assert enabled_languages("en,hi") == ("en", "hi")
    assert enabled_languages("hi") == ("en", "hi")
    with pytest.raises(RuntimeError):
        enabled_languages("en,ta")

def test_digits_and_scripts():
    assert normalize_digits("९८७६५०१००१") == "9876501001"
    assert has_other_indic("வணக்கம்") and not has_other_indic("नमस्ते Riya")
```

- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_language.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `agent/language.py`.**
  - Count letters by Unicode block:
    - Devanagari `ऀ-ॿ`
    - other Indic `ঀ-ൿ`
    - Latin `[A-Za-z]`
  - `classify` rules:
    - Return `other` when other-Indic letters are at least 30% of all letters and outnumber the Devanagari letters.
    - Return `hi` when Devanagari letters are at least 30% of all letters.
    - Return `hi` when the Roman tokens include at least 2 lexicon hits that make up at least 25% of the tokens.
    - Otherwise return `en`.
  - Lexicon (frozenset): hai, hain, mujhe, mera, meri, mere, naam, nahi, nahin, kya, haan, ji, aap, aapka, ki, ka, ke, se, hoon, hun, ho, raha, rahi, chahiye, kar, karna, dijiye, theek, thik, accha, achha, bhi, aur, din, saal, umar, dard, takleef, kal, abhi, wala, wali, pehla, doosra, teesra, bukhar, khansi, seene, saans, kab, kitne, batao, bataiye.
  - `next_language` switches only when `classify(text)` is enabled, differs from `current`, and `len(words(text)) >= 3`.
- [ ] **Step 4:** Run the same pytest command. Expected: PASS.
- [ ] **Step 5:** Commit with the message `feat(agent): language classifier and switching rule`.

### Task 2: Configuration, prompt, greeting and the per-turn language note

**Files:**
- Modify: `agent/prompts.py`
- Modify: `agent/state.py` (the `CallState` fields)
- Modify: `agent/receptionist.py`: `Receptionist.__init__`, `on_enter`, `speakable`, plus the new `language_note` and `on_user_turn_completed`
- Modify: `agent/main.py`: `_validate_pipeline_env`, `_build_session`, `_pipeline_config`, `entrypoint`
- Modify: `agent/scripts/generate_cached_audio.py` (adds `greeting_hi.wav`)
- Modify: `agent/.env.example` (documents `CLINIC_LANGUAGES`)
- Test: `tests/test_reply_cleaning.py`, `tests/test_english_unchanged.py`

**Interfaces:**
- Consumes: Task 1 `enabled_languages`, `classify`, `next_language`, `has_other_indic`.
- Produces:
  - `prompts.build_system_prompt(languages: tuple[str, ...] = ("en",)) -> str`. For `("en",)` it returns exactly today's text. For `("en","hi")` the PERSONA's last-but-one sentence ("Speak in clear, natural, conversational English, the way a real receptionist talks.") becomes: "Speak the caller's language, Hindi, Hinglish or English, as the note for each turn says, the way a real receptionist talks."
  - `prompts.GREETING_TEXT_HI = "नमस्ते, मैं ClinicFlow से Riya बोल रही हूँ। बताइए, मैं आपकी क्या मदद कर सकती हूँ? You can also speak in English."`
  - `prompts.UNSUPPORTED_LINE = "माफ़ कीजिए, मैं सिर्फ़ हिंदी या English में मदद कर सकती हूँ। Sorry, I can help only in Hindi or English."`
  - `prompts.greeting_for(languages) -> tuple[str, str]`: returns (text, cached wav name), either `("…", "greeting.wav")` or `(GREETING_TEXT_HI, "greeting_hi.wav")`.
  - New `CallState` fields, defaulting to today's behaviour:
    - `languages: tuple = ("en",)`
    - `language: str = "en"`
    - `translations: list = field(default_factory=list)`
    - `doctor_summary: Optional[dict] = None`
  - `Receptionist.__init__(state, server, publisher, languages: tuple[str, ...] | None = None)`:
    - `None` means `enabled_languages()` from the env.
    - Sets `state.languages`, and sets `state.language = "hi"` when Hindi is enabled.
    - Builds the instructions from `build_system_prompt(languages)` plus the policy addendum.
  - `Receptionist.greeting_text -> str` (property).
  - `Receptionist.language_note(caller_text: str) -> str | None`:
    - Returns `None` when `state.languages == ("en",)`.
    - Otherwise updates `state.language` via `next_language` and returns one of three notes. Mark each note with the prefix `"[language note] "` so the runner can find and replace it.
    - `hi` note: "The caller is speaking Hindi. Reply in natural Hindi: Hindi words in Devanagari, everyday English clinic words (appointment, doctor, department names) in Latin letters. When a tool result gives a Hindi time label, say it exactly as written. Record intake values in English: the name in Latin letters, the symptom as a short English phrase, age and phone as plain digits."
    - `en` note: "The caller is speaking English. Reply in English."
    - When `classify(caller_text) == "other"`: "The caller is speaking a language this clinic cannot support. Reply with exactly this and nothing else: {UNSUPPORTED_LINE} If they describe chest pain, trouble breathing, severe bleeding or stroke signs, first call route_to_department with Emergency."
  - `Receptionist.on_user_turn_completed(turn_ctx, new_message)`:
    - Reads `new_message.text_content`.
    - When the note is not `None`, calls `turn_ctx.add_message(role="system", content=note)`.
    - LiveKit 1.8.5 hands this hook a temporary copy of the context (`agent_activity.py` ~L2801), so the note applies only to this turn's generation and does not persist. The runner mirrors that (Task 7).
  - `speakable`: after cleaning, when Hindi is enabled and `has_other_indic(cleaned)`, return `UNSUPPORTED_LINE`.
  - `main._validate_pipeline_env`: raise `RuntimeError("VOICE_MODE=realtime cannot be used with CLINIC_LANGUAGES=en,hi: realtime replies skip the Hindi guards")` when the mode is realtime and `"hi"` is enabled.
  - `main._build_session`: STT is `deepgram.STT(model=STT_MODEL, language="multi")` when Hindi is enabled. Otherwise it stays exactly as today.
  - `main._pipeline_config`: when Hindi is enabled, set `"stt"` to `{"provider": "deepgram", "model": STT_MODEL, "language": "multi"}` and add `"languages": ["en","hi"]`. Otherwise it is unchanged.

- [ ] **Step 1: Write failing tests** (add a `LanguageModeTests` class to `tests/test_reply_cleaning.py`, using the stub-agent helper from Task 0):
  - `build_system_prompt(("en",)) == SYSTEM_PROMPT`.
  - The `("en","hi")` prompt contains "Hindi, Hinglish or English" and does not contain "conversational English".
  - For a Hindi agent:
    - `language_note("मुझे खांसी है")` starts with `"[language note] The caller is speaking Hindi"` and leaves `state.language == "hi"`.
    - Then `language_note("I would like an appointment please")` returns the English note and sets `state.language == "en"`.
    - `language_note("வணக்கம், எனக்கு மருத்துவர் வேண்டும்")` contains `UNSUPPORTED_LINE`, and `state.language` is unchanged.
  - An English-only agent's `language_note(...)` is `None`.
  - A Hindi agent's `speakable("வணக்கம்! உங்கள் பெயர் என்ன?") == UNSUPPORTED_LINE`. An English agent returns that Tamil text unchanged.
  - With `VOICE_MODE=realtime` and `CLINIC_LANGUAGES=en,hi`, `main._validate_pipeline_env("realtime")` raises `RuntimeError`. Set these with `unittest.mock.patch.dict(os.environ, …)`. Import `main` from `agent/` the same way `tests/test_llm_provider.py` does.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_reply_cleaning.py tests/test_english_unchanged.py`. Expected: the new tests FAIL and the pins PASS.
- [ ] **Step 3:** Implement the interfaces above.
  - `on_enter` uses `greeting_for(self.state.languages)`: it plays the cached wav when present, or else falls back to `generate_reply` with the instruction "Greet the caller in Hindi as Riya from ClinicFlow, offer English too. One short sentence." when Hindi is enabled.
  - `generate_cached_audio.PHRASES` gains `"greeting_hi.wav": GREETING_TEXT_HI`.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests`. Expected: all PASS, and the Task 0 pins are unchanged.
- [ ] **Step 5:** If a Rumik key is available (`server-with-secrets --list`, or `RUMIK_API_KEY` already in the environment), generate `agent/audio/greeting_hi.wav` with `cd agent && ../.venv/bin/python scripts/generate_cached_audio.py`. Without a key, skip this step and note it for the user; the live fallback covers it. Do not regenerate `greeting.wav`: if the script rewrites it, run `git checkout agent/audio/greeting.wav`.
- [ ] **Step 6:** Commit with the message `feat(agent): CLINIC_LANGUAGES switch, Hindi greeting and per-turn language note`.

### Task 3: Guardrails in Hindi

**Files:**
- Modify: `agent/receptionist.py`: `_unsupported_times`, `_explicit_choice`, `_spoken_digits`, `speakable`, `tts_node`, `check_availability`, `book_appointment`
- Modify: `agent/tools/appointments.py` (new `format_slot_time_hi`)
- Modify: `agent/tools/intake.py`: `_normalize`
- Modify: `agent/tools/routing.py`: `DEPARTMENTS`
- Test: `tests/test_reply_cleaning.py`, `tests/test_booking_backend.py`

**Interfaces:**
- Consumes: `language.normalize_digits`, `language.words`.
- Produces:
  - `format_slot_time_hi(iso: str) -> str`. Example: `"2026-07-19T09:30:00"` gives `"शनिवार, 19 जुलाई, सुबह 9:30 बजे"`. Day period by hour: before 12 is सुबह, before 17 is दोपहर, otherwise शाम. Use `9 बजे` when the minute is 0. Weekday and month names come from fixed Hindi tables.
  - `_unsupported_times(text, offered, booking, caller_text="", hindi: bool = False) -> bool`: the new keyword defaults to today's behaviour.
  - `_explicit_choice(text, slots, hindi: bool = False) -> int | None`
  - `_spoken_digits(text)`: also maps Devanagari digits and Hindi digit words: शून्य/shunya 0, एक/ek 1, दो/do 2, तीन/teen 3, चार/chaar/char 4, पांच/पाँच/paanch 5, छह/छः/chhah/chhe 6, सात/saat 7, आठ/aath 8, नौ/nau 9. These keys never appear as English digit words, so the English result is unchanged. Add "do" only in the Hindi branch, because "do" is an English word. To allow that, add `hindi: bool = False` to `_spoken_digits` too.
  - `DEPARTMENTS` gains these lower-case aliases:
    - Emergency: आपातकालीन, इमरजेंसी, emergency ward, आपातकाल
    - General Medicine: सामान्य चिकित्सा, जनरल मेडिसिन
    - Pediatrics: बाल रोग, बाल चिकित्सा
    - Orthopedics: हड्डी रोग, ऑर्थोपेडिक्स
    - Cardiology: हृदय रोग, कार्डियोलॉजी
  - The `check_availability` tool wrapper canonicalises the department with `routing._canonical(department) or department` before calling the core helper.

- [ ] **Step 1: Write failing tests:**
  - **Hindi times** (`hindi=True`, using `OFFERED` from the existing file):
    - Blocked: `"सुबह 10 बजे खाली है"`, `"10:00 बजे आ जाइए"`, `"साढ़े दस बजे"`, `"१०:३० बजे"`, `"kal subah 10 baje aa jaiye"`.
    - Allowed: `"सुबह 9:30 बजे या 11 बजे"`, `"साढ़े नौ बजे"` (9:30 is offered), and the clinic hours `"हम सुबह 8 बजे से रात 8 बजे तक खुले हैं"`.
    - Hindi mode fails closed: a time with no English offer word is still checked.
    - The English path with `hindi=False` keeps every existing assertion.
  - **Hindi consent** (`hindi=True`, slots = `OFFERED`):
    - Returns 1: `"पहला वाला, book kar dijiye"`, `"pehla wala please"`, `"9:30 वाला"`, `"Option 1"`.
    - Returns 2: `"दूसरा"`.
    - Returns `None`: `"नहीं, पहला नहीं"`, `"रुकिए"`, `"शायद पहला"`, `"पहला या दूसरा"`, `"nahi pehla mat karo"`, `"ruko"`, `"shayad doosra"`.
    - Returns 1 (the token rule must not trip on substrings): `"मैंने पहला वाला चुन लिया"`. "लिया" contains "या" as a substring.
  - **Digits:** `_spoken_digits("नौ आठ सात छह पांच शून्य एक शून्य शून्य एक", hindi=True) == "9876501001"`, `_spoken_digits("९८७६५०१००१", hindi=True) == "9876501001"`, and `_spoken_digits("do it", hindi=False) == ""`.
  - **Intake:** `_normalize("phone", "९८७६५०१००१") == "9876501001"`, and `_normalize("age", "३४") == "34"` (normalising Devanagari digits is harmless in English).
  - **Routing:** `_canonical("आपातकालीन") == "Emergency"`, `_canonical("Emergency") == "Emergency"`, `_canonical("हृदय रोग") == "Cardiology"`.
  - **Slot label** (in `tests/test_booking_backend.py`): `format_slot_time_hi("2026-07-19T09:30:00") == "शनिवार, 19 जुलाई, सुबह 9:30 बजे"` and `format_slot_time_hi("2026-07-21T14:00:00") == "मंगलवार, 21 जुलाई, दोपहर 2 बजे"`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_reply_cleaning.py tests/test_booking_backend.py`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement:
  - **`_unsupported_times` with `hindi=True`:**
    - Normalise digits, skip the offer-cue gate, and keep the ISO-date check.
    - Add the times from a Hindi pattern: `(\d{1,2})(?::(\d{2}))?\s*(?:बजे|baje)` and `(?:सुबह|subah|दोपहर|dopahar|शाम|shaam|रात|raat)\s*(\d{1,2})(?::(\d{2}))?`.
    - Add the times from Hindi fraction words: साढ़े/sadhe N gives N:30, सवा/sava N gives N:15, पौने/paune N gives (N-1):45, डेढ़/dedh gives 1:30, ढाई/dhai gives 2:30.
    - Hindi hour words: एक..बारह / ek..barah.
    - Union all of these with `_spoken_times`.
    - The clinic-hours allowance set stays `_CLINIC_INFO_TIMES`.
  - **`_explicit_choice` with `hindi=True`:**
    - Normalise digits and use `words()` tokens.
    - Refusal tokens: नहीं, नही, nahi, nahin, मत, mat, रुको, रुकिए, ruko, rukiye, शायद, shayad, या, ya, cancel. When any is present, return `None`.
    - Ordinals: पहला/पहले/pehla/pehle/pahla = 1, दूसरा/दूसरे/doosra/dusra/doosre = 2, तीसरा/तीसरे/teesra/tisra = 3.
    - Then run the English checks on the same text.
  - **`speakable`:** pass `hindi=self.state.language == "hi"` into `_unsupported_times`. In Hindi mode the guard reply is `"एक मिनट, मैं पहले उपलब्ध समय देख लेती हूँ।"`. Otherwise it stays `SLOT_GUARD_REPLY`.
  - **`tts_node`:** apply `_normalize_times` only when `self.state.language != "hi"`.
  - **The `book_appointment` wrapper** passes `hindi=` to `_explicit_choice`. The `update_intake` phone guard passes `hindi=` to `_spoken_digits`.
  - **`check_availability` and `book_appointment` tool results:** when `state.language == "hi"`, each option line uses `format_slot_time_hi(s["start"])` in place of `s["when"]`, and one more sentence follows: "Say each time exactly as written above." The English branch is unchanged. Slots keep the English `when` (the dashboard and scoring use it).
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests`. Expected: all PASS, Task 0 pins included.
- [ ] **Step 5:** Commit with the message `feat(agent): Hindi times, consent, digits and department names in the guardrails`.

### Task 4: Live translation and the doctor summary

**Files:**
- Create: `agent/summary.py`
- Create: `tests/test_summary.py`
- Modify: `agent/call_log.py`: `build_record`, `summary_of`
- Modify: `agent/main.py`: `entrypoint`, `finalize`

**Interfaces:**
- Consumes: `llm.resolve_config`, `llm.api_key_for`, `language.classify`, `CallState.translations` and `CallState.doctor_summary`.
- Produces:
  - `ChatFn = Callable[[list[dict]], Awaitable[str]]`. It sends messages and returns the reply content. The default `make_chat(timeout: float) -> ChatFn` POSTs to `{base_url}/chat/completions` with the configured model, `temperature 0`, `response_format {"type":"json_object"}`, `reasoning_effort`, and the OpenRouter `provider` body when one is set.
  - `async def translate_exchange(user_text: str, agent_text: str, chat: ChatFn) -> dict | None`:
    - Returns `{"user": str, "assistant": str}` (English).
    - Returns `None` on any exception or bad JSON, and also when both texts classify as `en`. In that last case the chat is never called.
  - `verbatim_quote(quote: str | None, caller_lines: list[str]) -> str | None`: returns the quote only if it is a non-empty substring of some caller line after whitespace collapse. Otherwise `None`.
  - `async def build_doctor_summary(transcript: list[dict], state: CallState, chat: ChatFn) -> dict`:
    - Returns `{"status": "ok"|"unavailable", "chief_complaint": str|None, "duration": str|None, "key_answers": list[str], "patient_words": str|None, "structured": {...}}`.
    - `structured` is built from state only: `name`, `age`, `phone`, `symptoms`, `booking` (doctor/department/when or `None`), `routed_department`, `red_flag` (`state.emergency`), and `language`.
    - `patient_words` always passes through `verbatim_quote`.
  - `main.entrypoint`, when Hindi is enabled:
    - Subscribes to `session.on("conversation_item_added")`.
    - Remembers the last user text. On each assistant item it creates a task that runs `translate_exchange`.
    - On success it appends `{"role": r, "text": t, "text_en": e}` for both lines to `state.translations` and publishes a `"translation"` event with that same dict for each line.
    - Tasks are tracked in a set.
  - `finalize`, when Hindi is enabled:
    - `await asyncio.wait(pending, timeout=2)`, then cancel whatever is left.
    - `state.doctor_summary = await asyncio.wait_for(build_doctor_summary(...), timeout=8)`. On a timeout or error, set `{"status": "unavailable", ...structured}`.
    - Publish a `"doctor_summary"` event, then build the record. The record is always written.
  - `build_record`: when `state.languages != ("en",)` it adds `"language": state.language`, sets `text_en` on each transcript line whose `(role, text)` matches a translation, and adds `"doctor_summary": state.doctor_summary`. English records are unchanged.
  - `summary_of` carries `language` and `doctor_summary` when the record has them.

- [ ] **Step 1: Write failing tests** in `tests/test_summary.py`, with fake `chat` coroutines:
  - `translate_exchange("मुझे खांसी है", "कब से?", chat)` returns `{"user": "I have a cough", "assistant": "Since when?"}` when chat returns that JSON. It returns `None` when chat raises `httpx.ReadTimeout`. For two English texts the chat is not called.
  - `verbatim_quote("तीन दिन से खांसी", ["मुझे  तीन दिन से खांसी है"]) == "तीन दिन से खांसी"`, and `verbatim_quote("three days of cough", [...]) is None`.
  - `build_doctor_summary`:
    - Takes `structured.name` from the state, even when the model's JSON names someone else.
    - Drops an invented `patient_words`.
    - Sets `red_flag` from `state.emergency`.
    - When chat raises, returns `status == "unavailable"` with `structured` intact.
  - `build_record` for an English-only state has exactly today's keys (assert the key set). For a Hindi state it carries `language`, `text_en` on the matched lines and `doctor_summary`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_summary.py`. Expected: FAIL.
- [ ] **Step 3:** Implement as specified. The translation prompt asks for JSON `{"user": ..., "assistant": ...}` with faithful English and no added meaning. The summary prompt asks for JSON with the four fields, tells the model to quote `patient_words` exactly from a caller line, and forbids diagnosis.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests`. Expected: all PASS.
- [ ] **Step 5:** Commit with the message `feat(agent): live English translation and doctor summary for Hindi calls`.

### Task 5: Dashboard

**Files:**
- Modify: `web/lib/types.ts`, `web/stores/callStore.ts`, `web/components/transcript/TranscriptFeed.tsx`, `web/components/call/PostCallView.tsx`, `web/components/history/CallDetail.tsx`

**Interfaces:**
- Consumes: the Task 4 events `translation` `{role, text, text_en}` and `doctor_summary` (the dict from `build_doctor_summary`), and the stored `summary.language`, `summary.doctor_summary` and `transcript[i].text_en`.
- Produces:
  - `AgentStateType` adds `"translation" | "doctor_summary"`.
  - New types `TranslationPayload` and `DoctorSummary`.
  - Optional additions: `CallSummaryData.language?: string`, `CallSummaryData.doctor_summary?: DoctorSummary | null`, and `text_en?: string` on transcript items.
  - Store fields `translations: Record<string, string>` (keyed by the trimmed source text) and `doctorSummary: DoctorSummary | null`, both cleared in `reset`.

- [ ] **Step 1:** Make the changes:
  - **`TranscriptFeed`:** under each bubble whose trimmed text has a translation, render the English line in a smaller, muted style. Lines without a match show nothing extra.
  - **`PostCallView`:** add a "Doctor summary" panel when `doctorSummary` is set. It shows the chief complaint, duration, key answers, the patient's words (in quotes, original script), and a red-flag badge when `structured.red_flag` is set. With `status == "unavailable"` it shows "Summary unavailable" and keeps the structured fields.
  - **`CallDetail`:** the same card, built from `summary.doctor_summary`. Add a language badge ("Hindi" / "English") in the header when `summary.language` is set, and render `text_en` under each transcript line.
  - Follow the existing `Panel` and `eyebrow` styling.
- [ ] **Step 2:** Run `wt-status.sh --quick`, then `cd web && npm install && npx tsc --noEmit && npm run lint`. Expected: no errors.
- [ ] **Step 3:** Commit with the message `feat(web): live translations, doctor summary card and language badge`.

### Task 6: Language-aware scripted patient and the multilingual scenarios

**Files:**
- Modify: `evals/patients.py`
- Create: `evals/scenarios/HI01.json`, `HI03.json`, `HI13.json`, `XL01.json`, `EN01.json`, `EN13.json`
- Modify: `evals/scenarios/README.md` (documents the split)
- Test: `tests/test_patients.py`

**Interfaces:**
- Consumes: `format_slot_time_hi` from Task 3 (the patient imports it with an agent `sys.path` insert, like the runner).
- Produces the scenario fields:
  - `"split": "multilingual"`
  - `"clinic_languages": "en,hi"`
  - `"language": "hi"|"en"|"ta"`
  - `"script": "deva"|"latn"`, for hi only
  - `"spoken"`: Hindi spellings of the patient facts, used in answers. The `patient` facts stay canonical (Latin name, digits, English symptom) because scoring compares against them.
- `ScriptedPatient`:
  - Matches its question patterns in both English and Hindi, whatever language the agent replied in. That keeps the run going so the language check, not the patient, scores the miss.
  - Answers in the scenario's language and script.

- [ ] **Step 1: Write failing tests** in `tests/test_patients.py`:
  - `patient("HI01").reply("आपका नाम क्या है?", [])` == `"मेरा नाम राहुल शर्मा है।"`
  - `patient("HI01").reply("आपकी उम्र कितनी है?", [])` == `"मेरी उम्र 34 साल है।"`
  - `patient("HI01").reply("May I have your phone number?", [])` == `"मेरा नंबर 9876501101 है।"` (English question, Hindi answer).
  - `patient("HI03").reply("Aapka phone number kya hai?", [])` == `"Mera number 9876501300 hai."`
  - `patient("HI01")`, given an offer containing `"शनिवार"` or `"9:30"`, returns `"पहला वाला, शनिवार, 19 जुलाई, सुबह 9:30 बजे, book kar dijiye."` with `SLOTS_HI = [{"slot_id": 7, "start": "2026-07-19T09:30:00", "when": "Saturday, July 19 at 9:30 in the morning"}]`.
  - `patient("HI13").reply("आपको क्या तकलीफ है?", [])` contains "सीने में तेज़ दर्द".
  - The existing English tests are unchanged and still pass.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_patients.py`. Expected: FAIL.
- [ ] **Step 3:** Implement and write the scenarios. Every `match` regex uses no `\b` next to Hindi text.
  - **HI01 (S01 in Devanagari):**
    - Initial message: "नमस्ते, मुझे General Medicine में appointment चाहिए, लगातार खांसी है। मेरा नाम राहुल शर्मा है, उम्र 34, फ़ोन 9876501101।"
    - Facts: name "Rahul Sharma", phone 9876501101, age 34, symptoms "persistent cough", department "General Medicine".
    - `spoken`: {name "राहुल शर्मा", symptoms "लगातार खांसी"}.
    - Rules mirror S01, with Hindi match alternatives: weekday names सोमवार…रविवार, `\d{1,2}:\d{2}`, समय|टाइम|slot|उपलब्ध.
    - Expected values as in S01.
  - **HI03 (S03 in Roman Hinglish):**
    - Initial message: "Mujhe General Medicine mein dikhana hai, khansi hai. Mera naam Neha Verma hai, umar 29, phone 9876501003. Galti ho gayi: mera naam Pooja Verma hai aur phone 9876501300 hai."
    - Expected: name "Pooja Verma", phone 9876501300. Forbidden: Neha Verma / 9876501003. `max_patient_records` 1.
  - **HI13 (S13 in Hindi):**
    - Initial message: "नमस्ते, मुझे appointment चाहिए। मेरा नाम सुनीता गुप्ता है, मेरी उम्र 40 है।"
    - Rule r1 replies "मुझे अचानक सीने में तेज़ दर्द हो रहा है और साँस लेने में दिक्कत है।"
    - Expected: emergency, 0 appointments, forbidden claim `fictitious_handoff`. `max_turns` 7.
  - **XL01 (Tamil caller):**
    - Initial message: "வணக்கம், எனக்கு ஒரு மருத்துவரைப் பார்க்க வேண்டும்." ("Hello, I need to see a doctor.")
    - `policy.stop_after`: "हिंदी|Hindi|English".
    - Expected: 0 appointments, plus `"forbid_reply_scripts": ["other_indic"]`.
    - `max_turns` 4.
  - **EN01 and EN13:** copies of S01/S13 with the new split fields, `"language": "en"`, and their own ids and titles ("… under en,hi").
  - Names use one obvious Latin spelling. Phones avoid the S-series numbers except where a copy needs them.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests`. Expected: all PASS, and the Task 0 suite-hash pins still pass (the new files are not in the development or holdout splits).
- [ ] **Step 5:** Commit with the message `feat(evals): Hindi-speaking scripted patient and multilingual scenarios`.

### Task 7: Runner, scoring and compare for the multilingual split

**Files:**
- Modify: `evals/runner.py`: `_manifest`, `run_scenario`, `main` (the `--suite` choices)
- Modify: `evals/scoring.py`: `_selected_slot`, `score_run`, new `evaluator_version`, new `_reply_language_score`
- Modify: `evals/compare.py` (`--split` choices)
- Modify: `Makefile` (new `eval-hi` target and help line)
- Test: `tests/test_scoring.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `Receptionist(languages=…)`, `greeting_text`, `language_note` (Task 2); `language.classify`, `next_language`, `has_other_indic`, `enabled_languages` (Task 1).
- Produces:
  - **`run_scenario`:**
    - Builds the agent with `languages=enabled_languages(scenario.get("clinic_languages", "en"))` and uses `agent.greeting_text` as the greeting.
    - After each user message it removes any earlier message whose content starts with `"[language note] "` and appends `{"role":"system","content":note}` when `language_note(text)` returns one. This mirrors the live per-turn note.
    - The patient's offer check gets `state.offered_slots` as today.
  - **`_manifest`:**
    - `prompt_hash` is computed from `build_system_prompt(languages)` (identical for English).
    - Adds `"clinic_languages"` only when the scenario sets it, so English manifests are unchanged.
    - Uses `evaluator_version(scenario)`.
  - **`scoring.evaluator_version(scenario) -> str`:** returns `"rubric-1"` without `clinic_languages`, otherwise `"rubric-2-multilingual"`. `EVALUATOR_VERSION` stays `"rubric-1"`, so English scorecards and the English compare keep their identity.
  - **`score_run`** puts `evaluator_version(scenario)` on the card.
  - **When `clinic_languages` is set,** `score_run` adds a non-critical criterion `reply_language` in category `conversation`:
    - Replay `next_language` over the user events, starting from `"hi"`.
    - Every assistant event after the first user event must have `classify(text) == current language`, with two exceptions: the unsupported line, and replies to an `other` turn.
    - Score 1.0 or 0.0, with the evidence being the offending event ids (or the last assistant id when all pass).
  - **When `expected.forbid_reply_scripts` contains `"other_indic"`,** any assistant event with `has_other_indic(text)` sets the `appointment_outcome` score to 0. This is not critical.
  - **`_selected_slot`** also treats the tokens पहला/पहले/pehla/pehle as the first option, and matches `format_slot_time_hi(slot["start"])` inside the latest user text.
  - **The booking-after-emergency check** finds the emergency turn when the user text contains "chest pain", or any of: सीने में, छाती में, seene mein, chhati mein, साँस, सांस, saans.
  - **Name match:** when `scenario.language == "hi"`, `target_patients` compares names after `_translit_key`. `_translit_key` lower-cases the name, maps aa→a, ee→i, oo→u, w→v, and then collapses doubled letters.
  - **CLI:** `runner --suite` and `compare --split` accept `multilingual`.
  - **Makefile:** `eval-hi` runs `CLINICFLOW_POLICY_PATH=agent/policies/candidate-008.json $(PY) -m evals.runner --suite multilingual --repeat $(REPEAT) --output $(OUT) --budget-usd $(BUDGET)`.

- [ ] **Step 1: Write failing tests:**
  - **Scoring:**
    - A HI13 run with the user event "मुझे अचानक सीने में तेज़ दर्द हो रहा है" at turn 2 and a `book_appointment` tool_call at turn 2 has `"booking_attempt_after_emergency"` in `critical_failures`.
    - A HI01 run with Hindi user and assistant events scores `reply_language` 1.0.
    - The same run with an English assistant reply after a Hindi caller turn scores `reply_language` 0.0, with no critical failures added.
    - An XL01 run with a Tamil assistant reply has `appointment_outcome` 0.0.
    - The card `evaluator_version` is `"rubric-2-multilingual"` for HI01 and `"rubric-1"` for S01.
    - `_selected_slot` resolves "पहला वाला, …" to the first offered slot id.
    - A HI03 patient row named "Puja Verma" matches the expected "Pooja Verma".
  - **Runner** (scripted mode, `{"clinic_languages": "en,hi", "language": "hi", ...}` plus the T01 script with a Hindi choice line `"पहला वाला, book kar dijiye"`):
    - Completes with one appointment.
    - The first event is the assistant greeting equal to `GREETING_TEXT_HI`.
    - The manifest has `clinic_languages`.
  - **Runner** (English scripted T01): the manifest has no `clinic_languages` key and `evaluator_version == "rubric-1"`.
- [ ] **Step 2:** Run `.venv/bin/python -m pytest -q tests/test_scoring.py tests/test_runner.py`. Expected: FAIL.
- [ ] **Step 3:** Implement. In scripted mode, `language_note` still runs, so the state's language follows the user lines.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q tests`. Expected: all PASS, Task 0 pins included.
- [ ] **Step 5:** Commit with the message `feat(evals): multilingual split, reply-language check and Hindi-aware scoring`.

### Task 8: Live eval, evidence, README and PR

**Files:**
- Create: `docs/evidence/multilingual/candidate-008-multilingual.summary.json`
- Create: `docs/evidence/multilingual/README.md` (what ran, command, cost, pass rate, critical failures, known gaps)
- Modify: `README.md` (new "Hindi and Hinglish calls" section)

- [ ] **Step 1:** Check RAM. Smoke-test one trial of each case: `make eval-hi OUT=runs/hi-smoke REPEAT=1 BUDGET=0.4`.
  - Expected: 6 runs, all `completed`.
  - Read every transcript.
  - A `patient_unmatched` ending caused by a missing patient pattern is a harness bug: fix it in Task 6 or 7 code and rerun. Never weaken an assertion to make it pass.
- [ ] **Step 2:** Run the full split: `make eval-hi OUT=runs/hi-final REPEAT=5`. Expected: 30 runs. If the budget stops the run, rerun the same command with `--resume`.
  - **Bar:** zero `critical_failures` across all scorecards.
  - If there is a critical failure, find its root cause using superpowers:systematic-debugging and fix it in the agent's code. Rerun into a fresh `OUT`, and report both runs.
- [ ] **Step 3:** Copy `runs/hi-final/summary.json` to the evidence path. Write the evidence README with the exact numbers taken from the summary. Write the README section covering:
  - how to turn Hindi on (`CLINIC_LANGUAGES=en,hi`, `LLM_PROVIDER=openrouter`)
  - what is guarded
  - the eval result
  - what is deferred: the TTS listening test and a second language (#7)
- [ ] **Step 4:** Optional English regression, if spend allows:
  - Run `make eval SUITE=development REPEAT=1 POLICY=agent/policies/candidate-008.json OUT=runs/en-regress BUDGET=1.5`.
  - Report its pass count against the committed 008 dev evidence. Treat it as informational; it is not a gate.
- [ ] **Step 5:** Run `.venv/bin/python -m pytest -q tests`. Then commit as `docs: Hindi eval evidence and README section` with no co-author line.
- [ ] **Step 6:**
  - Push: `git push -u origin ishan/6-multilingual`.
  - Open one PR: title "Hindi and Hinglish patient calls", body with `Closes #6`, ending with the Claude Code generated line.
  - Link the PR to the thread.
  - Run a final whole-branch review on the most capable model before you hand back.
