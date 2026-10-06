# Component — Source credit + `@your_handle`

Implementation: `../../starter/components/brand-frame.css` (`.credit`, `.handle`).

Every archival/borrowed asset carries an adjacent credit; the handle stays
visible on the closing scene at minimum (persistent throughout is also
valid — pick one and keep it consistent across the project).

```html
<p class="credit" id="credit1">المصدر: الجهة الناشرة</p>
<div class="handle" id="handle">@your_handle</div>
```

```css
.credit {
  position: absolute;
  left: 120px;
  bottom: 96px;
  direction: rtl;
  font-family: var(--ms-font);
  font-size: 32px; /* type-scale landscape credit floor (mobile-safe) */
  color: #d8d5cc;
  text-shadow: 0 1px 10px rgba(0, 0, 0, 0.5);
  z-index: 45;
}
.handle {
  position: absolute;
  right: 56px;
  bottom: 24px;
  direction: ltr;
  font-family: var(--ms-font);
  font-size: 30px; /* type-scale landscape handle size */
  font-weight: 500;
  letter-spacing: 0.12em;
  color: #f4f1ea;
  z-index: 45;
}
```

Timeline:

```js
tl.fromTo("#credit1", { opacity: 0 }, { opacity: 1, duration: 0.4 }, at);
tl.fromTo("#handle", { opacity: 0 }, { opacity: 0.85, duration: 0.5 }, 0.3);
```

Rules:
- Use the publisher/archive name exactly as it appears.
- `.credit` sits above `bottom-line.md`'s hairline, inside the text-safe
  bottom padding (130px), never overlapping it.
- `@your_handle` is never replaced by a source credit — both can be on
  screen at once (`.credit` left, `.handle` right).
- Every credited asset also gets a row in `sources.md`
  (`../../ASSET_POLICY.md` §Provenance record).
