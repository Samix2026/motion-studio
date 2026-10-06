# Component — Cinematic media frame

Implementation: `../../starter/components/cinematic-frame.css`.

Full-bleed frame for footage and stills, replacing `../tech-news-ar`'s
rounded `.card` treatment — this template's imagery fills the frame edge to
edge (`VISUAL_SYSTEM.md` §Full-bleed media), it is not boxed as a card.

```html
<figure class="cine-frame" id="s1frame">
  <video src="assets/<file>.mp4" muted playsinline
         data-start="0" data-duration="3.5"></video>
  <!-- or: <img src="assets/<file>.jpg" alt="" /> for a Ken Burns still -->
</figure>
```

```css
.cine-frame {
  position: absolute;
  inset: 0;
  overflow: hidden;
  background: #0b0f0c; /* dark-green-neutral base, never pure black */
}
.cine-frame video,
.cine-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}
```

Timeline: `tl.fromTo("#s1frame", { opacity: 0 }, { opacity: 1, duration: 0.35, ease: "power2.out" }, sceneStart);`
— a quick fade-in only on a hard cut where the previous scene wasn't
already full-bleed; two adjacent full-bleed scenes cut directly with no
frame-level fade (the cut itself is the transition).

Rules:
- Sits **under** the global grade wrapper (`COLOR_GRADE.md` Stage B) — that
  stage applies once at `#root`, never per frame. The per-shot correction
  (`COLOR_GRADE.md` Stage A) *does* apply here, on `.cine-frame img`/
  `.cine-frame video`, via that shot's own `--corr-*` custom properties.
- A `<video>` is always `muted`; its sound lives on a separate `<audio>`
  element per `../../AUDIO_DESIGN.md` §7. Never `crossorigin`.
- Ken Burns motion (`ken-burns-still.md`) animates the inner `img`/`video`,
  never `.cine-frame` itself — the frame stays fixed to the safe canvas.
- No rounded corners, no border, no card background — full bleed is the
  point.
