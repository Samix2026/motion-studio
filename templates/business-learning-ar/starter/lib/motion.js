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
    // horizontal rules draw from the right; vertical ones from the top.
    // o.origin overrides the start point (process_flow paths draw from their "from" end).
    lineDraw: function (tl, target, at, o) {
      var vertical = opt(o, "vertical", false);
      var from = vertical ? { scaleY: 0, transformOrigin: "50% 0%" } : { scaleX: 0, transformOrigin: "100% 50%" };
      if (o && o.origin) from.transformOrigin = o.origin;
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

  // ------------------------------------------------------------ process_flow actions
  // In-scene actions for the process_flow grammar. Geometry is read once at build
  // time from a fixed-size .pf-stage (never from font-dependent text); every visual
  // change is a finite tween or set at an absolute timeline position, so any frame
  // is reproducible from its time alone (forward, backward or jumping seeks).
  // Every fromTo names each animated property in BOTH from and to: GSAP does not
  // re-apply from-only values when a seek jumps over a tween.
  //   line  nodes: laid out by CSS flex in the content direction (RTL: right to left).
  //   floor nodes: data-pos="x,y" (fractions of the stage) = physical positions,
  //                never mirrored; data-pos-after="x,y" = position in the after state.
  function r3(v) { return Math.round(v * 1000) / 1000; }

  function center(stage, el) {
    var x = el.offsetWidth / 2, y = el.offsetHeight / 2, e = el;
    while (e && e !== stage) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
    return { x: x, y: y };
  }
  function node(stage, id) { return stage.querySelector('.pf-node[data-node="' + id + '"]'); }
  function pos(stage, id, state) {
    var n = node(stage, id);
    var p = (state === "after" && n.getAttribute("data-pos-after")) || n.getAttribute("data-pos");
    if (!p) return center(stage, n);
    var f = p.split(",").map(parseFloat);
    return { x: f[0] * stage.clientWidth, y: f[1] * stage.clientHeight };
  }
  // anchor: node id | "from,to" (path midpoint) | "#id" (element box center)
  function anchor(stage, at, state) {
    if (at.charAt(0) === "#") return center(stage, stage.querySelector(at));
    var ids = at.split(",");
    if (ids.length === 1) return pos(stage, ids[0], state);
    var a = pos(stage, ids[0], state), b = pos(stage, ids[1], state);
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }
  function segment(stage, path, state) {
    var a = pos(stage, path.getAttribute("data-from"), state);
    var b = pos(stage, path.getAttribute("data-to"), state);
    var dx = b.x - a.x, dy = b.y - a.y;
    return { left: a.x, top: a.y, width: Math.sqrt(dx * dx + dy * dy), rotation: Math.atan2(dy, dx) * 180 / Math.PI };
  }

  // Pure queue model (no DOM): items enter every inEvery s, travel `travel` s to the
  // step, and leave it no faster than one per serviceEvery s. Deterministic.
  function schedule(o) {
    var out = [], free = -Infinity;
    for (var i = 0; i < o.count; i++) {
      var enterAt = o.start + i * o.inEvery;
      var arrive = enterAt + o.travel;
      var depart = Math.max(arrive, free);
      free = depart + o.serviceEvery;
      out.push({ enter: r3(enterAt), arrive: r3(arrive), depart: r3(depart), exit: r3(depart + o.travel) });
    }
    return out;
  }
  // [[time, waiting]] from a schedule; departures sort before arrivals at equal times.
  function queueLevels(sched, until) {
    var ev = [];
    sched.forEach(function (s) {
      if (s.depart > s.arrive) { ev.push([s.arrive, 1]); ev.push([s.depart, -1]); }
    });
    ev.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var level = 0, out = [];
    ev.forEach(function (e) {
      if (until !== undefined && e[0] >= until) return;
      level += e[1];
      out.push([e[0], level]);
    });
    return out;
  }

  var flow = {
    schedule: schedule,
    queueLevels: queueLevels,

    // one-time static placement (build time, before any tween)
    place: function (stageSel) {
      var stage = one(stageSel);
      var W = stage.clientWidth, H = stage.clientHeight;
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-node[data-pos]"), function (n) {
        var f = n.getAttribute("data-pos").split(",").map(parseFloat);
        n.style.left = f[0] * 100 + "%";
        n.style.top = f[1] * 100 + "%";
        gsap.set(n, { xPercent: -50, yPercent: -50 });
      });
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-path[data-from][data-to]"), function (p) {
        var g = segment(stage, p, "problem");
        gsap.set(p, { left: g.left, top: g.top, width: g.width, rotation: g.rotation, yPercent: -50, transformOrigin: "0% 50%" });
      });
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-queue[data-at]"), function (q) {
        // plain left/top (no transform) so slot offsets stay exact for token targets
        var n = node(stage, q.getAttribute("data-at")), c = pos(stage, q.getAttribute("data-at"));
        q.style.left = c.x - q.offsetWidth / 2 + "px";
        q.style.top = c.y + n.offsetHeight / 2 + 24 + "px";
      });
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-hotspot[data-at]"), function (h) {
        var c = anchor(stage, h.getAttribute("data-at"), "problem");
        h.style.left = c.x + "px";
        h.style.top = c.y + "px";
        gsap.set(h, { xPercent: -50, yPercent: -50 });
      });
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-token, .pf-traveler"), function (t) {
        var c = t.getAttribute("data-at") ? pos(stage, t.getAttribute("data-at")) : { x: 0, y: 0 };
        gsap.set(t, { xPercent: -50, yPercent: -50, x: c.x, y: c.y });
      });
      return { width: W, height: H };
    },

    // work items move path[0] -> path[1] -> path[2]; items that must wait hand over
    // to the queue at path[1] (o.queue). o: path, tokens, inEvery, serviceEvery,
    // travel, until (absolute; later events are skipped), queue, counter.
    flowTokens: function (tl, stageSel, at, o) {
      var stage = one(stageSel), tokens = list(o.tokens);
      var A = pos(stage, o.path[0]), B = pos(stage, o.path[1]), C = pos(stage, o.path[2]);
      var travel = opt(o, "travel", 0.6), until = opt(o, "until", Infinity);
      var sched = schedule({ count: opt(o, "count", tokens.length), start: at, inEvery: o.inEvery,
                             serviceEvery: o.serviceEvery, travel: travel });
      var levels = queueLevels(sched, until);
      var slots = o.queue ? one(o.queue).querySelectorAll(".pf-q") : [];
      function levelAt(t) {
        var n = 0;
        levels.forEach(function (l) { if (l[0] <= t) n = l[1]; });
        return n;
      }
      sched.forEach(function (s, i) {
        var tok = tokens[i];
        if (!tok || s.enter >= until) return;
        var waits = s.depart > s.arrive && slots.length;
        var dest = B;
        if (waits) dest = center(stage, slots[Math.min(levelAt(s.arrive), slots.length) - 1]);
        tl.fromTo(tok, { x: A.x, y: A.y, opacity: 1 },
          { x: dest.x, y: dest.y, opacity: 1, duration: travel, ease: "power1.inOut", immediateRender: false }, s.enter);
        if (waits) tl.set(tok, { opacity: 0 }, s.arrive);
        if (s.depart >= until) return;
        tl.fromTo(tok, { x: B.x, y: B.y, opacity: 1 },
          { x: C.x, y: C.y, opacity: 1, duration: travel, ease: "power1.inOut", immediateRender: false }, s.depart);
        if (s.exit < until) tl.fromTo(tok, { opacity: 1 }, { opacity: 0, duration: 0.2, immediateRender: false }, s.exit);
      });
      if (o.queue) flow.queueBuild(tl, o.queue, levels, { counter: o.counter });
      return sched;
    },

    // shows a bounded queue: levels = [[absolute time, waiting count], ...].
    // Only the first N .pf-q slots exist; counts above N keep the queue full.
    // o.from = level already shown (when a later call continues the same queue).
    queueBuild: function (tl, queueSel, levels, o) {
      var slots = one(queueSel).querySelectorAll(".pf-q"), S = slots.length, prev = opt(o, "from", 0);
      levels.forEach(function (l) {
        var t = l[0], n = l[1], lo = Math.min(prev, n, S), hi = Math.min(Math.max(prev, n), S);
        for (var k = lo; k < hi; k++) {
          if (n > prev) tl.fromTo(slots[k], { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.18, ease: "back.out(1.6)", immediateRender: false }, t);
          else tl.fromTo(slots[k], { opacity: 1, scale: 1 }, { opacity: 0, scale: 0.6, duration: 0.18, ease: "power2.in", immediateRender: false }, t);
        }
        if (o && o.counter) flow.countTo(tl, o.counter, prev, n, t, { duration: 0.15 });
        prev = n;
      });
    },

    // travel between two locations along a .pf-path (data-from, data-to). The path
    // draws on the first outbound leg (reusing enter.lineDraw); o.traveler makes
    // o.trips round trips. o.state "after" uses data-pos-after. Returns trip end times.
    pathTrace: function (tl, pathSel, at, o) {
      var path = one(pathSel), stage = path.closest(".pf-stage"), state = opt(o, "state", "problem");
      var leg = opt(o, "leg", 1), dwell = opt(o, "dwell", 0.2), ends = [];
      if (opt(o, "draw", true)) enter.lineDraw(tl, path, at, { origin: "0% 50%", duration: leg, ease: "none" });
      var a = pos(stage, path.getAttribute("data-from"), state), b = pos(stage, path.getAttribute("data-to"), state);
      var t = at;
      for (var i = 0; i < opt(o, "trips", 1); i++) {
        if (o.traveler) {
          tl.fromTo(o.traveler, { x: a.x, y: a.y }, { x: b.x, y: b.y, duration: leg, ease: "power1.inOut", immediateRender: false }, t);
          tl.fromTo(o.traveler, { x: b.x, y: b.y }, { x: a.x, y: a.y, duration: leg, ease: "power1.inOut", immediateRender: false }, t + leg + dwell);
        }
        t = r3(t + 2 * leg + dwell);
        ends.push(t);
      }
      return ends;
    },

    // numeric transition (proxy value -> text, per the dataviz count-up pattern).
    // The proxy is a fresh object per call, so chained counts on one element seek cleanly.
    countTo: function (tl, target, from, to, at, o) {
      var el = one(target), proxy = { v: from };
      var fmt = function (v) { return opt(o, "prefix", "") + Math.round(v) + opt(o, "suffix", ""); };
      tl.fromTo(proxy, { v: from }, { v: to, duration: opt(o, "duration", 0.8), ease: opt(o, "ease", "power2.out"),
        immediateRender: false, onUpdate: function () { el.textContent = fmt(proxy.v); } }, at);
    },

    // the same stage moves from problem to after: nodes with data-pos-after move,
    // paths re-fit their endpoints, [data-state-only] elements swap, and the stage's
    // data-state attribute flips at the end (CSS state colors).
    stateMorph: function (tl, stageSel, at, o) {
      var stage = one(stageSel), d = opt(o, "duration", 1.2), ease = opt(o, "ease", "power2.inOut");
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-node[data-pos-after]"), function (n) {
        var a = n.getAttribute("data-pos").split(","), b = n.getAttribute("data-pos-after").split(",");
        tl.fromTo(n, { left: a[0] * 100 + "%", top: a[1] * 100 + "%" },
          { left: b[0] * 100 + "%", top: b[1] * 100 + "%", duration: d, ease: ease, immediateRender: false }, at);
      });
      Array.prototype.forEach.call(stage.querySelectorAll(".pf-path[data-from][data-to]"), function (p) {
        var g0 = segment(stage, p, "problem"), g1 = segment(stage, p, "after");
        tl.fromTo(p, g0, { left: g1.left, top: g1.top, width: g1.width, rotation: g1.rotation,
          duration: d, ease: ease, immediateRender: false }, at);
      });
      var scope = stage.closest(".g") || stage;
      tl.fromTo(scope.querySelectorAll('[data-state-only="problem"]'), { opacity: 1 },
        { opacity: 0, duration: 0.35, immediateRender: false }, at);
      tl.fromTo(scope.querySelectorAll('[data-state-only="after"]'), { opacity: 0 },
        { opacity: 1, duration: 0.45, immediateRender: false }, at + d / 2);
      tl.set(stage, { attr: { "data-state": "after" } }, at + d);
    }
  };

  root.MS = {
    enter: enter,
    exit: exit,
    camera: camera,
    shot: shot,
    flow: flow,
    parseRegion: parseRegion,
    regionTransform: regionTransform,
    applyReviewAttributes: applyReviewAttributes
  };
})(window);
