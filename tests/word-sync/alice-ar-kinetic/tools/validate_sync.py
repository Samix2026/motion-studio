#!/usr/bin/env python3
"""Deterministic caption-sync measurements for the kinetic-caption POC.

Compares phrase-group ranges (phrase-groups.json) against real word timings
(word-timings.json). No estimation, no rendering.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(ROOT))))

from timing import schema  # noqa: E402


def main() -> int:
    words = json.load(open(os.path.join(ROOT, "word-timings.json"), encoding="utf-8"))
    caps = json.load(open(os.path.join(ROOT, "phrase-groups.json"), encoding="utf-8"))
    doc = schema.validate(words)
    captions = caps["captions"]

    covered = set()
    rows = []
    for i, c in enumerate(captions, 1):
        ov = [w for w in doc["words"]
              if w["start_ms"] < c["end_ms"] and w["end_ms"] > c["start_ms"]]
        covered.update(id(w) for w in ov)
        lead = ov[0]["start_ms"] - c["start_ms"] if ov else None
        tail = c["end_ms"] - ov[-1]["end_ms"] if ov else None
        rows.append({"n": i, "text": c["text"], "start_ms": c["start_ms"],
                     "end_ms": c["end_ms"], "words": len(ov),
                     "lead_ms": lead, "tail_ms": tail})

    missed = [w["word"] for w in doc["words"] if id(w) not in covered]
    overlaps = [{"a": i + 1, "b": i + 2}
                for i in range(len(captions) - 1)
                if captions[i + 1]["start_ms"] < captions[i]["end_ms"]]
    gaps = [{"after": i + 1, "gap_ms": captions[i + 1]["start_ms"] - captions[i]["end_ms"]}
            for i in range(len(captions) - 1)]

    print("audio_duration_ms=%d  captions=%d  words=%d"
          % (doc["audio_duration_ms"], len(captions), len(doc["words"])))
    for r in rows:
        print("  %d  %5d-%5d  lead=%-4s tail=%-5s  %s"
              % (r["n"], r["start_ms"], r["end_ms"], r["lead_ms"], r["tail_ms"], r["text"]))
    print("missed_words:", missed)
    print("overlapping_caption_phrases:", overlaps)
    print("phrase_gaps_ms:", gaps)
    print(json.dumps({"rows": rows, "missed_words": missed,
                      "overlaps": overlaps, "gaps": gaps,
                      "audio_duration_ms": doc["audio_duration_ms"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
