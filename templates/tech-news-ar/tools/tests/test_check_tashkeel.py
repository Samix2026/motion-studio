"""Tests for tools/check-tashkeel.py (tashkeel + banned standalone word).

Run:
  python3 -m unittest discover -s templates/tech-news-ar/tools/tests -v
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parent.parent / "check-tashkeel.py"
_spec = importlib.util.spec_from_file_location("check_tashkeel", TOOL_PATH)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)  # type: ignore[union-attr]

BANNED = "بل"


def run_on(text: str):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "script.md").write_text(text, encoding="utf-8")
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["check-tashkeel.py", d]
        try:
            with contextlib.redirect_stdout(out):
                code = tool.main()
        finally:
            sys.argv = argv
        return code, out.getvalue()


class BannedWordTests(unittest.TestCase):
    def test_flags_standalone_word(self):
        for line in (
            BANNED,
            "ليس سهلا " + BANNED + " صعب",
            BANNED + " هو",
            "(" + BANNED + ")",
            "كلمة " + BANNED + "، ثم",
            "<p>" + BANNED + "</p>",
            "بَلْ",  # with tashkeel
            "بـل",  # with tatweel
        ):
            with self.subTest(line=line):
                self.assertTrue(any("banned word" in p for p in tool.line_problems(line)), line)

    def test_ignores_longer_words(self):
        for line in (
            "قبل",
            "مستقبل",
            "بلد",
            "بلغ",
            "مقابل",
            "و" + BANNED,  # prefixed form is a different token
            "قبل إضافة موظف أو معدات",
            "Lean waste",
        ):
            with self.subTest(line=line):
                self.assertEqual([p for p in tool.line_problems(line) if "banned" in p], [], line)

    def test_main_fails_on_banned_word_and_reports_line(self):
        code, out = run_on("سطر أول\nليس هذا " + BANNED + " ذاك\n")
        self.assertEqual(code, 1)
        self.assertIn("script.md:2: banned word", out)

    def test_allow_comment_still_exempts_line(self):
        code, _ = run_on("الكلمة " + BANNED + " محظورة <!-- check-tashkeel: allow -->\n")
        self.assertEqual(code, 0)


class TashkeelTests(unittest.TestCase):
    def test_flags_tashkeel_codes(self):
        self.assertEqual(tool.line_problems("مُحَمَّد"), ["U+064E", "U+064F", "U+0651"])

    def test_base_hamza_letters_allowed(self):
        self.assertEqual(tool.line_problems("آ أ إ ئ ؤ ء"), [])

    def test_main_clean_and_dirty(self):
        self.assertEqual(run_on("نص عربي بدون تشكيل\n")[0], 0)
        code, out = run_on("كَلمة\n")
        self.assertEqual(code, 1)
        self.assertIn("script.md:1: U+064E", out)


if __name__ == "__main__":
    unittest.main()
