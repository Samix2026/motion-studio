#!/usr/bin/env python3
"""Fail if Arabic tashkeel (diacritics) or a banned Arabic word appears in project text files.

Usage: python3 tools/check-tashkeel.py [project-dir]

Scans text files and reports every forbidden combining mark and every banned
standalone word with file:line. Exit 1 if any is found, 0 otherwise. Standard
library only.

Rule: CONTENT_RULES.md — no tashkeel in visible Arabic text, no banned words.
Base letters (آ أ إ ئ ؤ ء) are letters, not tashkeel, and are allowed.
A banned word matches only as a standalone word: it is not flagged inside a
longer word (e.g. قبل).
Allow a specific line by adding the comment: check-tashkeel: allow
"""
import os
import re
import sys

MARKS = (
    set(chr(c) for c in range(0x064B, 0x0660))   # tanween/fatha/damma/kasra/shadda/sukun
    | {chr(0x0670)}                               # superscript alef
    | set(chr(c) for c in range(0x0610, 0x061B))  # Arabic signs
    | set(chr(c) for c in range(0x06D6, 0x06EE))  # Quranic marks
)

BANNED_WORDS = ("\u0628\u0644",)  # the standalone word "ba-lam"; see CONTENT_RULES.md
# Arabic letters (tashkeel and tatweel are stripped before matching)
_AR_LETTER = "\u0621-\u063A\u0641-\u064A\u066E-\u066F\u0671-\u06D3\u06D5\u06EE-\u06EF\u06FA-\u06FC\u06FF"
_BANNED = re.compile("(?<![%s])(?:%s)(?![%s])" % (_AR_LETTER, "|".join(BANNED_WORDS), _AR_LETTER))

TEXT_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".svg"}
SKIP_DIRS = {".git", "node_modules", "renders", "snapshots", ".hyperframes"}
MAX_BYTES = 2_000_000


def line_problems(line: str) -> list:
    """Forbidden marks (as U+XXXX) and banned words found in one line."""
    problems = [f"U+{ord(c):04X}" for c in sorted({ch for ch in line if ch in MARKS})]
    bare = "".join(ch for ch in line if ch not in MARKS and ch != "\u0640")
    problems += [f"banned word {w}" for w in sorted(set(_BANNED.findall(bare)))]
    return problems


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if "check-tashkeel: allow" in line:
                    continue
                bad = line_problems(line)
                if bad:
                    findings.append(f"{path}:{lineno}: {' '.join(bad)}")

    if findings:
        print("FAIL: Arabic tashkeel or banned word found:")
        for f in findings:
            print("  " + f)
        return 1
    print("OK: no Arabic tashkeel or banned word found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
