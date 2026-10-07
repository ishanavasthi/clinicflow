"""Isolated text evaluations through the real Receptionist function tools.

The live path speaks the configured OpenAI-compatible chat/tool protocol. It
uses the voice agent's system prompt, decorated methods and HTTP persistence
client. Speech recognition and synthesis are outside this text evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from evals.contracts import SCHEMA_VERSION, content_hash, validate_run
from evals.fixtures import FIXED_CLOCK, build_fixture, read_final_state
from evals.patients import PatientPolicyError, ScriptedPatient
from evals.retry import ATTEMPTS, RETRYABLE_STATUS, retry_delay

ROOT = Path(__file__).resolve().parents[1]
# Both applications use loose top-level modules. These names do not overlap in
# the imports used here; isolate the server database via FastAPI dependency
# override rather than mutating its module-level engine.
for directory in (ROOT / "agent", ROOT / "server"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from db import get_session  # noqa: E402
from main import app as server_app  # noqa: E402
from receptionist import Receptionist  # noqa: E402
from server_client import ServerClient  # noqa: E402
from state import CallState  # noqa: E402


def _tool_schemas(agent: Receptionist) -> list[dict]:
    # This is the same schema builder the installed LiveKit OpenAI plugin uses
    # for the voice path; the decorated methods remain the source of truth.
    from livekit.agents import llm
    # Inspect class descriptors to avoid evaluating LiveKit's session-only
    # properties on an unstarted headless Agent instance.
    names = [name for name, item in vars(Receptionist).items() if isinstance(item, llm.FunctionTool)]
    return [llm.utils.build_strict_openai_schema(getattr(agent, name)) for name in names]


class EvaluationReceptionist(Receptionist):
    """Supply only LiveKit history-dependent phone verification in text mode."""

    def _recent_user_text(self, turns: int = 3) -> str:
        return " ".join(self.eval_user_history[-turns:])


class TracePublisher:
    def __init__(self, emit):
        self.emit = emit

    async def publish(self, type: str, payload: dict):
        self.emit("state", name=type, result=payload)


class FaultClient(ServerClient):
    def __init__(self, *, engine, fault: dict | None, emit, transport):
        super().__init__(base_url="http://evaluation.local")
        old = self._client
        self._client = httpx.AsyncClient(base_url=self.base_url, transport=transport, timeout=10)
        self._old_client = old
        self.engine = engine
        self.fault = fault or {}
        self.emit = emit
        self.counts: dict[str, int] = {}

    async def aclose(self):
        await self._client.aclose()
        await self._old_client.aclose()

    def _hit(self, operation: str) -> str | None:
        self.counts[operation] = self.counts.get(operation, 0) + 1
        if self.fault.get("operation") != operation:
            return None
        trigger = int(self.fault.get("trigger", 1))
        times = int(self.fault.get("times", 1))
        if trigger <= self.counts[operation] < trigger + times:
            effect = self.fault.get("effect", "raise")
            self.emit("state", name="fault", result={"operation": operation, "effect": effect, "attempt": self.counts[operation]})
            return effect
        return None

    async def create_patient(self, **fields):
        if self._hit("create_patient") == "raise":
            raise httpx.ConnectError("injected patient persistence outage")
        return await super().create_patient(**fields)

    async def update_patient(self, patient_id, **fields):
        if self._hit("update_patient") == "raise":
            raise httpx.ConnectError("injected patient persistence outage")
        return await super().update_patient(patient_id, **fields)

    async def availability(self, department, limit=3, **kwargs):
        effect = self._hit("availability")
        if effect == "raise":
            raise httpx.ConnectError("injected availability outage")
        if effect == "empty":
            return []
        return await super().availability(department, limit, **kwargs)

    async def book(self, patient_id, slot_id, reason, **kwargs):
        effect = self._hit("book")
        if effect == "raise":
            raise httpx.ConnectError("injected booking outage")
        if effect == "take_slot":
            from sqlmodel import Session
            from models import Slot
            with Session(self.engine) as session:
                slot = session.get(Slot, slot_id)
                slot.booked = True
                session.add(slot)
                session.commit()
        result = await super().book(patient_id, slot_id, reason, **kwargs)
        if effect == "commit_then_raise":
            raise httpx.ReadError("injected lost booking response after commit")
        return result


async def _post_with_retry(client: httpx.AsyncClient, body: dict, key: str, attempts: int = ATTEMPTS) -> httpx.Response:
    for attempt in range(attempts):
        response = await client.post("/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
        if response.status_code not in RETRYABLE_STATUS or attempt == attempts - 1:
            response.raise_for_status()
            return response
        await asyncio.sleep(retry_delay(response.headers, attempt))
    raise AssertionError("unreachable")


def _hash_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _revision() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _manifest(scenario: dict, *, mode: str, config: dict, suite_hash: str, fixed_clock: str) -> dict:
    from prompts import SYSTEM_PROMPT
    from policy import load_policy
    from evals.judge import SYSTEM as JUDGE_PROMPT
    from evals.scoring import EVALUATOR_VERSION
    policy = load_policy()
    effective_prompt = SYSTEM_PROMPT + ("\n\n" + policy["system_addendum"] if policy["system_addendum"] else "")
    source_paths = [ROOT / "agent" / part for part in (
        "receptionist.py", "prompts.py", "policy.py", "server_client.py", "state.py",
        "tools/appointments.py", "tools/intake.py", "tools/routing.py", "tools/faq.py",
    )]
    source_paths += [ROOT / "server" / part for part in ("models.py", "routes/appointments.py", "routes/patients.py")]
    settings = {"temperature": config.get("temperature", 0.2), "parallel_tool_calls": False,
                "reasoning_effort": config.get("reasoning_effort")}
    return {
        "code_revision": _revision(), "source_hash": _hash_files(source_paths),
        "agent_provider": config.get("provider"), "agent_model": config.get("model"),
        "agent_settings": settings, "prompt_hash": hashlib.sha256(effective_prompt.encode()).hexdigest(),
        "policy_hash": content_hash(policy),
        "judge_model": config.get("judge_model"),
        "judge_settings": {"temperature": 0} if config.get("judge_model") else None,
        "fixture_hash": content_hash({"fixture": scenario.get("fixture"), "fixed_clock": fixed_clock,
                                      "builder_hash": hashlib.sha256((ROOT / "evals" / "fixtures.py").read_bytes()).hexdigest()}),
        "suite_hash": suite_hash, "evaluator_version": EVALUATOR_VERSION,
        "judge": {"provider": config.get("provider"), "model": config.get("judge_model"),
                  "settings": {"temperature": 0},
                  "prompt_hash": hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest()},
        "dependencies": {name: _version(name) for name in ("livekit-agents", "fastapi", "sqlmodel", "httpx")},
        "fixed_clock": fixed_clock, "mode": mode,
    }


def _call_arguments(raw: str, name: str, tool_schemas: dict[str, dict], agent: Receptionist) -> dict:
    args = json.loads(raw)
    if not isinstance(args, dict) or name not in tool_schemas:
        raise ValueError("invalid tool call")
    fields = tool_schemas[name]["function"]["parameters"]["properties"]
    if set(args) - set(fields):
        raise ValueError("unexpected tool argument")
    signature = inspect.signature(getattr(agent, name))
    required = {key for key, value in signature.parameters.items()
                if key not in ("self", "context") and value.default is inspect.Parameter.empty}
    missing = required - set(args)
    if missing:
        raise ValueError(f"missing tool arguments: {sorted(missing)}")
    for field, description in fields.items():
        kind = description.get("type")
        if field in args and args[field] is not None and (
            (kind == "integer" and type(args[field]) is not int) or
            (kind == "string" and type(args[field]) is not str) or
            (isinstance(kind, list) and "integer" in kind and type(args[field]) is not int) or
            (isinstance(kind, list) and "string" in kind and type(args[field]) is not str)
        ):
            raise ValueError(f"invalid type for {field}")
    return args


async def run_scenario(scenario: dict, agent_config: dict, *, trial: int = 1,
                       mode: str = "live", suite_hash: str | None = None,
                       fixed_clock: str = FIXED_CLOCK, max_turns: int = 12,
                       max_tool_calls: int = 30, max_model_requests: int = 60,
                       work_dir: Path | None = None) -> dict:
    if mode not in ("live", "scripted"):
        raise ValueError("mode must be live or scripted")
    run_id = f"{scenario['id']}-t{trial:02d}-{mode}"
    suite_hash = suite_hash or content_hash([scenario])
    events: list[dict] = []
    turn = 0
    def emit(kind: str, **fields):
        event = {"id": f"e{len(events)+1:04d}", "kind": kind, "turn": turn, **fields}
        events.append(event)
        return event["id"]

    state = CallState(room_name=run_id)
    result = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "scenario_id": scenario["id"],
        "trial": trial, "mode": mode, "status": "completed", "manifest": _manifest(scenario, mode=mode, config=agent_config, suite_hash=suite_hash, fixed_clock=fixed_clock),
        "events": events, "final_state": {"patients": [], "appointments": [], "slots": [], "call_state": {}},
        "scenario": scenario,
    }
    key = agent_config.get("api_key") or os.getenv(agent_config.get("api_key_env", "LLM_API_KEY"), "")
    if mode == "live" and not key:
        result.update(status="blocked", error="Missing configured model API key")
        emit("error", text=result["error"])
        validate_run(result)
        return result
    from sqlmodel import Session
    owned_temp = None
    if work_dir is None:
        owned_temp = tempfile.TemporaryDirectory(prefix="clinicflow-eval-")
        work_dir = Path(owned_temp.name)
    database = work_dir / f"{run_id}.sqlite"
    engine = build_fixture(database, scenario, fixed_clock)
    def session_override():
        with Session(engine) as session:
            yield session
    server_app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=server_app)
    client = FaultClient(engine=engine, fault=scenario.get("fault"), emit=emit, transport=transport)
    agent = EvaluationReceptionist(state, client, TracePublisher(emit))
    agent.eval_user_history = []
    schemas = _tool_schemas(agent)
    schemas_by_name = {item["function"]["name"]: item for item in schemas}
    tool_count = 0
    requests = 0
    post_booking_replies = 0
    started = time.perf_counter()
    from prompts import GREETING_TEXT
    messages = [{"role": "system", "content": agent.instructions}]
    patient = ScriptedPatient(scenario)

    async def invoke(name: str, raw: str, provider_call_id: str | None = None):
        nonlocal tool_count
        tool_count += 1
        call_id = emit("tool_call", name=name, arguments=raw, provider_call_id=provider_call_id)
        if tool_count > max_tool_calls:
            output = "Tool-call budget exceeded"
            emit("tool_result", name=name, call_id=call_id, result=output, ok=False)
            raise RuntimeError(output)
        try:
            args = _call_arguments(raw, name, schemas_by_name, agent)
            output = await getattr(agent, name)(None, **args)
            ok = not bool(re.search(r"^(Could not|Booking did not|Do not offer|The caller has not|No open slots)", str(output)))
            emit("tool_result", name=name, call_id=call_id, result=output, ok=ok)
        except Exception as exc:
            output = f"Rejected tool call: {type(exc).__name__}: {exc}"
            emit("tool_result", name=name, call_id=call_id, result=output, ok=False)
        return output

    try:
        emit("assistant", text=GREETING_TEXT)
        initial = str(scenario["initial_message"])
        emit("user", text=initial)
        agent.eval_user_history.append(initial)
        messages.append({"role": "assistant", "content": GREETING_TEXT})
        messages.append({"role": "user", "content": initial})
        if mode == "scripted":
            for step in scenario.get("script", []):
                turn += 1
                if "user" in step:
                    utterance = str(step["user"])
                    emit("user", text=utterance)
                    agent.eval_user_history.append(utterance)
                await invoke(step["name"], json.dumps(step.get("arguments", {})))
        else:
            base_url = str(agent_config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
            async with httpx.AsyncClient(base_url=base_url, timeout=float(agent_config.get("timeout", 45))) as model_client:
                while turn < min(max_turns, int((scenario.get("policy") or {}).get("max_turns", max_turns))):
                    requests += 1
                    if requests > max_model_requests:
                        raise RuntimeError("model-request budget exceeded")
                    body = {"model": agent_config["model"], "messages": messages, "tools": schemas,
                            "tool_choice": "auto", "parallel_tool_calls": False,
                            "temperature": agent_config.get("temperature", 0.2)}
                    if agent_config.get("reasoning_effort"):
                        body["reasoning_effort"] = agent_config["reasoning_effort"]
                    response = await _post_with_retry(model_client, body, key)
                    payload = response.json()
                    if payload.get("usage"):
                        result.setdefault("usage", []).append(payload["usage"])
                    choice = payload["choices"][0]
                    message = choice["message"]
                    calls = message.get("tool_calls") or []
                    if calls:
                        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
                        for call in calls:
                            name = call.get("function", {}).get("name", "")
                            raw = call.get("function", {}).get("arguments", "{}")
                            output = await invoke(name, raw, call.get("id"))
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(output)})
                        continue
                    from receptionist import _clean_reply
                    spoken = _clean_reply(message.get("content") or "")
                    if not spoken:
                        raise RuntimeError("model produced neither a tool call nor assistant text")
                    emit("assistant", text=spoken)
                    messages.append({"role": "assistant", "content": spoken})
                    turn += 1
                    if state.booking is not None:
                        post_booking_replies += 1
                    continuation = bool((scenario.get("policy") or {}).get("continue_after_booking"))
                    if state.routed_department == "Emergency" or (state.booking is not None and (not continuation or post_booking_replies >= 2)):
                        result["termination"] = "booking_or_emergency_reply"
                        break
                    answer = patient.reply(spoken, state.offered_slots)
                    if answer is None:
                        result["termination"] = "patient_unmatched" if patient.unmatched else "patient_ended"
                        if patient.unmatched:
                            emit("patient_policy", text=f"no patient rule matched; patient ended the call: {patient.unmatched!r}")
                        break
                    emit("user", text=answer)
                    agent.eval_user_history.append(answer)
                    messages.append({"role": "user", "content": answer})
                else:
                    result["termination"] = "turn_budget"
    except PatientPolicyError as exc:
        result.update(status="patient_error", error=str(exc))
        emit("error", text=str(exc))
    except Exception as exc:
        result.update(status="agent_error", error=f"{type(exc).__name__}: {exc}")
        emit("error", text=result["error"])
    finally:
        result["latency_seconds"] = round(time.perf_counter() - started, 3)
        result["model_requests"] = requests
        result["tool_calls"] = tool_count
        result["final_state"] = read_final_state(engine, state)
        await client.aclose()
        server_app.dependency_overrides.pop(get_session, None)
        engine.dispose()
        if owned_temp:
            owned_temp.cleanup()
    validate_run(result)
    return result


def load_scenarios(suite: str) -> list[dict]:
    files = sorted((ROOT / "evals" / "scenarios").glob("*.json"))
    scenarios = [json.loads(path.read_text()) for path in files]
    return [s for s in scenarios if s.get("split") == suite or suite == "all"]


async def run_suite(args) -> dict:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "agent" / ".env")
    from llm import resolve_config
    cfg = resolve_config()
    config = {**cfg.as_dict(), "api_key_env": "LLM_API_KEY" if os.getenv("LLM_API_KEY") else cfg.key_env,
              "temperature": 0.2, "timeout": args.timeout,
              "judge_model": args.judge_model or cfg.model}
    scenarios = load_scenarios(args.suite)
    if not scenarios:
        raise RuntimeError(f"No scenarios for suite {args.suite}")
    suite_hash = content_hash(scenarios)
    args.output.mkdir(parents=True, exist_ok=True)
    runs, scorecards = [], []
    for scenario in scenarios:
        for trial in range(1, args.repeat + 1):
            run = await run_scenario(scenario, config, trial=trial, mode=args.mode, suite_hash=suite_hash,
                                     max_turns=args.max_turns, max_tool_calls=args.max_tool_calls,
                                     max_model_requests=args.max_model_requests, work_dir=args.output)
            if args.mode == "live" and run["status"] == "completed":
                from evals.judge import judge_run
                judge_config = {"base_url": config["base_url"], "model": args.judge_model or config["model"],
                                "api_key_env": config["api_key_env"], "temperature": 0,
                                "timeout_seconds": args.timeout}
                try:
                    run["semantic_judgment"] = await judge_run(run, scenario, judge_config)
                except Exception as exc:
                    run["judge_error"] = f"{type(exc).__name__}: {exc}"
            (args.output / f"{run['run_id']}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False, default=str))
            runs.append(run)
            from evals.scoring import score_run
            scorecards.append(score_run(run, scenario))
            (args.output / "summary.json").write_text(json.dumps({"schema_version": 1, "runs": runs, "scorecards": scorecards}, indent=2, ensure_ascii=False, default=str))
    return {"runs": runs, "scorecards": scorecards}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("development", "holdout", "all"), default="development")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--mode", choices=("live", "scripted"), default="live")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-model-requests", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--judge-model")
    args = parser.parse_args()
    if args.repeat < 1 or min(args.max_turns, args.max_tool_calls, args.max_model_requests) < 1:
        parser.error("repeat and budgets must be positive")
    summary = asyncio.run(run_suite(args))
    statuses = {status: sum(run["status"] == status for run in summary["runs"]) for status in ("completed", "blocked", "agent_error", "patient_error")}
    print(json.dumps({"output": str(args.output / "summary.json"), "statuses": statuses}))


if __name__ == "__main__":
    main()
