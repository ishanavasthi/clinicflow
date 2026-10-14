"""LLM provider selection (no keys, no network)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import llm  # noqa: E402

LLM_VARS = ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_REASONING_EFFORT",
            "OPENROUTER_HOST", "OPENROUTER_FALLBACKS", "OPENROUTER_API_KEY", "GROQ_API_KEY")


def env(**values):
    """Exactly these LLM variables, whatever the shell or agent/.env set."""
    cleared = {name: "" for name in LLM_VARS}
    return mock.patch.dict(os.environ, {**cleared, **values})


class OpenRouterConfigTests(unittest.TestCase):
    def test_default_host_lets_openrouter_route(self):
        with env(LLM_PROVIDER="openrouter"):
            config = llm.resolve_config()
        self.assertEqual(config.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(config.model, "openai/gpt-oss-120b")
        self.assertEqual(config.reasoning_effort, "low")
        self.assertIsNone(config.host)
        self.assertIsNone(config.extra_body())
        self.assertEqual(config.label, "openrouter(default)/openai/gpt-oss-120b")

    def test_pinned_host_falls_back_unless_told_not_to(self):
        with env(LLM_PROVIDER="openrouter", OPENROUTER_HOST="Cerebras"):
            config = llm.resolve_config()
        self.assertEqual(config.extra_body(), {"provider": {"order": ["cerebras"], "allow_fallbacks": True}})
        with env(LLM_PROVIDER="openrouter", OPENROUTER_HOST="groq", OPENROUTER_FALLBACKS="false"):
            config = llm.resolve_config()
        self.assertEqual(config.extra_body(), {"provider": {"order": ["groq"], "allow_fallbacks": False}})
        self.assertEqual(config.as_dict()["host"], "groq")

    def test_unknown_host_fails_at_startup(self):
        with env(LLM_PROVIDER="openrouter", OPENROUTER_HOST="venice"):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_HOST"):
                llm.resolve_config()

    def test_openrouter_reads_its_own_key_only(self):
        with env(LLM_PROVIDER="openrouter", GROQ_API_KEY="groq-key"):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                llm.api_key_for(llm.resolve_config())

    def test_other_providers_send_no_routing(self):
        with env(LLM_PROVIDER="groq", OPENROUTER_HOST="cerebras"):
            config = llm.resolve_config()
        self.assertIsNone(config.host)
        self.assertIsNone(config.extra_body())


if __name__ == "__main__":
    unittest.main()
