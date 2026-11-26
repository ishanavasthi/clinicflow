"""Which language the caller is speaking, and which one Riya should reply in.

Decided from the caller's text alone (not STT metadata), so the text-only eval
harness and the live call use exactly the same rule.

- `hi` covers Hindi in Devanagari and Hinglish in Roman letters: a Hinglish
  caller is answered in natural Hinglish.
- `other` is any other Indic script (Tamil, Bengali, ...). It is never the reply
  language: nobody on the team can check those replies, so the caller gets one
  fixed Hindi/English line instead.
- The reply language changes only on a caller turn of three or more words, so
  "appointment", "yes" or a phone number never flips it.

Python's `\\w` does not match Devanagari vowel signs, so `\\b` cannot be used
around Hindi words. Match Hindi by token with `words()` instead.
"""
from __future__ import annotations

import os
import re
from typing import Literal

SUPPORTED = ("en", "hi")
Language = Literal["en", "hi", "other"]

_TOKEN_RE = re.compile(r"[\wऀ-ॿ]+")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
# Bengali through Malayalam: every Indic block after Devanagari.
_OTHER_INDIC_RE = re.compile(r"[ঀ-ൿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Common Roman-script Hindi words. Two hits that make up a quarter of the turn
# mark it as Hinglish; English clinic words alone ("appointment") never do.
HINDI_ROMAN = frozenset("""
hai hain mujhe mera meri mere naam nahi nahin kya haan ji aap aapka aapki ki ka ke
se hoon hun ho raha rahi chahiye kar karna dijiye theek thik accha achha bhi aur
din saal umar umr dard takleef kal abhi wala wali pehla doosra teesra bukhar khansi
seene saans kab kitne batao bataiye mein main hua
""".split())

MIN_SWITCH_WORDS = 3


def words(text: str) -> list[str]:
    """Lower-cased word tokens, keeping Devanagari vowel signs inside words."""
    return _TOKEN_RE.findall((text or "").lower())


def normalize_digits(text: str) -> str:
    """Devanagari digits to ASCII, so every check compares plain digits."""
    return (text or "").translate(_DIGITS)


def has_other_indic(text: str) -> bool:
    return bool(_OTHER_INDIC_RE.search(text or ""))


def classify(text: str) -> Language:
    text = text or ""
    deva = len(_DEVANAGARI_RE.findall(text))
    other = len(_OTHER_INDIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    letters = deva + other + latin
    if not letters:
        return "en"
    if other > deva and other >= 0.3 * letters:
        return "other"
    if deva >= 0.3 * letters:
        return "hi"
    roman = [w for w in words(text) if w.isascii() and w.isalpha()]
    hits = sum(w in HINDI_ROMAN for w in roman)
    if hits >= 2 and hits >= 0.25 * len(roman):
        return "hi"
    return "en"


def enabled_languages(raw: str | None = None) -> tuple[str, ...]:
    """Parse CLINIC_LANGUAGES. English is always on; Hindi is opt-in."""
    if raw is None:
        raw = os.getenv("CLINIC_LANGUAGES")
    codes = {c.strip().lower() for c in (raw or "").split(",") if c.strip()}
    unknown = codes - set(SUPPORTED)
    if unknown:
        raise RuntimeError(
            f"CLINIC_LANGUAGES has unsupported codes {sorted(unknown)}; use en or en,hi"
        )
    return ("en", "hi") if "hi" in codes else ("en",)


def next_language(current: str, text: str, enabled: tuple[str, ...]) -> str:
    """The reply language after this caller turn."""
    detected = classify(text)
    if detected in enabled and detected != current and len(words(text)) >= MIN_SWITCH_WORDS:
        return detected
    return current
