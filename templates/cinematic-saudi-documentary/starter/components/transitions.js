/*
  components/transitions.js — the three transition families, and nothing else.

  Spec: ../TEMPLATE_RULES.md §5. Exactly three families exist:
    1. hard cut            — the default between beats;
    2. short dissolve      — one narrative pivot per cut, <= 0.6s;
    3. sound-led transition — a hard cut riding a whoosh/ambient swell.

  Load order (required):
    gsap  ->  lib/motion.js  ->  components/transitions.js

  Deterministic only: finite tweens, no clocks, no randomness. Transitions
  animate opacity/transform only, never layout properties.

  sound-led: HyperFrames owns audio playback, so the cue is a normal
  <audio id="..." data-start="..."> element placed at the same time as the
  visual cut (../../AUDIO_DESIGN.md §7). soundLed() places the visual cut and
  reports the pairing; it never touches the audio element.
*/
(function (root) {
  "use strict";

  var DISSOLVE_MAX = 0.6; // TEMPLATE_RULES §5: short dissolve is <= 0.6s
  var FRAME_FADE = 0.35; // quick frame fade on a cut where the previous scene was not full-bleed

  function num(value, fallback) {
    var n = parseFloat(value);
    return isNaN(n) ? fallback : n;
  }

  // hard cut — the clip boundary is the transition; the incoming frame is simply present
  function hardCut(tl, target, at) {
    tl.set(target, { opacity: 1 }, at);
  }

  // quick fade-in for an incoming full-bleed frame after a non-full-bleed beat
  function frameFadeIn(tl, target, at, o) {
    tl.fromTo(target, { opacity: 0 }, { opacity: 1, duration: num(o && o.duration, FRAME_FADE), ease: "power2.out" }, at);
  }

  // short dissolve — soft window straddling the cut, total length clamped to DISSOLVE_MAX.
  // The outgoing frame dims over the first half (ending at the cut); the incoming
  // frame rises over the second half (starting at the cut). Honest to the clip
  // boundaries: neither frame is animated where it is not on screen.
  function shortDissolve(tl, fromTarget, toTarget, at, o) {
    var d = Math.min(num(o && o.duration, 0.5), DISSOLVE_MAX);
    var half = d / 2;
    tl.to(fromTarget, { opacity: 0, duration: half, ease: "power1.in" }, at - half);
    tl.fromTo(toTarget, { opacity: 0 }, { opacity: 1, duration: half, ease: "power1.out" }, at);
    return d;
  }

  // sound-led — a hard cut riding a cue; returns the pairing for the scene map
  function soundLed(tl, target, at, o) {
    hardCut(tl, target, at);
    return { at: at, audioId: (o && o.audioId) || null };
  }

  // closing fade to black across the whole root
  function closingFade(tl, rootTarget, at, o) {
    tl.to(rootTarget, { opacity: 0, duration: num(o && o.duration, 0.6), ease: "power2.in" }, at);
  }

  root.CinTransitions = {
    hardCut: hardCut,
    frameFadeIn: frameFadeIn,
    shortDissolve: shortDissolve,
    soundLed: soundLed,
    closingFade: closingFade,
    DISSOLVE_MAX: DISSOLVE_MAX,
    FRAME_FADE: FRAME_FADE
  };
})(window);
