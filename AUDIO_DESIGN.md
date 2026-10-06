# AUDIO_DESIGN.md — contextual audio for Arabic motion-graphics videos

This document owns the Motion Studio audio rule (§0) and defines how a video
whose brief requests audio plans and uses it, so that sound supports the visual
action.

It uses only standard tools already in the stack: HyperFrames `<audio>` elements,
GSAP volume tweens, ordinary audio files (WAV/MP3/AAC), and FFmpeg for the final
mix. There is no custom audio engine.

## 0. Silent by default (global rule)

**Motion Studio videos are silent by default.** No music, sound effects,
ambience, narration, or audio stream may be added unless the video's `BRIEF.md`
explicitly requests audio.

- A silent video has no `<audio>` element, no audio in `assets/audio/`, and
  **0 audio streams** in the final MP4:
  `ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 <mp4>`
  prints nothing.
- Source footage is used muted; its audio track is never carried into the render.
- A request names what is wanted (for example "Audio: SFX on reveals" or
  "Narration: required"). A request for one kind does not authorize the others.
- Unrequested audio in the final output is a hard fail (`QUALITY_SCORE.md`).
- §1–§10 apply **only** to projects whose brief requests audio.

## 1. Principle

**Audio must support the visual action. Every important sound has a reason.**

- Sound is triggered by something visible (a card appears, a diagram connects,
  a chart updates), not by the passage of time alone.
- If you cannot name the visual event and the purpose, do not add the sound.
- Prefer a few well-placed cues over continuous sound design.

## 2. Sound vocabulary

| Visual event | Cue type | Example sound |
|--------------|----------|---------------|
| Terminal / code typing | `keyboard` | key presses, carriage return, terminal confirm |
| UI card / chip / selection | `click` | subtle click, soft tap, interface confirm |
| Scene transition / in-out | `whoosh` | light whoosh, soft sweep |
| Number / result / reveal | `impact` | soft hit, short emphasis (not a trailer boom) |
| AI / cybersecurity / scanning | `digital` | digital pulse, scan sweep, processing tone |
| Vehicles / robotics | `ambient` | low mechanical or road ambience, when useful |
| Data / charts | `tick` | only when synchronized with a visible change |
| Background | `music` | low-volume bed, style matched to subject |

Combinations are allowed when justified, e.g. `keyboard + low music`,
`whoosh → impact`.

## 3. Do not use

- Loud cinematic trailer effects.
- Excessive or stacked whooshes.
- Repetitive clicks or loops that draw attention to themselves.
- Random electronic sounds.
- Sounds unrelated to a visible action.
- Music that fights the SFX or the on-screen text.

## 4. Background music

Optional. Use only when it improves pacing and continuity.

- Keep it low and unobtrusive; it must never overpower SFX.
- It must never reduce readability or distract from the content.
- Match the style to the subject; avoid dramatic music for ordinary tech news.
- Duck or reduce the bed around important cues (see §8).
- Music **must** come from a source that permits the intended use (see
  `ASSET_POLICY.md`). Track its provenance in `sources.md`.
- If suitable licensed music is unavailable, use **no music** — never an asset
  with unclear licensing.

## 4a. Sourcing priority (SFX vs music)

1. **Contextual SFX** — prefer **ElevenLabs Sound Effects** when a custom sound
   is needed (e.g. a specific UI confirmation). Generate exactly one request at
   a time, keep cues minimal, and do not add a second SFX generation retry.
2. **Background music** — prefer **curated licensed music from trusted sources**
   such as **Pixabay** or **Mixkit**.
3. **Do not use the ElevenLabs Music API while the account is on the free
   plan.** It returns `402 paid_plan_required`; the account is free-tier.
4. **Do not upgrade solely for music** unless repeated tests show a clear quality
   advantage worth the subscription.
5. **Track every audio source and its license in `sources.md`** — curated or
   generated (see `ASSET_POLICY.md`). ElevenLabs-generated audio is allowed under
   its terms; record the prompt/model basis.

Verified `2026-09-13` (read-only probes + one SFX generation, no retries):
ElevenLabs Sound Effects = available (`200`, `audio/mpeg`); ElevenLabs Music =
blocked (`402`, free plan). Tier and remaining credits could not be read because
the key lacks the `user_read` scope.

## 5. Storyboard integration

When the brief requests audio, every scene/beat in `storyboard.md` includes an
**Audio cue** block (in a silent project the storyboard states `Audio cue: none`
once, or per scene):

```
Audio cue:
- type: keyboard + low music        # keyboard | click | whoosh | impact | digital | ambient | tick | music | none | combination
- trigger: during command typing    # the visible action that fires it
- at: 12.2s                         # approximate absolute timestamp
- duration: 1.4s
- purpose: reinforce the typing action
- intensity: subtle                 # subtle | audible | emphasis | very-subtle
- source: assets/audio/sfx/keyboard-typing.mp3   # asset (or TBD)
```

Use `type: none` when a scene of an audio project should stay silent.

## 6. Audio timeline workflow

```
script → storyboard → visual motion plan → audio cue plan
       → build → audio synchronization → validation → final mix → MP4
```

Synchronize significant motion events (and only those):

