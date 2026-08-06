# Deploying ClinicFlow on free tiers

This guide puts the whole stack online without a paid plan: the dashboard on
Vercel, the API and the agent worker on Render, and the media plane on LiveKit
Cloud. Every provider used here has a genuinely free tier at the volume a demo
needs.

Read the [Free tier reality check](#free-tier-reality-check) before a live
demo. Free hosting has real constraints (cold starts, ephemeral disks, rate
limits) and this guide is explicit about which ones bite and how to work
around them.

## Target topology

| Unit | Host | Free plan | Notes |
| --- | --- | --- | --- |
| `web/` (Next.js dashboard) | Vercel | Hobby | Static-ish SPA, no server routes to worry about |
| `server/` (FastAPI + SQLite) | Render | Free Web Service | Ephemeral disk, sleeps after 15 min idle |
| `agent/` (LiveKit worker) | Render | Free Web Service | Uses the worker's built-in health port |
| Media (WebRTC SFU) | LiveKit Cloud | Build plan | 5,000 free participant minutes/month |
| STT | Deepgram | Free credit | `nova-3` |
| LLM | Groq | Free tier | `openai/gpt-oss-120b`, rate limited |
| TTS | Rumik | Your key | |
| Keep-alive pings | cron-job.org or UptimeRobot | Free | Stops Render from sleeping the agent |

The agent is deployed as a **Web Service**, not a Background Worker, because
Render's Background Workers are paid-only. This works because a LiveKit agent
in production mode already runs an HTTP health server on port 8081 (`GET /`),
which is exactly what Render's port detection and health checks want.

## Before you start

You need:

- The repo pushed to GitHub (Render and Vercel both deploy from a Git remote).
- Accounts on Vercel, Render, and LiveKit Cloud.
- Your four provider keys: LiveKit (URL, key, secret), Deepgram, Groq, Rumik.

Deploy in this order: **LiveKit, then server, then agent, then web**, then come
back and fix CORS. Each step needs a URL from the previous one.

---

## Step 1: LiveKit Cloud

1. Create a project at https://cloud.livekit.io.
2. From Settings, copy the project URL (`wss://your-project.livekit.cloud`),
   the API key, and the API secret.

The **same three values** must be set on both the server and the agent. A
mismatch here is the single most common cause of "Start call does nothing":
the browser joins a room in one project and the agent is waiting for jobs in
another.

---

## Step 2: Deploy the server (Render)

New > Web Service > connect the repo.

| Setting | Value |
| --- | --- |
| Root Directory | `server` |
| Runtime | Python |
| Build Command | `pip install -e .` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Instance Type | Free |

Environment variables:

```
PYTHON_VERSION=3.12
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DATABASE_URL=sqlite:///./clinicflow.db
CORS_ORIGINS=http://localhost:3000
```

Leave `CORS_ORIGINS` as-is for now; you will add the Vercel domain in Step 5.

Verify with `curl https://clinicflow-server.onrender.com/health`. You want
`{"status":"ok","livekit_configured":true}`. The database seeds itself on first
boot (see the `lifespan` hook in `server/main.py`), so there is no manual seed
step.

Note the URL. The agent and the web app both need it.

---

## Step 3: Deploy the agent (Render)

The agent has no HTTP surface of its own, but the LiveKit worker exposes a
health endpoint on port 8081 in production mode. Point Render at it.

New > Web Service > same repo.

| Setting | Value |
| --- | --- |
| Root Directory | `agent` |
| Runtime | Python |
| Build Command | `pip install -e . && python main.py download-files` |
| Start Command | `python main.py start` |
| Health Check Path | `/` |
| Instance Type | Free |

`download-files` pre-fetches the silero VAD weights at build time so the first
call does not pay for the download.

Environment variables:

```
PYTHON_VERSION=3.12
PORT=8081
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DEEPGRAM_API_KEY=...
GROQ_API_KEY=...
RUMIK_API_KEY=...
CLINICFLOW_API_URL=https://clinicflow-server.onrender.com
```

`PORT=8081` matters. Render detects the port your process binds to, and the
worker's health server hardcodes 8081 in production mode. Setting `PORT`
explicitly tells Render where to look. If you would rather not rely on that,
make the port configurable with a one-line change in `agent/main.py`:

```python
cli.run_app(
    WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        port=int(os.getenv("PORT", "8081")),
    )
)
```

A healthy deploy logs `registered worker` and `HTTP server listening on
:8081`. If it logs missing env vars instead, `_validate_pipeline_env()` in
`agent/main.py` names exactly which key is absent.

---

## Step 4: Deploy the dashboard (Vercel)

Import the repo at https://vercel.com/new.

| Setting | Value |
| --- | --- |
| Framework Preset | Next.js |
| Root Directory | `web` |

One environment variable:

```
NEXT_PUBLIC_API_URL=https://clinicflow-server.onrender.com
```

Two things to get right:

- **Set it before the first build.** `NEXT_PUBLIC_*` values are inlined into
  the client bundle at build time, not read at runtime. Changing it later
  requires a redeploy, not just a restart.
- **It must be `https`.** The dashboard is served over HTTPS, so a plain
  `http://` API URL is blocked as mixed content and every request fails
  silently in the console.

---

## Step 5: Close the CORS loop

Go back to the Render server service and set:

```
CORS_ORIGINS=https://clinicflow.vercel.app
```

Use your real production domain. Render restarts the service on an env change.

Preview deployments get their own generated URLs, which will not match this
origin. If you want previews to work, either add them explicitly (the value is
comma-separated) or point previews at a separate server instance. For a demo,
production-only is fine.

---

## Step 6: Keep the agent awake

Render free services spin down after 15 minutes with no inbound traffic, and
take roughly 30 to 60 seconds to come back. For the server that is merely
annoying: the first `/token` request wakes it. For the agent it is fatal, since
a sleeping worker is not registered with LiveKit and will never be assigned a
call.

Set up a free cron ping (cron-job.org, UptimeRobot, or Better Stack) hitting
the agent's health endpoint every 10 minutes:

```
https://clinicflow-agent.onrender.com/
```

**Watch the hour budget.** Render's free tier gives 750 instance-hours per
month across the whole account. One always-on service consumes about 730 of
them. So: ping the agent continuously, and let the server sleep and wake on
demand. If you ping both around the clock you will run out around day 15 and
everything stops.

Before a scheduled demo, warm the server manually so the first click is not
sitting through a cold start:

```bash
curl https://clinicflow-server.onrender.com/health
```

---

## Verify the deployment

1. `curl .../health` on the server returns `livekit_configured: true`.
2. The agent's Render logs show `registered worker`.
3. The LiveKit Cloud dashboard lists your agent under Agents.
4. Open the Vercel URL, click **Start call**, allow the mic.
5. You hear Riya's greeting within a second or two (it is a cached audio clip).
6. The transcript panel fills in as you speak.
7. Book an appointment, then hang up and confirm the call appears in History.

If the greeting plays but nothing else happens, the agent is up and the LLM or
STT key is wrong. If nothing happens at all, the agent is asleep, crashed, or
pointed at a different LiveKit project.

---

## Free tier reality check

These are the constraints that actually show up in a demo. None of them are
bugs; they are the price of not paying.

**The database is ephemeral.** Render's free tier has no persistent disk, so
`clinicflow.db` lives on the container filesystem and is wiped on every deploy
and every wake-from-sleep. The server reseeds itself automatically on boot, so
departments, doctors, and FAQs are always there. What you lose is call history
and recordings from previous sessions. For a live demo this is mostly harmless
and arguably convenient. To make it durable, see
[Making persistence real](#making-persistence-real) below.

**Recordings vanish with the database.** They are written to `runs/recordings/`
on the same ephemeral disk. Playback works within a session and breaks after a
restart.

**512 MB of RAM on the agent.** silero VAD plus onnxruntime plus the LiveKit
runtime fits, but not with much headroom. One concurrent call is comfortable.
Do not plan a demo with three simultaneous callers on the free instance.

**Groq rate limits.** `gpt-oss-120b` on the free tier is capped around 8,000
tokens per minute. Hitting it makes the agent go quiet mid-call, and the error
handler in `main.py` speaks a short "I had a brief hiccup" fallback. Check the
agent logs for a `429`. The escape hatch is one env change, no code:

```
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
```

**LiveKit free minutes.** 5,000 participant minutes per month. Each call burns
two participants' worth (caller and agent) plus the hidden observer. Roughly
800 minutes of real conversation. Plenty for demos, not for a pilot.

**Cold starts.** Covered in Step 6. Warm the server before you demo.

---

## Making persistence real

If you want call history to survive restarts, swap SQLite for a free hosted
Postgres. [Neon](https://neon.tech) and [Supabase](https://supabase.com) both
have free tiers that do not expire. Render's own free Postgres is deleted after
30 days, so prefer Neon.

Two changes are needed:

1. Add `psycopg[binary]` to `server/pyproject.toml` dependencies.
2. In `server/db.py`, the `connect_args={"check_same_thread": False}` argument
   is SQLite-only and will raise on Postgres. Make it conditional:

   ```python
   connect_args = (
       {"check_same_thread": False}
       if _settings.database_url.startswith("sqlite")
       else {}
   )
   engine = create_engine(_settings.database_url, echo=False, connect_args=connect_args)
   ```

Then set `DATABASE_URL` to the Neon connection string. SQLModel handles the
rest; no model changes are required.

Recordings need object storage to survive (Cloudflare R2 has a free tier with
no egress fees), which means replacing the local-file logic in
`server/routes/calls.py`. That is a bigger change than it is worth for a demo,
and the honest production answer is LiveKit Egress rather than client-side
MediaRecorder anyway.

---

## Optional: deploy both Render services from a blueprint

Instead of clicking through the dashboard twice, commit this as `render.yaml`
at the repo root and use New > Blueprint. Secrets are marked `sync: false`, so
Render prompts for them instead of storing them in Git.

```yaml
services:
  - type: web
    name: clinicflow-server
    runtime: python
    plan: free
    rootDir: server
    buildCommand: pip install -e .
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
      - key: DATABASE_URL
        value: sqlite:///./clinicflow.db
      - key: CORS_ORIGINS
        sync: false
      - key: LIVEKIT_URL
        sync: false
      - key: LIVEKIT_API_KEY
        sync: false
      - key: LIVEKIT_API_SECRET
        sync: false

  - type: web
    name: clinicflow-agent
    runtime: python
    plan: free
    rootDir: agent
    buildCommand: pip install -e . && python main.py download-files
    startCommand: python main.py start
    healthCheckPath: /
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
      - key: PORT
        value: "8081"
      - key: CLINICFLOW_API_URL
        fromService:
          type: web
          name: clinicflow-server
          property: hostport
      - key: LIVEKIT_URL
        sync: false
      - key: LIVEKIT_API_KEY
        sync: false
      - key: LIVEKIT_API_SECRET
        sync: false
      - key: DEEPGRAM_API_KEY
        sync: false
      - key: GROQ_API_KEY
        sync: false
      - key: RUMIK_API_KEY
        sync: false
```

`fromService` with `property: hostport` yields a bare `host:port`, so if that
does not resolve to a usable URL for your setup, just set `CLINICFLOW_API_URL`
by hand to the full `https://...` server URL.

---

## Alternative hosts for the agent

Render is the recommended path because it is free, always-on with a ping, and
deploys straight from Git. Two alternatives if it does not suit you:

**LiveKit Cloud Agents.** LiveKit can host the worker itself, which removes the
health-port workaround, the keep-alive cron, and the cold starts entirely. It
is the cleanest deployment by a wide margin. Install the `lk` CLI, then
`lk agent create` from the `agent/` directory. Check the current plan limits
before relying on it, since agent hosting allowances differ from the free
participant minutes.

**Hugging Face Spaces.** A free CPU Basic Space (Docker SDK) runs the worker
with 16 GB of RAM, far more headroom than Render's 512 MB. Free Spaces sleep
after 48 hours of inactivity rather than 15 minutes, so no keep-alive cron is
needed for a demo week. You need a Dockerfile, and the Space must expose port
7860, so set the worker port accordingly.

Fly.io and Railway both work technically but no longer have a standing free
tier; they run on trial credit that expires.

---

## Cost if you outgrow free

Roughly, per month:

- Render Starter, both services: $14
- Render persistent disk, 1 GB: $0.25
- LiveKit Cloud beyond 5,000 minutes: usage-based, cents per hour
- Groq or OpenAI: usage-based, small at demo volume

Under $20 a month buys away every constraint in this document except the
deliberate mocks (telephony, EHR, Egress recording, department transfer), which
are product scope decisions rather than hosting limits. Those are documented in
the README.
