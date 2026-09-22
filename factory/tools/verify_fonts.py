#!/usr/bin/env python3
"""Verify every font the factory relies on actually rasterises.

Uses the factory's own FontBook (single source of truth for variable-font axis
handling) so this test fails if the renderer would silently fall back to a
system font.

    python3 tools/verify_fonts.py

Checks per style:
  * the expected TTF is the one actually loaded (no system fallback)
  * glyphs rasterise with real ink (not .notdef boxes / blank output)
  * variable axes were applied where expected

Writes fonts/_contact_sheet.png so a human can eyeball every face.
Exits non-zero on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pin_factory as pf  # noqa: E402

FONT_DIR = ROOT / "fonts"
TEXT = "AaBb Gg Qq 0123 — the quick brown fox jumps over the lazy dog"
SIZE = 56
PAD = 22

# style -> file we expect the FontBook to pick
EXPECTED = {
    "display": ("playfair", "PlayfairDisplay-VF.ttf", True),
    "display_black": ("playfair", "PlayfairDisplay-VF.ttf", True),
    "display_italic": ("playfair", "PlayfairDisplay-Italic-VF.ttf", True),
    "serif": ("dmserif", "DMSerifDisplay-Regular.ttf", False),
    "serif_italic": ("dmserif", "DMSerifDisplay-Italic.ttf", False),
    "sans": ("poppins", "Poppins-Regular.ttf", False),
    "sans_medium": ("poppins", "Poppins-Medium.ttf", False),
    "sans_semi": ("poppins", "Poppins-SemiBold.ttf", False),
    "sans_bold": ("poppins", "Poppins-Bold.ttf", False),
    "sans_black": ("poppins", "Poppins-ExtraBold.ttf", False),
    "sans_italic": ("poppins", "Poppins-Italic.ttf", False),
    "script": ("caveat", "Caveat-VF.ttf", True),
    "script_light": ("caveat", "Caveat-VF.ttf", True),
    "ui": ("inter", "Inter-VF.ttf", True),
    "ui_medium": ("inter", "Inter-VF.ttf", True),
    "ui_semi": ("inter", "Inter-VF.ttf", True),
    "ui_bold": ("inter", "Inter-VF.ttf", True),
}


def ink_pixels(img: Image.Image) -> int:
    gray = img.convert("L")
    bg = gray.getpixel((2, 2))
    px = gray.load()
    return sum(1 for y in range(gray.height) for x in range(gray.width)
               if abs(px[x, y] - bg) > 24)


def main() -> int:
    ok_img = ImageFont.load_default()
    book = pf.FontBook(font_dir=FONT_DIR, scale=1)
    failures: list[str] = []
    rows: list[tuple[str, Image.Image]] = []

    print(f"fonts dir: {FONT_DIR}")
    for style, (family, filename, variable) in EXPECTED.items():
        try:
            font = book.get(style, SIZE)
        except Exception as exc:
            failures.append(f"{style}: {exc}")
            print(f"FAIL {style:16s} {exc}")
            continue
        loaded = Path(font.path).name
        problems = []
        if loaded != filename:
            problems.append(f"loaded {loaded}, expected {filename}")
        axes = getattr(font, "_pin_axes", None)
        if variable and not axes:
            problems.append("variable axes not applied")
        bbox = font.getbbox(TEXT)
        img = Image.new("RGB", (max(bbox[2], 1) + PAD * 2, bbox[3] + PAD * 2), "white")
        ImageDraw.Draw(img).text((PAD - bbox[0], PAD - bbox[1]), TEXT, font=font, fill="black")
        ink = ink_pixels(img)
        if ink < 500:
            problems.append(f"no ink ({ink} px)")
        status = "OK  " if not problems else "FAIL"
        print(f"{status} {style:16s} {loaded:30s} axes={axes} ink={ink:6d}")
        for prob in problems:
            failures.append(f"{style}: {prob}")
            print(f"       ! {prob}")
        rows.append((f"{style}  [{family}]", img))

    if rows:
        width = max(r[1].width for r in rows) + 400
        lh = max(r[1].height for r in rows) + 10
        sheet = Image.new("RGB", (width, lh * len(rows)), "#f6f6f4")
        d = ImageDraw.Draw(sheet)
        for i, (label, img) in enumerate(rows):
            sheet.paste(img, (392, i * lh + 5))
            d.text((14, i * lh + 16), label, font=ok_img, fill="#111111")
        out = FONT_DIR / "_contact_sheet.png"
        sheet.save(out)
        print(f"\ncontact sheet -> {out} ({sheet.width}x{sheet.height})")

    print(f"\n{len(rows)} styles rendered, {len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
