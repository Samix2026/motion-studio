/*
  lib/motion.js — Motion Studio motion grammar + screenshot choreography.

  Adds tweens to ONE paused GSAP timeline at absolute positions (seconds).
  Deterministic and seek-safe: no randomness, no clocks, no async, finite
  tweens only. Animates transform, opacity and clip-path on DOM elements;
  it never reads, draws or modifies media pixels or source files.

  Load after GSAP with a script tag whose src is lib/motion.js.
  (Never write a closing script tag in this file: HyperFrames inlines it.)
  Registry of ids:  lib/grammars.json
*/
(function (root) {
  "use strict";

  function opt(o, key, fallback) {
    return o && o[key] !== undefined ? o[key] : fallback;
  }
  function one(target) {
    return typeof target === "string" ? document.querySelector(target) : target;
  }
  function list(target) {
    if (typeof target === "string") return Array.prototype.slice.call(document.querySelectorAll(target));
    return Array.prototype.concat(target);
  }

  // ------------------------------------------------------------ entries
  var enter = {
    // opacity 0 -> 1, scale 0.96 -> 1
    fadeScale: function (tl, target, at, o) {
      tl.fromTo(target, { opacity: 0, scale: opt(o, "scale", 0.96) },
        { opacity: 1, scale: 1, duration: opt(o, "duration", 0.6), ease: opt(o, "ease", "expo.out") }, at);
    },
    // RTL: content enters from the right (+x) toward its resting place
    rtlSlide: function (tl, target, at, o) {
      tl.fromTo(target, { opacity: 0, x: opt(o, "distance", 90) },
        { opacity: 1, x: 0, duration: opt(o, "duration", 0.7), ease: opt(o, "ease", "power4.out"),
          stagger: opt(o, "stagger", 0) }, at);
    },
    // RTL wipe: the left inset shrinks, so the reveal travels right -> left.
    // o.start (0..1) = share already revealed at `at` (frame-0 hooks use > 0).
    maskReveal: function (tl, target, at, o) {
      var hidden = Math.round((1 - opt(o, "start", 0)) * 100);
      tl.fromTo(target, { clipPath: "inset(0% 0% 0% " + hidden + "%)" },
        { clipPath: "inset(0% 0% 0% 0%)", duration: opt(o, "duration", 0.8), ease: opt(o, "ease", "power3.out") }, at);
    },
    // items appear one by one in DOM order (= reading order in RTL markup)
    staggerBuild: function (tl, targets, at, o) {
      tl.fromTo(list(targets), { opacity: 0, x: opt(o, "distance", 40) },
        { opacity: 1, x: 0, duration: opt(o, "duration", 0.5), ease: opt(o, "ease", "power3.out"),
          stagger: opt(o, "stagger", 0.14) }, at);
    },
    // horizontal rules draw from the right; vertical ones from the top
    lineDraw: function (tl, target, at, o) {
      var vertical = opt(o, "vertical", false);
      var from = vertical ? { scaleY: 0, transformOrigin: "50% 0%" } : { scaleX: 0, transformOrigin: "100% 50%" };
      var to = vertical ? { scaleY: 1 } : { scaleX: 1 };
      to.duration = opt(o, "duration", 0.6);
      to.ease = opt(o, "ease", "power2.inOut");
      tl.fromTo(target, from, to, at);
    },
    // the clip boundary is the cut: element is simply present
    hardCut: function (tl, target, at) {
      tl.set(target, { opacity: 1 }, at);
    }
  };

  // ------------------------------------------------------------ exits
  var exit = {
    fadeOut: function (tl, target, at, o) {
      tl.to(target, { opacity: 0, duration: opt(o, "duration", 0.35), ease: opt(o, "ease", "power2.in") }, at);
    },
    // continues the RTL wipe: the right inset grows
    maskOut: function (tl, target, at, o) {
      tl.fromTo(target, { clipPath: "inset(0% 0% 0% 0%)" },
        { clipPath: "inset(0% 100% 0% 0%)", duration: opt(o, "duration", 0.45), ease: opt(o, "ease", "power2.in") }, at);
    },
    hardCut: function () {}
  };

  // ------------------------------------------------------------ camera
  var camera = {
    pushIn: function (tl, target, at, duration, o) {
      tl.fromTo(target, { scale: 1, transformOrigin: opt(o, "origin", "50% 50%") },
        { scale: opt(o, "scale", 1.06), duration: duration, ease: "none" }, at);
    }
  };

  // ------------------------------------------------------------ screenshot choreography
  // Regions are fractions of the screenshot: [x, y, w, h] in 0..1.
  function parseRegion(value) {
    var p = String(value).split(",").map(parseFloat);
    return { x: p[0], y: p[1], w: p[2], h: p[3] };
  }

  // transform for .g-canvas (origin 0 0) that centers and fits a region
  function regionTransform(frame, region, fill) {
    var W = frame.clientWidth, H = frame.clientHeight;
    var s = Math.max(1, Math.min(1 / region.w, 1 / region.h) * (fill || 0.86));
    var cx = (region.x + region.w / 2) * W, cy = (region.y + region.h / 2) * H;
    var x = Math.min(0, Math.max(W - W * s, W / 2 - cx * s));
    var y = Math.min(0, Math.max(H - H * s, H / 2 - cy * s));
    return { scale: s, x: x, y: y };
  }

  var shot = {
    // position overlays (data-region / data-from + data-to) inside a .g-shot
    place: function (frameSel) {
      var frame = one(frameSel);
      var W = frame.clientWidth, H = frame.clientHeight;
      Array.prototype.forEach.call(frame.querySelectorAll("[data-region]"), function (node) {
        var r = parseRegion(node.getAttribute("data-region"));
        node.style.left = r.x * 100 + "%";
        node.style.top = r.y * 100 + "%";
        node.style.width = r.w * 100 + "%";
        node.style.height = r.h * 100 + "%";
      });
      Array.prototype.forEach.call(frame.querySelectorAll(".g-line[data-from][data-to]"), function (node) {
        var a = node.getAttribute("data-from").split(",").map(parseFloat);
        var b = node.getAttribute("data-to").split(",").map(parseFloat);
        var dx = (b[0] - a[0]) * W, dy = (b[1] - a[1]) * H;
        node.style.left = a[0] * 100 + "%";
        node.style.top = a[1] * 100 + "%";
        node.style.width = Math.sqrt(dx * dx + dy * dy) + "px";
        node.style.transform = "rotate(" + (Math.atan2(dy, dx) * 180 / Math.PI) + "deg)";
      });
    },
    // instant framing of one region
    cropTo: function (tl, frameSel, region, at, o) {
      var frame = one(frameSel);
      var t = regionTransform(frame, region, opt(o, "fill", 0.86));
      tl.set(frame.querySelector(".g-canvas"), { transformOrigin: "0 0", scale: t.scale, x: t.x, y: t.y }, at);
    },
    // animated move from the full view to one region
    zoomToDetail: function (tl, frameSel, region, at, duration, o) {
      var frame = one(frameSel);
      var t = regionTransform(frame, region, opt(o, "fill", 0.86));
      tl.fromTo(frame.querySelector(".g-canvas"), { transformOrigin: "0 0", scale: 1, x: 0, y: 0 },
        { scale: t.scale, x: t.x, y: t.y, duration: duration, ease: opt(o, "ease", "power3.inOut") }, at);
    },
    // move between two regions of the same screenshot
    panBetween: function (tl, frameSel, from, to, at, duration, o) {
      var frame = one(frameSel);
      var a = regionTransform(frame, from, opt(o, "fill", 0.86));
      var b = regionTransform(frame, to, opt(o, "fill", 0.86));
      tl.fromTo(frame.querySelector(".g-canvas"), { transformOrigin: "0 0", scale: a.scale, x: a.x, y: a.y },
        { scale: b.scale, x: b.x, y: b.y, duration: duration, ease: opt(o, "ease", "power2.inOut") }, at);
    },
    highlightBox: function (tl, boxSel, at, o) {
      tl.fromTo(boxSel, { opacity: 0, scale: 1.12 },
        { opacity: 1, scale: 1, duration: opt(o, "duration", 0.45), ease: opt(o, "ease", "back.out(1.6)") }, at);
    },
    spotlight: function (tl, spotSel, at, o) {
      tl.fromTo(spotSel, { opacity: 0 }, { opacity: 1, duration: opt(o, "duration", 0.5), ease: "power2.out" }, at);
    },
    calloutLine: function (tl, lineSel, at, o) {
      tl.fromTo(lineSel, { scaleX: 0 }, { scaleX: 1, duration: opt(o, "duration", 0.5), ease: "power2.out" }, at);
    }
  };

  // ------------------------------------------------------------ review attributes
  // Approved review operations only set attributes; this turns them into tweens.
  //   data-push-in="1.06" on a media element -> push_in across its scene
  function applyReviewAttributes(tl) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-push-in]"), function (node) {
      var scene = node.closest(".clip");
      if (!scene) return;
      var start = parseFloat(scene.getAttribute("data-start")) || 0;
      var duration = parseFloat(scene.getAttribute("data-duration")) || 0;
      if (duration > 0) camera.pushIn(tl, node, start, duration, { scale: parseFloat(node.getAttribute("data-push-in")) || 1.06 });
    });
  }

  root.MS = {
    enter: enter,
    exit: exit,
    camera: camera,
    shot: shot,
    parseRegion: parseRegion,
    regionTransform: regionTransform,
    applyReviewAttributes: applyReviewAttributes
  };
})(window);
