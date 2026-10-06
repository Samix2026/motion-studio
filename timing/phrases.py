"""Deterministic phrase / caption grouping from normalized word timings.

Groups consecutive words into phrases using real word boundaries and simple,
reproducible rules (pause, punctuation, length). No rendering is redesigned
here; this only exposes ``[{start_ms, end_ms, text, word_count}]`` for the
composition layer to consume.
"""

from __future__ import annotations

from typing import Dict, List

from . import schema

_PUNCT_BREAK = frozenset(".!?؟،,;:")


def group(words: List[Dict], max_gap_ms: int = 400, max_chars: int = 42,
          max_duration_ms: int = 4000, max_words: int = 9) -> List[Dict]:
    if not words:
        return []

    phrases: List[Dict] = []
    cur: List[Dict] = []

    def flush():
        if not cur:
            return
        text = " ".join(w["word"] for w in cur)
        phrases.append({
            "start_ms": cur[0]["start_ms"],
            "end_ms": cur[-1]["end_ms"],
            "text": text,
            "word_count": len(cur),
        })
        cur.clear()

    for i, w in enumerate(words):
        if cur:
            gap = w["start_ms"] - cur[-1]["end_ms"]
            chars = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            dur = w["end_ms"] - cur[0]["start_ms"]
            prev_text = cur[-1]["word"]
            if (gap > max_gap_ms or chars > max_chars or dur > max_duration_ms
                    or len(cur) >= max_words
                    or (prev_text and prev_text[-1] in _PUNCT_BREAK)):
                flush()
        cur.append(w)
    flush()
    return phrases


def to_captions(words: List[Dict], **kwargs) -> Dict:
    """Canonical caption document consumed by the composition/review layers."""
    return {"schema_version": 1, "source": "word-timings",
            "captions": group(words, **kwargs)}


def validate_captions(doc: Dict) -> Dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("captions"), list):
        raise schema.TimingError("captions: must be an object with a 'captions' list")
    prev_end = -1
    for i, c in enumerate(doc["captions"]):
        for k in ("start_ms", "end_ms", "text"):
            if k not in c:
                raise schema.TimingError("caption[%d]: missing '%s'" % (i, k))
        s, e = c["start_ms"], c["end_ms"]
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            raise schema.TimingError("caption[%d]: times must be numbers" % i)
        if s < 0 or e <= s:
            raise schema.TimingError("caption[%d]: invalid range" % i)
        if s < prev_end:
            raise schema.TimingError("caption[%d]: overlaps previous caption" % i)
        if not isinstance(c["text"], str) or not c["text"].strip():
            raise schema.TimingError("caption[%d]: empty text" % i)
        prev_end = e
    return doc
