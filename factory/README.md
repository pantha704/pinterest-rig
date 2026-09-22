# Pinterest Pin Design Factory

JSON spec in → **1000×1500 PNG pin** out. Six visually distinct templates, OFL Google
Fonts, parametric palettes, real auto-wrap/auto-fit, and rendering at 2× then downscaling
for crisp anti-aliased type.

```
factory/
├── pin_factory.py            # the whole renderer: canvas, text engine, 6 templates, audit
├── fonts/                    # OFL TTFs (Playfair Display, Poppins, Caveat, Inter, DM Serif Display)
├── specs/                    # 14 example JSON specs (2–3 per template)
├── samples/                  # 14 rendered 1000x1500 PNGs + _contact_sheet.png
├── assets/                   # original procedurally-drawn artwork used by the photo template
└── tools/
    ├── fetch_fonts.sh        # (re)download the fonts from the google/fonts repo
    ├── verify_fonts.py       # proves every font style rasterises (no silent system fallback)
    ├── make_sample_artwork.py# draws the original sample artwork (no stock imagery)
    └── verify_samples.py     # independent QA of the rendered PNGs + contact sheet
```

## Quick start

```bash
cd /home/ubuntu/pinterest-rig/factory

# one spec
python3 pin_factory.py render specs/sage-bold-title.json -o samples/pin.png

# every spec in specs/ -> samples/
python3 pin_factory.py render --all

# other useful commands
python3 pin_factory.py list        # templates
python3 pin_factory.py palettes    # palettes
python3 pin_factory.py fonts       # verify font loading + variable axes
python3 pin_factory.py audit --all # render + verify fit/overlap/contrast for every spec
python3 tools/verify_samples.py    # QA the PNGs on disk (+ contact sheet)
python3 tools/verify_fonts.py      # QA the fonts
```

Programmatic use:

```python
from pin_factory import render_spec

img = render_spec({"template": "quote_card", "palette": "editorial",
                   "quote": "Rest is not a reward.", "attribution": "Calm Studio"},
                  "out.png")          # -> PIL image, also saved as a 1000x1500 PNG
```

## The six templates

| template | look | key spec fields |
|---|---|---|
| `bold_title` | Full-width colour block, huge Playfair serif headline, kicker above, label + subtitle below | `kicker`, `title`, `label`, `subtitle`, `block_color`, `block_ink`, `title_max` |
| `pastel_gradient` | Soft multi-stop gradient, blurred blooms, grain, frosted white card with rounded corners | `gradient` (list of hex), `angle`, `chip`, `kicker`, `title`, `subtitle`, `divider`, `dots` |
| `quote_card` | Printed-card feel: hairline frame, oversized italic quote mark, serif quote, **script accent line**, tracked attribution | `quote`, `accent_line` (Caveat), `attribution`, `role`, `quote_mark`, `frame` |
| `listicle` | Colour band with a giant numeral + headline, then numbered rows (badge + item text, separators) | `count`, `headline`, `items` (list), `title`, `band_h`, `band_color`, `item_max` |
| `photo_frame` | Your image in a rounded frame with a soft shadow, badge pill, solid caption bar, padded background | `photo` (required), `fit` (`cover`/`contain`), `badge`, `title`, `subtitle`, `frame`, `frame_radius` |
| `editorial_minimal` | Magazine layout: hairline rules, heavy uppercase tracking, big serif headline, numbered index rows, asymmetric footer | `kicker`, `issue`, `title`, `deck`, `entries` (list), `margin`, `row_h` |

Shared fields: `palette`, `colors` (per-key overrides), `brand`, `handle`/`footer`, `bg`, `grain`.

### Palettes (parametric colour systems)

`sage`, `blush`, `navy`, `lavender`, `terracotta`, `editorial`, `sunset`, `mint`, `mono`, `sky`.
Each palette defines `bg, ink, sub, accent, accent2, surface, gradient[]` and any key can be
overridden per spec:

```json
{ "template": "listicle", "palette": "sunset",
  "colors": { "accent": "#D9532F", "bg": "#FFF8F1" } }
```

Small text (kickers, captions, footers, badges) is passed through `ensure_contrast()` /
`ensure_bg_contrast()`, which walk a colour toward black/white — or step a block a shade
darker — until it clears a contrast target. That is why every sample passes WCAG AA
regardless of palette, and why you can invent a new palette without checking contrast by hand.

## How the renderer works

* **Supersampling.** `Canvas` draws in design coordinates (1000×1500) but rasterises at
  `scale=2` (2000×3000) and downscales with LANCZOS in `render_spec`. `python3
  pin_factory.py render x.json --scale 3` renders even larger before the final resize.
* **Fonts.** `FontBook` resolves a logical style (`display`, `sans_semi`, `ui`, `script`, …)
  to a cached Pillow font. Variable fonts (Playfair, Caveat, Inter) have their `wght`
  (and `opsz`) axes set per request, and axis names are normalised (this build reports
  `b'Weight'`, not `wght`). Missing files fall back to DejaVu/Liberation with a warning —
  see *Fonts & licensing* below.
* **Auto-wrap + auto-fit.** `fit_text()` binary-searches the largest point size whose
  wrapped text fits the box (and `max_lines`); `wrap_text()` handles explicit newlines and
  hard-breaks monster words. All internal measurement is normalised to design pixels via
  `unit_of(font)`, so box math is exact at any supersample factor.
* **Letter-spacing.** Pillow has no native tracking, so `draw_line()` draws glyph by glyph
  with a per-character advance; `wrap_tracked()` measures the same way. `Canvas.tracked()`
  also shrinks the size until a tracked caps line fits its `max_width`.
