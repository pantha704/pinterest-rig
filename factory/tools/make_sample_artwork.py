#!/usr/bin/env python3
"""Generate the ORIGINAL artwork used by the sample pins.

Nothing here is stock imagery or scraped from the web — every asset is drawn
procedurally with Pillow/numpy, so the pins stay 100% original artwork (which is
what a Pinterest affiliate/aesthetic account needs).

    python3 tools/make_sample_artwork.py

Writes 1200x1500 PNGs into ./assets and prints their paths.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SS = 2  # supersample

W, H = 1200, 1500


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
    grad = np.repeat(row, img.width, axis=1)
    img.paste(Image.fromarray(grad, "RGB"), (0, 0))


def grain(img: Image.Image, amount: float = 5.0, seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, amount, (img.height, img.width, 1)).astype(np.float32)
    arr = np.asarray(img).astype(np.float32) + noise
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def save(img: Image.Image, name: str) -> Path:
    out = ASSETS / name
    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(out, "PNG", optimize=True)
    print(f"{out}  ({out.stat().st_size} bytes)")
    return out


def arch_sunset() -> Path:
    """Warm minimal arch + sun — the classic 2020s poster motif."""
    img, d = canvas("#F6E7D7")
    vertical_gradient(img, "#FBEEDF", "#F2D8BE")
    cx = W * SS / 2
    arch_w, arch_h = 640 * SS, 780 * SS
    base_y = 1180 * SS
    d.pieslice([cx - arch_w / 2, base_y - arch_h, cx + arch_w / 2, base_y - arch_h / 2 + arch_h / 2],
               180, 360, fill=hex2rgb("#C0603C"))
    d.rectangle([cx - arch_w / 2, base_y - arch_h / 2, cx + arch_w / 2, base_y], fill=hex2rgb("#C0603C"))
    d.ellipse([cx - 150 * SS, base_y - arch_h - 250 * SS, cx + 150 * SS, base_y - arch_h + 50 * SS],
              fill=hex2rgb("#E8A33D"))
    d.line([80 * SS, base_y + 60 * SS, W * SS - 80 * SS, base_y + 60 * SS],
           fill=hex2rgb("#7A4A33"), width=int(4 * SS))
    d.line([80 * SS, base_y + 120 * SS, W * SS - 80 * SS, base_y + 120 * SS],
           fill=hex2rgb("#7A4A33"), width=int(2 * SS))
    return save(grain(img), "art-arch-sunset.png")


def soft_waves() -> Path:
    """Layered sine waves in sage/teal — calm abstract for lifestyle pins."""
    img, d = canvas("#EDF3F0")
    vertical_gradient(img, "#F4F8F5", "#DCE9E3")
    layers = [("#BBD3C6", 980, 62, 0.0), ("#8FB6A5", 1090, 48, 0.9), ("#5D8C7B", 1210, 34, 1.8),
              ("#3B6656", 1330, 22, 2.7)]
    xs = np.arange(0, W * SS, 4)
    for color, base, amp, phase in layers:
        ys = base * SS + amp * SS * np.sin(xs / (210 * SS) * math.pi * 2 + phase)
        pts = list(zip(xs.tolist(), ys.tolist())) + [(W * SS, H * SS), (0, H * SS)]
        d.polygon(pts, fill=hex2rgb(color))
    d.ellipse([W * SS * 0.62, 240 * SS, W * SS * 0.62 + 220 * SS, 240 * SS + 220 * SS],
              fill=hex2rgb("#F0C77E"))
    return save(grain(img), "art-soft-waves.png")


def still_life() -> Path:
    """Flat minimal still life: vase, three stems, table line."""
    img, d = canvas("#F7F1EA")
    vertical_gradient(img, "#FBF6F0", "#EFE4D9")
    table_y = 1120 * SS
    d.rectangle([0, table_y, W * SS, H * SS], fill=hex2rgb("#E3D3C4"))
    d.line([0, table_y, W * SS, table_y], fill=hex2rgb("#C9B39F"), width=int(4 * SS))
    # vase
    vx, vw, vtop, vbot = W * SS / 2, 250 * SS, 760 * SS, table_y
    d.polygon([(vx - vw / 2, vtop), (vx + vw / 2, vtop), (vx + vw * 0.72, vbot), (vx - vw * 0.72, vbot)],
              fill=hex2rgb("#C98A5B"))
    d.ellipse([vx - vw / 2, vtop - 34 * SS, vx + vw / 2, vtop + 34 * SS], fill=hex2rgb("#B87A4C"))
    # stems + leaves
    for dx, lean, colr in ((-70, -0.35, "#4F7A5A"), (10, 0.05, "#3F6B4E"), (78, 0.4, "#5C8A66")):
        x0, y0 = vx + dx * SS, vtop - 20 * SS
        x1, y1 = x0 + lean * 260 * SS, y0 - 420 * SS
        d.line([x0, y0, x1, y1], fill=hex2rgb(colr), width=int(9 * SS))
        for t in (0.45, 0.72):
            lx, ly = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            d.ellipse([lx - 72 * SS, ly - 34 * SS, lx + 72 * SS, ly + 34 * SS], fill=hex2rgb(colr))
    d.ellipse([140 * SS, 300 * SS, 140 * SS + 170 * SS, 300 * SS + 170 * SS], fill=hex2rgb("#EBD7A6"))
    return save(grain(img), "art-still-life.png")


def checker_tiles() -> Path:
    """Monochrome tile pattern — good contrast backdrop for product-style pins."""
    img, d = canvas("#F3F1EC")
    tile = 150 * SS
    for row in range(0, H * SS // tile + 1):
        for col in range(0, W * SS // tile + 1):
            if (row + col) % 2 == 0:
                d.rectangle([col * tile, row * tile, (col + 1) * tile, (row + 1) * tile],
                            fill=hex2rgb("#DCD7CD"))
    d.ellipse([W * SS * 0.22, H * SS * 0.28, W * SS * 0.78, H * SS * 0.66], fill=hex2rgb("#2F4A57"))
    d.ellipse([W * SS * 0.34, H * SS * 0.36, W * SS * 0.66, H * SS * 0.56], fill=hex2rgb("#EDE7DA"))
    return save(grain(img, 3.0), "art-checker-plate.png")


def blurred_bloom() -> Path:
    """Soft blurred bloom — pairs with the pastel/quote templates."""
    img, d = canvas("#F6F1FA")
    vertical_gradient(img, "#FBF7FE", "#EFE7F8")
    for (cx, cy, r, color) in ((330, 430, 300, "#C6B4F2"), (820, 700, 360, "#F0A6C0"),
                               (520, 1120, 320, "#9FD3E8")):
        layer = Image.new("RGB", (W * SS, H * SS), hex2rgb("#F6F1FA"))
        dl = ImageDraw.Draw(layer)
        dl.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], fill=hex2rgb(color))
        layer = layer.filter(ImageFilter.GaussianBlur(r * SS * 0.42))
        img = Image.blend(img, layer, 0.55)
    return save(grain(img), "art-blurred-bloom.png")


def main() -> int:
    if not ASSETS.exists():
        ASSETS.mkdir(parents=True)
    for fn in (arch_sunset, soft_waves, still_life, checker_tiles, blurred_bloom):
        fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
