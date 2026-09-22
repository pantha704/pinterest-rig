#!/usr/bin/env python3
"""
pin_factory.py — a small, dependency-light Pinterest pin design factory.

    JSON spec  ->  1000x1500 PNG pin

Design goals
------------
* Six visually distinct templates (see TEMPLATES below).
* Everything is parametric: palettes are colour dicts, specs override them.
* Every text block auto-wraps and auto-fits (binary search on point size) so a
  long headline can never overflow or get clipped.
* Rendering happens at 2x (2000x3000) and is downscaled with LANCZOS, which is
  what gives clean anti-aliased type and soft shadows at the 1000x1500 target.
* Fonts are OFL Google Fonts stored in ./fonts (see tools/fetch_fonts.sh).

Usage
-----
    python3 pin_factory.py render specs/sage-bold-title.json
    python3 pin_factory.py render --all specs/ --outdir samples/
    python3 pin_factory.py list
    python3 pin_factory.py fonts

Programmatic
------------
    from pin_factory import render_spec
    render_spec({"template": "bold_title", "title": "Hello"}, "out.png")
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import textwrap
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required:  pip install pillow")

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy only accelerates gradients
    np = None

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

HERE = Path(__file__).resolve().parent
FONT_DIR = Path(os.environ.get("PIN_FACTORY_FONTS", HERE / "fonts"))
CACHE_DIR = HERE / "samples"

BASE_W, BASE_H = 1000, 1500          # Pinterest's 2:3 native pin size
DEFAULT_SCALE = 2                    # supersample factor -> 2000x3000 render

# Fallback faces if a downloaded TTF is missing (documented in README).
FALLBACK_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FALLBACK_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FALLBACK_SERIF = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]

_MISSING_FONTS: set[str] = set()


# --------------------------------------------------------------------------- #
# Colour helpers
# --------------------------------------------------------------------------- #

def hex2rgb(value: str) -> tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        raise ValueError(f"bad hex colour: {value!r}")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgba(value: str | Sequence, alpha: int | None = None) -> tuple[int, int, int, int]:
    """Accept '#rrggbb', '#rrggbbaa', (r,g,b) or (r,g,b,a)."""
    if isinstance(value, (tuple, list)):
        t = tuple(int(c) for c in value)
        if len(t) == 3:
            return (t[0], t[1], t[2], 255 if alpha is None else alpha)
        return (t[0], t[1], t[2], t[3] if alpha is None else alpha)
    v = value.strip().lstrip("#")
    if len(v) == 8:
        r, g, b, a = (int(v[i:i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a if alpha is None else alpha)
    r, g, b = hex2rgb(value)
    return (r, g, b, 255 if alpha is None else alpha)


def alpha_of(value: str, alpha: int) -> tuple[int, int, int, int]:
    r, g, b = hex2rgb(value[:7] if len(value) > 7 else value)
    return (r, g, b, alpha)


def with_alpha(value: str, alpha: int) -> str:
    """'#rrggbb' -> '#rrggbbaa' (clamped 0..255), for translucent fills."""
    r, g, b = hex2rgb(value[:7] if len(value) > 7 else value)
    return "#%02x%02x%02x%02x" % (r, g, b, max(0, min(255, int(alpha))))


def mix(c1: str, c2: str, t: float) -> str:
    """Linear blend of two hex colours, t=0 -> c1, t=1 -> c2."""
    a, b = hex2rgb(c1), hex2rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def luminance(value: str) -> float:
    r, g, b = (c / 255 for c in hex2rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(bg: str, light: str = "#FFFFFF", dark: str = "#141414") -> str:
    """Pick the higher-contrast text colour for a background."""
    return dark if luminance(bg) > 0.55 else light


def _linear(channel: float) -> float:
    channel /= 255.0
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def rel_luminance(rgb: Sequence[int]) -> float:
    """WCAG relative luminance of an (r, g, b) triple."""
    r, g, b = (_linear(float(c)) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: Sequence[int], bg: Sequence[int]) -> float:
    """WCAG contrast ratio, 1.0 .. 21.0."""
    lo, hi = sorted((rel_luminance(fg), rel_luminance(bg)))
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg: str, bg: str, target: float = 4.5) -> str:
    """Nudge `fg` toward black/white until it hits `target` contrast on `bg`.

    Keeps small type (kickers, captions, footers) legible on any palette
    without hand-tuning every colour: the palette keeps its hue, only the
    lightness moves.
    """
    if contrast_ratio(hex2rgb(fg), hex2rgb(bg)) >= target:
        return fg
    for direction in ("#000000", "#FFFFFF"):
        for step in range(1, 21):
            candidate = mix(fg, direction, step / 20)
            if contrast_ratio(hex2rgb(candidate), hex2rgb(bg)) >= target:
                return candidate
    return "#000000" if luminance(bg) > 0.5 else "#FFFFFF"


def ensure_bg_contrast(bg: str, ink: str = "#FFFFFF", target: float = 4.6) -> str:
    """Darken/lighten a background until `ink` clears `target` contrast on it.

    Used for colour-block headlines and caption bars: instead of flipping the
    text to black (which kills the palette), the block itself steps a shade
    darker until white type is safe on it.
    """
    if contrast_ratio(hex2rgb(ink), hex2rgb(bg)) >= target:
        return bg
    directions = ("#FFFFFF", "#000000") if luminance(bg) < 0.5 else ("#000000", "#FFFFFF")
    for direction in directions:
        for step in range(1, 25):
            candidate = mix(bg, direction, step / 24)
            if contrast_ratio(hex2rgb(ink), hex2rgb(candidate)) >= target:
                return candidate
    return bg


# --------------------------------------------------------------------------- #
# Palettes — fully parametric colour systems
# --------------------------------------------------------------------------- #

PALETTES: dict[str, dict[str, Any]] = {
    "sage": {
        "bg": "#F4F1E8", "ink": "#1F2A24", "sub": "#5A6A60",
        "accent": "#2F6F52", "accent2": "#C98A5B", "surface": "#FFFFFF",
        "gradient": ["#E7EFE6", "#CFE0D3", "#A9C4B0"],
    },
    "blush": {
        "bg": "#FDF3F1", "ink": "#3A2126", "sub": "#8A6A70",
        "accent": "#C25B6A", "accent2": "#E2A76F", "surface": "#FFFFFF",
        "gradient": ["#FCE7E9", "#F6D2D6", "#EFB8C4"],
    },
    "navy": {
        "bg": "#0E2036", "ink": "#F2F5FA", "sub": "#A9BBD4",
        "accent": "#F2C14E", "accent2": "#5EC4B6", "surface": "#162C48",
        "gradient": ["#122741", "#1B3A5C", "#0B1826"],
    },
    "lavender": {
        "bg": "#F6F3FC", "ink": "#2A2340", "sub": "#6C6390",
        "accent": "#7C5CE0", "accent2": "#F0A6C0", "surface": "#FFFFFF",
        "gradient": ["#EFE7FC", "#DFD3FA", "#C6B4F2"],
    },
    "terracotta": {
        "bg": "#FBF1E9", "ink": "#3B2318", "sub": "#8A6552",
        "accent": "#C0603C", "accent2": "#3E7C6A", "surface": "#FFFFFF",
        "gradient": ["#FBE3D3", "#F4C9AE", "#E5A57F"],
    },
    "editorial": {
        "bg": "#FBFAF7", "ink": "#121212", "sub": "#6B6B6B",
        "accent": "#121212", "accent2": "#B08D57", "surface": "#FFFFFF",
        "gradient": ["#F5F3EE", "#EAE6DE", "#DCD6CB"],
    },
    "sunset": {
        "bg": "#FFF6EB", "ink": "#38230F", "sub": "#8B6B47",
        "accent": "#E8663C", "accent2": "#F2A93B", "surface": "#FFFFFF",
        "gradient": ["#FFE9C7", "#FBC79A", "#F29E7A"],
    },
    "mint": {
        "bg": "#F0FAF7", "ink": "#12312B", "sub": "#4E7268",
        "accent": "#1E9E82", "accent2": "#F2B441", "surface": "#FFFFFF",
        "gradient": ["#DDF6EE", "#BEEBE0", "#9FDCCE"],
    },
    "mono": {
        "bg": "#F5F5F3", "ink": "#111111", "sub": "#6E6E6E",
        "accent": "#111111", "accent2": "#9AA0A6", "surface": "#FFFFFF",
        "gradient": ["#EDEDEB", "#DCDCDA", "#C7C7C4"],
    },
    "sky": {
        "bg": "#F2F7FD", "ink": "#14263B", "sub": "#5C7391",
        "accent": "#2E6FC7", "accent2": "#59B3D6", "surface": "#FFFFFF",
        "gradient": ["#E2EFFC", "#C7E1F8", "#A8CCF0"],
    },
}

RESERVED_COLOR_KEYS = set().union(*(p.keys() for p in PALETTES.values()))


def resolve_palette(spec: dict) -> dict:
    """Palette name -> colour dict, then apply per-spec overrides."""
    name = spec.get("palette", "sage")
    if name not in PALETTES:
        raise KeyError(f"unknown palette {name!r}; known: {', '.join(sorted(PALETTES))}")
    palette = dict(PALETTES[name])
    palette["name"] = name
    overrides = dict(spec.get("colors", {}))
    for key, value in overrides.items():
        palette[key] = value
    # convenience: gradient may be given as a single hex (flat) or a list
    grad = palette.get("gradient")
    if isinstance(grad, str):
        palette["gradient"] = [grad, grad]
    return palette


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #

# family -> spec.  'vf' entries are variable fonts; we set the wght axis.
FAMILIES: dict[str, dict[str, Any]] = {
    "playfair": {
        "vf": {"normal": "PlayfairDisplay-VF.ttf", "italic": "PlayfairDisplay-Italic-VF.ttf"},
        "axes": {"wght": {"400": 400, "500": 500, "600": 600, "700": 700, "800": 800, "900": 900}},
        "fallback": FALLBACK_SERIF,
    },
    "poppins": {
        "static": {
            (400, False): "Poppins-Regular.ttf",
            (300, False): "Poppins-Light.ttf",
            (500, False): "Poppins-Medium.ttf",
            (600, False): "Poppins-SemiBold.ttf",
            (700, False): "Poppins-Bold.ttf",
            (800, False): "Poppins-ExtraBold.ttf",
            (400, True): "Poppins-Italic.ttf",
            (700, True): "Poppins-BoldItalic.ttf",
        },
        "fallback": FALLBACK_REGULAR,
    },
    "caveat": {
        "vf": {"normal": "Caveat-VF.ttf", "italic": "Caveat-VF.ttf"},
        "axes": {"wght": {"400": 400, "500": 500, "600": 600, "700": 700}},
        "fallback": FALLBACK_REGULAR,
    },
    "inter": {
        "vf": {"normal": "Inter-VF.ttf", "italic": "Inter-Italic-VF.ttf"},
        "axes": {
            "wght": {"300": 300, "400": 400, "500": 500, "600": 600, "700": 700, "800": 800, "900": 900},
            "opsz": {"14": 14, "32": 32},
        },
        "fallback": FALLBACK_REGULAR,
    },
    "dmserif": {
        "static": {
            (400, False): "DMSerifDisplay-Regular.ttf",
            (700, False): "DMSerifDisplay-Regular.ttf",
            (400, True): "DMSerifDisplay-Italic.ttf",
        },
        "fallback": FALLBACK_SERIF,
    },
}

# logical style name -> (family, weight, italic) used by templates
STYLES: dict[str, tuple[str, int, bool]] = {
    "display": ("playfair", 800, False),
    "display_black": ("playfair", 900, False),
    "display_italic": ("playfair", 700, True),
    "serif": ("dmserif", 400, False),
    "serif_italic": ("dmserif", 400, True),
    "sans": ("poppins", 400, False),
    "sans_medium": ("poppins", 500, False),
    "sans_semi": ("poppins", 600, False),
    "sans_bold": ("poppins", 700, False),
    "sans_black": ("poppins", 800, False),
    "sans_italic": ("poppins", 400, True),
    "script": ("caveat", 700, False),
    "script_light": ("caveat", 400, False),
    "ui": ("inter", 400, False),
    "ui_medium": ("inter", 500, False),
    "ui_semi": ("inter", 600, False),
    "ui_bold": ("inter", 700, False),
}

AXIS_ALIASES = {
    "wght": "wght", "weight": "wght",
    "opsz": "opsz", "optical size": "opsz", "opticalsize": "opsz",
    "wdth": "wdth", "width": "wdth",
    "slnt": "slnt", "slant": "slnt", "ital": "ital", "italic": "ital",
}


def _axis_name(raw: Any) -> str:
    name = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
    key = name.strip().lower()
    return AXIS_ALIASES.get(key, key)


def unit_of(font: ImageFont.FreeTypeFont) -> float:
    """Supersample factor a font was loaded at (1.0 for unscaled fonts).

    All text measurement helpers divide by this so callers can think purely in
    design pixels (1000x1500) even though glyphs are rasterised at 2x.
    """
    return float(getattr(font, "_pin_scale", 1.0) or 1.0)


def _font_paths(family: str, weight: int, italic: bool) -> list[str]:
    cfg = FAMILIES.get(family)
    if cfg is None:
        raise KeyError(f"unknown font family {family!r}")
    paths: list[str] = []
    if "static" in cfg:
        table = cfg["static"]
        exact = table.get((weight, italic))
        same_style = [p for (w, it), p in table.items() if it == italic]
        nearest = min(same_style, key=lambda p: abs(table_key_weight(table, p, weight))) if same_style else None
        for candidate in (exact, nearest):
            if candidate and candidate not in paths:
                paths.append(candidate)
    for style_key in (("italic" if italic else "normal"), "normal"):
        vf = cfg.get("vf", {}).get(style_key)
        if vf and vf not in paths:
            paths.append(vf)
    fallback = cfg.get("fallback", FALLBACK_REGULAR)
    paths.extend(fallback if isinstance(fallback, list) else [fallback])
    return paths


def table_key_weight(table: dict, path: str, weight: int) -> int:
    for (w, _it), p in table.items():
        if p == path:
            return w - weight
    return 0


class FontBook:
    """Loads and caches Pillow fonts, applying variable-font axes."""

    def __init__(self, font_dir: Path | str = FONT_DIR, scale: int = DEFAULT_SCALE):
        self.dir = Path(font_dir)
        self.scale = scale
        self._cache: dict[tuple, ImageFont.FreeTypeFont] = {}

    # -- public ------------------------------------------------------------ #
    def get(self, style: str = "sans", size: int = 40, weight: int | None = None,
            family: str | None = None, italic: bool | None = None) -> ImageFont.FreeTypeFont:
        """Resolve a logical style ('display', 'sans_bold', ...) to a Pillow font.

        `family` / `weight` / `italic` override the style's defaults.
        Size is in DESIGN pixels; the returned font is scaled for supersampling.
        """
        fam, wgt, ital = STYLES.get(style, STYLES["sans"])
        fam = family or fam
        wgt = wgt if weight is None else weight
        ital = ital if italic is None else italic
        px = max(6, int(round(size * self.scale)))
        key = (fam, wgt, ital, px)
        if key in self._cache:
            return self._cache[key]
        font = self._load(fam, wgt, ital, px)
        font._pin_scale = self.scale  # type: ignore[attr-defined]
        self._cache[key] = font
        return font

    # -- internals --------------------------------------------------------- #
    def _load(self, family: str, weight: int, italic: bool, px: int) -> ImageFont.FreeTypeFont:
        for rel in _font_paths(family, weight, italic):
            path = self.dir / rel if not os.path.isabs(rel) else Path(rel)
            if not path.exists():
                if str(path) not in _MISSING_FONTS:
                    _MISSING_FONTS.add(str(path))
                continue
            try:
                used = path
                font = ImageFont.truetype(str(used), px)
                if os.path.isabs(rel) and not str(path).startswith(str(self.dir)):
                    warnings.warn(f"font {family} missing in {self.dir}; using system fallback {used.name}")
                if self._apply_axes(font, family, weight):
                    pass
                return font
            except Exception as exc:  # pragma: no cover
                warnings.warn(f"font load failed for {path.name}: {exc}")
                continue
        raise FileNotFoundError(
            f"no usable font for family={family!r}. Run tools/fetch_fonts.sh to populate {self.dir}"
        )

    def _apply_axes(self, font: ImageFont.FreeTypeFont, family: str, weight: int) -> bool:
        cfg = FAMILIES.get(family, {})
        wanted = dict(cfg.get("axes", {}).get("wght", {}))
        if not wanted:
            return False
        try:
            axes = font.get_variation_axes()
        except Exception:
            return False
        if not axes:
            return False
        order: list[str] = []
        values: list[float] = []
        for axis in axes:
            name = _axis_name(axis.get("name", ""))
            order.append(name)
            if name == "wght":
                values.append(float(wanted.get(str(weight), weight)))
            elif name == "opsz":
                values.append(float(axis.get("default", 32)))
            else:
                values.append(float(axis.get("default", 0)))
        try:
            font.set_variation_by_axes(values)
            font._pin_axes = dict(zip(order, values))  # type: ignore[attr-defined]
            return True
        except Exception as exc:  # pragma: no cover
            warnings.warn(f"variation axes failed for {family} {weight}: {exc}")
            return False


# --------------------------------------------------------------------------- #
# Text engine: wrap, fit, draw
# --------------------------------------------------------------------------- #

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Greedy word wrap that honours explicit newlines and breaks monster words.

    `max_width` is in DESIGN px; glyph advances are converted with `unit_of`.
    """
    u = unit_of(font)
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            probe = f"{current} {word}".strip()
            if font.getlength(probe) / u <= max_width or not current:
                if font.getlength(probe) / u > max_width and not current:
                    # single word wider than the box -> hard character break
                    chunk = ""
                    for ch in word:
                        if font.getlength(chunk + ch) / u <= max_width or not chunk:
                            chunk += ch
                        else:
                            lines.append(chunk)
                            chunk = ch
                    current = chunk
                else:
                    current = probe
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def block_height(lines: Sequence[str], font: ImageFont.FreeTypeFont, leading: float) -> float:
    return len(lines) * font.size * leading


