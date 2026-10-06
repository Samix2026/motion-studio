# Component — Topbar

Persistent header. Publisher name on the left (RTL text), category tag on the
right. Paste inside `#root`, before the scene clips.

```html
<div class="topbar" id="topbar">
  <div class="brand">
    <span class="brand-dot"></span>
    <span class="brand-word">اسم القناة</span>
  </div>
  <div class="tag">تقنية</div>
</div>
```

CSS:

```css
.topbar {
  position: absolute;
  top: 64px;
  left: 64px;
  right: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 50;
}
.brand { display: flex; align-items: center; gap: 16px; }
.brand-dot {
  display: block;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  background: var(--brand-primary);
  transform: rotate(45deg);
}
.brand-word {
  direction: rtl;
  font-family: var(--font-ar);
  font-size: 36px;
  font-weight: 600;
  color: var(--text);
}
.tag {
  direction: rtl;
  font-family: var(--font-ar);
  font-size: 30px;
  font-weight: 500;
  color: var(--brand-primary);
  border: var(--brand-border-width) solid color-mix(in srgb, var(--brand-primary) 45%, transparent);
  border-radius: 999px;
  padding: 8px 26px 10px;
}
```

Timeline: `tl.fromTo("#topbar", { opacity: 0, y: -16 }, { opacity: 1, y: 0, duration: 0.8, ease: "power2.out" }, 0.15);`
