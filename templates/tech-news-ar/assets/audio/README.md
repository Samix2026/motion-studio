# Audio assets

Place audio here only when the video's brief requests it. Videos are silent by
default (`../../../../AUDIO_DESIGN.md` §0); when audio is requested, use it only
when it supports the visual action.

```
assets/audio/
  sfx/       # short cues: keyboard, click, whoosh, impact, digital, tick
  music/     # low-volume background beds (optional)
  ambient/   # very subtle room / mechanical / road beds (optional)
```

## Rules

- **Naming:** kebab-case, descriptive, with the cue family
  (`sfx/keyboard-typing.wav`, `sfx/ui-click-soft.wav`,
  `music/low-tech-bed.mp3`, `ambient/room-tone-quiet.wav`).
- **Formats:** WAV for short SFX (clean edits), MP3/AAC for music beds.
  48 kHz target for the final mix.
- **One cue, one purpose.** Do not ship loops that play continuously "just in
  case".
- **License required.** Only use audio that permits the intended use (CC0 /
  public domain / a royalty-free license with clear terms, or original audio you
  own). Do not include copyrighted audio without a clear license.
- **Track provenance.** Record every external audio file in the project's
  `sources.md`: filename, source URL, creator/provider, license/usage status,
  and the scene where it is used.
- **If unclear, do not use it.** Prefer no music over an asset with unclear
  licensing.
- **Normalize before mixing.** Levels are relative; see `AUDIO_DESIGN.md` §9.
- Keep this template directory's `.gitkeep` files; do not commit large audio
  libraries into the template (put project-specific audio in the project's own
  `assets/audio/`).

## Wiring cues

Standard HyperFrames pattern (no custom engine):

```html
<audio id="sfx-click" src="assets/audio/sfx/ui-click-soft.wav"
       data-start="8.2" data-duration="0.3" data-volume="0.5"></audio>
```

See `AUDIO_DESIGN.md` §7 for volume automation and §8 for the FFmpeg final mix.