def _measure_block(font: ImageFont.FreeTypeFont, text: str, max_width: float,
                   leading: float, tracked: float = 0.0) -> tuple[list[str], float, float]:
    """-> (lines, widest line, block height) with all lengths in DESIGN px."""
    u = unit_of(font)
    lines = wrap_text(text, font, max_width) if not tracked else wrap_tracked(text, font, max_width, tracked)
    h = len(lines) * (font.size / u) * leading
    w = max((line_width(line, font, tracked) / u for line in lines), default=0.0)
    return lines, w, h


def line_width(line: str, font: ImageFont.FreeTypeFont, tracking: float = 0.0) -> float:
    """Width of one line in FONT pixels (callers convert with unit_of)."""
    if not tracking or not line:
        return font.getlength(line)
    return sum(font.getlength(ch) for ch in line) + tracking * (len(line) - 1)


def wrap_tracked(text: str, font: ImageFont.FreeTypeFont, max_width: float, tracking: float) -> list[str]:
    """Word wrap accounting for letter spacing; `max_width` in design px."""
    u = unit_of(font)
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = f"{current} {word}".strip()
        if line_width(probe, font, tracking) / u <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


@dataclass
class FittedText:
    """Result of an auto-fit: the font to use plus the wrapped lines."""
    font: ImageFont.FreeTypeFont
    lines: list[str]
    size: int
    leading: float
    width: float
    height: float
    line_gap: float
    tracking: float = 0.0

    @property
    def line_height(self) -> float:
        return self.size * self.leading


