#!/usr/bin/env python3
"""Independent QA of batch-001's rendered pins (not the renderer's own logs).

Same checks the factory applies to its own samples (see
factory/tools/verify_samples.py) but pointed at content/batch-001, plus a
manifest cross-check so the batch is provably self-consistent:

  * every PNG: exactly 1000x1500, RGB/RGBA, sane size, real ink, colour variety,
    tonal span, no accidental edge bleed on padded templates
  * no duplicate files, cross-template perceptual distinctness
  * manifest.csv <-> rendered/: one row per PNG, every row's file exists,
    board/template/keyword columns non-empty, title/description limits hold

Writes rendered/_contact_sheet.png so a human can eyeball the whole batch.

    python3 tools/verify_batch.py [--json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
BATCH = HERE.parent
RENDERED = BATCH / "rendered"
SPECS = BATCH / "specs"
MANIFEST = BATCH / "manifest.csv"
FONTS = Path("/home/ubuntu/pinterest-rig/factory/fonts")

TARGET = (1000, 1500)
MIN_KB = 15
# padded layouts keep a clean outer margin (soft shadows count as ink, hence the floor)
MIN_INK_MARGIN = {"photo_frame": 28, "quote_card": 28, "editorial_minimal": 28}


def spec_templates() -> dict[str, str]:
    out = {}
    for path in SPECS.glob("*.json"):
        try:
            out[path.stem] = json.loads(path.read_text())["template"]
        except Exception:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        problems.append(f"unreadable: {exc}")
        return info
    info["size"], info["mode"] = img.size, img.mode
    info["kilobytes"] = round(path.stat().st_size / 1024, 1)
    if img.size != TARGET:
        problems.append(f"size {img.size} != {TARGET}")
    if img.mode not in ("RGB", "RGBA"):
        problems.append(f"unexpected mode {img.mode}")
    if info["kilobytes"] < MIN_KB:
        problems.append(f"suspiciously small ({info['kilobytes']} KB)")

    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    info["std"] = round(float(gray.std()), 2)
    info["distinct_colors"] = int(len(np.unique(arr.reshape(-1, 3), axis=0)))
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
    med = float(np.median(gray))
    p_lo, p_hi = (float(np.percentile(gray, q)) for q in (0.5, 99.5))
    info["contrast_span"] = int(max(med - p_lo, p_hi - med))
    if info["contrast_span"] < 90:
        problems.append(f"low tonal span ({info['contrast_span']}) — type may be low-contrast")
    ink_mask = np.abs(gray.astype(int) - bg) > 24
    ys, xs = np.nonzero(ink_mask)
    if len(xs):
        info["ink_margins"] = [int(xs.min()), int(ys.min()),
                               gray.shape[1] - 1 - int(xs.max()), gray.shape[0] - 1 - int(ys.max())]
    return info


def cross_check_manifest(pngs: list[Path]) -> tuple[list[str], dict]:
    problems: list[str] = []
    rows: list[dict] = []
    if not MANIFEST.exists():
        return ["manifest.csv missing"], {"rows": 0}
    with open(MANIFEST, newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        rows = list(reader)
    want = ["file", "template", "board", "title", "description", "alt_text", "target_keyword"]
    if cols != want:
        problems.append(f"manifest columns {cols} != {want}")
    files = {p.name for p in pngs}
    listed = set()
    for r in rows:
        name = Path(r.get("file", "")).name
        listed.add(name)
        if name not in files:
            problems.append(f"manifest row for {name} has no rendered PNG")
        if not r.get("template") or not r.get("board") or not r.get("alt_text"):
            problems.append(f"{name}: empty template/board/alt_text")
        t, d, k = r.get("title", ""), r.get("description", ""), r.get("target_keyword", "")
        if len(t) > 100:
            problems.append(f"{name}: title {len(t)} chars > 100")
        if not (150 <= len(d) <= 400):
            problems.append(f"{name}: description {len(d)} chars not in 150-400")
        tags = [w for w in d.split() if w.startswith("#")]
        if len(tags) > 3:
            problems.append(f"{name}: {len(tags)} hashtags > 3")
        if "http" in d or "www." in d:
            problems.append(f"{name}: description contains a link (batch-001 is link-free)")
        if not k:
            problems.append(f"{name}: empty target_keyword")
    for extra in sorted(files - listed):
        problems.append(f"rendered PNG {extra} has no manifest row")
    return problems, {"rows": len(rows), "columns": cols}


def make_contact_sheet(pngs: list[Path], mapping: dict[str, str]) -> Path:
    cols, tw, th, pad, label_h = 5, 260, 390, 16, 38
    rows = (len(pngs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), "#101418")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(FONTS / "Inter-VF.ttf"), 15)
        font.set_variation_by_axes([600, 14])
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    for i, path in enumerate(pngs):
        r, col = divmod(i, cols)
        x = pad + col * (tw + pad)
        y = pad + r * (th + label_h + pad)
        sheet.paste(Image.open(path).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x, y + th + 9), f"{mapping.get(path.stem, '?')} · {path.stem[:30]}",
               font=font, fill="#E8EDF2")
    out = RENDERED / "_contact_sheet.png"
    sheet.save(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-similarity", type=float, default=0.985)
    args = ap.parse_args()

    mapping = spec_templates()
    pngs = sorted(p for p in RENDERED.glob("*.png") if not p.name.startswith("_"))
    report: dict = {"count": len(pngs), "pins": [], "problems": []}
    if not pngs:
        print("no rendered pins found", file=sys.stderr)
        return 1

    fps: dict[str, np.ndarray] = {}
    for path in pngs:
        info = check_one(path)
        info["template"] = mapping.get(path.stem, "unknown")
        floor = MIN_INK_MARGIN.get(info["template"], 0)
        if floor and info.get("ink_margins") and min(info["ink_margins"]) < floor:
            info["problems"].append(
                f"ink reaches {min(info['ink_margins'])}px from the edge (min {floor}px for {info['template']})")
        report["pins"].append(info)
        report["problems"].extend(f"{path.name}: {p}" for p in info["problems"])
        try:
            fps[path.name] = fingerprint(Image.open(path))
        except Exception:  # noqa: BLE001
            pass

    counts: dict[str, int] = {}
    for info in report["pins"]:
        counts[info["template"]] = counts.get(info["template"], 0) + 1
    report["template_counts"] = counts
    if len(pngs) < 20:
        report["problems"].append(f"only {len(pngs)} pins rendered, expected 20")
    for tmpl, n in counts.items():
        if tmpl == "unknown":
            report["problems"].append("pin(s) without a matching spec")
        elif n < 3:
            report["problems"].append(f"template {tmpl} has only {n} pins, expected >= 3")

    names = list(fps)
    cross = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            sim = float(np.corrcoef(fps[a].ravel(), fps[b].ravel())[0, 1])
            if mapping.get(Path(a).stem) != mapping.get(Path(b).stem):
                cross.append((sim, a, b))
    report["max_cross_template_similarity"] = round(max(cross, default=(0, "", ""))[0], 4)
    report["cross_template_pairs"] = len(cross)
    for sim, a, b in cross:
        if sim > args.min_similarity:
            report["problems"].append(f"{a} and {b} look nearly identical (sim={sim:.3f})")

    hashes: dict[str, list[str]] = {}
    for path in pngs:
        hashes.setdefault(hashlib.sha256(path.read_bytes()).hexdigest()[:16], []).append(path.name)
    for group in (v for v in hashes.values() if len(v) > 1):
        report["problems"].append(f"identical files: {group}")

    mprobs, minfo = cross_check_manifest(pngs)
    report["manifest"] = minfo
    report["problems"].extend(mprobs)
    report["contact_sheet"] = str(make_contact_sheet(pngs, mapping))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"pins: {report['count']}  templates: {counts}")
        print(f"manifest: {minfo.get('rows')} rows, columns {minfo.get('columns')}")
        print(f"cross-template similarity (max): {report['max_cross_template_similarity']} "
              f"over {report['cross_template_pairs']} pairs")
        for info in report["pins"]:
            print(f"  {'OK  ' if not info['problems'] else 'FAIL'} {Path(info['file']).name:44s} "
                  f"{info.get('size')} {info.get('mode')} {info.get('kilobytes'):>7} KB  "
                  f"ink={info.get('ink_ratio')} colours={info.get('distinct_colors')} "
                  f"span={info.get('contrast_span')} margins={info.get('ink_margins')} "
                  f"tmpl={info.get('template')}")
        print(f"contact sheet: {report['contact_sheet']}")
        if report["problems"]:
            print("\nPROBLEMS:")
            for p in report["problems"]:
                print("  !", p)
        else:
            print("\nall batch checks passed")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
