#!/usr/bin/env python3
"""Fail if Arabic tashkeel (diacritics) appears in project text files.

Usage: python3 tools/check-tashkeel.py [project-dir]

Scans text files and reports every forbidden combining mark with file:line.
Exit 1 if any mark is found, 0 otherwise. Standard library only.

Rule: CONTENT_RULES.md — no tashkeel in visible Arabic text.
Base letters (آ أ إ ئ ؤ ء) are letters, not tashkeel, and are allowed.
Allow a specific line by adding the comment: check-tashkeel: allow
"""
import os
import sys

MARKS = (
    set(chr(c) for c in range(0x064B, 0x0660))   # tanween/fatha/damma/kasra/shadda/sukun
    | {chr(0x0670)}                               # superscript alef
    | set(chr(c) for c in range(0x0610, 0x061B))  # Arabic signs
    | set(chr(c) for c in range(0x06D6, 0x06EE))  # Quranic marks
)

TEXT_EXT = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".svg"}
SKIP_DIRS = {".git", "node_modules", "renders", "snapshots", ".hyperframes"}
MAX_BYTES = 2_000_000


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
                bad = sorted({ch for ch in line if ch in MARKS})
                if bad:
                    codes = " ".join(f"U+{ord(c):04X}" for c in bad)
                    findings.append(f"{path}:{lineno}: {codes}");

    if findings:
        print("FAIL: Arabic tashkeel found:")
        for f in findings:
            print("  " + f)
        return 1
    print("OK: no Arabic tashkeel found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
