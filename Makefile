# ClinicFlow developer commands.
# Run each target in its own terminal for the full stack: `make server`,
# `make agent`, `make web`.

.PHONY: help setup server agent web seed demo

help:
	@echo "ClinicFlow commands:"
	@echo "  make setup    Install deps for all three packages"
	@echo "  make seed     Reseed the SQLite database"
	@echo "  make server   Run the FastAPI API on :8000"
	@echo "  make agent    Run the LiveKit agent worker (M1+)"
	@echo "  make web      Run the Next.js dashboard on :3000"

setup:
	cd server && uv venv --python 3.12 .venv && uv pip install -e .
	cd agent && uv venv --python 3.12 .venv && uv pip install -e .
	cd web && npm install

seed:
	cd server && .venv/bin/python seed.py

server:
	cd server && .venv/bin/uvicorn main:app --reload --port 8000

agent:
	cd agent && .venv/bin/python main.py dev

web:
	cd web && npm run dev