* **Gradients & shadows.** `linear_gradient()` is numpy-vectorised with a light dither;
  `soft_blob()` and `shadow()` render on a separate RGBA layer and Gaussian-blur it.

## Verification (`audit`)

`python3 pin_factory.py audit --all` re-renders every spec and, for each text box:
plots the tight ink rect, samples the real background with a median ring filter, computes
the WCAG contrast ratio, and fails on text that escapes its box/canvas, overlaps another
text box, or drops under `--min-contrast` (default 4.5). Current state:

```
14/14 specs OK · 12–18 text boxes each · min text contrast 4.72:1 · all 1000x1500
```

`tools/verify_samples.py` re-checks the PNGs on disk independently (size, mode, ink,
colour variety, tonal span, edge bleed, per-template counts, duplicate hashes,
cross-template perceptual distinctness) and writes `samples/_contact_sheet.png`.

## Adding a template

1. Write a function registered with the decorator — it receives a `Canvas` and the spec
   dict, and draws in 1000×1500 design coordinates:

```python
@template("my_layout", "One-line description shown by `pin_factory.py list`")
def tpl_my_layout(c: Canvas, spec: dict) -> None:
    p = c.palette
    c.fill(p["bg"])
    c.rect((0, 0, c.w, 420), ensure_bg_contrast(p["accent"], "#FFFFFF", 5.0))
    c.fitted(spec["title"], (88, 500, c.w - 88, 1000), style="display", max_size=120,
             min_size=40, leading=1.08, color=ensure_contrast(p["ink"], p["bg"], 7.0),
             align="left", role="title")          # role= shows up in audit output
    brand_footer(c, spec, y=c.h - 92, color=ensure_contrast(p["sub"], p["bg"], 5.0))
```

2. Add `specs/my-layout.json` with `{"template": "my_layout", ...}`.
3. `python3 pin_factory.py render specs/my-layout.json && python3 pin_factory.py audit specs/my-layout.json`.
4. `python3 tools/verify_samples.py` to refresh the contact sheet.

Useful `Canvas` API: `fill`, `rect`, `circle`, `line`, `polygon`, `linear_gradient`,
`soft_blob`, `grain`, `shadow`, `photo`, `text`, `tracked`, `fitted`, `measure_tracked`.
Anything the templates need but don't have belongs on `Canvas`, not in a template.

Helper reference:

| helper | purpose |
|---|---|
| `c.fitted(text, box, style=..., max_size=..., min_size=..., leading=..., max_lines=..., align=..., valign=..., role=...)` | auto-wrap + auto-fit + draw; returns the `FittedText` (`lines`, `size`, `width`, `height`) |
| `c.tracked(text, center, size=..., tracking=..., max_width=..., anchor=..., role=...)` | uppercased, letter-spaced label that shrinks to fit |
| `c.photo(path, box, fit="cover", radius=..., shadow=True, ...)` | crop/letterbox an image into a box with rounded corners and a soft shadow |
| `ensure_contrast(fg, bg, target)` / `ensure_bg_contrast(bg, ink, target)` | keep small type legible on any palette |
| `mix(a, b, t)`, `with_alpha(hex, a)`, `readable_on(bg)`, `contrast_ratio(fg, bg)` | colour utilities |

## Fonts & licensing

All five families are SIL Open Font License 1.1 (Google Fonts). TTFs live in `fonts/`,
with the licence text per family in `fonts/licenses/`.

| family | file(s) | used for |
|---|---|---|
| Playfair Display | `PlayfairDisplay-VF.ttf`, `PlayfairDisplay-Italic-VF.ttf` | `display`, `display_black`, `display_italic` |
| Poppins | `Poppins-{Light,Regular,Medium,SemiBold,Bold,ExtraBold,Italic,BoldItalic}.ttf` | `sans*` |
| Caveat | `Caveat-VF.ttf` | `script`, `script_light` |
| Inter | `Inter-VF.ttf`, `Inter-Italic-VF.ttf` | `ui*` |
| DM Serif Display | `DMSerifDisplay-Regular.ttf`, `DMSerifDisplay-Italic.ttf` | `serif`, `serif_italic` |

Re-download anytime with `bash tools/fetch_fonts.sh` (sources:
`raw.githubusercontent.com/google/fonts/main/ofl/...`); each file is checked for HTTP 200
and non-zero size. `python3 tools/verify_fonts.py` then proves that every style loads the
*expected* file (catching silent fallbacks), applies its variable axes, and puts real ink
on the canvas; it writes `fonts/_contact_sheet.png`.

**Fallback behaviour:** if a TTF is missing, `FontBook` warns and uses
`/usr/share/fonts/truetype/dejavu/…` (or Liberation) so rendering never hard-fails. This did
not trigger for any sample here — all 15 TTFs downloaded and all 17 styles verified —
but it is why a degraded render still produces output instead of an exception.

## Imagery policy

`assets/` contains only original artwork generated by `tools/make_sample_artwork.py`
(procedural Pillow/numpy drawings: arches, waves, still life, tiles, blooms). No stock
photos, no scraped images — swap in your own artwork via the `photo` field.

## Notes / gotchas

* Render time is ~1–3 s per pin at `scale=2` (mostly the LANCZOS downscale and gradients).
* Spec numbers are JSON, so `"frame": [132, 196, 868, 1004]` needs no conversion; `frame`
  is `[x0, y0, x1, y1]` in design px.
* Grain and gradient dithering are seeded, so renders are deterministic — re-running
  `render --all` produces byte-identical PNGs (verified by hash in `verify_samples.py`).
