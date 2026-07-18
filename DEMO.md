# ClinicFlow demo script (~5 minutes)

Prep: `make reset`, then start `make server`, `make agent`, `make web`. Open
http://localhost:3000 in Chrome or Safari and allow the microphone. Speak in
plain English and let Riya finish each turn before you reply.

Backup: if the network or a provider misbehaves, fall back to the screenshots in
`docs/backup/` and narrate from them.

---

## 1. Set the scene (30s)

Show the idle dashboard: the icon sidebar, the live clock, and the five
departments with their doctors. Line: "Every panel you'll see updates live from
the AI's tool calls, there's no scripted animation."

## 2. Incoming call + intake (90s)

Click **Simulate incoming call**. Riya greets instantly (cached audio).

Say, one line at a time, waiting for her question each time:

- "Hi, I've had a bad knee for a couple of weeks and I'd like to see a doctor."
- your name, e.g. "Rajat Patidar"
- your age, e.g. "twenty seven"  (note it stores as 27)
- your number, e.g. "nine four one three, five one three, five nine five"  (stored as 10 digits)

Point at the **Patient intake** panel ticking green as each detail lands, and the
transcript streaming on the left.

## 3. FAQ mid-flow (30s)

Interrupt the flow: "Quick question, what are your hours?" Riya answers, then
returns to intake. Point at the **timeline** logging the FAQ as a separate step.

## 4. Booking (60s)

Let intake finish (name, age, phone, symptom). Riya proposes Orthopedics and reads
a few times; pick one: "The first one works." Watch the **Appointment** panel
animate to "Booked" and the **routing** switchboard light up Orthopedics. Mention
the row is written to SQLite (double-book protected).

## 5. Emergency, the wow beat (45s)

End the call, click **New call**, start a fresh one, and say:

> "I have severe chest pain and I'm having trouble breathing."

Riya skips intake and routes to **Emergency** immediately; the DepartmentFlow
switchboard flashes rose with a fast pulse and the timeline logs an emergency
routing. This is the guardrail: she won't run a five-field intake on a heart
attack.

## 6. Wrap: recording + summary (30s)

**End call.** The post-call view shows the **recording player** (play it back),
the **call summary**, and the frozen panels. Mention the whole call is also saved
as JSON under `runs/calls/`. Close on the architecture: "Swap the browser for a
SIP trunk and this answers a real phone number; the tool + persistence seams are
already real."

---

## Handy extras to mention

- **Mute** pauses your mic so you can think; the agent simply waits.
- The **edit** pencil on intake lets an operator correct a misheard value; it
  patches the real patient record.
- The agent is guardrailed: it records only what you actually say, asks one thing
  at a time, and never claims a booking a tool did not confirm.

## If the agent goes quiet

Check `runs/agent.log` for a Groq `429` (free-tier rate limit). Either upgrade the
Groq tier or set `LLM_MODEL`/`LLM_BASE_URL` in `agent/.env` to a higher-limit
endpoint (e.g. OpenAI `gpt-4o-mini`) and restart the agent.
