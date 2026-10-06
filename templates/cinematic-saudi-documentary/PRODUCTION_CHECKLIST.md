# PRODUCTION_CHECKLIST.md — cinematic Saudi documentary run sheet

Run every item in order for each project made from
`templates/cinematic-saudi-documentary/`. Each step has a pass condition; a
failed step stops the run — do not skip forward to compensate.

Template source of truth: `TEMPLATE_RULES.md`, `VISUAL_SYSTEM.md`,
`COLOR_GRADE.md`, `AUDIO_PROFILE.md`, `components/`. Global rules:
`../../VIDEO_WORKFLOW.md`, `../../CONTENT_RULES.md`, `../../ASSET_POLICY.md`,
`../../AUDIO_DESIGN.md`.

---

## 1 · Asset gate  →  `asset-checkpoint.md`

- [ ] Copy `asset-checkpoint-template.md` into the project as
      `asset-checkpoint.md`.
- [ ] One row per candidate asset, every column answered (no `TBD`).
- [ ] `cinematic quality` is never `weak`.
- [ ] **8–18 passing assets.** Story decides the count inside the range —
      never pad to reach a number.
- [ ] Every narrative beat (past / identity / people / transformation /
      present / future / closing) has a passing asset.
- [ ] Still assets are ≥ 4K so a 3–6% push stays sharp.
- [ ] **Pass:** ≥ 8 passing AND every beat covered. **Fail:** stop, go back to
      sourcing. Do not lower the bar, do not add a passing-but-unneeded asset.

## 2 · License verification

- [ ] Every asset's license is recorded in `sources.md` (file, type, source
      page, direct asset URL, license, author, resolution).
- [ ] No unlicensed/unclear asset, no AI-generated image, no watermarked comp
      in anything beyond internal evaluation.
- [ ] CC BY-SA assets are flagged as ShareAlike and reviewed before any
      production master (`../../ASSET_POLICY.md`).
- [ ] Every borrowed asset has an adjacent on-screen credit
      (`components/source-credit.md`).
- [ ] **Pass:** every file in `assets/` appears in `sources.md` and vice versa.

## 3 · Narrative map  →  `narrative.md`

- [ ] 10–15 short MSA sentences, one idea each, no tashkeel, no filler, no
      repetition, no generic motivational phrasing (`TEMPLATE_RULES.md` §2).
- [ ] Progression reads as a story (past → identity → people →
      transformation → present → future → closing), not a fact list.
- [ ] **Pass:** every sentence is one visual beat, with nothing on screen that
      the assets and known facts do not support.

## 4 · Shot map  →  `storyboard.md` / scene map

- [ ] One row per sentence: time, your scene id, the sentence, asset,
      Ken Burns move, transition in/out, audio cue, brand-frame element.
- [ ] Durations sum to the target length; no gap, no overlap error.
- [ ] Exactly the 3 transition families are used — hard cut, short dissolve
      (≤ 0.6s, one narrative pivot), sound-led (`TEMPLATE_RULES.md` §5).
- [ ] Ken Burns per still is one continuous move, 3–6%, no mid-shot direction
      change (`TEMPLATE_RULES.md` §4).
- [ ] At most one of {section title, lower third} animates at a time.
- [ ] **Pass:** the map can be built from the components without inventing a
      new effect per scene.

## 5 · Color correction table

- [ ] Copy the Stage A values into the scene map's per-shot correction column
      (`COLOR_GRADE.md` §Stage A, `scene-map-example.md`).
- [ ] Every value is inside the Stage A ranges (brightness 0.9–1.12, contrast
      0.95–1.08, saturate 0.9–1.05, sepia 0–0.08, hue-rotate ±6°).
- [ ] Values are **not** identical across all shots — per-shot means per-shot;
      an uncorrected shot keeps neutral defaults.
- [ ] Skin-tone shots: hue-rotate within ±6°, checked after Stage A and after
      Stage B.
- [ ] Flag-forward shots: no hue-rotate/duotone; `.is-flag-safe` on the root
      lightens the Stage B shadow overlay.
- [ ] Stage B applied exactly once, on `#root`
      (`components/color-grade.css`), never per scene.
- [ ] **Pass:** mixed sources read as one piece; no shot's correction is
      visible as its own effect.

## 6 · Audio plan

- [ ] Silent by default (`../../AUDIO_DESIGN.md` §0): unless the brief requests
      audio, every scene is `type: none`, there is no `<audio>`, and the render
      has 0 audio streams. The items below apply only when audio is requested.
- [ ] Scene map carries an Audio cue block per scene, restricted to the
      `AUDIO_PROFILE.md` vocabulary (or `type: none`).
- [ ] 3–6 cues total for a 35–45s cut; no cue without a visible trigger.
- [ ] Every external audio file is licensed and recorded in `sources.md`.
- [ ] Music: one restrained bed preferred; **no unlicensed patriotic melody**;
      if nothing licensed and high-quality exists, use no music.
- [ ] Wiring follows `../../AUDIO_DESIGN.md` §7–§9 (video muted + separate
      `<audio>`, no `crossorigin`, FFmpeg final mix, ≤ −1 dBTP, audio = video).
- [ ] **Pass:** deliberate silence is valid and documented; an unjustified cue
      is a fail.

## 7 · Contact sheet

- [ ] After the preview render, export one frame at each scene midpoint.
- [ ] Review at phone scale: RTL order, no clipped/overflowing text, hierarchy
      holds, imagery dominant, one chrome element at a time, no card look.
- [ ] **Pass:** every frame is legible and the chrome never competes with the
      image.

## 8 · Lint / check / tashkeel

- [ ] `python3 tools/check-tashkeel.py .` → 0 marks.
- [ ] `npx hyperframes@0.8.35 lint .` → 0 errors / 0 warnings.
- [ ] `npx hyperframes@0.8.35 check . --at <scene midpoints> --snapshots` → 0 errors /
      0 warnings / 0 layout issues.
- [ ] `npx hyperframes@0.8.35 render` output verified with `ffprobe`: codec, 1920×1080,
      30 fps, intended frame count/duration, 0 audio streams unless the brief requested audio.
- [ ] **Pass:** all four clean. Fix before proceeding.

## 9 · Final review gate

- [ ] Run the post-preview review (`python3 review/cli.py review <project>`);
      inspect every finding.
- [ ] No rendered-freeze findings in imagery-led scenes (supporting chrome may
      hold; the frame must not be static for long stretches unless intended).
- [ ] Confirm no hard fail (`QUALITY_SCORE.md`): verified facts, attribution
      present, every asset tracked, no tashkeel, RTL correct, no clipped text,
      correct names, validation clean, output matches spec.
- [ ] Human creative/technical approval recorded before any final master.
- [ ] Publication metadata set by hand only, after a human publishes.
- [ ] **Pass:** `ready_to_publish` is true only with the human gate recorded;
      below the bar or any hard fail → do not publish.

---

## Quick command block

```bash
# from the project root, after copying starter/
python3 tools/check-tashkeel.py .
npx hyperframes@0.8.35 lint .
npx hyperframes@0.8.35 check . --at 1.8,5.4,9.0,12.6 --snapshots
npx hyperframes@0.8.35 render . --skill=motion-graphics -q high -f 30 -o ./renders/preview.mp4
python3 ../../review/cli.py review .
```
