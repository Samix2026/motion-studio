# Word-sync fixture (`alice-ar-kinetic`)

A small HyperFrames project used by the narration, review and grammar tests
(`narration/tests`, `review/tests/test_narration_lock.py`,
`design/tests/test_grammar.py`). It is a test fixture, not a template.

- `narration.mp3` is a **synthetic placeholder**: a 220 Hz sine tone of the
  same nominal length (10.9 s) as the narration the timings were measured on,
  generated with FFmpeg for this repository:

  ```bash
  ffmpeg -f lavfi -i "sine=frequency=220:sample_rate=44100:duration=10.913" \
    -ac 1 -b:a 32k -map_metadata -1 narration.mp3
  ```

  The original text-to-speech recording is not distributed. Tests only need
  the file to exist with that duration.
- `narration.word-timings.json` / `word-timings.json` are the word-level
  timings (start/end in ms) for the Arabic script shown in `index.html`.
- `tools/build.py` rebuilds `phrase-groups.json` and `index.html` from the
  timings, offline.
- Fonts: IBM Plex Sans Arabic, SIL OFL 1.1 (`assets/fonts/OFL.txt`).
