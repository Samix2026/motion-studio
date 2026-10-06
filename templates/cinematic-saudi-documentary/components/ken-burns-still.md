# Component — Ken Burns still

Implementation: `../../starter/components/ken-burns.js` (`CinKB`) — `CinKB.apply(tl)` runs one pass over every `[data-kb]` frame, and `CinKB.pushIn/pullOut/lateral/parallax` are the explicit API. Values are clamped to the 3-6% band.

One reusable module for still-image motion, parameterized per shot — never
hand-authored per scene. Reuses `MS.camera.pushIn` from
`../tech-news-ar/lib/motion.js` (copied into every project per this
template's `README.md`) instead of a new motion engine; pull-out and
lateral are the same primitive run in the direction the shot needs.

Rules (`../TEMPLATE_RULES.md` §4): default movement **3–6%**, no aggressive
zoom, no face distortion, no fake 3D on architecture, no direction changes
mid-shot.

```html
<figure class="kb-still" id="s1still" data-kb="push-in" data-kb-amount="1.04">
  <img src="assets/<file>" alt="" />
</figure>
```

```css
.kb-still {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.kb-still img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  will-change: transform;
}
```

## Push-in (default)

```js
// reuses MS.camera.pushIn directly — scale 1 -> 1.04 (4%) over the shot's duration
MS.camera.pushIn(tl, "#s1still img", sceneStart, sceneDuration, { scale: 1.04 });
```

## Pull-out

Same primitive, reversed: start at the target scale, settle to 1.

```js
tl.fromTo("#s1still img",
  { scale: 1.04, transformOrigin: "50% 50%" },
  { scale: 1, duration: sceneDuration, ease: "none" },
  sceneStart);
```

## Subtle lateral movement

```js
// 3% translate, matched to the still's crop headroom
tl.fromTo("#s1still img",
  { x: "-1.5%" },
  { x: "1.5%", duration: sceneDuration, ease: "none" },
  sceneStart);
```

## Foreground/background parallax (only when safe)

Only when the still genuinely has separable layers (e.g. a foreground
subject shot against a distinct background) and cropping the two layers
independently will not ghost or clip. Split the still into two absolutely
positioned images and offset their push-in amounts:

```js
MS.camera.pushIn(tl, "#s1bg img", sceneStart, sceneDuration, { scale: 1.06 });
MS.camera.pushIn(tl, "#s1fg img", sceneStart, sceneDuration, { scale: 1.03 });
```

If the asset doesn't cleanly separate, use plain push-in/pull-out instead —
parallax is optional, not a default.

## Parameters

| Param | Range | Notes |
|---|---|---|
| direction | push-in / pull-out / lateral / parallax | one per shot, never mixed mid-shot |
| amount | 1.03–1.06 (scale) or 1.5–3% (lateral translate) | stays within the 3–6% rule |
| duration | matches the scene's `data-duration` | one continuous move, no easing bounce |
| ease | `"none"` | linear — a Ken Burns move must not accelerate/decelerate like a UI tween |

## Do not

- Scale beyond 1.06 or lateral beyond 3% in either direction (6% total).
- Animate a face close enough that the push distorts features — reframe or
  crop tighter instead of scaling more.
- Apply any 3D transform (`rotateX`/`rotateY`/`perspective`) to simulate
  depth on flat architecture.
- Change direction partway through a single shot's duration.
