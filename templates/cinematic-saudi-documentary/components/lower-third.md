# Component — Lower-third Arabic text area

Implementation: `../../starter/components/brand-frame.css` (`.lower-third`, `.lt-line`).

Carries the narrative sentence for the current beat. RTL scoped to the
container per `../../CONTENT_RULES.md` §RTL / bidi — never on `<html>`.

```html
<div class="lower-third" id="lt1">
  <p class="lt-line">من قلب الجزيرة العربية، بدأت حكاية أرض قديمة.</p>
</div>
```

```css
.lower-third {
  position: absolute;
  left: 120px;
  right: 120px;
  bottom: 130px;
  max-width: 1180px;
  z-index: 45;
}
.lt-line {
  direction: rtl;
  text-align: right;
  font-family: var(--ms-font);
  font-size: 44px;
  line-height: 1.35;
  font-weight: 500;
  color: #f4f1ea;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.55); /* scrim, keeps text readable over the grade */
}
```

Timeline (fade + small rise, one line replaces the previous on cut):

```js
tl.fromTo("#lt1", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, 0.15);
tl.to("#lt1", { opacity: 0, duration: 0.3, ease: "power2.in" }, sceneDuration - 0.3);
```

Rules:
- One sentence per beat, matching `narrative.md` / the scene map exactly —
  no paraphrasing on screen.
- Stays inside the 1180px-max text band (`VISUAL_SYSTEM.md`).
- Only one chrome element (title or lower third) animates in at a time
  (`VISUAL_SYSTEM.md` §What this system does not do).
- The text-shadow scrim is the fix for readability against the grade —
  never lower `--grade-contrast` in `COLOR_GRADE.md` to compensate.
