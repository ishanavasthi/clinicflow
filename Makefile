# ClinicFlow developer commands.
# For the full stack, run each in its own terminal: `make server`, `make agent`,
# `make web`. Use `make reset` before a demo for a clean database.

.PHONY: help setup seed reset demo server agent web console verify latency test eval eval-report improve apply compare

help:
	@echo "ClinicFlow commands:"
	@echo "  make setup    Install deps for all three packages"
	@echo "  make reset    Wipe the DB and recordings, then reseed (clean demo state)"
	@echo "  make seed     Reseed the SQLite database"
	@echo "  make server   Run the FastAPI API on :8000"
	@echo "  make agent    Run the LiveKit agent worker"
	@echo "  make web      Run the Next.js dashboard on :3000"
	@echo "  make console  Talk to the agent via the local mic (no browser)"
	@echo "  make verify   Run the scripted booking + provider smoke tests"
	@echo "  make latency  Report voice latency (p50/p95) across recorded calls"
	@echo ""
	@echo "Evaluation (see README 'Assignment results'):"
	@echo "  make test         Offline tests: scheduling, backend, scorer, loop tooling (no keys)"
	@echo "  make eval         Live development suite: OUT=runs/x [POLICY=agent/policies/...] [REPEAT=5]"
	@echo "  make eval-report  Rebuild the README results tables from docs/evidence"
	@echo "  make improve      Generate a proposal: SUMMARY=... POLICY=... PROPOSAL=..."
	@echo "  make apply        Apply it: PROPOSAL=... POLICY=... SUMMARY=... CANDIDATE=..."
	@echo "  make compare      Gate a candidate: BASELINE=... CANDIDATE_SUMMARY=... REPORT=..."

setup:
	cd server && uv venv --python 3.12 .venv && uv pip install -e .
	cd agent && uv venv --python 3.12 .venv && uv pip install -e .
	cd web && npm install

seed:
	cd server && .venv/bin/python seed.py

# Clean slate for a demo: remove the database and any recordings, then reseed.
reset:
	rm -f server/clinicflow.db
	rm -f runs/recordings/*
	cd server && .venv/bin/python seed.py
	@echo "Reset done. Fresh database seeded; recordings cleared."

# Reseed and print the run instructions (services run in their own terminals).
demo: reset
	@echo ""
	@echo "Start the stack in three terminals:"
	@echo "  make server"
	@echo "  make agent"
	@echo "  make web      then open http://localhost:3000"
	@echo "See DEMO.md for the recruiter demo script."

server:
	cd server && .venv/bin/uvicorn main:app --reload --port 8000

agent:
	cd agent && .venv/bin/python main.py dev

web:
	cd web && npm run dev

console:
	cd agent && .venv/bin/python main.py console

# Deterministic checks (need the server running for the scripted booking test).
verify:
	cd agent && CLINICFLOW_API_URL=http://localhost:8000 .venv/bin/python scripts/scripted_call_test.py
	cd agent && .venv/bin/python scripts/pipeline_smoke_test.py
	cd agent && .venv/bin/python scripts/latency_selftest.py

# What the caller waited, pooled over every call archived in runs/calls/.
# Add --per-call for a line per call, --json for the raw numbers.
latency:
	cd agent && .venv/bin/python scripts/latency_report.py --per-call

# ---- Evaluation harness ----------------------------------------------------
PY ?= .venv/bin/python
REPEAT ?= 5
SUITE ?= development
BUDGET ?= 1.5
EVIDENCE := docs/evidence

test:
	$(PY) -m pytest -q tests

eval:
	@test -n "$(OUT)" || (echo "set OUT=runs/<name>"; exit 1)
	CLINICFLOW_POLICY_PATH=$(or $(POLICY),agent/policies/baseline.json) \
		$(PY) -m evals.runner --suite $(SUITE) --repeat $(REPEAT) --output $(OUT) --budget-usd $(BUDGET)

eval-report:
	$(PY) -m evals.report Baseline=$(EVIDENCE)/sim-v2/baseline-dev.summary.json \
		"Gen 002"=$(EVIDENCE)/sim-v2/candidate-002-dev.summary.json \
		"Eng 003"=$(EVIDENCE)/sim-v2/candidate-003-dev.summary.json \
		"Eng 005"=$(EVIDENCE)/sim-v2/candidate-005-dev.summary.json \
		"Final 008"=$(EVIDENCE)/iteration-008/candidate-008-dev.summary.json
	$(PY) -m evals.report Baseline=$(EVIDENCE)/final/baseline-holdout.summary.json \
		"Final 008"=$(EVIDENCE)/final/candidate-008-holdout.summary.json

improve:
	$(PY) -m evals.improve generate --summary $(SUMMARY) --policy $(POLICY) --output $(PROPOSAL)

apply:
	$(PY) -m evals.improve apply --proposal $(PROPOSAL) --policy $(POLICY) --summary $(SUMMARY) --output $(CANDIDATE)

compare:
	$(PY) -m evals.compare --baseline $(BASELINE) --candidate $(CANDIDATE_SUMMARY) --output $(REPORT)
