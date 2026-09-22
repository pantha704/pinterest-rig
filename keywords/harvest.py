#!/usr/bin/env python3
"""
Pinterest trends + keyword harvester (logged-out, polite).

Discovers and uses the same JSON endpoints the Pinterest Trends React app calls:
  /top_trends_filtered/  -> trending terms + relative volume + seasonality metadata
  /prefix_match/         -> autocomplete-style suggestions with 52-week interest series
  /related_terms/        -> related searches for a seed term
  /metrics/              -> interest-over-time series for explicit terms

Politeness: sequential only, 3-5s randomised gaps, hard request budget, incremental
writes so partial results survive an interrupt.

Usage: python3 harvest.py trends|suggestions|all
"""
import json, os, random, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
os.makedirs(RAW, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://trends.pinterest.com"
HDRS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9", "Referer": "https://trends.pinterest.com/"}
DELAY = (3.0, 5.0)
BUDGET = 170                      # hard cap for the whole run
END_DATE = time.strftime("%Y-%m-%d", time.gmtime())
COUNTER = os.path.join(HERE, "_reqcount.txt")
REQLOG = os.path.join(HERE, "raw", "reqlog.txt")


def _count():
    try:
        return int(open(COUNTER).read().strip() or 0)
    except Exception:
        return 0


def _bump(url, status):
    n = _count() + 1
    open(COUNTER, "w").write(str(n))
    with open(REQLOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t{status}\t{url}\n")
    return n


def get(path, params, save_as=None, retries=2):
    """One politeness-paced GET. Returns (status, parsed_or_text)."""
    params = {k: v for k, v in params.items() if v is not None}
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries + 1):
        if _count() >= BUDGET:
            print(f"!! budget {BUDGET} reached, stopping", file=sys.stderr)
            return -2, None
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=35) as r:
                status, body = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode("utf-8", "replace")
        except Exception as e:
            status, body = -1, str(e)
        n = _bump(url, status)
        if save_as:
            with open(os.path.join(RAW, save_as), "w") as f:
                f.write(body if isinstance(body, str) else str(body))
        if status in (429, 500, 502, 503):
            wait = 20 * (attempt + 1)
            print(f"   [{status}] backing off {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        time.sleep(random.uniform(*DELAY))
        try:
            return status, json.loads(body)
        except Exception:
            return status, body
    return status, None


def save_json(name, obj):
    tmp = os.path.join(HERE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(HERE, name))


# --------------------------------------------------------------------------- A
COUNTRIES = [("US", "US"), ("GB", "GB+IE"), ("GB", "GB"), ("CA", "CA"),
             ("AU", "AU"), ("DE", "DE")]
PRESETS = [(1, "top_monthly"), (2, "top_yearly"), (3, "trending_now"),
           (4, "growing")]


def harvest_trends():
    for cc, cparam in COUNTRIES:
        label = cc if cparam == cc else f"{cc}({cparam})"
        outfile = f"trends_{cc}.json" if cparam == cc else f"trends_{cc}_altreg.json"
        existing = {}
        if os.path.exists(os.path.join(HERE, outfile)):
            existing = json.load(open(os.path.join(HERE, outfile)))
        by_preset = existing.get("presets", {})
        for pv, pname in PRESETS:
            status, j = get("/top_trends_filtered/",
                            {"lookbackWindow": 2, "endDate": END_DATE,
                             "rankingMethod": 3, "country": cparam,
                             "trendsPreset": pv, "numTermsToReturn": 50},
                            save_as=f"tt_{cc}_{pname}.json")
            vals = (j or {}).get("values") if isinstance(j, dict) else None
            n = len(vals) if vals else 0
            print(f"[trends] {label} preset={pname}({pv}) -> {status} terms={n}")
            if vals:
                by_preset[pname] = {"preset_value": pv, "country_param": cparam,
                                    "end_date": END_DATE, "values": vals}
            save_json(outfile, {
                "source": "https://trends.pinterest.com/top_trends_filtered/",
                "country": cc, "country_param": cparam, "end_date": END_DATE,
                "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "presets": by_preset})
    print(f"[trends] done, requests total={_count()}")


# --------------------------------------------------------------------------- B
SEEDS = ["home decor", "desk setup", "wallpaper", "planner", "budget",
         "skincare", "outfit ideas", "gift ideas", "coloring pages",
         "journal ideas", "aesthetic room", "meal prep", "travel tips",
         "wedding", "study motivation"]


def harvest_suggestions():
    path = os.path.join(HERE, "suggestions.json")
    doc = json.load(open(path)) if os.path.exists(path) else {
        "source": "https://trends.pinterest.com/prefix_match/ + /related_terms/",
        "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": SEEDS, "records": []}
    have = {(r["seed"], r["suggestion"], r["source"]) for r in doc["records"]}
    for seed in SEEDS:
        for cc in ("US", "GB"):
            status, j = get("/prefix_match/", {"query": seed, "country": cc},
                            save_as=f"pm_{cc}_{seed.replace(' ', '_')}.json")
            rows = j if isinstance(j, list) else []
            print(f"[sug] prefix_match {cc} '{seed}' -> {status} n={len(rows)}")
            for r in rows:
                term = (r or {}).get("term")
                if not term:
                    continue
                key = (seed, term, "prefix_match")
                if key in have:
                    continue
                have.add(key)
                counts = r.get("counts") or []
                doc["records"].append({
                    "seed": seed, "suggestion": term, "source": "prefix_match",
                    "country": cc, "counts_52w": counts,
                    "latest_interest": counts[-1] if counts else None,
                    "mean_interest": round(sum(counts) / len(counts), 1) if counts else None,
                    "max_interest": max(counts) if counts else None})
            save_json("suggestions.json", doc)
        status, j = get("/related_terms/", {
            "requestTerm": seed, "country": "US", "endDate": END_DATE,
            "aggregation": 2, "lookback": 90, "predictedDays": 0,
            "shouldMock": "false"}, save_as=f"rt_US_{seed.replace(' ', '_')}.json")
        rows = j if isinstance(j, list) else (j or {}).get("values", []) \
            if isinstance(j, dict) else []
        print(f"[sug] related_terms US '{seed}' -> {status} n={len(rows)}")
        for r in rows:
            if isinstance(r, str):
                term, extra = r, {}
            elif isinstance(r, dict):
                term = r.get("term") or r.get("query")
                extra = r
            else:
                continue
            if not term:
                continue
            key = (seed, term, "related_terms")
            if key in have:
                continue
            have.add(key)
            counts = extra.get("counts") or []
            doc["records"].append({
                "seed": seed, "suggestion": term, "source": "related_terms",
                "country": "US", "counts_52w": counts,
                "latest_interest": counts[-1] if counts else None,
                "mean_interest": round(sum(counts) / len(counts), 1) if counts else None,
                "max_interest": max(counts) if counts else None})
        save_json("suggestions.json", doc)
    print(f"[sug] done, records={len(doc['records'])}, requests total={_count()}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("trends", "all"):
        harvest_trends()
    if what in ("suggestions", "all"):
        harvest_suggestions()
