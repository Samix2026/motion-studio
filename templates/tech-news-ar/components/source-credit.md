# Component — Source credit

Every borrowed image carries an adjacent credit. The whole piece is also
credited in `sources.md`.

```html
<p class="credit">المصدر: الناشر</p>
```

```css
.credit {
  direction: rtl;
  font-family: var(--font-ar);
  font-size: 26px;
  color: var(--brand-credit-color);
  letter-spacing: 0.01em;
}
```

Timeline: `tl.fromTo(".credit", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 8.05);`

Notes:
- Use the publisher name exactly as it appears (e.g. `Anthropic`).
- Keep the credit inside the safe zone, below the media card.
- `@your_handle` is the publisher handle in the persistent footer and is
  never replaced by a source credit.
