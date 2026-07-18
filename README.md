# ClinicFlow

An AI Healthcare Receptionist: a real-time voice agent that answers patient
calls, runs intake, books appointments, answers FAQs, and routes callers to the
right department, paired with a live, SaaS-quality dashboard that mirrors every
call as it happens.

## Architecture

Three deployable units meeting at LiveKit:

```
web/     Next.js dashboard: call simulator (mic over WebRTC) + live operator console
server/  FastAPI + SQLite: token minting, seeded EHR, CRUD + recording storage
agent/   Python LiveKit worker: silero VAD -> Deepgram STT -> gpt-oss-120b (Groq) -> Rumik muga TTS
```

One LiveKit room per call. The browser both places the "incoming call" (publishes
the mic) and renders the dashboard off that same connection, because the agent
forwards transcriptions and structured `agent-state` events to every participant.
So everything realtime rides on transport LiveKit already provides, with no custom
WebSocket server. FastAPI handles persistence only and never touches the audio
path. Intake, availability, booking, FAQ logging, and routing are all LLM function
tools, so every state change is an auditable tool call that also drives the UI.

## Features

- Real-time bidirectional voice with barge-in; instant cached greeting.
- Live transcript, patient intake, availability/booking, department-routing
  switchboard, and a conversation timeline, all updating from the agent's tools.
- Emergency override: red-flag symptoms skip intake and route to Emergency at once.
- Call controls: mute/pause (the agent waits), end, and a post-call view with
  recording playback and an editable patient record.
- Every call is saved as JSON (transcript + patient details) and, optionally, an
  audio recording under `runs/`.

## Prerequisites

- Node 20+ and npm
- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 for the two Python packages)
- API keys: LiveKit Cloud, Rumik, Deepgram, Groq (OpenAI works as an LLM fallback)

## Setup

```bash
make setup                       # install deps for server, agent, and web
cp server/.env.example server/.env
cp agent/.env.example  agent/.env
cp web/.env.local.example web/.env.local   # fill in your keys
```

`LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` must be the same LiveKit
project across `server/.env` and `agent/.env`.

## Run

```bash
make reset      # clean demo state: wipe + reseed the DB, clear recordings
```

Then, each in its own terminal:

```bash
make server     # FastAPI on http://localhost:8000 (auto-seeds on first boot)
make agent      # LiveKit agent worker
make web        # dashboard on http://localhost:3000
```

Open http://localhost:3000, click **Simulate incoming call**, allow the mic, and
talk to Riya. See `DEMO.md` for the recruiter demo script.

Other commands: `make console` (talk to the agent via the local mic, no browser),
`make verify` (deterministic booking + provider smoke tests), `make seed` (reseed).

## Troubleshooting

- **The agent goes silent mid-call.** Almost always Groq's free-tier rate limit
  (gpt-oss-120b is capped at 8000 tokens/minute); check `runs/agent.log` for a
  `429`. Either upgrade the Groq tier, or switch the model with one line in
  `agent/.env`: set `LLM_MODEL`/`LLM_BASE_URL` to a higher-limit endpoint (for
  example OpenAI `gpt-4o-mini` with your `OPENAI_API_KEY`).
- **No audio in the browser.** Allow microphone access; the agent's voice plays
  through the page once connected.
- **Nothing happens on "Simulate call".** Confirm all three services are up and the
  LiveKit keys match across `server/.env` and `agent/.env`.

## Run logs

Service logs, per-call JSON (transcript + patient details), and recordings are
written under `runs/` so a session can be reviewed afterward. The directory is
tracked; its contents are gitignored.

## Deliberate mocks (with real upgrade paths)

- Telephony -> browser WebRTC (SIP + a carrier is a config change, not code).
- EHR -> seeded SQLite behind a real integration seam (swap in an FHIR client).
- Recording -> client MediaRecorder instead of LiveKit Egress.
- Department transfer -> status change + visualization (no second agent).

`.plans/` (local only) holds the milestone plan and interview notes (approach,
guardrails, difficulties).
