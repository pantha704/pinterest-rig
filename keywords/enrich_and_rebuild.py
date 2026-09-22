#!/usr/bin/env python3
"""Enrichment round: related_terms for the 15 seeds in GB (UK long-tail), then
rebuild suggestions.json / csv purely from raw/ payloads (no re-fetch needed)."""
import csv, glob, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harvest import get, SEEDS, save_json  # reuse the polite fetch client

RAW = os.path.join(HERE, "raw")


def enrich_gb_related():
    for seed in SEEDS:
        fn = f"rt_GB_{seed.replace(' ', '_')}.json"
        if os.path.exists(os.path.join(RAW, fn)):
            print(f"[skip] {fn} exists")
            continue
        st, j = get("/related_terms/", {
            "requestTerm": seed, "country": "GB", "endDate": time.strftime("%Y-%m-%d", time.gmtime()),
            "aggregation": 2, "lookback": 90, "predictedDays": 0, "shouldMock": "false"},
            save_as=fn)
        n = len(j) if isinstance(j, list) else 0
        print(f"[enrich] related_terms GB '{seed}' -> {st} n={n}")


def _series(rec):
    counts = rec.get("counts") or []
    if not counts:
        return {}
    return {"counts_52w": counts, "latest_interest": counts[-1],
            "mean_interest": round(sum(counts) / len(counts), 1),
            "max_interest": max(counts),
            "trend_52w": round(counts[-1] - counts[0], 1)}


def rebuild():
    records, seen = [], set()

    def add(seed, term, source, country, rec):
        key = (seed, term, source, country)
        if not term or key in seen:
            return
        seen.add(key)
        records.append({"seed": seed, "suggestion": term, "source": source,
                        "country": country, **_series(rec)})

    for f in sorted(glob.glob(os.path.join(RAW, "pm_*.json"))):
        m = re.match(r"pm_(US|GB)_(.+)\.json$", os.path.basename(f))
        if not m:
            continue
        cc, seed = m.group(1), m.group(2).replace("_", " ")
        try:
            rows = json.load(open(f))
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict):
                add(seed, r.get("term"), "prefix_match", cc, r)

    for f in sorted(glob.glob(os.path.join(RAW, "rt_*.json"))):
        m = re.match(r"rt_(US|GB)_(.+)\.json$", os.path.basename(f))
        if not m:
            continue
        cc, seed = m.group(1), m.group(2).replace("_", " ")
        try:
            rows = json.load(open(f))
        except Exception:
            continue
        if isinstance(rows, dict):
            rows = rows.get("values", [])
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, str):
                add(seed, r, "related_terms", cc, {})
            elif isinstance(r, dict):
                add(seed, r.get("term") or r.get("query"), "related_terms", cc, r)

    doc = {"source": "https://trends.pinterest.com/prefix_match/ + /related_terms/",
           "endpoint_notes": "prefix_match = Pinterest autocomplete-style suggestions; "
                             "related_terms = 'related searches' for the seed",
           "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "countries": ["US", "GB"],
           "interest_scale": "counts_52w are weekly values normalised 0-100 by Pinterest "
                             "per term; last element = most recent week",
           "seeds": SEEDS, "record_count": len(records), "records": records}
    save_json("suggestions.json", doc)

    with open(os.path.join(HERE, "suggestions.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["seed", "suggestion", "source"])
        for r in sorted(records, key=lambda x: (x["seed"], x["source"], x["country"])):
            w.writerow([r["seed"], r["suggestion"], r["source"]])

    with open(os.path.join(HERE, "suggestions_detailed.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["seed", "suggestion", "source", "country", "latest_interest",
                    "mean_interest", "max_interest", "trend_52w"])
        for r in sorted(records, key=lambda x: (-(x.get("latest_interest") or 0))):
            w.writerow([r["seed"], r["suggestion"], r["source"], r["country"],
                        r.get("latest_interest"), r.get("mean_interest"),
                        r.get("max_interest"), r.get("trend_52w")])

    print(f"records={len(records)}  "
          f"US={sum(1 for r in records if r['country']=='US')} "
          f"GB={sum(1 for r in records if r['country']=='GB')}")


if __name__ == "__main__":
    enrich_gb_related()
    rebuild()
