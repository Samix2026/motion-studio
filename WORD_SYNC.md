# WORD_SYNC.md — canonical word-level timing (Video Studio Agent)

One provider-neutral representation for word timing, adapters that normalize a
provider's **real** timestamps into it, a cache that lives with the voice asset,
deterministic phrase grouping, and read-only consumption by the existing review
layer.

It never generates audio, never calls a provider, and never estimates or
fabricates a timestamp.

## Pipeline position

```
… → Asset/Audio Generation → Composition
    → Word-level Timing Integration → Preview Render
    → Deterministic Analysis → AI Review → …
```

Voice generation and **visual** rendering are independent: a visual rerender,
caption restyle, or review run reads cached timings and must not call TTS.

## Canonical format

```json
{
  "schema_version": 1,
  "provider": "elevenlabs",
  "audio_duration_ms": 12340,
  "words": [
    {"word": "example", "start_ms": 1520, "end_ms": 1830, "confidence": null}
  ]
}
```

Validation (`timing/schema.py`) rejects: negative timestamps, `end_ms <= start_ms`,
out-of-order words, overlapping words, words past `audio_duration_ms`, bad
`confidence`, and malformed provider data. Provider-specific fields never reach
the canonical document.

## Layout

```
timing/
  schema.py            # canonical format + validation
  adapter.py           # provider registry
  adapters/elevenlabs.py
  cache.py             # sibling *.word-timings.json next to the voice asset
  phrases.py           # deterministic phrase/caption grouping
  cli.py               # providers | normalize | validate | phrases | show
  tests/
```

## ElevenLabs adapter boundary

`timing/adapters/elevenlabs.py` is a **pure function over provider response
data** — no network, no generation. It accepts the documented response shapes:

1. Character alignment (`alignment` / `normalized_alignment` with
   `characters`, `character_start_times_seconds`, `character_end_times_seconds`)
   — as returned by the text-to-speech "with-timestamps" endpoints.
2. A pre-grouped word list in seconds or explicit milliseconds.

It converts to milliseconds, groups characters into words on whitespace, strips
provider keys, and validates the result. Adding another provider means adding a
module with `normalize(response, audio_duration_ms=None) -> canonical` and
registering it in `timing/adapter.py`.

## Caching with the voice asset

For `assets/audio/voice/narration.mp3` the cache is the sibling
`narration.word-timings.json`:

```python
from timing import cache
doc = cache.load_cached("assets/audio/voice/narration.mp3")  # no provider call
cache.write_for_voice(voice_path, doc)                        # refuses to overwrite
```

- `write_for_voice` raises `FileExistsError` unless `overwrite=True`.
- `load_cached` reads locally; it never touches the provider (enforced by a test).
- Timing is generated once, then reused by captions, review, and rerenders.

## Captions / phrase grouping

`timing/phrases.py` exposes `group(words, …)` and `to_captions(words, …)`,
returning `[{start_ms, end_ms, text, word_count}]` built from real word
boundaries (pause > `max_gap_ms`, sentence punctuation, `max_chars`,
`max_duration_ms`, `max_words`). It does not redesign caption rendering; the
composition layer consumes the ranges.

## How review consumes timings

`review/analyzer.py` gains a read-only caption-sync check:

- Finds timings in this order: `<project>/word-timings.json`, then any
  `assets/**/*.word-timings.json` (the voice-asset cache).
- Finds caption timing in `captions.json` (project root or `assets/`) or from
  `data-role="caption"` elements (`data-start` / `data-duration`).
- For each caption it measures against the overlapping spoken words:
  - **begins materially before speech** → `lead = first_word.start_ms − caption.start_ms`
  - **ends before the spoken phrase ends** → offset `= caption.end_ms − last_word.end_ms`
- Tolerance: `caption_sync_tolerance_ms` (default **150 ms**) in
  `review/rules/defaults.json`.
- Findings use the existing `caption_audio_sync` category with `unit:
  "milliseconds"` and `source: "word-timings+captions"`, so they validate
  against the existing `proposal_schema.py`. No second reviewer/proposal layer.

Measured fact (offset in ms) stays separate from AI judgment (whether to fix it).

## Missing-timestamp behavior

- No timings → `caption_audio_sync` stays **unavailable**; no finding.
- Timings but no captions → **unavailable**.
- Malformed/invalid timings → **unavailable** with the validation error; never
  partially trusted, never inferred.
- A caption with no overlapping speech is skipped (not a fabricated finding).

## Tests

```bash
python3 -m unittest discover -s timing/tests -v
python3 -m unittest discover -s review/tests -v
```

Timing: valid ElevenLabs alignment normalizes; malformed rejected; negative /
end-before-start / beyond-duration / ordering / overlap rejected; round-trip;
cache reuse without a provider call; phrase grouping on real boundaries;
caption validation. Review: caption ending early; caption beginning early;
aligned captions produce nothing; tolerance; unavailable without timings;
malformed timings unavailable; skipped non-overlapping caption; read-only
analysis; no provider call. All fixtures are JSON mocks of the documented
response shape — **no paid API call is made**.

## Future provider adapters

Add `timing/adapters/<provider>.py` with `normalize(...)` and register it. The
renderer and review consume only the canonical format, so no downstream change
is required.
