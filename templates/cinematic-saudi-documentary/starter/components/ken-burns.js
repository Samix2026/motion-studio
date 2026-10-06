/*
  components/ken-burns.js — one reusable Ken Burns module for stills.

  Spec: ../components/ken-burns-still.md · rules: ../TEMPLATE_RULES.md §4.
  Wraps MS.camera.pushIn from lib/motion.js (the shared primitive) instead of
  introducing a second motion engine.

  Load order (required):
    gsap  ->  lib/motion.js  ->  components/ken-burns.js

  Deterministic only: no clocks, no randomness, no async, finite tweens.
  Every move is a single continuous transform tween with ease "none" — a Ken
  Burns move must not accelerate or decelerate like a UI tween.

  Band (TEMPLATE_RULES §4): scale 1.03–1.06, lateral travel <= 3% total.
  Values outside the band are clamped to the nearest legal value rather than
  silently producing an aggressive move.

  Attribute form (the frame needs an id; motion targets its img/video):
    <figure class="cine-frame" id="s1frame" data-kb="push-in" data-kb-amount="1.04">
      <img src="assets/<file>" alt="" data-layout-allow-overflow />
    </figure>
  data-kb:      push-in | pull-out | lateral
  data-kb-amount: scale (1.03–1.06) or lateral travel percent (1–3)
  data-kb-direction: rtl (default) | ltr, lateral only
*/
(function (root) {
  "use strict";

  var SCALE_MIN = 1.03;
  var SCALE_MAX = 1.06;
  var LAT_MIN = 1;
  var LAT_MAX = 3;
  var EASE = "none";
  var ORIGIN = "50% 50%";

  function num(value, fallback) {
    var n = parseFloat(value);
    return isNaN(n) ? fallback : n;
  }
  function clamp(n, lo, hi) {
    return Math.min(hi, Math.max(lo, n));
  }
  function mediaOf(node) {
    if (!node) return null;
    if (node.tagName === "IMG" || node.tagName === "VIDEO") return node;
    return node.querySelector("img, video");
  }
  function windowOf(node) {
    var scene = node && node.closest ? node.closest(".clip") : null;
    if (!scene) return null;
    var duration = num(scene.getAttribute("data-duration"), 0);
    if (!duration) return null;
    return { at: num(scene.getAttribute("data-start"), 0), duration: duration };
  }

  // scale 1 -> amount, across the shot
  function pushIn(tl, target, at, duration, o) {
    var amount = clamp(num(o && o.amount, 1.04), SCALE_MIN, SCALE_MAX);
    MS.camera.pushIn(tl, target, at, duration, { scale: amount, origin: ORIGIN });
  }

  // scale amount -> 1, across the shot
  function pullOut(tl, target, at, duration, o) {
    var amount = clamp(num(o && o.amount, 1.04), SCALE_MIN, SCALE_MAX);
    tl.fromTo(target, { scale: amount, transformOrigin: ORIGIN }, { scale: 1, duration: duration, ease: EASE }, at);
  }

  // subtle lateral drift: +travel -> -travel (rtl) or the reverse (ltr)
  function lateral(tl, target, at, duration, o) {
    var travel = clamp(num(o && o.amount, 1.5), LAT_MIN, LAT_MAX);
    var rtl = !o || o.direction !== "ltr";
    var from = (rtl ? travel : -travel) + "%";
    var to = (rtl ? -travel : travel) + "%";
    tl.fromTo(target, { x: from }, { x: to, duration: duration, ease: EASE }, at);
  }

  // optional parallax — only when the asset genuinely separates into layers
  function parallax(tl, bgTarget, fgTarget, at, duration, o) {
    pushIn(tl, bgTarget, at, duration, { amount: clamp(num(o && o.bg, 1.06), SCALE_MIN, SCALE_MAX) });
    pushIn(tl, fgTarget, at, duration, { amount: clamp(num(o && o.fg, 1.03), SCALE_MIN, SCALE_MAX) });
  }

  // attribute-driven pass over the whole composition
  function apply(tl) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-kb]"), function (node) {
      if (!node.id) return;
      var w = windowOf(node);
      if (!w) return;
      var media = mediaOf(node);
      if (!media) return;
      var kind = node.getAttribute("data-kb");
      var amount = num(node.getAttribute("data-kb-amount"), 0) || null;
      var direction = node.getAttribute("data-kb-direction") || "rtl";
      if (kind === "pull-out") pullOut(tl, media, w.at, w.duration, { amount: amount || 1.04 });
      else if (kind === "lateral") lateral(tl, media, w.at, w.duration, { amount: amount || 1.5, direction: direction });
      else pushIn(tl, media, w.at, w.duration, { amount: amount || 1.04 });
    });
  }

  root.CinKB = {
    pushIn: pushIn,
    pullOut: pullOut,
    lateral: lateral,
    parallax: parallax,
    apply: apply,
    limits: { scaleMin: SCALE_MIN, scaleMax: SCALE_MAX, lateralMin: LAT_MIN, lateralMax: LAT_MAX, ease: EASE }
  };
})(window);
