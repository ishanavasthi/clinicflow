"""Persona, FAQ knowledge block, and Muga tone-tag rules for the receptionist.

The full system prompt is assembled in M1. This module holds the static text so
the persona and the FAQ knowledge base live in one reviewable place.
"""
from __future__ import annotations

# Filled out in M1. Kept as a named constant so receptionist.py can import it now.
SYSTEM_PROMPT = ""

# Injected into the system prompt in M2 so the agent answers FAQs directly
# without a RAG lookup (10 items fit comfortably in-prompt).
FAQ_KNOWLEDGE = ""
