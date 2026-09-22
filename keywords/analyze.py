#!/usr/bin/env python3
"""Unified ranked term table, US/UK-centric.

Why US/UK-centric: Pinterest returns `normalizedCount` normalised to 100 within each
(country, preset) request, so values from different requests are not directly
comparable. A US/UK pinning account therefore gets an honest ranking by reading the
US and GB views side by side rather than by pooling every region into one scale.
"""
import csv, glob, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
# (file suffix, region label, preset priority) - lower priority number = better volume proxy
VOLUME_ORDER = {"top_monthly": 0, "top_yearly": 1, "growing": 2, "trending_now": 3}


def load_trends():
    terms = {}

    def touch(t):
        return terms.setdefault(t, {"term": t, "views": {}, "us": None, "gb": None})

    for f in glob.glob(os.path.join(HERE, "trends_*.json")):
        suf = os.path.basename(f)[len("trends_"):-len(".json")]
        region = {"US": "US", "GB": "GB", "GB_altreg": "GB+IE",
                  "CA": "CA", "DE": "DE"}.get(suf, suf)
        doc = json.load(open(f))
        for preset, blk in doc.get("presets", {}).items():
            for v in blk.get("values", []):
                t = (v.get("term") or "").strip().lower()
                if not t:
                    continue
                rec = touch(t)
                view = {"region": region, "preset": preset,
                        "interest": v.get("normalizedCount"),
                        "searchCount": v.get("searchCount"),
                        "seasonality_score": v.get("seasonality_score"),
                        "mom_change": (v.get("mom_change") or {}).get("value"),
                        "yoy_change": (v.get("yoy_change") or {}).get("value"),
                        "wow_change": (v.get("wow_change") or {}).get("value"),
                        "reverseRank": v.get("reverseRank")}
                rec["views"][f"{region}:{preset}"] = view
                for slot in ("us", "gb"):
                    if slot == "us" and region != "US":
                        continue
                    if slot == "gb" and not region.startswith("GB"):
                        continue
                    cur = rec[slot]
                    if cur is None or VOLUME_ORDER[preset] < VOLUME_ORDER[cur["preset"]]:
                        rec[slot] = view
    return terms


def load_suggestions():
    doc = json.load(open(os.path.join(HERE, "suggestions.json")))
    agg = {}
    for r in doc["records"]:
        t = r["suggestion"].strip().lower()
        a = agg.setdefault(t, {"seeds": set(), "sources": set(), "countries": set(),
                               "latest_interest": 0, "mean_interest": 0})
        a["seeds"].add(r["seed"])
        a["sources"].add(r["source"])
        a["countries"].add(r["country"])
        a["latest_interest"] = max(a["latest_interest"], r.get("latest_interest") or 0)
        a["mean_interest"] = max(a["mean_interest"], r.get("mean_interest") or 0)
    return agg


def main():
    terms = load_trends()
    sugg = load_suggestions()
    for t, a in sugg.items():
        rec = terms.setdefault(t, {"term": t, "views": {}, "us": None, "gb": None})
        rec["from_suggestions"] = {
            "seeds": sorted(a["seeds"]), "sources": sorted(a["sources"]),
            "countries": sorted(a["countries"]),
            "latest_interest": a["latest_interest"], "mean_interest": a["mean_interest"]}
    rows = list(terms.values())

    def key(r):
        us = (r["us"] or {}).get("interest") or 0
        gb = (r["gb"] or {}).get("interest") or 0
        # primary: best of the two target markets; ties broken toward the US view
        return (-max(us, gb), -us, -gb)

    rows.sort(key=key)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "end_date": "2026-09-22",
           "method": "rank = Pinterest relative volume (normalizedCount, 0-100, top term in "
                     "each country view = 100), taking the best of the US and GB views; "
                     "preset preference top_monthly > top_yearly > growing > trending_now",
           "regions": ["US", "GB(+IE)", "GB", "CA", "DE"],
           "term_count": len(rows), "terms": rows}
    json.dump(doc, open(os.path.join(HERE, "terms_ranked.json"), "w"),
              indent=1, ensure_ascii=False)

    with open(os.path.join(HERE, "top_terms.csv"), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["rank", "term", "us_interest", "us_preset", "gb_interest",
                    "gb_preset", "ca_interest", "de_interest",
                    "us_seasonality", "us_mom_change", "us_yoy_change",
                    "from_suggestions"])
        for r in rows:
            ca = next((v["interest"] for k, v in r["views"].items() if k.startswith("CA:")), None)
            de = next((v["interest"] for k, v in r["views"].items() if k.startswith("DE:")), None)
            us = r["us"] or {}
            w.writerow([r["rank"], r["term"], us.get("interest"), us.get("preset"),
                        (r["gb"] or {}).get("interest"), (r["gb"] or {}).get("preset"),
                        ca, de, us.get("seasonality_score"), us.get("mom_change"),
                        us.get("yoy_change"), "Y" if r.get("from_suggestions") else ""])

    print(f"terms={len(rows)} ->  terms_ranked.json, top_terms.csv\n")
    hdr = f"{'#':>3} {'TERM':<36}{'US':>4} {'GB':>4} {'CA':>4} {'DE':>4}  {'SZN':>5} {'MOM%':>6}  SUG"
    print(hdr)
    for r in rows[:60]:
        us, gb = r["us"] or {}, r["gb"] or {}
        ca = next((v["interest"] for k, v in r["views"].items() if k.startswith("CA:")), None)
        de = next((v["interest"] for k, v in r["views"].items() if k.startswith("DE:")), None)
        szn = us.get("seasonality_score")
        mom = us.get("mom_change")
        szn_s = f"{szn:.2f}" if szn is not None else "-"
        mom_s = f"{mom:.1f}" if mom is not None else "-"
        print(f"{r['rank']:>3} {r['term'][:35]:<36}"
              f"{us.get('interest') if us.get('interest') is not None else '-':>4} "
              f"{gb.get('interest') if gb.get('interest') is not None else '-':>4} "
              f"{ca if ca is not None else '-':>4} {de if de is not None else '-':>4}  "
              f"{szn_s:>5} {mom_s:>6}  "
              f"{'Y' if r.get('from_suggestions') else '-'}")


if __name__ == "__main__":
    main()
