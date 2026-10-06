# Component — Logo slot (top-right identity)

Implementation: `../../starter/components/brand-frame.css` (`.logo-slot`, `.logo-slot img`, `.logo-slot .mark`).

Quiet, persistent identity mark. Not the subject's own logo unless the
project is explicitly about that institution (`../../ASSET_POLICY.md`
§Brand logos and visual identity).

```html
<div class="logo-slot" id="logoSlot">
  <img src="assets/logo.svg" alt="" />
  <!-- or, with no logo file: <span class="mark"></span> -->
</div>
```

```css
.logo-slot {
  position: absolute;
  top: 56px;
  right: 56px;
  width: 72px;
  height: 72px;
  opacity: 0.85;
  z-index: 50;
}
.logo-slot img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}
```

Timeline: `tl.fromTo("#logoSlot", { opacity: 0 }, { opacity: 0.9, duration: 0.6, ease: "power2.out" }, 0.2);`

Rules:
- Never the reused reference video's logo (`TEMPLATE_RULES.md` §6).
- Stays inside the 56px chrome inset (`VISUAL_SYSTEM.md`).
- Present every scene; does not re-animate on scene changes, only on entry.
