# ClinicFlow developer commands.
# For the full stack, run each in its own terminal: `make server`, `make agent`,
# `make web`. Use `make reset` before a demo for a clean database.

.PHONY: help setup seed reset demo server agent web console verify

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