def fit_text(book: FontBook, text: str, *, style: str = "sans", box_w: float, box_h: float,
             max_size: int = 120, min_size: int = 12, leading: float = 1.15,
             max_lines: int | None = None, tracking: float = 0.0,
             weight: int | None = None, family: str | None = None,
             italic: bool | None = None) -> FittedText:
    """Largest point size (design px) whose wrapped text fits box_w x box_h.

    Binary search on size; the predicate is monotonic because larger type
    produces more lines and taller blocks. Falls back to min_size, which is
    always returned even if it technically overflows (never raises on text).
    """
    text = str(text)
    tracking = float(tracking)
    lo, hi = int(min_size), int(max_size)
    best: FittedText | None = None

    def evaluate(size: int) -> FittedText:
        font = book.get(style, size, weight=weight, family=family, italic=italic)
        # tracking is proportional to size so it scales with the type
        tr = tracking * size if tracking else 0.0
        lines, w, h = _measure_block(font, text, box_w, leading, tr)
        return FittedText(font=font, lines=lines, size=size, leading=leading,
                          width=w, height=h, line_gap=size * leading, tracking=tr)

    def ok(cand: FittedText) -> bool:
        if max_lines is not None and len(cand.lines) > max_lines:
            return False
        return cand.height <= box_h and cand.width <= box_w + 0.5

    # binary search for the largest fitting size
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = evaluate(mid)
        if ok(cand):
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        best = evaluate(min_size)
    return best


def draw_line(canvas: "Canvas", xy: tuple[float, float], text: str, font: ImageFont.FreeTypeFont,
              fill: Any, anchor: str = "la", tracking: float = 0.0, spacing: float | None = None) -> None:
    """Draw one line of text; supports manual letter-spacing via `tracking`."""
    x, y = canvas.S(xy)
    if not tracking:
        canvas.draw.text((x, y), text, font=font, fill=fill, anchor=anchor)
        return
    total = line_width(text, font, tracking)
    # horizontal placement mirroring Pillow's anchor semantics (centred/right)
    ax = anchor[0]
    if ax == "m":
        x -= total / 2
    elif ax == "r":
        x -= total
    cursor = x
    for ch in text:
        canvas.draw.text((cursor, y), ch, font=font, fill=fill, anchor="l" + anchor[1])
        cursor += font.getlength(ch) + tracking


def draw_block(canvas: "Canvas", fitted: FittedText, box: tuple[float, float, float, float],
               fill: Any, align: str = "center", valign: str = "center",
               gap_scale: float = 1.0, role: str = "text") -> float:
    """Lay a FittedText block inside `box` (design coords). Returns the bottom y."""
    x0, y0, x1, y1 = box
    lh = fitted.line_height * gap_scale
    total = lh * len(fitted.lines)
    if valign == "top":
        y = y0
    elif valign == "bottom":
        y = y1 - total
    else:
        y = y0 + (y1 - y0 - total) / 2
    if align == "center":
        ax, cx = "mm", (x0 + x1) / 2
    elif align == "right":
        ax, cx = "rm", x1
    else:
        ax, cx = "lm", x0
    # record the tight ink rectangle for auditing (design coords)
    ink_w = max((line_width(line, fitted.font, fitted.tracking) for line in fitted.lines), default=0.0) / canvas.scale
    if align == "center":
        rx0 = cx - ink_w / 2
    elif align == "right":
        rx0 = cx - ink_w
    else:
        rx0 = cx
    canvas.text_log.append({
        "role": role, "text": " ".join(fitted.lines).replace("\n", " ")[:120], "lines": len(fitted.lines),
        "size": fitted.size, "style": fitted.font._pin_style if hasattr(fitted.font, "_pin_style") else "",
        "rect": (rx0, y, rx0 + ink_w, y + total),
        "box": box, "fill": rgba(fill), "fill_ratio": (ink_w * total) / max(1.0, (x1 - x0) * (y1 - y0)),
    })
    for line in fitted.lines:
        draw_line(canvas, (cx, y + lh / 2), line, fitted.font, fill, anchor=ax, tracking=fitted.tracking)
        y += lh
    return y


# --------------------------------------------------------------------------- #
# Canvas + drawing primitives (all coordinates are DESIGN coordinates)
# --------------------------------------------------------------------------- #

