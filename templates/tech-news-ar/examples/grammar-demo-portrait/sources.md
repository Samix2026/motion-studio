# Sources — scene-grammar demo (portrait)

Demo fixture for the scene-grammar library. The on-screen copy is sample
tech-news text whose claims are attributed to the public pages below. All
media are neutral placeholder SVGs drawn for this repository; no third-party
images or logos are included. Replace them with media you have the right to use.

## Claim sources
| # | Description | URL | What it proves |
|---|-------------|-----|----------------|
| 1 | NVIDIA Blog — Physical AI Takes the Wheel | https://blogs.nvidia.com/blog/robotaxi-leaders-full-stack-open-platform/ | Core claim (attributed to NVIDIA); stack layers; DRIVE Hyperion and DRIVE AGX |
| 2 | NVIDIA — In-vehicle computing | https://www.nvidia.com/en-us/solutions/autonomous-vehicles/in-vehicle-computing/ | DRIVE Hyperion and DRIVE AGX Thor details, sensor counts |
| 3 | NVIDIA — DRIVE Hyperion | https://www.nvidia.com/en-us/solutions/autonomous-vehicles/drive-hyperion/ | Hyperion as a reference compute and sensor architecture |
| 4 | NVIDIA — AI training | https://www.nvidia.com/en-us/solutions/autonomous-vehicles/ai-training/ | Model training on DGX |

## Assets used
| file | type | origin path | direct asset URL | licensing/usage note |
|------|------|-------------|------------------|----------------------|
| `assets/placeholder-hero.svg` | SVG 1280x720 | this repository | — | Project-owned placeholder (Apache-2.0); stands in for a hero image |
| `assets/placeholder-stack.svg` | SVG 1920x1080 | this repository | — | Project-owned placeholder (Apache-2.0); contains the detail board the demo zooms to |
| `assets/placeholder-logo.svg` | SVG | this repository | — | Project-owned placeholder (Apache-2.0); stands in for a brand logo, topbar only |
| `assets/fonts/Alexandria-{arabic,latin}.woff2` | WOFF2 (variable) | https://github.com/google/fonts/tree/main/ofl/alexandria | https://fonts.google.com/specimen/Alexandria | SIL Open Font License 1.1 (`assets/fonts/OFL-Alexandria.txt`); studio typography |

## Audio sources
None (silent demo).

## Notes
- The zoom/highlight region (`data-region="0.53,0.71,0.29,0.195"`) matches the detail board drawn in `placeholder-stack.svg`; update it when you swap the image.
- No tashkeel in any Arabic text.
