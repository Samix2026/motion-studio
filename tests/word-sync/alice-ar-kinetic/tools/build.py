#!/usr/bin/env python3
"""Build the Alice Arabic kinetic-caption POC from cached word timings.

Deterministic, offline. Reads narration.word-timings.json (the cache beside the
voice asset), groups phrases with the existing timing/phrases logic, writes
phrase-groups.json, and generates an isolated HyperFrames composition
(index.html). It never calls a provider and never estimates timing.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(_ROOT)))
sys.path.insert(0, _REPO)

from timing import cache, phrases  # noqa: E402

PROJECT = _ROOT
VOICE = os.path.join(PROJECT, "narration.mp3")
TIMINGS = os.path.join(PROJECT, "word-timings.json")
PHRASES = os.path.join(PROJECT, "phrase-groups.json")
INDEX = os.path.join(PROJECT, "index.html")

DURATION_MS = 10913  # audio length (ffprobe), used for composition duration

# Product names that must never be split across caption groups (multi-word
# names are protected by construction with max_words=5 below, then asserted).
PROTECTED = ["OpenAI", "Claude Code", "Gemini", "HUMAIN Cloud"]
HIGHLIGHT = [("Claude Code", "Claude Code"), ("HUMAIN Cloud", "HUMAIN Cloud"),
             ("OpenAI", "OpenAI"), ("Gemini", "Gemini")]


def _ms(ms: int) -> float:
    return round(ms / 1000.0, 3)


def build_groups(words):
    caps = phrases.to_captions(words, max_words=5, max_chars=42,
                               max_gap_ms=400, max_duration_ms=4000)
    phrases.validate_captions(caps)
    groups = caps["captions"]
    texts = [g["text"] for g in groups]
    for name in PROTECTED:
        assert any(name in t for t in texts), "product name split: %s" % name
    for g in groups:
        assert 2 <= g["word_count"] <= 5, "phrase size out of range: %r" % g
    return caps


def _highlight(text: str) -> str:
    out = html.escape(text, quote=False)
    for _find, label in HIGHLIGHT:
        # Word boundaries must not require an ASCII boundary on the left: Arabic
        # prefixes (e.g. "وClaude") attach directly to the Latin name.
        out = re.sub(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(label),
                     '<span class="hl">%s</span>' % label, out)
    return out


def build_index(groups):
    divs, script = [], []
    for i, g in enumerate(groups, 1):
        s, e = _ms(g["start_ms"]), _ms(g["end_ms"])
        divs.append(
            '        <p class="phrase" id="p%d"><span class="txt">%s</span></p>'
            % (i, _highlight(g["text"])))
        if i == 1:
            # first phrase is partially revealed at frame 0 (content at 0s),
            # then settles from the right like the later phrases.
            script.append('      tl.fromTo("#p1", { opacity: 0.55, x: 60 }, '
                          '{ opacity: 1, x: 0, duration: 0.4, ease: "power3.out" }, 0);')
        else:
            script.append('      MS.enter.rtlSlide(tl, "#p%d", %s, { distance: 140, duration: 0.4 });'
                          % (i, s))
        if i < len(groups):
            nxt = _ms(groups[i]["start_ms"])
            fade = max(0.05, min(0.3, round(nxt - e, 3)))
            script.append('      MS.exit.fadeOut(tl, "#p%d", %s, { duration: %s });'
                          % (i, e, fade))
            script.append('      tl.set("#p%d", { opacity: 0 }, %s);' % (i, nxt))

    return TEMPLATE.replace("__DURATION__", "%.3f" % (DURATION_MS / 1000.0)) \
                   .replace("__PHRASES__", "\n".join(divs)) \
                   .replace("__TIMELINE__", "\n".join(script))


TEMPLATE = """<!doctype html>
<!--
  Alice Arabic kinetic-caption POC (isolated test project).
  Word timings: ElevenLabs alignment via timing/ (real provider data).
  Captions: timing/phrases groups, one phrase at a time, RTL, 16:9.
  Motion: lib/motion.js helpers on one paused GSAP timeline.
-->
<html lang="ar" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>Alice AR kinetic captions - POC</title>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <script src="lib/motion.js"></script>
    <link rel="stylesheet" href="lib/type.css" />
    <link rel="stylesheet" href="lib/grammar.css" />
    <style>
      @font-face {
        font-family: "IBM Plex Sans Arabic";
        src: url("assets/fonts/IBMPlexSansArabic-Regular.ttf") format("truetype");
        font-weight: 400; font-display: block;
      }
      @font-face {
        font-family: "IBM Plex Sans Arabic";
        src: url("assets/fonts/IBMPlexSansArabic-Medium.ttf") format("truetype");
        font-weight: 500; font-display: block;
      }
      @font-face {
        font-family: "IBM Plex Sans Arabic";
        src: url("assets/fonts/IBMPlexSansArabic-Bold.ttf") format("truetype");
        font-weight: 700; font-display: block;
      }
      :root {
        --brand-background: #0b0b0d;
        --brand-background-gradient: radial-gradient(120% 90% at 50% 42%, #16161a 0%, #0d0d10 55%, #0b0b0d 100%);
        --brand-text: #f5f3ef;
        --brand-primary: #d97757;
        --brand-highlight-color: #e0925f;
        --ms-font: "IBM Plex Sans Arabic", sans-serif;
      }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: var(--brand-background); }
      #root {
        position: relative; width: 1920px; height: 1080px; overflow: hidden;
        font-family: var(--ms-font); background: var(--brand-background-gradient);
      }
      #cap { position: absolute; inset: 0; overflow: hidden; }
      .cap-wrap { position: absolute; inset: 0; direction: rtl; }
      .phrase {
        position: absolute; inset: 0; display: flex;
        align-items: center; justify-content: center;
        direction: rtl; text-align: center; padding: 0 170px;
        font-family: var(--ms-font); font-weight: 500;
        font-size: 78px; line-height: 1.35; letter-spacing: -0.01em;
        color: var(--brand-text); will-change: transform, opacity;
      }
      .phrase .txt { display: block; width: 100%; text-align: center; }
      .hl { color: var(--brand-highlight-color); }
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-format="landscape"
      data-start="0"
      data-duration="__DURATION__"
      data-fps="30"
      data-width="1920"
      data-height="1080"
    >
      <audio id="nar" src="narration.mp3" data-start="0" data-duration="__DURATION__" data-volume="1"></audio>

      <section id="cap" class="clip" data-start="0" data-duration="__DURATION__"
               data-track-index="1" data-narration-locked="true">
        <div class="cap-wrap">
__PHRASES__
        </div>
      </section>
    </div>

    <script>
      const tl = gsap.timeline({ paused: true });
__TIMELINE__
      MS.applyReviewAttributes(tl);
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def main() -> int:
    doc = cache.load_cached(VOICE)
    if doc is None:
        print("no cached word timings beside %s" % VOICE)
        return 1
    with open(TIMINGS, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    caps = build_groups(doc["words"])
    with open(PHRASES, "w", encoding="utf-8") as fh:
        json.dump(caps, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    # canonical caption doc for the review layer (same ranges as phrase-groups)
    with open(os.path.join(PROJECT, "captions.json"), "w", encoding="utf-8") as fh:
        json.dump(caps, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(build_index(caps["captions"]))
    print("words=%d groups=%d" % (len(doc["words"]), len(caps["captions"])))
    for g in caps["captions"]:
        print("  %5d-%5d  w=%d  %s" % (g["start_ms"], g["end_ms"], g["word_count"], g["text"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
