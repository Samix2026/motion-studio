# scene-map-example.md — worked 40s scene map

Built from `narrative-example.md`'s beat map. Example only, same placeholder
caveat as that file. Grade (`COLOR_GRADE.md`) is applied once at the
composition root and is not repeated per row below. Its Audio cue column
illustrates a project whose brief **requested** audio; by default every row is
`type: none` (`../../AUDIO_DESIGN.md` §0).

| Scene | Time | Sentence (lower third) | Type | Ken Burns | Transition in | Transition out | Audio cue | Brand frame |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.0–3.0s | من قلب الجزيرة العربية، بدأت حكاية أرض قديمة. | still | push-in, 4%, 3.0s (`components/ken-burns-still.md`) | hard cut (frame-0: content visible at 0s) | hard cut | type: ambient · trigger: opening wide shot · at: 0.0s · duration: 3.0s · purpose: ground the place · intensity: very-subtle · source: TBD | logo slot fades in 0.2s; bottom line present |
| 2 | 3.0–6.0s | الرمال حفظت أثر قوافل مرت من هنا منذ قرون. | still | lateral drift, right→left, 3%, 3.0s | hard cut | hard cut | type: none | lower third enters 3.15s |
| 3 | 6.0–9.0s | هنا تشكلت هوية لم تتغير رغم مرور الزمن. | still | pull-out, 4%, 3.0s | hard cut | hard cut | type: none | lower third updates |
| 4 | 9.0–12.5s | اللغة والعادات توارثتها الأجيال دون انقطاع. | footage (trim to 3.5s) | none — native motion carries the shot | hard cut | hard cut | type: heritage/craft · trigger: visible calligraphy or majlis action · at: 9.3s · duration: 1.2s · purpose: tie sound to a visible craft action · intensity: subtle · source: TBD | lower third updates |
| 5 | 12.5–16.0s | في كل مدينة وقرية، يعيش ناس يحملون هذا الإرث. | footage (trim to 3.5s) | none — native motion carries the shot | hard cut | hard cut | type: ambient city · trigger: street-level wide · at: 12.5s · duration: 3.5s · purpose: one establishing city beat, not stacked · intensity: very-subtle · source: TBD | lower third updates |
| 6 | 16.0–19.5s | أيدي الحرفيين ما زالت تصنع ما تعلمته من الآباء. | footage (trim to 3.5s) | none — native motion carries the shot | hard cut | short dissolve (0.5s, into scene 7) | type: heritage/craft · trigger: visible hand movement · at: 16.2s · duration: 1.5s · purpose: reinforce the craft action · intensity: subtle · source: TBD | lower third updates |
| 7 | 19.5–23.0s | ثم جاء وقت التغيير، بخطى واثقة لا متسرعة. | footage (trim to 3.5s) | none — native motion carries the shot | short dissolve (0.5s, from scene 6) | sound-led (whoosh under hard cut into scene 8) | type: whoosh · trigger: pivot cut craft→construction · at: 22.6s · duration: 0.6s · purpose: carry the one narrative pivot · intensity: audible · source: TBD | small section title "التحول" enters, holds 2.0s |
| 8 | 23.0–26.5s | المدن ارتفعت، والطرق امتدت، والمشاريع تعددت. | footage (trim to 3.5s) | none — native motion carries the shot | sound-led (from scene 7) | hard cut | type: none | title exits, lower third resumes |
| 9 | 26.5–30.0s | اليوم تقف المملكة بين إرثها وطموحها. | still | push-in, 5%, 3.5s | hard cut | hard cut | type: none | lower third updates |
| 10 | 30.0–33.5s | الشباب يبني، والعالم يراقب هذا التحول عن قرب. | footage (trim to 3.5s) | none — native motion carries the shot | hard cut | hard cut | type: crowd · trigger: group of people in frame · at: 30.2s · duration: 1.8s · purpose: low textural presence under a people beat · intensity: very-subtle · source: TBD | lower third updates |
| 11 | 33.5–37.0s | الغد يكتب الآن، بخطوات مبنية على أساس متين. | still | lateral drift, left→right, 4%, 3.5s | hard cut | hard cut | type: none | lower third updates |
| 12 | 37.0–40.0s | أرض واحدة، جذور راسخة، ومستقبل لم يكتمل بعد. | still (echoes scene 1's asset family) | pull-out, 3%, 3.0s | hard cut | fade to black, 0.6s | type: low impact · trigger: closing line lands · at: 37.1s · duration: 0.5s · purpose: give the closing statement one soft landing · intensity: subtle · source: TBD | source-credit + `@your_handle` hold through the fade |
| — | 0.0–40.0s | — | — | — | — | — | type: music · trigger: continuous bed, ducked at scene 7's whoosh and scene 12's impact · at: 0.0s · duration: 40.0s · purpose: continuity across cuts · intensity: subtle · source: TBD (must be licensed, `AUDIO_PROFILE.md`) | — |

Total: 12 visual scenes, 40.0s, 3 transition families used (hard cut / short
dissolve / sound-led — none else), 1 narrative pivot, 6 Ken Burns stills
(all within 3–6%), 6 footage clips carrying their own native motion, 6 SFX
cues + 1 music bed (well under one-cue-per-scene).
