"""English-only behaviour is pinned to the committed evidence.

The 60/80 English results in docs/evidence were produced with exactly this
prompt, these scenarios and these tool schemas. Hindi support must leave all
of them unchanged when CLINIC_LANGUAGES is unset or "en".
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from evals.contracts import content_hash  # noqa: E402
from policy import load_policy  # noqa: E402
from prompts import GREETING_TEXT, SYSTEM_PROMPT  # noqa: E402
from state import CallState  # noqa: E402

# From docs/evidence/iteration-008 and docs/evidence/final manifests.
PROMPT_HASH_008 = "020a847233444679eb26dc0e5f5645053bfa78d457a9fb8a0ec45d17669e0e45"
DEV_SUITE_HASH = "0949287d0d6d431dfae11563550d3176b956d56a23a43f564f27db6cea672255"
HOLDOUT_SUITE_HASH = "72a52cee2f346a3b2351cbfca4c343f48ab5ef275b6c943ee701848cee8ce82b"
# Captured from origin/main before the Hindi work started.
TOOL_SCHEMA_HASH = "2119e75a212ae108842d901cf47ac6e4a38b28a6511dd6f438ecf1ed993e6404"


class _Stub:
    async def publish(self, *args, **kwargs):
        return None


def english_agent():
    # Imported here, not at module load: evals.runner puts the server's `main`
    # on sys.modules, which would shadow agent/main.py for tests collected later.
    from evals.runner import EvaluationReceptionist
    return EvaluationReceptionist(CallState(), _Stub(), _Stub())


class EnglishUnchanged(unittest.TestCase):
    def test_effective_prompt_hash(self):
        policy = load_policy(ROOT / "agent" / "policies" / "candidate-008.json")
        prompt = SYSTEM_PROMPT + "\n\n" + policy["system_addendum"]
        self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), PROMPT_HASH_008)

    def test_suite_hashes(self):
        from evals.runner import load_scenarios
        self.assertEqual(content_hash(load_scenarios("development")), DEV_SUITE_HASH)
        self.assertEqual(content_hash(load_scenarios("holdout")), HOLDOUT_SUITE_HASH)

    def test_tool_schemas(self):
        from evals.runner import _tool_schemas
        schemas = _tool_schemas(english_agent())
        digest = hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, TOOL_SCHEMA_HASH)

    def test_greeting(self):
        self.assertEqual(GREETING_TEXT, "Hi, this is Riya at ClinicFlow. How can I help you today?")


if __name__ == "__main__":
    unittest.main()
