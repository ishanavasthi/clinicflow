"""LLM provider wiring for the cascaded pipeline.

Three providers, picked with `LLM_PROVIDER` in agent/.env:

    groq    (default)  openai/gpt-oss-120b on Groq's OpenAI-compatible endpoint.
                       Chosen for time-to-first-token: on a live call TTFT is the
                       stage the caller actually feels, and Groq is the fastest
                       option here.
    openai             the official API. Usually slower to first token, but
                       stronger instruction-following, and on a paid key there is
                       no free-tier rate limit to cut a call off mid-sentence.
    openrouter         the same gpt-oss-120b through OpenRouter, on a paid key,
                       so no 8000 tokens/min cap. OPENROUTER_HOST picks who
                       serves it: `default` lets OpenRouter route the request,
                       `groq` or `cerebras` asks for that host first.
                       OPENROUTER_FALLBACKS=false makes the pin strict (fail
                       rather than move to a slower host); by default a pinned
                       host that is down falls back to another, because a slow
                       reply beats a dead call.

All three speak the OpenAI protocol, so switching changes only the base URL, the
key, the model, and for OpenRouter the routing preference. Keeping it to an env flip is deliberate: `make latency` can then
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
    "openrouter": _Defaults(
        base_url="https://openrouter.ai/api/v1",
        model="openai/gpt-oss-120b",
        key_env="OPENROUTER_API_KEY",
        reasoning_effort="low",
    ),
}

# OPENROUTER_HOST values and the OpenRouter provider slug each one pins.
OPENROUTER_HOSTS: dict[str, str | None] = {
    "default": None,
    "groq": "groq",
    "cerebras": "cerebras",
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    key_env: str
    reasoning_effort: str | None
    # OpenRouter only: the pinned host (None lets OpenRouter route) and whether
    # it may fall back to another host when the pinned one fails.
    host: str | None = None
    allow_fallbacks: bool = True

    @property
    def label(self) -> str:
        if self.provider == "openrouter":
            return f"{self.provider}({self.host or 'default'})/{self.model}"
        return f"{self.provider}/{self.model}"

    def extra_body(self) -> dict | None:
        """OpenRouter's routing preference, sent with every request."""
        if self.provider != "openrouter" or self.host is None:
            return None
        return {"provider": {"order": [self.host], "allow_fallbacks": self.allow_fallbacks}}

    def as_dict(self) -> dict:
        """Recorded on every call so a latency comparison knows what produced it."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "reasoning_effort": self.reasoning_effort,
            "host": self.host,
            "allow_fallbacks": self.allow_fallbacks,
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
    host, allow_fallbacks = None, True
    if provider == "openrouter":
        host, allow_fallbacks = _openrouter_routing()
    return LLMConfig(
        provider=provider,
        model=_env("LLM_MODEL") or defaults.model,
        base_url=_env("LLM_BASE_URL") or defaults.base_url,
        key_env=defaults.key_env,
        reasoning_effort=None if effort in (None, "none") else effort,
        host=host,
        allow_fallbacks=allow_fallbacks,
    )


def _openrouter_routing() -> tuple[str | None, bool]:
    """OPENROUTER_HOST and OPENROUTER_FALLBACKS, validated at startup."""
    name = (_env("OPENROUTER_HOST") or "default").lower()
    if name not in OPENROUTER_HOSTS:
        raise RuntimeError(
            f"OPENROUTER_HOST={name!r} is not one of: " + ", ".join(OPENROUTER_HOSTS)
        )
    fallbacks = (_env("OPENROUTER_FALLBACKS") or "true").lower()
    if fallbacks not in ("true", "false"):
        raise RuntimeError(f"OPENROUTER_FALLBACKS={fallbacks!r} must be true or false")
    return OPENROUTER_HOSTS[name], fallbacks == "true"


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
        extra_body=config.extra_body() or NOT_GIVEN,
    )


def describe() -> str:
    config = resolve_config()
    effort = f", reasoning_effort={config.reasoning_effort}" if config.reasoning_effort else ""
    strict = ", no fallbacks" if config.host and not config.allow_fallbacks else ""
    return f"LLM: {config.label} at {config.base_url}{effort}{strict}"
