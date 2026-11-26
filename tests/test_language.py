"""Caller-language detection and the rule for switching the reply language."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from language import (  # noqa: E402
    classify, enabled_languages, has_other_indic, next_language, normalize_digits, words,
)

EN_HI = ("en", "hi")
TAMIL = "எனக்கு ஒரு மருத்துவரை பார்க்க வேண்டும்"


class ClassifyTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("मुझे तीन दिन से खांसी है"), "hi")
        self.assertEqual(classify("Mujhe teen din se khansi hai, appointment chahiye"), "hi")
        self.assertEqual(classify("मुझे General Medicine में appointment चाहिए"), "hi")
        self.assertEqual(classify("I need an appointment for a cough"), "en")
        self.assertEqual(classify("Is this the right department for my knee?"), "en")
        self.assertEqual(classify(TAMIL), "other")
        self.assertEqual(classify("9876501001"), "en")
        self.assertEqual(classify(""), "en")

    def test_words_keep_devanagari_vowel_signs(self):
        self.assertEqual(words("नहीं, पहला नहीं!"), ["नहीं", "पहला", "नहीं"])
        self.assertEqual(words("Pehla wala, 9:30"), ["pehla", "wala", "9", "30"])


class SwitchingTests(unittest.TestCase):
    def test_switching_needs_three_words_in_the_other_language(self):
        self.assertEqual(next_language("hi", "appointment", EN_HI), "hi")
        self.assertEqual(next_language("hi", "yes please", EN_HI), "hi")
        self.assertEqual(next_language("hi", "9876501001", EN_HI), "hi")
        self.assertEqual(next_language("hi", "I would like to book an appointment", EN_HI), "en")
        self.assertEqual(next_language("en", "haan ji", EN_HI), "en")
        self.assertEqual(next_language("en", "mujhe kal ka time chahiye", EN_HI), "hi")

    def test_unsupported_language_never_becomes_the_reply_language(self):
        self.assertEqual(next_language("hi", TAMIL, EN_HI), "hi")
        self.assertEqual(next_language("en", TAMIL, EN_HI), "en")

    def test_hindi_needs_to_be_enabled(self):
        self.assertEqual(next_language("en", "मुझे खांसी है और बुखार", ("en",)), "en")


class ConfigTests(unittest.TestCase):
    def test_enabled_languages(self):
        self.assertEqual(enabled_languages(None), ("en",))
        self.assertEqual(enabled_languages(""), ("en",))
        self.assertEqual(enabled_languages("en"), ("en",))
        self.assertEqual(enabled_languages("en,hi"), EN_HI)
        self.assertEqual(enabled_languages(" hi "), EN_HI)
        with self.assertRaises(RuntimeError):
            enabled_languages("en,ta")


class ScriptTests(unittest.TestCase):
    def test_digits_and_scripts(self):
        self.assertEqual(normalize_digits("९८७६५०१००१"), "9876501001")
        self.assertEqual(normalize_digits("सुबह ९:३० बजे"), "सुबह 9:30 बजे")
        self.assertTrue(has_other_indic("வணக்கம்"))
        self.assertTrue(has_other_indic("নমস্কার"))
        self.assertFalse(has_other_indic("नमस्ते Riya"))
        self.assertFalse(has_other_indic("Hello"))


if __name__ == "__main__":
    unittest.main()
