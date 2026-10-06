# REFERENCE_ANALYZER.md — reference style analysis (V1)

Extracts **abstract style metadata** from reference material so planning can aim
at a visual/pacing register. It describes style; it never reproduces content.

It never copies scripts, wording, scene order, shot sequence, logos, branding,
signature characters, unique compositions, or any asset, and it never generates
assets from the reference. It does not touch a video project or a brand profile.

## Pipeline position

```
Reference Input → Reference Analyzer → (style metadata)
    → Script / Storyboard → Asset Plan → Cost Gate → … → Review
```

Style metadata is **optional context for planning only**. It never overrides
factual accuracy, source attribution, Arabic RTL rules, the no-tashkeel policy,
or brand-specific requirements.

## Layout

```
reference/
  schema.py      # profile validation; observed/inferred whitelists
  analyzer.py    # orchestration + inference rules + save/report
  video.py       # ffprobe/ffmpeg measurement (pure parse functions)
  images.py      # image-set header parsing (stdlib)
  cli.py         # analyze | show | list
  profiles/      # <reference_id>.json
  reports/       # <reference_id>.md
  tests/
```

stdlib only; local `ffprobe`/`ffmpeg` are used when present. No CV/ML deps, no
network.

## Supported inputs (V1)

| Input | How | What is measured |
|---|---|---|
| Local video file | `ffprobe` + optional `ffmpeg` scene detection | duration, dimensions, fps, aspect ratio, audio presence, integrated loudness, cut count, avg scene duration, first cut, cut density |
| Local image / screenshot set | header parsing (PNG/JPEG/GIF/BMP) | image count, dominant aspect ratio, representative dimensions |
| Manual observations | `--manual observations.json` | whitelisted `observed` values + whitelisted `inferred` traits |

Channel/video URL support is **not** in V1 (no scraping, no network fetching).

## Observed vs inferred

`observed` holds measured facts (or values explicitly provided by the user).
`inferred` holds interpretation. They never share keys, and the schema rejects
unsupported fields — which is also why there is no field for scripts, wording,
logos, or branding.

```json
{
  "schema_version": 1,
  "reference_id": "sample-1a2b3c4d",
  "source_type": "video",
  "observed": {
    "duration_seconds": 34.2, "scene_count": 12,
    "average_scene_duration": 2.85, "cut_density": "high",
    "dominant_aspect_ratio": "16:9", "audio_present": true
  },
  "inferred": {
    "pacing": "fast", "hook_speed": "fast",
    "layout_style": null, "camera_motion": null,
    "transition_style": null, "headline_scale": null,
    "secondary_scale": null, "contrast": null,
    "music_energy": null, "sfx_density": null, "content_pattern": null
  },
  "unavailable": [
    {"field": "text_density", "reason": "not measured offline in V1"},
    {"field": "layout_style", "reason": "not measurable offline in V1; provide via --manual"}
  ]
}
```

**Measurable offline in V1:** aspect ratio, duration, rough scene/cut density,
average scene duration, first-cut timing, dominant pacing, hook speed,
audio presence, integrated loudness.

**Not measurable offline in V1** (stay `unavailable` unless provided manually,
never guessed): text density, layout style, camera motion, transition style,
headline/secondary scale, contrast/palette behaviour, music energy, SFX
density, content flow pattern.

### Deterministic thresholds

- pacing: `avg_scene_duration < 2.5 s` → fast; `< 5.0 s` → moderate; else slow.
- hook speed: `first_cut < 1.5 s` → fast; `< 3.0 s` → moderate; else slow.
- cut density: `≥ 20 cuts/min` → high; `≥ 8` → medium; else low.

## What it intentionally does not copy

Scripts, wording, transcripts, captions, exact scene order, shot sequence,
logos, watermarks, channel/brand names, signature characters, and unique
compositions. Manual input is **whitelisted**, so fields like `script`,
`transcript`, `logo`, `brand`, `channel`, or `watermark` are dropped. Tests
assert this.

## How style profiles are consumed

- Saved to `reference/profiles/<reference_id>.json` with a human report in
  `reference/reports/<reference_id>.md`.
- Optional planning context read by a person/agent when writing
  `storyboard.md`/`script.md` for a project.
- They do **not** modify `brands/*.json`, do **not** auto-apply to a project,
  and are **not** a quality-defect source. `review/analyzer.py` does not read
  them; a future Review V2 may surface them as non-scoring context only.

## CLI

```bash
python3 reference/cli.py analyze <path> [--id ID] [--no-scene-detection]
python3 reference/cli.py analyze --manual reference/tests/fixtures/manual_observations.json
python3 reference/cli.py show <reference_id>
python3 reference/cli.py list
```

Analysis is read-only for everything except `reference/profiles` and
`reference/reports`.

## Limitations (V1)

- No channel/URL support; no scraping, no network.
- Scene/cut detection relies on `ffmpeg` scene scores; when ffmpeg is absent or
  the file is unsupported, scene metrics are marked `unavailable` (never
  guessed).
- No OCR, so text density is unavailable unless provided manually.
- Music vs SFX classification is not attempted; only loudness is measured.
- Image header parsing covers PNG/JPEG/GIF/BMP; other formats are skipped.
- Deterministic thresholds are documented heuristics, not provider truth.

## Future channel/video URL support

Add a fetch layer behind an explicit opt-in flag, keep the analyzer offline by
default, and normalize provider metadata into the same `observed` whitelist.
Any network capability must be added deliberately and documented; V1
intentionally has none.
