"""LLM provider wiring for the cascaded pipeline.

Two providers, picked with `LLM_PROVIDER` in agent/.env:

    groq    (default)  openai/gpt-oss-120b on Groq's OpenAI-compatible endpoint.
                       Chosen for time-to-first-token: on a live call TTFT is the
                       stage the caller actually feels, and Groq is the fastest
                       option here.
    openai             the official API. Usually slower to first token, but
                       stronger instruction-following, and on a paid key there is
                       no free-tier rate limit to cut a call off mid-sentence.

Both speak the OpenAI protocol, so switching changes only the base URL, the key,
and the model. Keeping it to an env flip is deliberate: `make latency` can then
measure the two against the same call script instead of arguing about them.

Everything is overridable: LLM_MODEL, LLM_BASE_URL, LLM_API_KEY,
LLM_REASONING_EFFORT.

For the speech-to-speech alternative (no separate STT/LLM/TTS), see realtime.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from livekit.agents import NOT_GIVEN
from livekit.plugins import openai

DEFAULT_PROVIDER = "groq"


@dataclass(frozen=True)
class _Defaults:
    base_url: str
    model: str
    key_env: str
    reasoning_effort: str | None


PROVIDERS: dict[str, _Defaults] = {
    "groq": _Defaults(
        base_url="https://api.groq.com/openai/v1",
        model="openai/gpt-oss-120b",
        key_env="GROQ_API_KEY",
        # gpt-oss is a reasoning model; keep the effort low so it stays snappy.
        reasoning_effort="low",
    ),
    "openai": _Defaults(
        base_url="https://api.openai.com/v1",
        # A non-reasoning model by default: no reasoning tokens to wait through
        # before the first spoken word. gpt-5-mini is the option if the call needs
        # more reasoning than latency.
        model="gpt-4.1-mini",
        key_env="OPENAI_API_KEY",
        reasoning_effort=None,
    ),
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    key_env: str
    reasoning_effort: str | None

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"

    def as_dict(self) -> dict:
        """Recorded on every call so a latency comparison knows what produced it."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "reasoning_effort": self.reasoning_effort,
        }


def _env(name: str) -> str | None:
    value = os.getenv(name)
    value = value.strip() if value else ""
    return value or None


def resolve_config() -> LLMConfig:
    """The active provider and model, from env, without touching the network."""
    provider = (_env("LLM_PROVIDER") or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER={provider!r} is not one of: "
            + ", ".join(sorted(PROVIDERS))
        )
    defaults = PROVIDERS[provider]
    effort = _env("LLM_REASONING_EFFORT") or defaults.reasoning_effort
    return LLMConfig(
        provider=provider,
        model=_env("LLM_MODEL") or defaults.model,
        base_url=_env("LLM_BASE_URL") or defaults.base_url,
        key_env=defaults.key_env,
        reasoning_effort=None if effort in (None, "none") else effort,
    )


def api_key_for(config: LLMConfig) -> str:
    """The key for the selected provider only.

    Deliberately not a fallback chain across providers: sending a Groq key to
    api.openai.com fails with a 401 that reads like an OpenAI outage, so the
    provider's own variable (or an explicit LLM_API_KEY) is the only thing that
    counts.
    """
    key = _env("LLM_API_KEY") or _env(config.key_env)
    if not key:
        raise RuntimeError(
            f"LLM_PROVIDER is {config.provider!r} but {config.key_env} is not set. "
            f"Add {config.key_env} to agent/.env (or set LLM_API_KEY to override)."
        )
    return key


def build_llm() -> openai.LLM:
    config = resolve_config()
    return openai.LLM(
        model=config.model,
        base_url=config.base_url,
        api_key=api_key_for(config),
        # Low temperature keeps the model from role-playing the caller's side.
        temperature=0.2,
        # One tool at a time makes the intake flow controllable and prevents the
        # model from firing several fabricated update_intake calls at once.
        parallel_tool_calls=False,
        reasoning_effort=config.reasoning_effort or NOT_GIVEN,
    )


def describe() -> str:
    config = resolve_config()
    effort = f", reasoning_effort={config.reasoning_effort}" if config.reasoning_effort else ""
    return f"LLM: {config.label} at {config.base_url}{effort}"
