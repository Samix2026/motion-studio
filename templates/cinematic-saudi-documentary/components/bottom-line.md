# Component — Thin bottom accent line

Implementation: `../../starter/components/brand-frame.css` (`.bottom-line`).

A single hairline, brand-colored, present throughout. Not a progress bar —
this template is not beat-segmented like `../../tech-news-ar`'s footer.

```html
<div class="bottom-line" id="bottomLine"></div>
```

```css
.bottom-line {
  position: absolute;
  left: 56px;
  right: 56px;
  bottom: 56px;
  height: 2px;
  background: color-mix(in srgb, var(--accent, #006c35) 70%, transparent);
  transform-origin: right center; /* draws right-to-left, RTL-consistent */
  z-index: 44;
}
```

Timeline (draws once, on the opening scene; stays static after):

```js
tl.fromTo("#bottomLine", { scaleX: 0 }, { scaleX: 1, duration: 0.8, ease: "power2.inOut" }, 0.1);
```

Rules:
- One draw-in at the top of the piece, not re-triggered per scene.
- Sits inside the 56px chrome inset, never inside the text-safe padding.
- `--accent` defaults to the Saudi flag green (`#006c35`) — never recolor it
  via the grade (`COLOR_GRADE.md` §Flag protection).
