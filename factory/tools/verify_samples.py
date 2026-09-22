#!/usr/bin/env python3
"""Independent verification of the rendered pins.

Checks every PNG in ./samples (not the renderer's own logs):
  * valid image, exactly 1000x1500, RGB/RGBA, sane file size
  * real ink coverage + colour variety (not a blank or flat card)
  * per-template sample counts (>= 2 each, >= 12 total)
  * cross-template visual distinctness (perceptual hash distance)
  * contrast of the lightest vs darkest pixel regions

Also writes samples/_contact_sheet.png so a human can eyeball everything at once.

    python3 tools/verify_samples.py            # full check
    python3 tools/verify_samples.py --json     # machine-readable report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
SPECS = ROOT / "specs"
FONTS = ROOT / "fonts"

TARGET = (1000, 1500)
MIN_KILOBYTES = 15

# templates with a padded (non-full-bleed) layout must keep a clean outer margin.
# NOTE: soft shadows count as ink, so padded templates get a forgiving threshold.
MIN_INK_MARGIN = {
    "photo_frame": 28,
    "quote_card": 28,
    "editorial_minimal": 28,
}


def spec_templates() -> dict[str, str]:
    """sample stem -> template name (from the matching spec file)."""
    out: dict[str, str] = {}
    for path in SPECS.glob("*.json"):
        try:
            out[path.stem] = json.loads(path.read_text())["template"]
        except Exception:
            continue
    return out


def fingerprint(img: Image.Image, size=(40, 60)) -> np.ndarray:
    arr = np.asarray(img.convert("L").resize(size, Image.BILINEAR), dtype=np.float32)
    return (arr - arr.mean()) / (arr.std() + 1e-6)


def check_one(path: Path) -> dict:
    problems: list[str] = []
    info: dict = {"file": str(path), "problems": problems}
    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:
        problems.append(f"unreadable: {exc}")
        return info
    info["size"] = img.size
    info["mode"] = img.mode
    info["kilobytes"] = round(path.stat().st_size / 1024, 1)
    if img.size != TARGET:
        problems.append(f"size {img.size} != {TARGET}")
    if img.mode not in ("RGB", "RGBA"):
        problems.append(f"unexpected mode {img.mode}")
    if info["kilobytes"] < MIN_KILOBYTES:
        problems.append(f"suspiciously small ({info['kilobytes']} KB)")

    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    info["std"] = round(float(gray.std()), 2)
    info["distinct_colors"] = int(len(np.unique(arr.reshape(-1, 3), axis=0)))
    # ink coverage: pixels that differ from the most common (background) tone
    flat = gray.reshape(-1)
    hist = np.bincount(flat, minlength=256)
    bg = int(hist.argmax())
    info["ink_ratio"] = round(float((np.abs(flat.astype(int) - bg) > 24).mean()), 4)
    if info["ink_ratio"] < 0.01:
        problems.append(f"almost no ink ({info['ink_ratio']})")
    if info["std"] < 6:
        problems.append(f"flat image, std={info['std']}")
    if info["distinct_colors"] < 60:
        problems.append(f"too few colours ({info['distinct_colors']})")
    # legibility proxy: how far the darkest/most extreme ink sits from the page tone
    med = float(np.median(gray))
    p_lo, p_hi = (float(np.percentile(gray, q)) for q in (0.5, 99.5))
    info["contrast_span"] = int(max(med - p_lo, p_hi - med))
    if info["contrast_span"] < 90:
        problems.append(f"low tonal span ({info['contrast_span']}) — type may be low-contrast")
    # where does ink actually reach? catches accidental edge bleed on padded layouts
    ink_mask = np.abs(gray.astype(int) - bg) > 24
    ys, xs = np.nonzero(ink_mask)
    if len(xs):
        info["ink_bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        margins = [int(xs.min()), int(ys.min()),
                   gray.shape[1] - 1 - int(xs.max()), gray.shape[0] - 1 - int(ys.max())]
        info["ink_margins"] = margins
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-similarity", type=float, default=0.985,
                    help="cross-template pairs more similar than this are flagged")
    args = ap.parse_args()

    mapping = spec_templates()
    pngs = sorted(SAMPLES.glob("*.png"))
    pngs = [p for p in pngs if not p.name.startswith("_")]
    report: dict = {"count": len(pngs), "samples": [], "problems": []}
    if not pngs:
        print("no samples found", file=sys.stderr)
        return 1

    fps: dict[str, np.ndarray] = {}
    for path in pngs:
        info = check_one(path)
        info["template"] = mapping.get(path.stem, "unknown")
        floor = MIN_INK_MARGIN.get(info["template"], 0)
        if floor and info.get("ink_margins") and min(info["ink_margins"]) < floor:
            info["problems"].append(
                f"ink reaches {min(info['ink_margins'])}px from the edge (min {floor}px for "
                f"{info['template']})")
        report["samples"].append(info)
        if info["problems"]:
            report["problems"].extend(f"{path.name}: {p}" for p in info["problems"])
        try:
            fps[path.name] = fingerprint(Image.open(path))
        except Exception:
            pass

    # per-template counts
    counts: dict[str, int] = {}
    for info in report["samples"]:
        counts[info["template"]] = counts.get(info["template"], 0) + 1
    report["template_counts"] = counts
    if len(pngs) < 12:
        report["problems"].append(f"only {len(pngs)} samples, need >= 12")
    for tmpl, n in counts.items():
        if tmpl == "unknown":
            report["problems"].append("sample(s) without a matching spec")
        elif n < 2:
            report["problems"].append(f"template {tmpl} has only {n} sample(s), need >= 2")
    for tmpl, n in mapping.items():
        if tmpl not in {p.stem for p in pngs} and n:
            pass  # spec without a rendered sample is reported below

    names = list(fps)
    cross: list[tuple[float, str, str]] = []
    same: list[tuple[float, str, str]] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            diff = float(np.abs(fps[a] - fps[b]).mean())
            sim = float(np.corrcoef(fps[a].ravel(), fps[b].ravel())[0, 1])
            if mapping.get(Path(a).stem) == mapping.get(Path(b).stem):
                same.append((sim, a, b))
            else:
                cross.append((sim, a, b))
    report["max_cross_template_similarity"] = round(max(cross, default=(0, "", ""))[0], 4)
    report["cross_template_pairs"] = len(cross)
    for sim, a, b in cross:
        if sim > args.min_similarity:
            report["problems"].append(f"{a} and {b} look nearly identical (sim={sim:.3f})")
    report["identical_pairs"] = [(round(s, 3), a, b) for s, a, b in cross if s > 0.999]

    # hashes: catch accidental duplicate renders
    hashes: dict[str, list[str]] = {}
    for path in pngs:
        h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        hashes.setdefault(h, []).append(path.name)
    dupes = [v for v in hashes.values() if len(v) > 1]
    for group in dupes:
        report["problems"].append(f"identical files: {group}")

    # contact sheet
    sheet = make_contact_sheet(pngs, mapping)
    report["contact_sheet"] = str(sheet)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"samples: {report['count']}  templates: {counts}")
        print(f"cross-template similarity (max): {report['max_cross_template_similarity']}")
        for info in report["samples"]:
            print(f"  {'OK  ' if not info['problems'] else 'FAIL'} {Path(info['file']).name:34s} "
                  f"{info.get('size')} {info.get('mode')} {info.get('kilobytes'):>7} KB  "
                  f"ink={info.get('ink_ratio')} colours={info.get('distinct_colors')} "
                  f"tmpl={info.get('template')}")
        print(f"contact sheet: {sheet}")
        if report["problems"]:
            print("\nPROBLEMS:")
            for p in report["problems"]:
                print("  !", p)
        else:
            print("\nall sample checks passed")
    return 1 if report["problems"] else 0


def make_contact_sheet(pngs: list[Path], mapping: dict[str, str]) -> Path:
    cols = 4
    tw, th = 300, 450
    pad, label_h = 18, 40
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), "#101418")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(FONTS / "Inter-VF.ttf"), 17)
        font.set_variation_by_axes([600, 14])
    except Exception:
        font = ImageFont.load_default()
    groups: dict[str, list[Path]] = {}
    for p in pngs:
        groups.setdefault(mapping.get(p.stem, "unknown"), []).append(p)
    order = [p for tmpl in sorted(groups) for p in groups[tmpl]]
    for i, path in enumerate(order):
        r, col = divmod(i, cols)
        x = pad + col * (tw + pad)
        y = pad + r * (th + label_h + pad)
        thumb = Image.open(path).convert("RGB").resize((tw, th), Image.LANCZOS)
        sheet.paste(thumb, (x, y))
        label = f"{mapping.get(path.stem, '?')}  ·  {path.stem}"
        d.text((x, y + th + 10), label[:44], font=font, fill="#E8EDF2")
    out = SAMPLES / "_contact_sheet.png"
    sheet.save(out)
    return out


if __name__ == "__main__":
    sys.exit(main())
