#!/usr/bin/env node
// hf_trace.mjs — the ONLY HyperFrames/browser integration point of the numeric trace.
//
// Seeks the composition's registered deterministic timeline frame by frame and
// samples numeric visual state (transform, opacity, box) of a SELECTED set of
// elements. No screenshots, no encoding, no render.
//
// Interface used (all public): @hyperframes/producer exports createFileServer,
// createCaptureSession, initializeSession, closeCaptureSession,
// getCompositionDuration; @hyperframes/core/compiler bundleToSingleHtml; in page,
// window.__hf.seek(t) (the seek the official hyperframes-animation sampler uses),
// falling back to seeking window.__timelines. A HyperFrames change should only
// ever require edits here; studio/trace.py consumes the JSON below.
//
// Usage: node studio/hf_trace.mjs <project-dir> --fps N --width W --height H
//          --out trace.raw.json [--selectors JSON] [--max-elements N] [--chunk N]
// Env:   MS_TRACE_NODE_MODULES — node_modules dir holding @hyperframes/producer + core.
// Output: {ok, duration, fps, frames, elements, tracks{key.prop:[v per frame]},
//          stage_visible[], reseek_mismatches[] (visible only), reseek_invisible,
//          reseek_overflow, truncated, timing_ms}

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

function arg(name, dflt) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : dflt;
}

const projectDir = resolve(process.argv[2] ?? ".");
const out = arg("out");
const fps = Number(arg("fps", 30));
const width = Number(arg("width", 1920));
const height = Number(arg("height", 1080));
const selectors = JSON.parse(arg("selectors", "{}"));
const maxElements = Number(arg("max-elements", 400));
const chunk = Number(arg("chunk", 60));
if (!out) throw new Error("--out is required");

const t0 = Date.now(); // tool timing only; never used for visual state
const nodeModules = resolve(process.env.MS_TRACE_NODE_MODULES ?? "node_modules");
// ESM-only packages: resolve the documented "exports" entry by hand.
const load = async (pkg, sub = ".") => {
  const dir = join(nodeModules, pkg);
  const entry = JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).exports[sub];
  return import(pathToFileURL(join(dir, typeof entry === "string" ? entry : entry.import)).href);
};

