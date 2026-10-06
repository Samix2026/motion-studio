# Component — Small section title

Implementation: `../../starter/components/brand-frame.css` (`.section-title`, `.title-line`).

Used **only at structural pivots** (`VISUAL_SYSTEM.md` §Elements), not on
every scene — e.g. entering the transformation beat in
`scene-map-example.md` scene 7.

```html
<div class="section-title" id="title1">
  <h2 class="title-line">التحول</h2>
</div>
```

```css
.section-title {
  position: absolute;
  left: 50%;
  bottom: 220px;
  transform: translateX(-50%);
  max-width: 1600px;
  z-index: 46;
}
.title-line {
  direction: rtl;
  text-align: center;
  font-family: var(--ms-font);
  font-size: 56px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: #f4f1ea;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.55);
}
```

Timeline (holds briefly, then exits before the lower third resumes):

```js
tl.fromTo("#title1", { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, at);
tl.to("#title1", { opacity: 0, duration: 0.4, ease: "power2.in" }, at + 2.0);
```

Rules:
- One or two words, never a sentence — this is a section marker, not a
  narrative line.
- Never appears in the same instant as the lower third.
- No generic motivational phrasing (`TEMPLATE_RULES.md` §2).