class Canvas:
    """A supersampled RGBA canvas that speaks 1000x1500 design coordinates."""

    def __init__(self, palette: dict, scale: int = DEFAULT_SCALE,
                 size: tuple[int, int] = (BASE_W, BASE_H)):
        self.palette = palette
        self.scale = scale
        self.w, self.h = size
        self.img = Image.new("RGBA", (self.w * scale, self.h * scale), rgba(palette["bg"]))
        self.draw = ImageDraw.Draw(self.img, "RGBA")
        self.book = FontBook(scale=scale)
        # every text draw is recorded here (design coords) so the layout can be
        # audited after rendering: bounds, fit ratio, declared colours.
        self.text_log: list[dict] = []

    # -- geometry ---------------------------------------------------------- #
    def S(self, xy: tuple[float, float]) -> tuple[float, float]:
        return (xy[0] * self.scale, xy[1] * self.scale)

    def s(self, v: float) -> float:
        return v * self.scale

    def box(self, xy: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        return tuple(v * self.scale for v in xy)  # type: ignore[return-value]

    # -- solid + shapes ---------------------------------------------------- #
    def fill(self, color: str) -> None:
        self.draw.rectangle([0, 0, self.img.width, self.img.height], fill=rgba(color))

    def rect(self, xy, color, outline=None, width=0, radius=0) -> None:
        b = self.box(xy)
        fill = rgba(color) if color else None
        line = rgba(outline) if outline else None
        if radius:
            self.draw.rounded_rectangle(b, radius=self.s(radius), fill=fill, outline=line,
                                        width=int(self.s(width)) if width else 0)
        else:
            self.draw.rectangle(b, fill=fill, outline=line,
                                width=int(self.s(width)) if width else 0)

    def circle(self, center, r, color, outline=None, width=0) -> None:
        cx, cy = self.S(center)
        b = [cx - self.s(r), cy - self.s(r), cx + self.s(r), cy + self.s(r)]
        self.draw.ellipse(b, fill=rgba(color) if color else None,
                          outline=rgba(outline) if outline else None,
                          width=int(self.s(width)) if width else 0)

    def line(self, p0, p1, color, width=1.0) -> None:
        self.draw.line([self.S(p0), self.S(p1)], fill=rgba(color), width=max(1, int(self.s(width))))

    def polygon(self, points, color) -> None:
        self.draw.polygon([self.S(p) for p in points], fill=rgba(color))

    # -- gradients --------------------------------------------------------- #
    def linear_gradient(self, stops: Sequence[str], xy=(0, 0, BASE_W, BASE_H), angle: float = 135.0,
                        dither: int = 3) -> None:
        """Paint a linear gradient into `xy`. angle in degrees: 0 = left->right."""
        x0, y0, x1, y1 = [int(self.s(v)) for v in xy]
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        stops = list(stops) or [self.palette["bg"]]
        if len(stops) == 1:
            self.draw.rectangle([x0, y0, x1, y1], fill=rgba(stops[0]))
            return
        colors = [hex2rgb(s) for s in stops]
        if np is not None:
            theta = math.radians(angle)
            dx, dy = math.cos(theta), math.sin(theta)
            ys, xs = np.mgrid[0:h, 0:w]
            proj = xs * dx + ys * dy
            lo, hi = float(proj.min()), float(proj.max())
            t = (proj - lo) / max(1e-6, hi - lo)
            pos = np.linspace(0.0, 1.0, len(colors))
            arr = np.zeros((h, w, 3), dtype=np.float32)
            for c in range(3):
                arr[..., c] = np.interp(t, pos, [col[c] for col in colors])
            if dither:
                arr += np.random.default_rng(7).integers(-dither, dither + 1, arr.shape[:2])[..., None]
            tile = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")
        else:  # pragma: no cover - numpy fallback
            tile = Image.new("RGB", (1, h))
            px = tile.load()
            for y in range(h):
                t = y / max(1, h - 1)
                seg = t * (len(colors) - 1)
                i = min(int(seg), len(colors) - 2)
                f = seg - i
                px[0, y] = tuple(round(colors[i][c] + (colors[i + 1][c] - colors[i][c]) * f) for c in range(3))
        self.img.paste(tile.convert("RGBA"), (x0, y0))

    def soft_blob(self, center, radius, color, alpha=70, blur=None) -> None:
        """A blurred colour blob — the 'aesthetic' soft shapes."""
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = self.S(center)
        r = self.s(radius)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=alpha_of(color, alpha))
        layer = layer.filter(ImageFilter.GaussianBlur(self.s(blur if blur is not None else radius * 0.45)))
        self.img.alpha_composite(layer)

    def grain(self, amount: int = 8) -> None:
        """Subtle paper grain; keeps big flat fields from looking synthetic."""
        if np is None:
            return
        rng = np.random.default_rng(11)
        small = rng.normal(0, amount, (self.h // 3, self.w // 3)).astype("float32")
        noise = Image.fromarray(np.clip(128 + small, 0, 255).astype("uint8"), "L").resize(self.img.size, Image.BILINEAR)
        layer = Image.merge("RGBA", (noise, noise, noise, Image.new("L", self.img.size, 26)))
        base = self.img.copy()
        self.img = Image.blend(base, Image.alpha_composite(base, layer), 0.55)
        self.draw = ImageDraw.Draw(self.img, "RGBA")

    # -- shadows ----------------------------------------------------------- #
    def shadow(self, xy, blur=24, offset=(0, 10), alpha=60, radius=0, spread=0) -> None:
        x0, y0, x1, y1 = self.box(xy)
        pad = self.s(blur * 3)
        layer = Image.new("L", (int(x1 - x0 + pad * 2), int(y1 - y0 + pad * 2)), 0)
        d = ImageDraw.Draw(layer)
        b = [pad, pad, pad + (x1 - x0), pad + (y1 - y0)]
        if spread:
            b = [b[0] - self.s(spread), b[1] - self.s(spread), b[2] + self.s(spread), b[3] + self.s(spread)]
        if radius:
            d.rounded_rectangle(b, radius=self.s(radius), fill=alpha)
        else:
            d.rectangle(b, fill=alpha)
        layer = layer.filter(ImageFilter.GaussianBlur(self.s(blur)))
        shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        shadow.putalpha(layer)
        self.img.alpha_composite(shadow, (int(x0 - pad + self.s(offset[0])), int(y0 - pad + self.s(offset[1]))))

    # -- images ------------------------------------------------------------ #
    def photo(self, path: Path | str, xy, fit: str = "cover", radius: int = 0,
              shadow: bool = True, shadow_blur: int = 22, shadow_offset=(0, 12),
              border: str | None = None, border_width: int = 0) -> None:
        """Place a photo (contain/cover) inside xy with optional rounded corners."""
        src = Image.open(path).convert("RGB")
        x0, y0, x1, y1 = xy
        tw, th = x1 - x0, y1 - y0
        pw, ph = int(self.s(tw)), int(self.s(th))
        sw, sh = src.size
        if fit == "cover":
            ratio = max(pw / sw, ph / sh)
            new = (max(1, round(sw * ratio)), max(1, round(sh * ratio)))
            src = src.resize(new, Image.LANCZOS)
            left = (new[0] - pw) // 2
            top = int((new[1] - ph) * float(os.environ.get("PIN_PHOTO_FOCUS", "0.42")))
            src = src.crop((left, top, left + pw, top + ph))
        else:
            ratio = min(pw / sw, ph / sh)
            new = (max(1, round(sw * ratio)), max(1, round(sh * ratio)))
            src = src.resize(new, Image.LANCZOS)
            plate = Image.new("RGB", (pw, ph), hex2rgb(self.palette.get("surface", "#FFFFFF")))
            plate.paste(src, ((pw - new[0]) // 2, (ph - new[1]) // 2))
            src = plate
        if radius:
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=self.s(radius), fill=255)
        else:
            mask = None
        if shadow:
            self.shadow((x0, y0, x1, y1), blur=shadow_blur, offset=shadow_offset, alpha=64, radius=radius)
        self.img.paste(src, (int(self.s(x0)), int(self.s(y0))), mask)
        if border and border_width:
            self.rect(xy, None, outline=border, width=border_width, radius=radius)

    # -- text -------------------------------------------------------------- #
    def text(self, xy, text: str, style="sans", size=32, color=None, anchor="la",
             tracking=0.0, weight=None, family=None, italic=None, role: str = "text") -> None:
        font = self.book.get(style, size, weight=weight, family=family, italic=italic)
        font._pin_style = style  # type: ignore[attr-defined]
        fill = rgba(color or self.palette["ink"])
        tr = self.s(tracking * size if tracking else 0)
        draw_line(self, xy, str(text), font, fill, anchor=anchor, tracking=tr)
        self.text_log.append({
            "role": role, "text": str(text).replace("\n", " ")[:120], "lines": 1, "size": size,
            "style": style,
            "rect": self._text_rect(str(text), font, xy, anchor, tr),
            "box": None, "fill": fill, "fill_ratio": None,
        })

    def _text_rect(self, text: str, font, xy, anchor: str, tracking: float) -> tuple:
        """Approximate ink rect of a single-line draw, in DESIGN coords."""
        s = self.scale  # font metrics are in supersampled px; convert to design px
        w = line_width(text, font, tracking) / s
        ax, ay = anchor[0], (anchor[1] if len(anchor) > 1 else "a")
        x0 = xy[0] if ax == "l" else (xy[0] - w / 2 if ax == "m" else xy[0] - w)
        asc, desc = (m / s for m in font.getmetrics())
        top = {"a": 0.0, "t": 0.0, "m": -(asc - desc) / 2.0, "s": -asc, "b": -asc, "d": asc}.get(ay, 0.0)
        y0 = xy[1] + top
        return (x0, y0, x0 + w, y0 + asc + desc) if ay != "d" else (x0, y0 - desc, x0 + w, y0)

    def fitted(self, text: str, box, style="sans", max_size=120, min_size=14, leading=1.15,
               max_lines=None, color=None, align="center", valign="center", tracking=0.0,
               weight=None, family=None, italic=None, gap_scale=1.0, role="text") -> FittedText:
        """Auto-fit + auto-wrap + draw in one call. Returns the FittedText."""
        x0, y0, x1, y1 = box
        fitted = fit_text(self.book, text, style=style, box_w=x1 - x0, box_h=y1 - y0,
                          max_size=max_size, min_size=min_size, leading=leading,
                          max_lines=max_lines, tracking=tracking, weight=weight,
                          family=family, italic=italic)
        fitted.font._pin_style = style  # type: ignore[attr-defined]
        draw_block(self, fitted, box, rgba(color or self.palette["ink"]), align=align,
                   valign=valign, gap_scale=gap_scale, role=role)
        return fitted

    def tracked(self, text: str, center, size=22, color=None, style="ui_semi", tracking=0.18,
                anchor="mm", role="label", max_width: float | None = None, min_size: int = 13) -> str:
        """Uppercased, letter-spaced text (editorial look).

        Auto-shrinks the point size until the tracked line fits `max_width`
        design px — tracked caps are the easiest thing to overflow a pin.
        Returns the string actually drawn.
        """
        up = str(text).upper()
        if max_width:
            guard = 0
            while size > min_size and self.measure_tracked(up, size, style, tracking) > max_width and guard < 200:
                size -= 1
                guard += 1
        self.text(center, up, style=style, size=size, color=color, anchor=anchor, tracking=tracking, role=role)
        return up

    def measure_tracked(self, text: str, size=22, style="ui_semi", tracking=0.18) -> float:
        font = self.book.get(style, size)
        return line_width(str(text).upper(), font, self.s(tracking * size)) / self.scale

    # -- output ------------------------------------------------------------ #
    def save(self, path: Path | str, size=(BASE_W, BASE_H)) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = self.img.convert("RGB")
        if size and (out.width, out.height) != tuple(size):
            out = out.resize(size, Image.LANCZOS)
        out.save(path, "PNG", optimize=True)
        return path


# --------------------------------------------------------------------------- #
# Template registry
# --------------------------------------------------------------------------- #

TEMPLATES: dict[str, Callable[[Canvas, dict], None]] = {}
TEMPLATE_META: dict[str, str] = {}


def template(name: str, description: str = "") -> Callable:
    def deco(fn: Callable[[Canvas, dict], None]):
        TEMPLATES[name] = fn
        TEMPLATE_META[name] = description or (fn.__doc__ or "").strip().split("\n")[0]
        return fn
    return deco


def spec_get(spec: dict, key: str, default: Any = None) -> Any:
    """Spec lookup that also understands '#rrggbb' colour keys."""
    value = spec.get(key, default)
    return value


def brand_footer(canvas: Canvas, spec: dict, *, y: float = BASE_H - 74,
                 color: str | None = None, size: int = 22, style: str = "ui_medium",
                 tracking: float = 0.14) -> None:
    """Shared footer: optional brand line + handle, centred."""
    brand = spec.get("brand")
    handle = spec.get("handle") or spec.get("footer")
    if not brand and not handle:
        return
    text = " · ".join(x for x in (str(brand).upper() if brand else None, handle) if x)
    fallback = ensure_contrast(canvas.palette.get("sub", canvas.palette["ink"]),
                               canvas.palette.get("bg", "#FFFFFF"), 5.0)
    canvas.tracked(text, (BASE_W / 2, y), size=size, color=color or fallback,
                   style=style, tracking=tracking, max_width=BASE_W - 130, role="footer")


# --------------------------------------------------------------------------- #
# Template 1 — bold serif title card with a colour block
# --------------------------------------------------------------------------- #

@template("bold_title", "Bold serif title over a solid colour block (high-contrast, mobile-first)")
def tpl_bold_title(c: Canvas, spec: dict) -> None:
    p = c.palette
    block_color = spec.get("block_color", p["accent"])
    block_text = spec.get("block_ink", readable_on(block_color))
    # keep the palette hue but step the block darker until the title is safe on it
    block_color = ensure_bg_contrast(block_color, block_text, 5.2)

    c.fill(p["bg"])

    # big colour block, slightly bled off the edges for a modern crop feel
    bx = (0, c.h * 0.16, c.w, c.h * 0.70)
    c.rect(bx, block_color)
    # a thin offset rule adds designerly tension
    c.rect((0, bx[1] - 10, c.w, bx[1] - 4), p.get("accent2", block_color))

    pad = 78
    # small text on the page background is contrast-clamped per palette
    sub_c = ensure_contrast(p["sub"], p["bg"], 5.2)
    accent_c = ensure_contrast(p["accent"], p["bg"], 5.2)

    # kicker above the block
    kicker = spec.get("kicker")
    if kicker:
        c.tracked(kicker, (c.w / 2, bx[1] - 62), size=26, color=sub_c, tracking=0.24,
                  max_width=c.w - 190)

    inner = (pad, bx[1] + 54, c.w - pad, bx[3] - 46)
    title = spec.get("title", "Your title here")
    fitted = c.fitted(title, inner, style=spec.get("title_style", "display"),
                      max_size=int(spec.get("title_max", 150)), min_size=46,
                      leading=1.06, color=block_text, align="center", valign="center",
                      max_lines=spec.get("title_lines", 4), role="title")

    # eyebrow label under the block
    label = spec.get("label")
    if label:
        c.tracked(label, (c.w / 2, bx[3] + 66), size=24, color=accent_c, tracking=0.22,
                  max_width=c.w - 150)

    sub = spec.get("subtitle")
    if sub:
        c.fitted(sub, (pad + 30, bx[3] + 108, c.w - pad - 30, BASE_H - 130),
                 style=spec.get("subtitle_style", "sans"), max_size=40, min_size=20,
                 leading=1.42, color=sub_c, align="center", max_lines=3, role="subtitle")

    if spec.get("rule", True):
        rule_y = BASE_H - 116
        c.line((c.w / 2 - 40, rule_y), (c.w / 2 + 40, rule_y), p.get("accent2", p["accent"]), width=2)

    brand_footer(c, spec, color=sub_c)


# --------------------------------------------------------------------------- #
# Template 2 — soft pastel gradient aesthetic card
# --------------------------------------------------------------------------- #

@template("pastel_gradient", "Soft multi-stop gradient + frosted card (aesthetic/soft-life look)")
def tpl_pastel_gradient(c: Canvas, spec: dict) -> None:
    p = c.palette
    stops = spec.get("gradient") or p["gradient"]
    c.linear_gradient(stops, angle=float(spec.get("angle", 128)))

    # soft light blooms give the gradient depth without clutter
    c.soft_blob(spec.get("blob1", (188, 336)), 300, p["accent2"], alpha=52, blur=150)
    c.soft_blob(spec.get("blob2", (836, 1148)), 330, p["accent"], alpha=44, blur=170)
    c.soft_blob((706, 214), 190, "#FFFFFF", alpha=95, blur=120)
    if spec.get("grain", True):
        c.grain(amount=7)

    # frosted card
    card = (86, 268, c.w - 86, 1216)
    if spec.get("card", True):
        c.shadow(card, blur=34, offset=(0, 20), alpha=54, radius=56)
        c.rect(card, with_alpha(p["surface"], 214), radius=56)
        c.rect((card[0] + 14, card[1] + 14, card[2] - 14, card[3] - 14),
               None, outline=with_alpha(p["accent2"], 120), width=1.4, radius=44)
    # what the card actually looks like: surface at 84% over the mid gradient stop
    card_bg = mix(stops[len(stops) // 2], p["surface"], 0.84)
    kicker_c = ensure_contrast(p["accent"], card_bg, 5.0)
    sub_c = ensure_contrast(p["sub"], card_bg, 5.0)
    ink_c = ensure_contrast(p["ink"], card_bg, 7.0)

    inner_pad = 74
    ix0, ix1 = card[0] + inner_pad, card[2] - inner_pad
    y = card[1] + 96

    chip = spec.get("chip")
    if chip:
        label = str(chip).upper()
        tw = c.measure_tracked(label, 22, "ui_semi", 0.16)
        cw, chh = tw + 58, 56
        chip_c = ensure_bg_contrast(p["accent"], spec.get("chip_ink", "#FFFFFF"), 4.8)
        c.rect((c.w / 2 - cw / 2, y, c.w / 2 + cw / 2, y + chh), chip_c, radius=chh / 2)
        c.tracked(label, (c.w / 2, y + chh / 2 + 1), size=22, color=spec.get("chip_ink", "#FFFFFF"),
                  style="ui_semi", tracking=0.16, max_width=c.w - 300, role="chip")
        y += chh + 44

    kicker = spec.get("kicker")
    if kicker:
        c.tracked(kicker, (c.w / 2, y + 14), size=24, color=kicker_c, tracking=0.26,
                  max_width=c.w - 260)
        y += 62

    title_h = 300 if spec.get("subtitle") else 420
    fitted_title = c.fitted(spec.get("title", "Soft Living"),
                            (ix0, y, ix1, y + title_h), style=spec.get("title_style", "sans_semi"),
                            max_size=int(spec.get("title_max", 96)), min_size=40, leading=1.16,
                            color=ink_c, align="center", max_lines=3, role="title")
    y += title_h + 12

    if spec.get("divider", True):
        dy = y
        c.line((c.w / 2 - 26, dy), (c.w / 2 + 26, dy), kicker_c, width=2.4)
        y += 30

    sub = spec.get("subtitle")
    if sub:
        c.fitted(sub, (ix0, y, ix1, y + 190), style=spec.get("subtitle_style", "sans"),
                 max_size=34, min_size=20, leading=1.45, color=sub_c, align="center",
                 max_lines=3, role="subtitle")
        y += 200

    if spec.get("dots", True):
        for i in range(3):
            c.circle((c.w / 2 + (i - 1) * 30, min(y + 30, card[3] - 96)), 5,
                     p["accent"] if i == 1 else with_alpha(p["accent2"], 150))

    brand_footer(c, spec, y=card[3] + 96, color=ensure_contrast(p["ink"], p["bg"], 5.0),
                 size=21, tracking=0.16)


# --------------------------------------------------------------------------- #
# Template 3 — quote card with script + italic accents
# --------------------------------------------------------------------------- #

@template("quote_card", "Editorial quote card: serif quote, script accent line, italic quote mark")
def tpl_quote_card(c: Canvas, spec: dict) -> None:
    p = c.palette
    c.fill(p["bg"])
    if spec.get("grain", True):
        c.grain(amount=5)

    # printed-card frame
    if spec.get("frame", True):
        c.rect((44, 44, c.w - 44, c.h - 44), None, outline=with_alpha(p["sub"], 90),
               width=1.6, radius=6)

    # oversized italic quote mark, sits behind the quote as a soft accent
    mark = spec.get("quote_mark", "\u201c")
    c.text((128, 208), mark, style="display_italic", size=int(spec.get("mark_size", 260)),
           color=with_alpha(p["accent"], 96), anchor="la", role="bleed")

    qx0, qx1 = 128, c.w - 128
    quote = spec.get("quote", "Your words here.")
    c.fitted(quote, (qx0, 330, qx1, 900), style=spec.get("quote_style", "serif"),
             max_size=int(spec.get("quote_max", 82)), min_size=34, leading=1.3,
             color=ensure_contrast(p["ink"], p["bg"], 7.0), align="center",
             max_lines=spec.get("quote_lines", 6), role="quote")

    y = 962
    accent_line = spec.get("accent_line")
    if accent_line:
        c.fitted(accent_line, (qx0 - 20, y, qx1 + 20, y + 150), style=spec.get("accent_style", "script"),
                 max_size=int(spec.get("accent_max", 96)), min_size=40, leading=1.1,
                 color=ensure_contrast(p["accent"], p["bg"], 5.6), align="center",
                 max_lines=2, role="script_acc")
        y += 168

    if spec.get("rule", True):
        c.line((c.w / 2 - 44, y), (c.w / 2 + 44, y), with_alpha(p["accent2"], 200), width=2)
        y += 44

    attribution = spec.get("attribution") or spec.get("author")
    if attribution:
        who = str(attribution).upper()
        if spec.get("role"):
            who = f"{who}  ·  {str(spec['role']).upper()}"
        c.tracked(who, (c.w / 2, y + 12), size=24, color=ensure_contrast(p["sub"], p["bg"], 5.0),
                  style="ui_semi", tracking=0.2, max_width=c.w - 220, role="attribution")

    brand_footer(c, spec, y=c.h - 116, color=ensure_contrast(p["sub"], p["bg"], 5.0),
                 size=21, tracking=0.16)


# --------------------------------------------------------------------------- #
# Template 4 — numbered listicle card ("5 ... ideas")
# --------------------------------------------------------------------------- #

@template("listicle", "Numbered list card: big numeral header + numbered item rows")
def tpl_listicle(c: Canvas, spec: dict) -> None:
    p = c.palette
    items = [str(x) for x in spec.get("items", []) if str(x).strip()]
    if not items:
        items = ["First idea goes here", "Second idea goes here", "Third idea goes here"]
    count = str(spec.get("count") or len(items))

    band_h = float(spec.get("band_h", 330))
    band_c = spec.get("band_color", p["accent"])
    band_ink = spec.get("band_ink", readable_on(band_c))
    band_c = ensure_bg_contrast(band_c, band_ink, 5.0)

    c.fill(p["bg"])
    c.rect((0, 0, c.w, band_h), band_c)

    # huge numeral + headline sit side by side inside the colour band
    num_x = 96
    num = c.fitted(count, (num_x, 24, num_x + 300, band_h - 24), style=spec.get("count_style", "display_black"),
                   max_size=int(spec.get("count_max", 240)), min_size=90, leading=1.0,
                   color=band_ink, align="left", valign="center", max_lines=1, role="count")
    head_x = num_x + max(210.0, num.width + 44)
    c.fitted(spec.get("headline", "ideas"), (head_x, 40, c.w - 84, band_h - 44),
             style=spec.get("headline_style", "display"), max_size=int(spec.get("headline_max", 92)),
             min_size=34, leading=1.08, color=band_ink, align="left", max_lines=3, role="headline")

    y = band_h + 62
    title = spec.get("title")
    if title:
        t = c.fitted(title, (88, y, c.w - 88, y + 150), style=spec.get("title_style", "sans_semi"),
                     max_size=int(spec.get("title_max", 46)), min_size=26, leading=1.32,
                     color=ensure_contrast(p["ink"], p["bg"], 7.0), align="left", max_lines=3,
                     role="title")
        y += t.height / 1.32 + 54

    rows_top = y
    rows_bottom = c.h - 168
    row_h = (rows_bottom - rows_top) / len(items)
    badge_r = min(34.0, row_h * 0.3)
    text_size = int(spec.get("item_max", 34))

    for i, item in enumerate(items, start=1):
        cy = rows_top + row_h * (i - 0.5)
        if i > 1 and spec.get("separators", True):
            c.line((88, rows_top + row_h * (i - 1)), (c.w - 88, rows_top + row_h * (i - 1)),
                   with_alpha(p["sub"], 70), width=1.3)
        badge_ink = spec.get("badge_ink", readable_on(p["accent"]))
        badge_c = ensure_bg_contrast(p["accent"], badge_ink, 5.0)
        c.circle((88 + badge_r, cy), badge_r, badge_c)
        c.text((88 + badge_r, cy + 1), str(i), style="sans_bold", size=int(badge_r * 1.14),
               color=badge_ink, anchor="mm", role="item_num")
        box = (88 + badge_r * 2 + 34, cy - row_h / 2 + 6, c.w - 84, cy + row_h / 2 - 6)
        c.fitted(item, box, style=spec.get("item_style", "sans_medium"), max_size=text_size,
                 min_size=21, leading=1.28, color=ensure_contrast(p["ink"], p["bg"], 7.0),
                 align="left", max_lines=3, role=f"item{i}")

    brand_footer(c, spec, y=c.h - 92, color=ensure_contrast(p["sub"], p["bg"], 5.0),
                 size=21, tracking=0.16)


# --------------------------------------------------------------------------- #
# Template 5 — product / photo frame
# --------------------------------------------------------------------------- #

@template("photo_frame", "Padded photo frame: your image, soft shadow, caption bar, optional badge")
def tpl_photo_frame(c: Canvas, spec: dict) -> None:
    p = c.palette
    photo_spec = spec.get("photo")
    if not photo_spec:
        raise ValueError("template 'photo_frame' requires a 'photo' path in the spec")
    photo_path = resolve_asset(photo_spec, spec)

    pad_color = spec.get("pad_color", p["bg"])
    c.fill(pad_color)
    if spec.get("pad_gradient", False):
        c.linear_gradient([pad_color, mix(pad_color, p["accent"], 0.14)], angle=110)
    if spec.get("grain", True):
        c.grain(amount=4)

    # kicker above the photo (also acts as the visual "hook")
    kicker = spec.get("kicker")
    if kicker:
        c.tracked(kicker, (c.w / 2, 96), size=25, color=ensure_contrast(p["accent"], pad_color, 5.0),
                  tracking=0.24, max_width=c.w - 180)

    frame = tuple(spec.get("frame", (132, 196, c.w - 132, 1004)))
    radius = int(spec.get("frame_radius", 26))
    c.photo(photo_path, frame, fit=spec.get("fit", "cover"), radius=radius,
            shadow=spec.get("shadow", True), shadow_blur=int(spec.get("shadow_blur", 26)),
            shadow_offset=tuple(spec.get("shadow_offset", (0, 18))))

    # badge pill overlapping the lower-left corner of the photo
    badge = spec.get("badge")
    if badge:
        label = str(badge).upper()
        tw = c.measure_tracked(label, 22, "ui_semi", 0.14)
        bw, bh = tw + 56, 58
        bx0, by0 = frame[0] + 26, frame[3] - bh - 26
        c.shadow((bx0, by0, bx0 + bw, by0 + bh), blur=14, offset=(0, 8), alpha=60, radius=bh / 2)
        badge_c = spec.get("badge_color", p["accent"])
        badge_ink = spec.get("badge_ink", readable_on(badge_c))
        badge_c = ensure_bg_contrast(badge_c, badge_ink, 4.8)
        c.rect((bx0, by0, bx0 + bw, by0 + bh), badge_c, radius=bh / 2)
        c.tracked(label, (bx0 + bw / 2, by0 + bh / 2 + 1), size=22, color=badge_ink,
                  style="ui_semi", tracking=0.14, max_width=bw - 30, role="badge")

    # caption bar
    bar_y0 = float(spec.get("caption_y", frame[3] + 34))
    bar_pad = float(spec.get("caption_pad", 30))
    title = spec.get("title") or spec.get("caption") or ""
    cap_bg = spec.get("caption_color", p["accent"])
    cap_ink = spec.get("caption_ink", readable_on(cap_bg))
    cap_bg = ensure_bg_contrast(cap_bg, cap_ink, 5.0)
    bar_box = (frame[0], bar_y0, frame[2], bar_y0 + float(spec.get("caption_h", 148)))
    if spec.get("caption_bar", True):
        c.rect(bar_box, cap_bg, radius=int(spec.get("caption_radius", 18)))
    c.fitted(title, (bar_box[0] + bar_pad, bar_box[1] + 14, bar_box[2] - bar_pad, bar_box[3] - 14),
             style=spec.get("caption_style", "serif"), max_size=int(spec.get("caption_max", 62)),
             min_size=26, leading=1.12, color=cap_ink, align="center", max_lines=2, role="caption")

    sub = spec.get("subtitle")
    if sub:
        c.fitted(sub, (frame[0] + 8, bar_box[3] + 30, frame[2] - 8, bar_box[3] + 190),
                 style=spec.get("subtitle_style", "sans"), max_size=32, min_size=19, leading=1.4,
                 color=ensure_contrast(p["sub"], pad_color, 5.0), align="center", max_lines=3,
                 role="subtitle")

    brand_footer(c, spec, y=c.h - 78, color=ensure_contrast(p["sub"], pad_color, 5.0),
                 size=21, tracking=0.16)


# --------------------------------------------------------------------------- #
# Template 6 — minimal editorial (hairline rules + uppercase tracking)
# --------------------------------------------------------------------------- #

@template("editorial_minimal", "Magazine-style card: hairline rules, tracked caps, big serif, whitespace")
def tpl_editorial_minimal(c: Canvas, spec: dict) -> None:
    p = c.palette
    ink = ensure_contrast(p["ink"], p["bg"], 9.0)
    sub = ensure_contrast(p["sub"], p["bg"], 5.2)
    accent = ensure_contrast(p["accent"], p["bg"], 5.2)
    rule = spec.get("rule_color", with_alpha(sub, 120))
    m = float(spec.get("margin", 88))

    c.fill(p["bg"])
    if spec.get("grain", True):
        c.grain(amount=4)

    def hairline(y: float, weight: float = 1.2) -> None:
        c.line((m, y), (c.w - m, y), rule, width=weight)

    # top frieze: rule, kicker left, issue right
    hairline(104, 2.0)
    kicker = spec.get("kicker")
    if kicker:
        c.tracked(kicker, (m, 148), size=23, color=accent, style="ui_semi", tracking=0.28,
                  anchor="lm", max_width=(c.w - 2 * m) * 0.62, role="kicker")
    issue = spec.get("issue")
    if issue:
        c.tracked(issue, (c.w - m, 148), size=21, color=sub, style="ui_medium", tracking=0.2,
                  anchor="rm", max_width=(c.w - 2 * m) * 0.34, role="issue")

    # headline
    title_y0 = float(spec.get("title_y", 232))
    t = c.fitted(spec.get("title", "The quiet edit"), (m, title_y0, c.w - m, title_y0 + 430),
                 style=spec.get("title_style", "serif"), max_size=int(spec.get("title_max", 112)),
                 min_size=40, leading=1.06, color=ink, align="left", valign="top",
                 max_lines=spec.get("title_lines", 4), role="title")
    y = title_y0 + t.height / 1.06 + float(spec.get("deck_gap", 46))

    hairline(y, 1.0)
    y += 44

    deck = spec.get("deck") or spec.get("subtitle")
    if deck:
        d = c.fitted(deck, (m, y, c.w - m, y + 230), style=spec.get("deck_style", "ui"),
                     max_size=int(spec.get("deck_max", 33)), min_size=19, leading=1.5,
                     color=sub, align="left", valign="top", max_lines=4, role="deck")
        y += d.height / 1.5 + 54

    entries = [str(e) for e in spec.get("entries", [])][: int(spec.get("max_entries", 4))]
    if entries:
        row_h = float(spec.get("row_h", 74))
        y += 6
        hairline(y, 1.0)
        for i, item in enumerate(entries, start=1):
            ry = y + row_h * (i - 0.5)
            num = f"{i:02d}"
            c.tracked(num, (m, ry), size=22, color=accent, style="ui_semi", tracking=0.18,
                      anchor="lm", max_width=70, role=f"idx{i}")
            c.tracked(item, (m + 86, ry), size=23, color=ink, style="ui_medium", tracking=0.13,
                      anchor="lm", max_width=c.w - m - (m + 86), role=f"entry{i}")
            if i < len(entries):
                c.line((m, y + row_h * i), (c.w - m, y + row_h * i), with_alpha(sub, 70), width=1.0)
        y += row_h * len(entries)
        hairline(y, 1.0)

    # footer sits below the rules: brand left, handle right (asymmetric, editorial)
    fy = max(y + 74, c.h - 132)
    brand = spec.get("brand")
    handle = spec.get("handle") or spec.get("footer")
    if brand:
        c.tracked(brand, (m, fy), size=21, color=ink, style="ui_semi", tracking=0.2,
                  anchor="lm", max_width=(c.w - 2 * m) * 0.5, role="brand")
    if handle:
        c.tracked(handle, (c.w - m, fy), size=21, color=sub, style="ui_medium", tracking=0.18,
                  anchor="rm", max_width=(c.w - 2 * m) * 0.5, role="handle")


# --------------------------------------------------------------------------- #
# Rendering entry points
# --------------------------------------------------------------------------- #

def render_spec(spec: dict, out_path: Path | str | None = None, scale: int = DEFAULT_SCALE,
                assert_size: bool = True, log: list | None = None) -> Image.Image:
    """Render one spec dict -> PIL image (and optionally save a PNG).

    Pass a list as `log` to receive the per-text-box audit records.
    """
    if "template" not in spec:
        raise KeyError("spec is missing the required 'template' key")
    name = spec["template"]
    if name not in TEMPLATES:
        raise KeyError(f"unknown template {name!r}; known: {', '.join(sorted(TEMPLATES))}")
    palette = resolve_palette(spec)
    if spec.get("bg"):
        palette["bg"] = spec["bg"]
    canvas = Canvas(palette, scale=scale)
    TEMPLATES[name](canvas, spec)
    img = canvas.img.convert("RGB")
    if (img.width, img.height) != (BASE_W, BASE_H):
        img = img.resize((BASE_W, BASE_H), Image.LANCZOS)
    if assert_size and img.size != (BASE_W, BASE_H):
        raise AssertionError(f"render produced {img.size}, expected {(BASE_W, BASE_H)}")
    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG", optimize=True)
    if log is not None:
        log.extend(canvas.text_log)
    return img


# --------------------------------------------------------------------------- #
# Audit: text bounds, fit ratios, WCAG contrast, safe margins
# --------------------------------------------------------------------------- #

def _ring_background(img: Image.Image, rect: tuple[float, float, float, float],
                     pad: int = 7) -> tuple[int, int, int]:
    """Median colour of the pixels just outside `rect` — i.e. what the text sits on."""
    xa, xb = sorted((rect[0], rect[2]))
    ya, yb = sorted((rect[1], rect[3]))
    x0 = int(max(0, min(img.width - 1, xa)))
    x1 = int(max(0, min(img.width, xb + 1)))
    y0 = int(max(0, min(img.height - 1, ya)))
    y1 = int(max(0, min(img.height, yb + 1)))
    outer = (max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad))
    strip = img.crop(outer).convert("RGB")
    if strip.width == 0 or strip.height == 0:
        return (255, 255, 255)
    if np is not None:
        arr = np.asarray(strip).reshape(-1, 3)
    else:  # pragma: no cover
        arr = [strip.getpixel((x, y)) for y in range(strip.height) for x in range(strip.width)]
    lum = [rel_luminance(px) for px in arr]
    order = sorted(range(len(lum)), key=lambda i: lum[i])
    return tuple(int(c) for c in arr[order[len(order) // 2]])


def audit_spec(spec_path: Path | str, scale: int = DEFAULT_SCALE,
               min_contrast: float = 4.5, margin: float = 32.0) -> dict:
    """Render a spec and verify the layout: bounds, margins, contrast, fit."""
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    log: list[dict] = []
    img = render_spec(spec, None, scale=scale, log=log)
    problems: list[str] = []
    entries: list[dict] = []
    for item in log:
        rect = item["rect"]
        x0, y0, x1, y1 = rect
        bg = _ring_background(img, rect)
        ratio = contrast_ratio(item["fill"], bg)
        inside = x0 >= -1 and y0 >= -1 and x1 <= img.width + 1 and y1 <= img.height + 1
        near_edge = min(x0, y0, img.width - x1, img.height - y1) < margin
        # long text must not be a single overflowing line
        box = item.get("box")
        overflow = False
        if box:
            overflow = (x1 - x0) > (box[2] - box[0]) + 1.5 or (y1 - y0) > (box[3] - box[1]) + 1.5
        status = "ok"
        decorative = item["role"] in ("bleed", "decoration")
        if not inside or overflow:
            status = "FAIL"
            problems.append(f"{item['role']}: text escapes its box/canvas -> {item['text'][:48]!r}")
        elif ratio < min_contrast and not decorative:
            status = "FAIL"
            problems.append(f"{item['role']}: contrast {ratio:.2f}:1 < {min_contrast}:1 for {item['text'][:48]!r}")
        elif near_edge and not decorative:
            status = "edge"
        entries.append({**item, "contrast": round(ratio, 2), "bg": bg,
                        "rect": [round(v, 1) for v in rect], "status": status})
    # text boxes must not collide with each other (catches cramped layouts)
    boxes = [(e["rect"], e["role"], e["text"]) for e in entries]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ax0, ay0, ax1, ay1), ar, at = boxes[i]
            (bx0, by0, bx1, by1), br, bt = boxes[j]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 1.0 and oy > 1.0 and ar != "bleed" and br != "bleed":
                problems.append(f"overlap: {ar} {at[:24]!r} x {br} {bt[:24]!r} "
                                f"({ox:.0f}x{oy:.0f}px)")
                for e in entries:
                    if e["rect"] == boxes[i][0] or e["rect"] == boxes[j][0]:
                        e["status"] = "FAIL"
    return {
        "spec": str(spec_path), "template": spec.get("template"), "palette": spec.get("palette"),
        "size": list(img.size), "text_boxes": len(entries), "problems": problems,
        "min_contrast_seen": min((e["contrast"] for e in entries), default=None),
        "min_contrast_text": min((e["contrast"] for e in entries
                                  if e["role"] not in ("bleed", "decoration")), default=None),
        "ok": not problems, "entries": entries,
    }


def render_file(spec_path: Path | str, out_path: Path | str | None = None,
                scale: int = DEFAULT_SCALE) -> Path:
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.setdefault("_spec_dir", str(spec_path.resolve().parent))
    if out_path is None:
        out_path = CACHE_DIR / f"{spec_path.stem}.png"
    render_spec(spec, out_path, scale=scale)
    return Path(out_path)


def resolve_asset(path: str | Path, spec: dict | None = None) -> Path:
    """Find an asset: absolute, cwd-relative, factory-relative, assets/, spec-relative."""
    p = Path(path)
    candidates = [p]
    if not p.is_absolute():
        candidates += [HERE / p, HERE / "assets" / p.name, HERE / "assets" / p]
        if spec and spec.get("_spec_dir"):
            candidates += [Path(spec["_spec_dir"]) / p, Path(spec["_spec_dir"]) / p.name]
    for cand in candidates:
        if cand.exists():
            return cand
    raise FileNotFoundError(f"photo not found: {path} (tried {[str(c) for c in candidates]})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pin_factory", description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="render one spec or a whole specs directory")
    r.add_argument("spec", nargs="?", help="path to a JSON spec")
    r.add_argument("--all", action="store_true", help="render every *.json in --specs-dir")
    r.add_argument("--specs-dir", default=str(HERE / "specs"))
    r.add_argument("-o", "--out", help="output PNG path (single spec)")
    r.add_argument("--outdir", default=str(CACHE_DIR), help="output dir for --all")
    r.add_argument("--scale", type=int, default=DEFAULT_SCALE, help="supersample factor (default 2)")
    r.add_argument("--json", action="store_true", help="print a JSON report")

    sub.add_parser("list", help="list templates")
    sub.add_parser("palettes", help="list palettes")
    sub.add_parser("fonts", help="check that every configured font loads")

    a = sub.add_parser("audit", help="render specs and verify fit/contrast/margins")
    a.add_argument("spec", nargs="?")
    a.add_argument("--all", action="store_true", help="audit every *.json in --specs-dir")
    a.add_argument("--specs-dir", default=str(HERE / "specs"))
    a.add_argument("--min-contrast", type=float, default=4.5)
    a.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        for name, desc in TEMPLATES.items():
            print(f"{name:14s} {desc}")
        return 0

    if args.cmd == "palettes":
        for name, pal in PALETTES.items():
            print(f"{name:12s} bg={pal['bg']} ink={pal['ink']} accent={pal['accent']}")
        return 0

    if args.cmd == "fonts":
        book = FontBook()
        bad = 0
        for style in STYLES:
            try:
                f = book.get(style, 48)
                axes = getattr(f, "_pin_axes", None)
                print(f"OK   {style:14s} path={Path(f.path).name:32s} axes={axes}")
            except Exception as exc:
                bad += 1
                print(f"FAIL {style:14s} {exc}")
        return 1 if bad else 0

    if args.cmd == "audit":
        specs = sorted(Path(args.specs_dir).glob("*.json")) if args.all else [Path(args.spec)]
        reports = [audit_spec(sp, min_contrast=args.min_contrast) for sp in specs]
        if args.json:
            print(json.dumps(reports, indent=2))
        else:
            for rep in reports:
                flag = "OK  " if rep["ok"] else "FAIL"
                print(f"{flag} {Path(rep['spec']).name:34s} boxes={rep['text_boxes']:2d} "
                      f"min_text_contrast={rep['min_contrast_text']} size={rep['size']}")
                for prob in rep["problems"]:
                    print(f"       ! {prob}")
        return 0 if all(r["ok"] for r in reports) else 1

    # render
    if args.all:
        specs = sorted(Path(args.specs_dir).glob("*.json"))
        if not specs:
            print(f"no specs in {args.specs_dir}", file=sys.stderr)
            return 1
        report = []
        for sp in specs:
            out = Path(args.outdir) / f"{sp.stem}.png"
            render_file(sp, out, scale=args.scale)
            report.append({"spec": str(sp), "out": str(out)})
            print(f"rendered {out}")
        if args.json:
            print(json.dumps(report, indent=2))
        return 0

    if not args.spec:
        ap.error("provide a spec path or --all")
    out = render_file(args.spec, args.out, scale=args.scale)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