const compiledDir = mkdtempSync(join(tmpdir(), "ms-trace-"));
let server;
let session;
let producer;
try {
  producer = await load("@hyperframes/producer");
  const compiler = await load("@hyperframes/core", "./compiler");
  writeFileSync(join(compiledDir, "index.html"), await compiler.bundleToSingleHtml(projectDir));
  server = await producer.createFileServer({ projectDir, compiledDir, port: 0 });
  session = await producer.createCaptureSession(server.url, compiledDir,
    { width, height, fps, format: "png" }, null);
  await producer.initializeSession(session);
  const duration = await producer.getCompositionDuration(session);
  const frames = Math.round(duration * fps);
  const tReady = Date.now();

  // Pick elements once: scene roots, declared selectors, animated tween targets.
  const elements = await session.page.evaluate(({ selectors, maxElements }) => {
    const picked = new Map();
    const root = document.querySelector("[data-composition-id]") ?? document.body;
    const keyOf = (el) => {
      if (el.id) return el.id;
      const owner = el.parentElement?.closest("[id]");
      const cls = [...el.classList].slice(0, 1).map((c) => "." + c).join("");
      const sib = owner ? [...owner.querySelectorAll(el.tagName + cls)].indexOf(el) : 0;
      return `${owner?.id ?? "root"}>${el.tagName.toLowerCase()}${cls}:${sib}`;
    };
    const add = (el, reason, key) => {
      if (!(el instanceof Element) || picked.has(el)) return;
      picked.set(el, { key: key ?? keyOf(el), reason, scene: el.closest(".clip")?.id ?? null });
    };
    for (const [name, sel] of Object.entries(selectors)) {
      const el = document.querySelector(sel);
      if (el) add(el, "declared", name);
    }
    document.querySelectorAll(".clip").forEach((el) => add(el, "scene"));
    const walk = (node) => {
      if (!node) return;
      if (typeof node.getChildren === "function") {
        for (const c of node.getChildren(true, true, true)) walk(c);
        return;
      }
      for (const t of node.targets?.() ?? []) add(t, "animated");
    };
    for (const tl of Object.values(window.__timelines ?? {})) walk(tl);
    for (const a of document.getAnimations?.() ?? []) add(a.effect?.target, "animated"); // CSS/WAAPI
    const list = [...picked.entries()];
    const seen = new Set();
    window.__msTraceEls = [];
    const meta = [];
    for (const [el, m] of list.slice(0, maxElements)) {
      let k = m.key;
      for (let n = 2; seen.has(k); n++) k = `${m.key}~${n}`;
      seen.add(k);
      window.__msTraceEls.push(el);
      meta.push({ ...m, key: k });
    }
    window.__msTraceRoot = root;
    window.__msTraceKinds = meta.map((m) => m.reason);
    // Media/canvas content counts toward "is anything on stage" without being traced.
    window.__msTraceMedia = [...root.querySelectorAll("canvas, video, img, svg")]
      .filter((el) => !picked.has(el));
    return { meta, total: list.length };
  }, { selectors, maxElements });

  const sample = (frameList) => session.page.evaluate((frameList, fps) => {
    const seek = (t) => {
      if (window.__hf && typeof window.__hf.seek === "function") return window.__hf.seek(t);
      for (const tl of Object.values(window.__timelines ?? {})) tl.seek?.(t);
    };
    const r6 = (v) => (Number.isFinite(v) ? Math.round(v * 1000) / 1000 : String(v));
    const alphaOf = (el) => {
      let a = 1;
      for (let n = el; n && n instanceof Element; n = n.parentElement) {
        const s = getComputedStyle(n);
        if (s.display === "none" || s.visibility === "hidden") return 0;
        a *= parseFloat(s.opacity);
      }
      return a;
    };
    return frameList.map((f) => {
      seek(f / fps);
      const rr = window.__msTraceRoot.getBoundingClientRect();
      let visible = 0;
      const rows = window.__msTraceEls.map((el, i) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        // The element's own transform, whatever wrote it (GSAP, CSS, WAAPI).
        const m = new DOMMatrix(cs.transform === "none" ? undefined : cs.transform);
        const alpha = alphaOf(el);
        // Scene roots are containers: a visible empty scene is not content.
        if (window.__msTraceKinds[i] !== "scene" && alpha > 0.01 && r.width > 0 && r.height > 0 && r.right > rr.left && r.left < rr.right
            && r.bottom > rr.top && r.top < rr.bottom) visible++;
        return [m.m41, m.m42, Math.hypot(m.m11, m.m12), Math.hypot(m.m21, m.m22),
          Math.atan2(m.m12, m.m11) * 180 / Math.PI, parseFloat(cs.opacity), alpha,
          r.left - rr.left, r.top - rr.top, r.width, r.height].map(r6);
      });
      for (const el of window.__msTraceMedia) {
        const r = el.getBoundingClientRect();
        if (alphaOf(el) > 0.01 && r.width > 0 && r.height > 0 && r.right > rr.left && r.left < rr.right
            && r.bottom > rr.top && r.top < rr.bottom) visible++;
      }
      const probe = typeof window.__msTrace === "function" ? window.__msTrace(f / fps) : null;
      return { f, rows, visible, probe };
    });
  }, frameList, fps);

  const PROPS = ["x", "y", "scaleX", "scaleY", "rotation", "opacity", "alpha",
    "box.x", "box.y", "box.w", "box.h"];
  const tracks = {};
  const stageVisible = new Array(frames);
  const put = (name, f, v) => { (tracks[name] ??= new Array(frames).fill(null))[f] = v; };
  const forward = [];
  for (let s = 0; s < frames; s += chunk) {
    const list = [];
    for (let f = s; f < Math.min(frames, s + chunk); f++) list.push(f);
    for (const row of await sample(list)) {
      forward[row.f] = row.rows;
      stageVisible[row.f] = row.visible;
      row.rows.forEach((vals, i) => vals.forEach((v, p) => put(`${elements.meta[i].key}.${PROPS[p]}`, row.f, v)));
      for (const [k, v] of Object.entries(row.probe ?? {})) put(`probe.${k}`, row.f, Number.isFinite(v) ? Math.round(v * 1000) / 1000 : String(v));
    }
  }
  const tSample = Date.now();

  // Seek-order determinism: revisit every 7th frame in reverse; any difference
  // means visual state depends on how the frame was reached.
  const revisit = [];
  for (let f = frames - 1; f >= 0; f -= 7) revisit.push(f);
  const reseekMismatches = [];
  let invisibleMismatches = 0;
  let visibleOverflow = 0;
  for (let s = 0; s < revisit.length; s += chunk) {
    for (const row of await sample(revisit.slice(s, s + chunk))) {
      row.rows.forEach((vals, i) => vals.forEach((v, p) => {
        const a = forward[row.f][i][p];
        const same = a === v || (typeof a === "number" && typeof v === "number" && Math.abs(a - v) <= 0.01);
        if (same) return;
        const alpha = [forward[row.f][i][6], vals[6]];
        if (!alpha.some((x) => typeof x === "number" && x > 0.01)) invisibleMismatches++;
        else if (reseekMismatches.length < 500) {
          reseekMismatches.push({ frame: row.f, track: `${elements.meta[i].key}.${PROPS[p]}`, forward: a,
            reseek: v, alpha });
        } else visibleOverflow++;
      }));
    }
  }

  writeFileSync(out, JSON.stringify({
    ok: true, duration, fps, frames, width, height,
    elements: elements.meta, truncated: Math.max(0, elements.total - elements.meta.length),
    tracks, stage_visible: stageVisible, reseek_mismatches: reseekMismatches,
    reseek_invisible: invisibleMismatches, reseek_overflow: visibleOverflow,
    timing_ms: { init: tReady - t0, sample: tSample - tReady, reseek: Date.now() - tSample },
  }));
} catch (err) {
  writeFileSync(out, JSON.stringify({ ok: false, error: String(err?.stack ?? err).slice(0, 2000) }));
  process.exitCode = 1;
} finally {
  if (session) await producer.closeCaptureSession(session).catch(() => {});
  server?.close?.();
  rmSync(compiledDir, { recursive: true, force: true });
}
