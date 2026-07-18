# ClinicFlow

An AI Healthcare Receptionist: a real-time voice agent that answers patient
calls, runs intake, books appointments, answers FAQs, and routes callers to the
right department, paired with a live SaaS-quality dashboard that mirrors every
call as it happens.

## Architecture

Three deployable units meeting at LiveKit:

```
web/     Next.js dashboard: caller pane (mic over WebRTC) + observer dashboard
server/  FastAPI + SQLite: token minting, seeded EHR, CRUD persistence
agent/   Python LiveKit worker: VAD -> Deepgram STT -> gpt-4o-mini -> Rumik TTS
```

The browser plays both roles: a caller pane joins a LiveKit room to simulate an
incoming call, and the dashboard joins the same room as a hidden observer.
Everything realtime rides on transport LiveKit already provides (live transcript
and token-by-token AI text via transcription streams, structured agent-state via
the data channel), so there is no custom WebSocket server. FastAPI handles
persistence only and never touches the audio path.

## Prerequisites

- Node 20+ and npm
- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 for the two Python packages)
- Accounts/keys: LiveKit Cloud, Rumik, Deepgram, OpenAI

## Setup

```bash
make setup          # installs server, agent, and web dependencies
```

Then create the env files from the examples and fill in your keys:

```bash
cp server/.env.example server/.env
cp agent/.env.example  agent/.env
cp web/.env.local.example web/.env.local
```

`LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` must be the same
project across `server/.env` and `agent/.env`.

## Run

Each in its own terminal:

```bash
make server         # FastAPI on http://localhost:8000 (auto-seeds on first boot)
make agent          # LiveKit agent worker (voice pipeline lands in M1)
make web            # dashboard on http://localhost:3000
```

Reseed the database at any time with `make seed`.

## Current status: M0 scaffold complete

- `server/`: token endpoint (caller/observer grants), seeded departments,
  doctors, slots, FAQs, and patients, plus read CRUD. Verified minting valid
  LiveKit JWTs and serving seed data.
- `agent/`: package structure and config validation in place; the AgentSession
  voice pipeline and function tools land in M1 and M2.
- `web/`: Next.js 16 + Tailwind v4 + shadcn/ui dashboard shell with a working
  call simulator that mints a token and joins a LiveKit room.

See `.plans/` (local only) for the full milestone plan and interview notes.
