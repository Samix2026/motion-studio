"""ElevenLabs alignment adapter.

Normalizes REAL ElevenLabs timestamp output into the canonical format. It is a
pure function over provider response data: no network, no generation.

Supported (documented) shapes
-----------------------------
1. Character alignment, as returned by the text-to-speech "with-timestamps"
   endpoints under ``alignment`` or ``normalized_alignment``::

     {
       "alignment": {
         "characters": ["H", "e", "l", "l", "o", " ", "w"],
         "character_start_times_seconds": [0.0, 0.05, ...],
         "character_end_times_seconds":   [0.05, 0.10, ...]
       },
       "audio_duration_seconds": 12.34
     }

2. A pre-grouped word list (seconds, or explicit milliseconds)::

     {"words": [{"text": "Hello", "start": 0.0, "end": 0.42}, ...]}
     {"words": [{"word": "Hello", "start_ms": 0, "end_ms": 420}, ...]}

Provider-specific keys never survive into the canonical document.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .. import schema
from ..schema import TimingError

_AUDIO_DURATION_KEYS_MS = ("audio_duration_ms",)
_AUDIO_DURATION_KEYS_S = ("audio_duration_seconds",)


def _duration_ms(resp: Dict, param: Optional[int]) -> Optional[int]:
    for k in _AUDIO_DURATION_KEYS_MS:
        v = resp.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(round(float(v)))
    for k in _AUDIO_DURATION_KEYS_S:
        v = resp.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(round(float(v) * 1000))
    if param:
        return int(param)
    return None


def _from_words(items: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for it in items:
        if not isinstance(it, dict):
            raise TimingError("elevenlabs: word entry must be an object")
        text = it.get("text", it.get("word"))
        if not isinstance(text, str) or not text.strip():
            continue
        if "start_ms" in it or "end_ms" in it:
            s, e = it.get("start_ms"), it.get("end_ms")
        else:
            s, e = it.get("start"), it.get("end")
            if isinstance(s, (int, float)):
                s = s * 1000
            if isinstance(e, (int, float)):
                e = e * 1000
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            raise TimingError("elevenlabs: word '%s' missing start/end" % text)
        out.append({"word": text.strip(), "start_ms": int(round(float(s))),
                    "end_ms": int(round(float(e))), "confidence": None})
    return out


def _from_characters(align: Dict) -> List[Dict]:
    chars = align.get("characters")
    starts = align.get("character_start_times_seconds")
    ends = align.get("character_end_times_seconds")
    if not (isinstance(chars, list) and isinstance(starts, list) and isinstance(ends, list)):
        raise TimingError("elevenlabs: malformed character alignment")
    if not (len(chars) == len(starts) == len(ends)):
        raise TimingError("elevenlabs: character/timestamp length mismatch")

    words: List[Dict] = []
    buf: List[str] = []
    w_start: Optional[float] = None
    w_end: Optional[float] = None

    def flush():
        nonlocal buf, w_start, w_end
        text = "".join(buf).strip()
        if text and w_start is not None and w_end is not None:
            words.append({"word": text, "start_ms": int(round(w_start * 1000)),
                          "end_ms": int(round(w_end * 1000)), "confidence": None})
        buf, w_start, w_end = [], None, None

    for ch, s, e in zip(chars, starts, ends):
        if not isinstance(ch, str) or not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            raise TimingError("elevenlabs: malformed character alignment entry")
        if ch.isspace():
            flush()
            continue
        if w_start is None:
            w_start = float(s)
        w_end = float(e)
        buf.append(ch)
    flush()
    return words


def normalize(response: Dict, audio_duration_ms: Optional[int] = None) -> Dict:
    if not isinstance(response, dict):
        raise TimingError("elevenlabs: response must be an object")
    dur = _duration_ms(response, audio_duration_ms)

    if isinstance(response.get("words"), list):
        words = _from_words(response["words"])
    else:
        align = response.get("normalized_alignment") or response.get("alignment")
        if not isinstance(align, dict):
            raise TimingError("elevenlabs: unrecognized response shape (no words/alignment)")
        words = _from_characters(align)

    if not words:
        raise TimingError("elevenlabs: no usable word timings in response")
    if dur is None:
        dur = words[-1]["end_ms"]  # container duration derived from provider data
    if dur < words[-1]["end_ms"]:
        raise TimingError("elevenlabs: word timings exceed the audio duration")
    return schema.make("elevenlabs", dur, words)