| Motion event | Typical cue |
|--------------|-------------|
| Card / chip appears | `click` |
| Headline lands | `impact` (light) |
| Terminal types | `keyboard` |
| Diagram connects | `digital` |
| Scene exits / enters | `short whoosh` |

Do not over-sync every minor animation. One cue per meaningful beat is usually
enough.

## 7. HyperFrames audio pattern

Use standard HyperFrames media elements. Key rules (see
`hyperframes-core/references/variables-and-media.md`):

- A `<video>` is always `muted`; its sound lives on a **separate** `<audio>`.
- Every `<audio>` needs an **`id`** (the mixer selects `audio[id][src]`).
- Never add `crossorigin`.
- Never call `.play()`, `.pause()`, or seek in composition code.
- Place cues with `data-start` / `data-duration` and a static `data-volume`
  baseline.

```html
<!-- cue at 12.2s, lasts 1.4s -->
<audio id="sfx-keyboard" src="assets/audio/sfx/keyboard-typing.mp3"
       data-start="12.2" data-duration="1.4" data-volume="0.6"></audio>

<!-- low music bed across the whole piece -->
<audio id="music-bed" src="assets/audio/music/low-tech-bed.mp3"
       data-start="0" data-duration="60" data-volume="0.12"></audio>
```

Ducking / fades: animate `volume` on the timeline. A tween's value **replaces**
the `data-volume` baseline rather than scaling it, so author the tween targets
accordingly.

```js
// dip the bed under a cue, then restore (finite, seek-safe)
tl.to("#music-bed", { volume: 0.05, duration: 0.4, ease: "power2.out" }, 12.0);
tl.to("#music-bed", { volume: 0.12, duration: 0.6, ease: "power2.in" }, 13.6);
```

HyperFrames mixes these clips during render. It does not normalize loudness or
do advanced ducking, so use FFmpeg (§8) for the final mix when needed.

## 8. FFmpeg final mix

Use FFmpeg for final assembly, offsets, ducking, loudness normalization, and
limiting. Keep the video stream untouched (`-c:v copy`) unless it also changes.

Plain mix with offsets and a music bed:

```bash
ffmpeg -y -i video.mp4 \
  -i assets/audio/sfx/keyboard-typing.wav \
  -i assets/audio/sfx/ui-click.wav \
  -i assets/audio/music/low-tech-bed.mp3 \
  -filter_complex "\
    [1:a]volume=0.6,adelay=12200|12200[k];\
    [2:a]volume=0.5,adelay=3000|3000[c];\
    [3:a]volume=0.12,afade=t=in:st=0:d=1,afade=t=out:st=58:d=2[m];\
    [k][c][m]amix=inputs=3:duration=longest:normalize=0[mix];\
    [mix]alimiter=limit=-1dB:level=false,aresample=48000[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k -shortest out.mp4
```

Music ducking under a cue with a sidechain compressor:

```bash
ffmpeg -y -i video.mp4 -i music.wav -i sfx.wav -filter_complex \
  "[1:a][2:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=250[ducked];\
   [ducked][2:a]amix=inputs=2:normalize=0[aout]" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac out.mp4
```

Loudness normalization for a delivery master:

```bash
ffmpeg -y -i mixed.mp4 -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:v copy -c:a aac mixed-norm.mp4
```

Requirements for the final MP4:

- H.264 video, **AAC** audio, **48 kHz** preferred, stereo unless mono is more
  appropriate.
- No clipping (true peak ≤ −1 dBTP), no unintended silence/cutoffs.
- **Audio duration must equal video duration** (`-shortest` or explicit trims).

Verify the audio stream and duration with `ffprobe`:

```bash
ffprobe -v error -select_streams a:0 \
  -show_entries stream=codec_name,sample_rate,channels,channel_layout \
  -show_entries format=duration -of default=noprint_wrappers=1 renders/video.mp4
```

## 9. Levels (documented defaults)

Levels are **relative**; normalize each source before mixing and never hardcode
one loudness for every asset.

| Layer | Default | Notes |
|-------|---------|-------|
| Ambient | ≈ −30 dBFS | barely audible; never competes |
| Music bed | ≈ −26 to −22 dBFS | duck 4–6 dB under cues |
| Contextual SFX | peak ≈ −16 to −12 dBFS | clearly audible, not aggressive |
| Important impact | peak ≈ −10 to −7 dBFS | slightly stronger than normal SFX |
| Final true peak | ≤ −1 dBTP | prevent clipping |

Guidelines: normalize assets toward a common reference (e.g. −18 dBFS RMS)
before mixing; give every cue a 10–30 ms fade to avoid clicks; fade music in/out
over 0.5–2 s; keep the whole mix below the ceiling.

## 10. Quality checks (audio)

- Sound matches a visible action.
- No unnecessary SFX; no repetitive effects.
- Timing is synchronized with the motion.
- Music is not too loud and does not reduce readability.
- No clipping; no abrupt cuts or dropouts.
- No missing audio assets.
- All external audio sources documented in `sources.md` (filename, source URL,
  creator/provider, license/usage, scene).
- Final MP4 contains the expected audio stream (when audio was planned).
- Audio duration matches video duration.

These feed the Technical validation category in `QUALITY_SCORE.md`. A silent
video (the default, §0) can score full marks; the only audio check it needs is
0 audio streams.
