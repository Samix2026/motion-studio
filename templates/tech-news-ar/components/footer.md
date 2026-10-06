# Component — Footer (`@your_handle` + progress)

Required persistent footer. The five progress segments fill from the right, one
per beat.

```html
<div class="footer" id="footer">
  <div class="progress">
    <span class="seg" id="p1"></span>
    <span class="seg" id="p2"></span>
    <span class="seg" id="p3"></span>
    <span class="seg" id="p4"></span>
    <span class="seg" id="p5"></span>
  </div>
  <div class="handle">@your_handle</div>
</div>
```

CSS:

```css
.footer {
  position: absolute;
  left: 64px;
  right: 64px;
  bottom: 76px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 26px;
  z-index: 50;
}
.progress { display: flex; flex-direction: row-reverse; gap: 10px; }
.seg {
  display: block;
  width: 64px;
  height: 5px;
  border-radius: 3px;
  background: var(--brand-progress-fill);
  transform-origin: right center;
}
.handle {
  direction: ltr;
  font-family: var(--font-ui);
  font-size: 32px;
  font-weight: 500;
  letter-spacing: 0.14em;
  color: #cbc9c4;
}
```

Timeline (fills span each scene exactly):

```js
tl.fromTo("#footer", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.8, ease: "power2.out" }, 0.35);
tl.fromTo("#p1", { scaleX: 0 }, { scaleX: 1, duration: 6.5, ease: "none" }, 0);
tl.fromTo("#p2", { scaleX: 0 }, { scaleX: 1, duration: 7.5, ease: "none" }, 6.5);
tl.fromTo("#p3", { scaleX: 0 }, { scaleX: 1, duration: 7.0, ease: "none" }, 14);
tl.fromTo("#p4", { scaleX: 0 }, { scaleX: 1, duration: 6.5, ease: "none" }, 21);
tl.fromTo("#p5", { scaleX: 0 }, { scaleX: 1, duration: 4.5, ease: "none" }, 27.5);
```
