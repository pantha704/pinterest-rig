#!/usr/bin/env python3
"""Generate the ORIGINAL 'cozy autumn -> Christmas home' artwork for batch-001.

Every asset is drawn procedurally with Pillow + numpy: no stock imagery, nothing
scraped, no text/lettering/numbers, no logos or brands, no people. Eight flat
minimal editorial pieces for a home/lifestyle Pinterest account, drawn at 2x
supersample and LANCZOS downscaled to exactly 1200x1500 RGB PNG.

    python3 tools/make_seasonal_artwork.py

Writes the 8 PNGs + _contact_sheet.png into content/batch-001/assets/, verifies
every file and exits non-zero if any check fails.

House style (canvas / vertical_gradient / grain / save) is copied from
factory/tools/make_sample_artwork.py. One deliberate deviation: the film grain is
sampled at half resolution and quantised before being added. Full-resolution
gaussian noise at sigma 5 (what the factory script uses) costs 1.4-2.2 MB per
PNG at this size, which breaks the 150-600 KB budget these assets must fit; the
correlated grain measures the same visual strength (whole-image grey std is
unchanged) at roughly 0.4-0.5 MB.
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent          # content/batch-001
ASSETS = ROOT / "assets"

W, H = 1200, 1500      # final output size
SS = 2                 # supersample factor -> draw at 2400x3000
MARGIN = 80            # keep-out margin in final px: keep motifs inside it

GRAIN_AMOUNT = 5.0     # gaussian sigma (house style is ~4-6)
GRAIN_DIV = 2          # noise sampled at 1/2 res -> correlated, compresses well
GRAIN_STEP = 6         # noise quantised to multiples of this -> PNG budget


# --------------------------------------------------------------------------
# helpers (house style)
# --------------------------------------------------------------------------
def hex2rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def canvas(bg: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W * SS, H * SS), hex2rgb(bg))
    return img, ImageDraw.Draw(img)


def vertical_gradient(img: Image.Image, top: str, bottom: str) -> None:
    a, b = np.array(hex2rgb(top), dtype=np.float32), np.array(hex2rgb(bottom), dtype=np.float32)
    t = np.linspace(0, 1, img.height, dtype=np.float32)[:, None]
    row = (a[None, :] * (1 - t) + b[None, :] * t).astype(np.uint8)[:, None, :]
    img.paste(Image.fromarray(np.repeat(row, img.width, axis=1), "RGB"), (0, 0))


def grain(img: Image.Image, amount: float = GRAIN_AMOUNT, seed: int = 3) -> Image.Image:
    """Soft film grain, deterministic and correlated so the PNG stays in budget."""
    rng = np.random.default_rng(seed)
    small = rng.normal(0.0, amount, (img.height // GRAIN_DIV, img.width // GRAIN_DIV))
    layer = Image.fromarray(np.clip(small + 128.0, 0, 255).astype(np.uint8), "L")
    layer = layer.resize((img.width, img.height), Image.BILINEAR)
    noise = np.asarray(layer).astype(np.float32) - 128.0
    noise = np.round(noise / GRAIN_STEP) * GRAIN_STEP
    arr = np.asarray(img).astype(np.float32) + noise[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def save(img: Image.Image, name: str, seed: int = 3, amount: float = GRAIN_AMOUNT) -> Path:
    """LANCZOS downscale to exactly 1200x1500, add film grain, write the PNG.

    Grain is added AFTER the downscale on purpose: grain applied to the 2x render
    is resampled by the LANCZOS pass into a continuum of values, which triples the
    PNG size (1.2-1.5 MB) and blows the 150-600 KB budget. Post-downscale grain
    measures the same whole-image grey std at ~0.4-0.5 MB.
    """
    out = ASSETS / name
    out.parent.mkdir(parents=True, exist_ok=True)
    grain(img.resize((W, H), Image.LANCZOS), amount=amount, seed=seed).save(
        out, "PNG", optimize=True)
    print(f"wrote {out}  ({out.stat().st_size / 1024:.1f} KB)")
    return out


# --------------------------------------------------------------------------
# scale-aware drawing helpers: geometry is written in FINAL pixels, the helpers
# multiply by SS, so layout numbers below read like the finished poster.
# --------------------------------------------------------------------------
def _b(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [x0 * SS, y0 * SS, x1 * SS, y1 * SS]


def rect(d, x0, y0, x1, y1, colour) -> None:
    d.rectangle(_b(x0, y0, x1, y1), fill=hex2rgb(colour))


def rrect(d, x0, y0, x1, y1, radius, colour) -> None:
    d.rounded_rectangle(_b(x0, y0, x1, y1), radius=radius * SS, fill=hex2rgb(colour))


def ell(d, cx, cy, rx, ry, colour) -> None:
    d.ellipse(_b(cx - rx, cy - ry, cx + rx, cy + ry), fill=hex2rgb(colour))


def poly(d, pts, colour) -> None:
    d.polygon([(x * SS, y * SS) for x, y in pts], fill=hex2rgb(colour))


def seg(d, x0, y0, x1, y1, colour, width=3) -> None:
    d.line(_b(x0, y0, x1, y1), fill=hex2rgb(colour), width=max(1, int(round(width * SS))))


def arc(d, cx, cy, rx, ry, start, end, colour, width=4) -> None:
    d.arc(_b(cx - rx, cy - ry, cx + rx, cy + ry), start, end,
          fill=hex2rgb(colour), width=max(1, int(round(width * SS))))


def gradient_box(img, x0, y0, x1, y1, top, bottom) -> None:
    """Vertical gradient clipped to a box (used for the window glass)."""
    x0i, y0i, x1i, y1i = [int(round(v * SS)) for v in (x0, y0, x1, y1)]
    x0i, y0i = max(0, x0i), max(0, y0i)
    x1i, y1i = min(img.width, x1i), min(img.height, y1i)
    if x1i <= x0i or y1i <= y0i:
        return
    a, b = np.array(hex2rgb(top), np.float32), np.array(hex2rgb(bottom), np.float32)
    t = np.linspace(0, 1, y1i - y0i, dtype=np.float32)[:, None]
    row = (a[None, :] * (1 - t) + b[None, :] * t).astype(np.uint8)[:, None, :]
    img.paste(Image.fromarray(np.repeat(row, x1i - x0i, axis=1), "RGB"), (x0i, y0i))


def blend_rect(img, x0, y0, x1, y1, colour, alpha) -> None:
    """Tint a region towards `colour` by `alpha` (flat-design shading)."""
    x0i, y0i, x1i, y1i = [int(round(v * SS)) for v in (x0, y0, x1, y1)]
    x0i, y0i = max(0, x0i), max(0, y0i)
    x1i, y1i = min(img.width, x1i), min(img.height, y1i)
    if x1i <= x0i or y1i <= y0i:
        return
    reg = np.asarray(img.crop((x0i, y0i, x1i, y1i))).astype(np.float32)
    c = np.array(hex2rgb(colour), np.float32)
    reg = reg * (1.0 - alpha) + c * alpha
    img.paste(Image.fromarray(np.clip(reg, 0, 255).astype(np.uint8), "RGB"), (x0i, y0i))


def radial_glow(img, cx, cy, r, colour, strength=0.4, clip=None) -> None:
    """Soft radial light wash (lamp / firelight), clipped to a rectangle."""
    bx0, by0, bx1, by1 = clip if clip else (0, 0, W, H)
    x0i, y0i = max(0, int(round(bx0 * SS))), max(0, int(round(by0 * SS)))
    x1i, y1i = min(img.width, int(round(bx1 * SS))), min(img.height, int(round(by1 * SS)))
    if x1i <= x0i or y1i <= y0i:
        return
    reg = np.asarray(img.crop((x0i, y0i, x1i, y1i))).astype(np.float32)
    ys = (np.arange(y0i, y1i, dtype=np.float32) - cy * SS) / (r * SS)
    xs = (np.arange(x0i, x1i, dtype=np.float32) - cx * SS) / (r * SS)
    dist = np.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2)
    alpha = (np.clip(1.0 - dist, 0.0, 1.0) ** 1.7) * strength
    c = np.array(hex2rgb(colour), np.float32)
    reg = reg * (1.0 - alpha[:, :, None]) + c[None, None, :] * alpha[:, :, None]
    img.paste(Image.fromarray(np.clip(reg, 0, 255).astype(np.uint8), "RGB"), (x0i, y0i))


# --------------------------------------------------------------------------
# shape helpers (deterministic; no PIL rotation -> no resampling artefacts)
# --------------------------------------------------------------------------
def leaf_points(cx, cy, length, width, angle_deg, tip=0.75, steps=26):
    """Lens/teardrop polygon: a leaf, plume or bow loop, rotated by angle_deg."""
    us = np.linspace(0.0, 1.0, steps)
    hw = (width / 2.0) * np.sin(np.pi * us) ** tip
    lx = (us - 0.5) * length
    pts = list(zip(lx.tolist(), hw.tolist())) + list(zip(lx[::-1].tolist(), (-hw[::-1]).tolist()))
    ca, sa = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]


def star_points(cx, cy, r_out, r_in, points=4, rot=90.0):
    """4-point sparkle star (points = number of spikes)."""
    pts = []
    for k in range(points * 2):
        ang = math.radians(rot + k * (180.0 / points))
        r = r_out if k % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy - r * math.sin(ang)))
    return pts


def flame(d, cx, base_y, w, h, colour, core) -> None:
    """Simple teardrop flame: rounded base, pointed tip."""
    ell(d, cx, base_y - w * 0.42, w / 2.0, w * 0.58, colour)
    poly(d, [(cx - w / 2.0, base_y - w * 0.45), (cx + w / 2.0, base_y - w * 0.45),
             (cx, base_y - h)], colour)
    ell(d, cx, base_y - w * 0.30, w * 0.26, w * 0.32, core)
    poly(d, [(cx - w * 0.26, base_y - w * 0.32), (cx + w * 0.26, base_y - w * 0.32),
             (cx, base_y - h * 0.62)], core)


def stocking(img, d, cx, top_y, colour, cuff_colour, foot=1) -> None:
    """Flat boot: straight leg over a rounded foot, contrast cuff."""
    leg, foot_w, body_h, foot_h = 50, 74, 150, 88
    rect(d, cx - leg, top_y, cx + leg, top_y + body_h + 20, colour)
    x_a = cx - leg - foot_w if foot < 0 else cx - leg
    x_b = cx + leg if foot < 0 else cx + leg + foot_w
    rrect(d, x_a, top_y + body_h - 12, x_b, top_y + body_h + foot_h, foot_h / 2.0, colour)
    blend_rect(img, x_a, top_y + body_h + foot_h - 12, x_b, top_y + body_h + foot_h,
               "#6B4A32", 0.12)                                      # foot shade
    rect(d, cx - leg - 9, top_y - 8, cx + leg + 9, top_y + 44, cuff_colour)
    blend_rect(img, cx - leg - 9, top_y + 38, cx + leg + 9, top_y + 44, "#6B4A32", 0.16)


# --------------------------------------------------------------------------
# 1. autumn-arch-sunset
# --------------------------------------------------------------------------
def autumn_arch_sunset() -> Path:
    img, d = canvas("#FBEEDF")
    vertical_gradient(img, "#FBEEDF", "#F2D8BE")

    cx, base_y, arch_w = 600.0, 1030.0, 700.0
    r = arch_w / 2.0
    cap_y = 650.0                                    # centre of the arch cap
    d.pieslice(_b(cx - r, cap_y - r, cx + r, cap_y + r), 180, 360, fill=hex2rgb("#C0603C"))
    rect(d, cx - r, cap_y, cx + r, base_y, "#C0603C")

    ell(d, cx, 858, 150, 150, "#E8A33D")             # low sun, sitting on the horizon

    seg(d, 80, 1120, 1120, 1120, "#7A4A33", 6)       # three thin horizon rules
    seg(d, 200, 1186, 1000, 1186, "#7A4A33", 3)
    seg(d, 320, 1248, 880, 1248, "#7A4A33", 2)

    return save(img, "autumn-arch-sunset.png", seed=101)


# --------------------------------------------------------------------------
# 2. autumn-leaves-wreath
# --------------------------------------------------------------------------
def autumn_leaves_wreath() -> Path:
    img, d = canvas("#FBF3E7")
    vertical_gradient(img, "#FDF8F0", "#F3E2CC")

    cx, cy, ring = 600.0, 720.0, 300.0
    colours = ("#C0603C", "#D9A059", "#6E7A4F", "#C97F52")
    n = 18
    for i in range(n):
        a = 360.0 * i / n
        rad = math.radians(a)
        lx = cx + ring * math.cos(rad)
        ly = cy + ring * math.sin(rad)
        tang = a + 90.0 + (10.0 if i % 2 else -10.0)   # leaves follow the circle
        poly(d, leaf_points(lx, ly, 198, 96, tang, tip=0.8), colours[i % len(colours)])

    return save(img, "autumn-leaves-wreath.png", seed=202)


# --------------------------------------------------------------------------
# 3. autumn-dried-stems
# --------------------------------------------------------------------------
def autumn_dried_stems() -> Path:
    img, d = canvas("#F9F2E8")
    vertical_gradient(img, "#FDF8F1", "#EFE1D0")

    table_y = 1150.0
    rect(d, 0, table_y, W, H, "#E7D7C4")
    seg(d, 0, table_y, W, table_y, "#CDB69E", 4)

    vx, v_top = 600.0, 830.0
    poly(d, [(vx - 125, v_top), (vx + 125, v_top), (vx + 155, table_y), (vx - 155, table_y)],
         "#C97F52")
    blend_rect(img, vx + 55, v_top, vx + 155, table_y, "#8E5230", 0.13)      # soft form shade
    ell(d, vx, v_top, 125, 40, "#B06B43")                                    # vase mouth
    ell(d, vx, v_top - 10, 96, 22, "#E5C3A2")                                # inner rim

    plumes = ((-100, 176, 470, -17, "#D9A059"),
              (-42, 142, 566, -7, "#E7CBA3"),
              (14, 206, 612, 3, "#D9A059"),
              (70, 138, 540, 9, "#C98A5B"))
    for dx, wid, hgt, tilt, colr in plumes:
        x0, y0 = vx + dx, v_top - 12
        x1 = x0 + math.tan(math.radians(tilt)) * hgt
        y1 = y0 - hgt
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        seg(d, x0, y0, x0 + (x1 - x0) * 0.78, y0 + (y1 - y0) * 0.78, "#B08A5E", 5)
        poly(d, leaf_points((x0 + x1) / 2.0, (y0 + y1) / 2.0, hgt, wid, ang, tip=0.95), colr)

    for dx, hgt, tilt in ((-16, 430, -4), (52, 452, 6)):                     # two bare stems
        x0, y0 = vx + dx, v_top - 12
        x1, y1 = x0 + math.tan(math.radians(tilt)) * hgt, y0 - hgt
        seg(d, x0, y0, x1, y1, "#B08A5E", 5)
        poly(d, leaf_points(x1, y1 - 9, 54, 26, math.degrees(math.atan2(y1 - y0, x1 - x0)), 0.9),
             "#6E7A4F")

    return save(img, "autumn-dried-stems.png", seed=303)


# --------------------------------------------------------------------------
# 4. autumn-stripe-wallpaper
# --------------------------------------------------------------------------
def autumn_stripe_wallpaper() -> Path:
    img, d = canvas("#F6E6CF")
    period, wide, narrow = 200, 84, 16
    for x in range(0, W, period):
        rect(d, x, 0, x + wide, H, "#FDF6EA")                       # wide cream
        rect(d, x + wide, 0, x + wide + narrow, H, "#B85C3C")       # narrow rust
        rect(d, x + wide + narrow, 0, x + period - narrow, H, "#F5E6D2")   # wide cream (warm)
        rect(d, x + period - narrow, 0, x + period, H, "#6F7A50")   # narrow olive

    wain_y = 1000.0                                                  # wainscot, 1/3 from bottom
    blend_rect(img, 0, wain_y, W, 1444, "#E2C9AA", 0.42)             # panelled lower wall
    seg(d, 0, wain_y, W, wain_y, "#B99A78", 6)                       # wainscot rail
    blend_rect(img, 0, wain_y + 6, W, wain_y + 22, "#8B6F53", 0.30)  # shadow under the rail
    rect(d, 0, 1444, W, 1452, "#C9AC88")                             # baseboard cap
    blend_rect(img, 0, 1452, W, H, "#DCC4A2", 0.55)                  # baseboard
    blend_rect(img, 0, 1452, W, 1458, "#8B6F53", 0.22)

    return save(img, "autumn-stripe-wallpaper.png", seed=404, amount=4.5)


# --------------------------------------------------------------------------
# 5. cozy-window-rain
# --------------------------------------------------------------------------
def cozy_window_rain() -> Path:
    img, d = canvas("#FBEBD6")
    vertical_gradient(img, "#FCEEDC", "#EAD3B5")

    fx0, fy0, fx1, fy1 = 250.0, 250.0, 950.0, 1050.0     # window frame box
    ft = 38.0                                            # frame thickness
    glass = Image.new("RGB", (W * SS, H * SS), hex2rgb("#FBEBD6"))
    gd = ImageDraw.Draw(glass)
    gradient_box(glass, fx0, fy0, fx1, fy1, "#A8BAC6", "#7F94A3")   # dusk sky outside
    rng = np.random.default_rng(77)
    x = fx0 + 14
    while x < fx1 - 12:                                  # rain falls over the whole glass
        y = fy0 - 30.0
        while y < fy1:
            length = float(rng.uniform(96, 168))
            seg(gd, x, y, x + 20, y + length, "#B7C8D2", 3)
            y += length + float(rng.uniform(26, 92))
        x += float(rng.uniform(44, 70))
    for _ in range(64):                                  # droplets
        dx = float(rng.uniform(fx0 + 10, fx1 - 10))
        dy = float(rng.uniform(fy0 + 10, fy1 - 10))
        ell(gd, dx, dy, 3.4, 3.4, "#C2D0D8")
    rect(gd, fx0, fy0, fx1, fy0 + ft, "#E4D2B6")         # frame + mullions on top
    rect(gd, fx0, fy1 - ft, fx1, fy1, "#E4D2B6")
    rect(gd, fx0, fy0, fx0 + ft, fy1, "#E4D2B6")
    rect(gd, fx1 - ft, fy0, fx1, fy1, "#E4D2B6")
    rect(gd, 583, fy0 + ft, 617, fy1 - ft, "#E4D2B6")
    rect(gd, fx0 + ft, 633, fx1 - ft, 667, "#E4D2B6")
    rect(gd, fx0 + ft, fy0 + ft, fx0 + ft + 10, fy1 - ft, "#F2E4CE")     # light from the left
    rect(gd, 583, fy0 + ft, 593, fy1 - ft, "#F2E4CE")
    img.paste(glass, (0, 0))

    rect(d, 118, fy1, 1082, fy1 + 62, "#D9C4A5")                          # sill
    seg(d, 118, fy1, 1082, fy1, "#EEDFC7", 3)
    seg(d, 118, fy1 + 62, 1082, fy1 + 62, "#B79C7A", 4)
    blend_rect(img, 118, fy1 + 6, 1082, fy1 + 62, "#8B6F53", 0.10)        # sill under-shade

    rrect(d, 318, 952, 412, fy1 + 2, 16, "#C0603C")                       # mug
    arc(d, 404, 1000, 26, 30, -78, 78, "#C0603C", 11)
    ell(d, 365, 952, 47, 12, "#E09A73")                                   # rim
    ell(d, 365, 953, 30, 6, "#7E3C1F")                                    # coffee
    blend_rect(img, 300, fy1 - 5, 470, fy1 + 28, "#8B6F53", 0.22)         # contact shadow

    rect(d, 508, 1030, 800, fy1 + 2, "#6E7A4F")                           # books
    rect(d, 508, 1030, 800, 1036, "#F3E7D2")
    rect(d, 528, 1006, 778, 1030, "#A03B47")
    rect(d, 528, 1006, 778, 1012, "#F3E7D2")
    blend_rect(img, 490, fy1 - 5, 830, fy1 + 28, "#8B6F53", 0.22)

    radial_glow(img, 300, 1240, 560, "#E8A33D", 0.30)                     # lamp light, room
    radial_glow(img, 366, 940, 210, "#E8A33D", 0.24)
    radial_glow(img, 600, 1090, 430, "#E8A33D", 0.16, clip=(118, fy1, 1082, fy1 + 62))
    radial_glow(img, 250, 640, 300, "#F6C980", 0.12, clip=(0, 0, 1160, 1200))

    return save(img, "cozy-window-rain.png", seed=505)


# --------------------------------------------------------------------------
# 6. christmas-tree-minimal
# --------------------------------------------------------------------------
def christmas_tree_minimal() -> Path:
    img, d = canvas("#FAF4E9")
    vertical_gradient(img, "#FCF9F2", "#F3EADA")

    ell(d, 600, 1218, 186, 19, "#E0CEAF")                            # soft ground shadow
    rect(d, 564, 1136, 636, 1216, "#7A4A33")                         # trunk
    poly(d, [(600, 856), (298, 1184), (902, 1184)], "#2C4636")       # bottom tier
    poly(d, [(600, 664), (332, 1012), (868, 1012)], "#32503B")       # middle tier
    poly(d, [(600, 498), (402, 830), (798, 830)], "#38573F")         # top tier
    poly(d, star_points(600, 414, 76, 25, 4), "#D9A059")             # 4-point star

    return save(img, "christmas-tree-minimal.png", seed=606)


# --------------------------------------------------------------------------
# 7. christmas-gift-stack
# --------------------------------------------------------------------------
def christmas_gift_stack() -> Path:
    img, d = canvas("#FBF3E6")
    vertical_gradient(img, "#FCF7EC", "#F1E1CB")

    ell(d, 600, 1342, 442, 26, "#DBC5A2")                            # ground shadow

    def box(x0, y0, x1, y1, body, lid, ribbon) -> None:
        rect(d, x0, y0, x1, y1, body)
        rect(d, x0, y0, x1, y0 + 46, lid)
        seg(d, x0, y0 + 46, x1, y0 + 46, lid, 3)
        rect(d, 568, y0, 632, y1, ribbon)                            # vertical ribbon
        rect(d, x0, y0 + (y1 - y0 - 54) / 2.0, x1, y0 + (y1 - y0 + 54) / 2.0, ribbon)
        blend_rect(img, x0, y1 - 10, x1, y1, "#6B4A32", 0.10)

    box(242, 940, 958, 1330, "#E7D3AC", "#D9C294", "#9E3B4A")        # sand cream, berry ribbon
    box(330, 590, 870, 940, "#9E3B4A", "#8C3340", "#E8D3AE")         # berry, cream ribbon
    box(420, 300, 780, 590, "#2E4636", "#263B2D", "#D9A059")         # forest, ochre ribbon

    poly(d, [(566, 286), (566, 350), (524, 396), (506, 366), (548, 320), (548, 290)],
         "#D9A059")                                                  # ribbon tail, left
    poly(d, [(634, 286), (634, 350), (676, 396), (694, 366), (652, 320), (652, 290)],
         "#D9A059")                                                  # ribbon tail, right
    poly(d, leaf_points(514, 250, 178, 108, 203, 0.9), "#E8A33D")    # bow loops
    poly(d, leaf_points(686, 250, 178, 108, -23, 0.9), "#E8A33D")
    ell(d, 600, 288, 31, 31, "#C98428")                              # knot

    return save(img, "christmas-gift-stack.png", seed=707)


# --------------------------------------------------------------------------
# 8. christmas-mantel-garland
# --------------------------------------------------------------------------
def christmas_mantel_garland() -> Path:
    img, d = canvas("#FBF2E3")
    vertical_gradient(img, "#FCF7EC", "#EFDCC2")

    rect(d, 300, 700, 900, 1240, "#EFE2CC")                          # fireplace surround
    rect(d, 372, 782, 828, 1240, "#3E322B")                          # hearth opening
    radial_glow(img, 600, 1250, 330, "#E8A33D", 0.60, clip=(372, 782, 828, 1240))
    rrect(d, 452, 1152, 748, 1192, 18, "#7A4A33")                    # logs
    rrect(d, 476, 1190, 724, 1224, 16, "#6A4030")
    flame(d, 548, 1166, 58, 134, "#E8A33D", "#FBE3B4")               # fire in the hearth
    flame(d, 652, 1166, 58, 134, "#E8A33D", "#FBE3B4")
    flame(d, 600, 1174, 46, 96, "#F3C05A", "#FCE9C4")

    rect(d, 220, 640, 980, 700, "#E5D2B7")                           # mantel slab
    rect(d, 220, 640, 980, 648, "#F4E7D2")
    seg(d, 220, 700, 980, 700, "#C2A57F", 5)

    blend_rect(img, 296, 704, 904, 748, "#8B6F53", 0.16)             # shadow under the slab
    blend_rect(img, 240, 700, 350, 810, "#8B6F53", 0.12)             # shadows on the chimney breast
    blend_rect(img, 856, 700, 966, 810, "#8B6F53", 0.12)
    blend_rect(img, 316, 690, 884, 806, "#8B6F53", 0.14)             # shadow behind the swag
    stocking(img, d, 292, 706, "#9E3B4A", "#F0E2CB", foot=-1)        # stockings
    stocking(img, d, 908, 706, "#2E4636", "#F0E2CB", foot=1)

    x0g, x1g = 316.0, 884.0                                          # garland swag
    steps = 60
    tops, bots = [], []
    for i in range(steps + 1):
        t = i / steps
        x = x0g + (x1g - x0g) * t
        top = 652.0 + 122.0 * math.sin(math.pi * t)
        thick = 96.0 - 30.0 * math.sin(math.pi * t)
        tops.append((x, top))
        bots.append((x, top + thick))
    poly(d, tops + bots[::-1], "#2E4636")
    for i in range(19):                                              # sprigs along the top edge
        t = (i + 0.5) / 19
        x = x0g + (x1g - x0g) * t
        top = 652.0 + 122.0 * math.sin(math.pi * t)
        poly(d, leaf_points(x, top + 6, 60, 34, 196 + (i % 3) * 14, 0.9), "#3E5B47")
    for i in range(13):                                              # berries and baubles
        t = (i + 0.5) / 13
        x = x0g + (x1g - x0g) * t
        top = 652.0 + 122.0 * math.sin(math.pi * t)
        thick = 96.0 - 30.0 * math.sin(math.pi * t)
        ell(d, x, top + thick * 0.55, 15, 15, ("#C0603C", "#D9A059", "#EFE3CF")[i % 3])

    for cx, hgt in ((368, 150), (832, 196)):                         # candles on small holders
        top = 640 - hgt
        ell(d, cx, 640, 44, 13, "#D9C4A0")
        ell(d, cx, 636, 34, 9, "#EADCC2")
        rect(d, cx - 22, top, cx + 22, 638, "#F3E7D2")
        blend_rect(img, cx + 9, top, cx + 22, 638, "#BFA88A", 0.28)
        ell(d, cx, top, 22, 8, "#FBF3E4")
        radial_glow(img, cx, top - 46, 190, "#E8A33D", 0.42)
        flame(d, cx, top - 4, 34, 74, "#E8A33D", "#FBE3B4")

    return save(img, "christmas-mantel-garland.png", seed=808)


# --------------------------------------------------------------------------
# contact sheet: 4 columns, dark background, filename labels
# --------------------------------------------------------------------------
def make_contact_sheet(paths, out: Path) -> Path:
    cols, tw, th, pad, label_h = 4, 300, 375, 22, 30
    rows = math.ceil(len(paths) / cols)
    sheet_w = pad + cols * (tw + pad)
    sheet_h = pad + rows * (th + label_h + pad)
    sheet = Image.new("RGB", (sheet_w, sheet_h), hex2rgb("#141414"))
    sd = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 19)
    except OSError:
        font = ImageFont.load_default()
    for i, p in enumerate(paths):
        c, r = i % cols, i // cols
        x, y = pad + c * (tw + pad), pad + r * (th + label_h + pad)
        with Image.open(p) as im:
            sd.rectangle([x - 1, y - 1, x + tw, y + th], outline=hex2rgb("#3A3A3A"))
            sheet.paste(im.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        sd.text((x, y + th + 7), p.name, fill=hex2rgb("#E6DECE"), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "PNG", optimize=True)
    print(f"wrote {out}  ({sheet.size[0]}x{sheet.size[1]}, "
          f"{out.stat().st_size / 1024:.1f} KB)")
    return out


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------
def verify(paths) -> tuple[bool, str]:
    lines, seen, failed = [], {}, []
    for p in paths:
        with Image.open(p) as im:
            mode, size = im.mode, im.size
            rgb = im.convert("RGB")
            colour_count = len(rgb.getcolors(maxcolors=1 << 24) or [])
            grey = np.asarray(rgb.convert("L"), dtype=np.float32)
        kb = p.stat().st_size / 1024.0
        std = float(grey.std())
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        problems = []
        if size != (W, H):
            problems.append(f"size {size}")
        if mode != "RGB":
            problems.append(f"mode {mode}")
        if not (150.0 <= kb <= 600.0):
            problems.append(f"{kb:.1f} KB out of 150-600")
        if kb <= 15.0:
            problems.append("too small")
        if std <= 6.0:
            problems.append(f"std {std:.2f}")
        if colour_count <= 60:
            problems.append(f"colours {colour_count}")
        if sha in seen:
            problems.append(f"duplicate of {seen[sha]}")
        seen[sha] = p.name
        if problems:
            failed.append(f"{p.name}: " + "; ".join(problems))
        lines.append(f"{p.name:<28} {size[0]}x{size[1]}  {mode}  {kb:6.1f} KB  "
                     f"std={std:6.2f}  colours={colour_count:5d}  sha256={sha[:12]}"
                     + ("   <-- FAIL" if problems else ""))
    verdict = "PASS" if not failed else "FAIL: " + " | ".join(failed)
    report = "\n".join(lines + ["", verdict])
    return (not failed), report


# --------------------------------------------------------------------------
def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    paths = [fn() for fn in (autumn_arch_sunset, autumn_leaves_wreath, autumn_dried_stems,
                             autumn_stripe_wallpaper, cozy_window_rain,
                             christmas_tree_minimal, christmas_gift_stack,
                             christmas_mantel_garland)]
    make_contact_sheet(paths, ASSETS / "_contact_sheet.png")

    ok, report = verify(paths)
    print("\n" + report + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
