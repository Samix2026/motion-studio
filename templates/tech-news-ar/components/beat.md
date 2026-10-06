# Component — Beat scene (clip)

One beat = one `.clip` section. `data-start`/`data-duration` are absolute
seconds and must tile the root `data-duration` with no gaps.

```html
<section id="scene2" class="clip" data-start="6.5" data-duration="7.5" data-track-index="2">
  <div class="scene">
    <h1 id="s2h" class="headline small">ماذا حدث</h1>
    <p id="s2s" class="sub">وصف مختصر للخبر</p>
    <figure id="s2media" class="card">
      <img src="assets/<file>" alt="" />
    </figure>
    <p class="credit">المصدر: الناشر</p>
  </div>
</section>
```

CSS:

```css
.clip { position: absolute; inset: 0; width: 100%; height: 100%; }
.scene {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 40px;
  width: 100%;
  height: 100%;
  padding: 200px 72px 320px; /* safe zone */
  direction: rtl;
  text-align: center;
}
.headline {
  max-width: 920px;
  font-family: var(--font-ar);
  font-size: 84px;
  font-weight: var(--brand-headline-weight);
  line-height: 1.5;
  letter-spacing: var(--brand-headline-tracking);
  color: var(--text);
}
.headline.small { font-size: 74px; }
.sub {
  max-width: 860px;
  font-family: var(--font-ar);
  font-size: 42px;
  line-height: 1.6;
  color: var(--muted);
}
```

Timeline per beat (absolute positions):

```js
tl.fromTo("#s2h", { opacity: 0, y: 46, filter: "blur(12px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.9, ease: "power3.out" }, 6.75);
tl.fromTo("#s2s", { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.75, ease: "power2.out" }, 7.2);
```
