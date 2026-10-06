"""Canonical word-timing schema (stdlib only).

Canonical document:

{
  "schema_version": 1,
  "provider": "elevenlabs",
  "audio_duration_ms": 12340,
  "words": [
    {"word": "example", "start_ms": 1520, "end_ms": 1830, "confidence": null}
  ]
}

Validation rejects negative timestamps, end < start, out-of-order/overlapping
sequences, words past the audio duration, and malformed provider data.
"""

from __future__ import annotations

from typing import Dict, List

SCHEMA_VERSION = 1


class TimingError(ValueError):
    pass


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(doc: Dict) -> Dict:
    if not isinstance(doc, dict):
        raise TimingError("timing: must be an object")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise TimingError("timing: schema_version must be %d" % SCHEMA_VERSION)
    provider = doc.get("provider")
    if not isinstance(provider, str) or not provider:
        raise TimingError("timing: 'provider' must be a non-empty string")
    dur = doc.get("audio_duration_ms")
    if not _is_num(dur) or dur <= 0:
        raise TimingError("timing: 'audio_duration_ms' must be a positive number")
    dur = int(round(float(dur)))
    words = doc.get("words")
    if not isinstance(words, list):
        raise TimingError("timing: 'words' must be a list")

    cleaned: List[Dict] = []
    prev_start = -1
    prev_end = -1
    for i, w in enumerate(words):
        where = "word[%d]" % i
        if not isinstance(w, dict):
            raise TimingError("timing: %s must be an object" % where)
        text = w.get("word")
        if not isinstance(text, str) or not text.strip():
            raise TimingError("timing: %s 'word' must be a non-empty string" % where)
        s, e = w.get("start_ms"), w.get("end_ms")
        if not _is_num(s) or not _is_num(e):
            raise TimingError("timing: %s start_ms/end_ms must be numbers" % where)
        s, e = int(round(float(s))), int(round(float(e)))
        if s < 0 or e < 0:
            raise TimingError("timing: %s negative timestamp" % where)
        if e < s:
            raise TimingError("timing: %s end_ms < start_ms" % where)
        if e == s:
            raise TimingError("timing: %s zero-length word" % where)
        if e > dur:
            raise TimingError("timing: %s end_ms %d exceeds audio_duration_ms %d"
                              % (where, e, dur))
        if s < prev_start:
            raise TimingError("timing: %s out of order (start_ms %d < previous %d)"
                              % (where, s, prev_start))
        if s < prev_end:
            raise TimingError("timing: %s overlaps the previous word" % where)
        conf = w.get("confidence")
        if conf is not None and (not _is_num(conf) or not (0.0 <= float(conf) <= 1.0)):
            raise TimingError("timing: %s confidence must be null or within 0..1" % where)
        cleaned.append({"word": text, "start_ms": s, "end_ms": e,
                        "confidence": None if conf is None else float(conf)})
        prev_start, prev_end = s, e

    return {"schema_version": SCHEMA_VERSION, "provider": provider,
            "audio_duration_ms": dur, "words": cleaned}


def make(provider: str, audio_duration_ms: int, words: List[Dict]) -> Dict:
    return validate({"schema_version": SCHEMA_VERSION, "provider": provider,
                     "audio_duration_ms": audio_duration_ms, "words": words})


def is_valid(doc: Dict) -> bool:
    try:
        validate(doc)
        return True
    except TimingError:
        return False
