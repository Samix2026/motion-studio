# Component — Media card (official screenshot)

Frame official screenshots in a rounded card. Replace the `.media-slot`
placeholder in the template with a `.card`.

```html
<figure id="s2media" class="card">
  <img src="assets/<file>" alt="وصف مختصر" />
</figure>
```

For a wide screenshot where only one side is relevant, crop by anchoring and
zooming, and mark the intentional overflow so the layout audit stays clean:

```html
<figure id="s2media" class="card left">
  <img src="assets/<file>" alt="" data-layout-allow-overflow />
</figure>
```

```css
.card {
  position: relative;
  width: 936px;
  height: 560px;
  border-radius: var(--brand-radius);
  overflow: hidden;
  border: var(--brand-border-width) var(--brand-border-style) var(--brand-border-color);
  background: var(--brand-surface);
}
.card img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: var(--brand-image-fit);
  object-position: var(--brand-image-position);
  transform: scale(var(--brand-image-scale));
}
.card.left img {
  object-position: left center;
  transform: scale(1.95);          /* hide irrelevant side (explicit crop overrides tokens) */
  transform-origin: left center;
}
```

Timeline: `tl.fromTo("#s2media", { opacity: 0, y: 44, scale: 0.98 }, { opacity: 1, y: 0, scale: 1, duration: 0.9, ease: "power3.out" }, 7.65);`

Rules:
- Only official/primary media; keep the credit line beneath it.
- Do not show screenshots containing fictional sample data (see ASSET_POLICY.md).
- Do not add `crossorigin` to media elements.
