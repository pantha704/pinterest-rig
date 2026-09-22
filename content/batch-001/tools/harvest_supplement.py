#!/usr/bin/env python3
"""Supplementary logged-out keyword harvest for batch-001 gap terms.

The main harvest (keywords/harvest.py) returned almost no Christmas *decor*
terms, and no autumn-home / printable-wall-art terms. Batch-001 pins target
those boards, so this script pulls a small, polite top-up from the same
keyless endpoints the Pinterest Trends app uses:

    /prefix_match/?query=<seed>&country=<cc>
    /related_terms/?requestTerm=<seed>&country=<cc>&endDate=..&aggregation=..

Politeness: sequential, 3-5 s randomised gaps, 8 requests total, its own
request log (content/batch-001/data/reqlog.txt).

    python3 harvest_supplement.py
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
REQLOG = DATA / "reqlog.txt"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://trends.pinterest.com"
HDRS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9", "Referer": "https://trends.pinterest.com/"}
DELAY = (3.0, 5.0)
END_DATE = time.strftime("%Y-%m-%d", time.gmtime())

# (seed, country) for prefix_match
PREFIX_SEEDS = [
    ("christmas home decor", "US"),
    ("christmas home decor", "GB"),
    ("christmas decorations", "US"),
    ("cozy christmas", "US"),
    ("fall home decor", "US"),
    ("autumn home decor", "GB"),
    ("printable wall art", "US"),
]
# (seed, country) for related_terms
RELATED_SEEDS = [
    ("christmas home decor", "US"),
]


def get(path: str, params: dict) -> tuple[int, object]:
    params = {k: v for k, v in params.items() if v is not None}
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        status, body = -1, str(e)
    with open(REQLOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{status}\t{url}\n")
    try:
        return status, json.loads(body)
    except Exception:  # noqa: BLE001
        return status, body


def series_summary(counts) -> dict:
    """52-week series 0-100 -> latest / mean / max + 52w change (first->last)."""
    vals = [c.get("count") if isinstance(c, dict) else c for c in (counts or [])]
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        return {}
    return {"latest": round(vals[-1], 1), "mean": round(sum(vals) / len(vals), 1),
            "max": round(max(vals), 1), "trend_52w": round(vals[-1] - vals[0], 1),
            "weeks": len(vals)}


def rows_of(j) -> list:
    """prefix_match returns a bare list; related_terms returns a list or {values:[...]}."""
    if isinstance(j, list):
        return [r for r in j if r]
    if isinstance(j, dict):
        for key in ("values", "suggestions", "relatedSearches", "results"):
            v = j.get(key)
            if isinstance(v, list):
                return [r for r in v if r]
    return []


def main() -> int:
    out = {
        "harvested": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "https://trends.pinterest.com/prefix_match/ + /related_terms/",
        "note": "supplementary gap-fill for batch-001 (christmas decor / autumn home / printable wall art)",
        "rows": [],
    }
    n = 0
    for seed, cc in PREFIX_SEEDS:
        status, j = get("/prefix_match/", {"query": seed, "country": cc})
        rows = rows_of(j)
        print(f"[prefix] {cc} {seed!r} -> {status} n={len(rows)}")
        for r in rows:
            term = (r or {}).get("term")
            if not term:
                continue
            summ = series_summary(r.get("counts"))
            out["rows"].append({"seed": seed, "suggestion": term, "source": "prefix_match",
                                "country": cc, **summ})
        n += 1
        time.sleep(random.uniform(*DELAY))
    for seed, cc in RELATED_SEEDS:
        status, j = get("/related_terms/", {"requestTerm": seed, "country": cc,
                                            "endDate": END_DATE, "aggregation": 2,
                                            "lookback": 90, "predictedDays": 0,
                                            "shouldMock": "false"})
        rows = rows_of(j)
        print(f"[related] {cc} {seed!r} -> {status} n={len(rows)}")
        for r in rows:
            if isinstance(r, str):
                term, extra = r, {}
            else:
                term, extra = (r or {}).get("term") or (r or {}).get("query"), (r or {})
            if not term:
                continue
            summ = series_summary(extra.get("counts"))
            out["rows"].append({"seed": seed, "suggestion": term, "source": "related_terms",
                                "country": cc, **summ})
        n += 1
        time.sleep(random.uniform(*DELAY))

    dst = DATA / "supplement_keywords.json"
    dst.write_text(json.dumps(out, indent=2))

    # flat CSV, sorted by latest interest
    csv = DATA / "supplement_keywords.csv"
    cols = ["seed", "suggestion", "source", "country", "latest", "mean", "max", "trend_52w", "weeks"]
    with open(csv, "w") as f:
        f.write(",".join(cols) + "\n")
        for r in sorted(out["rows"], key=lambda r: -(r.get("latest") or 0)):
            f.write(",".join(str(r.get(c, "")) for c in cols) + "\n")

    print(f"\n{len(out['rows'])} rows -> {dst}\n{csv}  ({n} requests)")
    for r in sorted(out["rows"], key=lambda r: -(r.get("latest") or 0))[:40]:
        print(f"  {r['suggestion']!r:48s} {r['country']} {r['source']:14s} "
              f"latest={r.get('latest')} mean={r.get('mean')} max={r.get('max')} 52w={r.get('trend_52w')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
