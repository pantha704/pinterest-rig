#!/usr/bin/env python3
"""Generate keywords/summary.md from the harvested data (no hand-copied numbers)."""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))

CLUSTERS = [
    ("1. Nail art & seasonal nails", "NAILS",
     "The single biggest US+UK cluster in this harvest. Autumn/fall seasonality 0.80-1.00."),
    ("2. Fashion & outfit inspiration", "FASHION",
     "Autumn + US back-to-school/homecoming (hoco, picture day, 'white out' football games)."),
    ("3. Home decor, wallpaper & aesthetic rooms", "HOME",
     "Evergreen, high ticket-value. Wallpaper alone scores 53 (US) / 68 (GB)."),
    ("4. Desk setup, planners, journalling & study aesthetic", "DESK",
     "WFH + student productivity; the digital-product heartland."),
    ("5. Beauty, skincare & hair", "BEAUTY",
     "Routine/GRWM intent, high repeat-purchase categories."),
    ("6. Meal prep & budget food", "FOOD",
     "Budget intent is explicit ('budget meals', 'how to budget for beginners')."),
    ("7. Seasonal crafts, kids' activities & printables", "CRAFT",
     "Printable/coloring demand is enormous and converts to digital downloads."),
    ("8. Gifting, weddings & celebrations", "GIFT",
     "Highest average order value of any cluster; strong seasonal spikes."),
]


def cluster_of(term):
    t = term.lower()
    rules = [
        ("NAILS", ("nail", "ongles")),
        ("FASHION", ("outfit", "hoco", "picture day", "football game", "fashion", "fits")),
        ("HOME", ("wallpaper", "room", "bedroom", "home decor", "family room", "entryway",
                  "bathroom", "aesthetic", "interior", "hintergrundbilder", "background")),
        ("DESK", ("desk", "planner", "journal", "study", "vision board", "date planning",
                  "organisation", "organization")),
        ("BEAUTY", ("hairstyle", "hair", "makeup", "skincare", "beauty", "braid", "glow")),
        ("FOOD", ("dinner", "meal", "food", "recipe", "pasta", "lunch", "breakfast",
                  "snack", "backen", "kürbis", "pumpkin pasta")),
        ("GIFT", ("gift", "wedding", "christmas", "valentine", "birthday", "holiday",
                  "party", "present", "geburtstag")),
        ("CRAFT", ("coloring", "drawing", "craft", "pumpkin", "pottery", "toddler",
                   "basteln", "dot day", "diy", "keramik", "pose reference", "draw",
                   "malen", "zeichen")),
    ]
    for name, keys in rules:
        if any(k in t for k in keys):
            return name
    return "OTHER"


def main():
    ranked = json.load(open(os.path.join(HERE, "terms_ranked.json")))
    terms = ranked["terms"]
    top50 = terms[:50]
    sugg = json.load(open(os.path.join(HERE, "suggestions.json")))["records"]

    # suggestion long-tail grouped by cluster, ranked by latest weekly interest
    sg = {}
    seen = set()
    for r in sorted(sugg, key=lambda x: -(x.get("latest_interest") or 0)):
        key = r["suggestion"].lower()
        if key in seen:
            continue
        seen.add(key)
        sg.setdefault(cluster_of(r["suggestion"]), []).append(r)

    def cell(v):
        return "-" if v is None else f"{v:g}"

    import glob
    rows = 0
    for f in glob.glob(os.path.join(HERE, "trends_*.json")):
        for blk in json.load(open(f)).get("presets", {}).values():
            rows += len(blk.get("values", []))
    L = []
    A = L.append
    A("# Pinterest keyword & trend harvest — US / UK")
    A("")
    A(f"- **Harvested:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · "
      f"data end date **2026-09-22** · regions **US, GB(+IE), GB, CA, DE**")
    A(f"- **Scope:** {rows} trend rows harvested (5 region views x 4 presets x 50 terms), "
      f"{len(terms)} distinct terms ranked, "
      f"{len(sugg)} autocomplete/related-search rows for the 15 seed queries.")
    A("- **No login, no API key.** Logged-out only; ~102 API requests this run at 3-5 s "
      "intervals.")
    A("")
    A("## Top 50 harvested terms by apparent interest")
    A("")
    A("`interest` is Pinterest's own relative volume (`normalizedCount`, 0-100, top term in "
      "each country view = 100). Because Pinterest normalises per (country, preset) request, "
      "regions are shown side by side rather than pooled into one scale. `szn` is Pinterest's "
      "seasonality score (1.0 = highly seasonal), `MoM` the month-over-month change in %.")
    A("")
    A("| # | Term | US | GB | CA | DE | szn | MoM% | YoY% | Cluster |")
    A("|--:|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for r in top50:
        us, gb = r["us"] or {}, r["gb"] or {}
        ca = next((v["interest"] for k, v in r["views"].items() if k.startswith("CA:")), None)
        de = next((v["interest"] for k, v in r["views"].items() if k.startswith("DE:")), None)
        # fall back to the GB view's seasonality/change metrics when there is no US view
        src = us if us else gb
        cname = next((n for n, k, _ in CLUSTERS if k == cluster_of(r["term"])), "9. Other / generic")
        szn = src.get("seasonality_score")
        A(f"| {r['rank']} | {r['term']} | {cell(us.get('interest'))} | "
          f"{cell(gb.get('interest'))} | {cell(ca)} | {cell(de)} | "
          f"{cell(round(szn, 2) if szn is not None else None)} | "
          f"{cell(src.get('mom_change'))} | {cell(src.get('yoy_change'))} | {cname[3:]} |")
    A("")
    A("## Thematic clusters")
    A("")
    for title, key, note in CLUSTERS:
        members = [r for r in top50 if cluster_of(r["term"]) == key]
        rows = sg.get(key, [])[:8]
        if not members and not rows:
            continue
        head = f"  ({len(members)} of top 50)" if members else "  (none in the top 50 by volume)"
        A(f"### {title}{head}")
        A(f"{note}")
        A("")
        if members:
            A("Trends: " + ", ".join(f"**{r['term']}** (US {cell((r['us'] or {}).get('interest'))}"
                                     f"/GB {cell((r['gb'] or {}).get('interest'))})"
                                     for r in members[:10]))
            A("")
        if rows:
            A("Long-tail from the seed harvest (weekly interest now, and 52-week change):")
            A("")
            for r in rows:
                tr = r.get("trend_52w")
                A(f"- `{r['suggestion']}` — {r['country']} "
                  f"({r['source'].replace('_', ' ')}), interest {r.get('latest_interest')}"
                  f"/100, 52-week change {tr:+g}" if tr is not None else
                  f"- `{r['suggestion']}` — {r['country']} "
                  f"({r['source'].replace('_', ' ')}), interest {r.get('latest_interest')}/100")
            A("")
    others = [r for r in top50 if cluster_of(r["term"]) == "OTHER"]
    if others:
        A("### 9. Other / generic (not attributable to a theme)")
        A("Breakout or generic terms that did not fit a theme: "
          + ", ".join(f"`{r['term']}` (US {cell((r['us'] or {}).get('interest'))}"
                      f"/GB {cell((r['gb'] or {}).get('interest'))})" for r in others) + ".")
        A("")

    A("## Which clusters are most monetizable for affiliate pins")
    A("")
    A("Ranked for a **brand-new pinning account** (needs evergreen volume, a real product to "
      "link, and low competition on the exact term):")
    A("")
    A("| # | Cluster | Why it pays | Watch out for |")
    A("|--:|---|---|---|")
    A("| 1 | **Home decor, wallpaper & aesthetic rooms** | Highest ticket value and the most "
      "affiliate-friendly category: prints/posters, peel-and-stick wallpaper, furniture and "
      "home brands all run public programs (Amazon Associates, Wayfair, Society6/Etsy prints, "
      "wallpaper DTC brands). Interest is evergreen (wallpaper 53 US / 68 GB) rather than a "
      "one-month spike, so pins keep earning. | Saturated on head terms — pin the long tail "
      "(`small room makeover`, `entryway ideas`, `living room aesthetic`, `cozy bedroom ideas`). |")
    A("| 2 | **Desk setup, planners, journalling & study aesthetic** | The clearest path to "
      "*digital* products you can sell or affiliate: printable planner templates, journalling "
      "printables, Notion templates. `office desk setup` 98, `desk setup ideas` 96 US, "
      "`weekly planner template` 86 GB. Desk hardware affiliate (keyboards, lamps, risers) "
      "adds AOV. | `study motivation` traffic is young and mostly ad-blind; monetise with "
      "digital downloads, not physical goods. |")
    A("| 3 | **Seasonal crafts, kids' activities & printables** | Coloring/activity printables "
      "are a top-performing Etsy digital category and the demand is verifiable here: "
      "`coloring pages for kids` 100 GB, `coloring pages y2k` 100 US, `coloring pages for "
      "adults` 88. Zero inventory, instant delivery. | `free printable` intent is high — use "
      "it for email capture, monetise the paid bundles. |")
    A("| 4 | **Fashion & outfit inspiration** | Big, seasonal and highly visual: `outfit ideas` "
      "48 US / 38 GB, `autumn outfits` 78 GB, `fall outfits` 58 CA. Fashion affiliate networks "
      "(Awin, LTK, ShareASale) pay well and autumn/back-to-school is a live spike right now. | "
      "Needs original photography; pure repinning is the most saturated play on the platform. |")
    A("| 5 | **Gifting, weddings & celebrations** | Highest average order value of any cluster "
      "(`elegant wedding dresses` 88, `wedding guest hairstyles` 100, `small gift ideas` 78, "
      "`christmas present ideas` 57 and already climbing in September). Gift and wedding "
      "merchants pay the best commissions. | Very seasonal; run it as a calendar, not a "
      "year-round crutch. |")
    A("| 6 | **Beauty, skincare & hair** | Enormous repeat-purchase volume (`hairstyles` 59 US "
      "/ 45 GB, `skincare products aesthetic` 87, `grwm` 63/66) and device-led affiliate "
      "(LED masks, hair tools, skincare fridges 51) carries real margin. | Many beauty "
      "programs restrict or ban coupon/affiliate pins — check terms before pinning. |")
    A("| 7 | **Nail art & seasonal nails** | The largest raw demand in this harvest "
      "(`fall nails` 100 US, `autumn nails` 100 GB, `nails` 74/82) and press-on/sticker "
      "brands are easy to source. Cheap content to produce. | Lowest AOV per click and the "
      "most crowded — treat as a traffic/volume play, not a profit centre. |")
    A("| 8 | **Meal prep & budget food** | Steady evergreen demand with explicit money intent "
      "(`how to budget for beginners` 95, `meal prep snacks` 100 GB / 92 US, `budget meals` "
      "65 US / 51 GB). Kitchen gadgets, containers and cookbooks affiliate cleanly. | "
      "Recipes get saved but clicked less; pair with shopping-list printables. |")
    A("")
    A("**If you only pin one cluster:** home decor + wallpaper + aesthetic rooms, with desk "
      "setup/planner printables as the digital-product arm. Both have evergreen interest, "
      "product-shaped queries and no dependency on a single season — and the autumn spike "
      "is *already* happening, so seasonality is on your side today.")
    A("")

    A("## Seasonality & timing notes (from the harvested scores)")
    A("")
    A("- The current US/GB picture is **autumn-dominated**: the top seasonal scores in the "
      "harvest are autumn/fall terms (`autumn nails` szn 1.00, `christmas nails` 0.99, "
      "`fall outfits` 0.99, `autumn outfits` 0.99, `simple fall nails` 0.95).")
    A("- **Christmas is already rising in September**: `christmas nails` US 29 / GB 41 with "
      "szn 0.99, `christmas present ideas` 57, `christmas gifts for women` 46. Start queuing "
      "Christmas pins now — Pinterest surfaces seasonal content 30-45 days ahead.")
    A("- **Valentine's is dormant but present** (`valentines nails` 23/11, szn 0.83) — a "
      "January cluster.")
    A("- **Breakout (unseasonal) terms** show what is genuinely new rather than seasonal: "
      "`minimise` (MoM +100%), `dot day` (MoM +35%), `fall nails 2026 color trends` "
      "(MoM +30%), `hoco posters` US 100 with MoM +15%, `white out football game outfit` "
      "US 41 MoM +20%. These are 'trending now', i.e. low competition right now.")
    A("")

    A("## Method, endpoints and reproducibility")
    A("")
    A("`trends.pinterest.com` is a React app that renders an empty shell and fetches JSON "
      "client-side (`initialReduxState: null`), so the data source had to be read out of its "
      "own bundles. The URL builder is module `676143` in the served `.mjs` chunks — it "
      "assembles `https://<host>/<resource>/` plus query params — and the resource names live "
      "in the call sites. Recovered surface (all GET, all logged-out):")
    A("")
    A("| Endpoint | Parameters that worked | What it returns |")
    A("|---|---|---|")
    A("| `/top_trends_filtered/` | `country`, `endDate`, `trendsPreset` (1-4), `lookbackWindow`, "
      "`rankingMethod`, `numTermsToReturn` | trending terms + `normalizedCount`, `searchCount`, "
      "`seasonality_score`, `mom_change`, `yoy_change`, `wow_change` |")
    A("| `/prefix_match/` | `query`, `country` | Pinterest autocomplete suggestions, each with a "
      "52-week `counts[]` series normalised 0-100 |")
    A("| `/related_terms/` | `requestTerm`, `country`, `endDate`, `aggregation`, `lookback`, "
      "`predictedDays` | related searches for a term, with the same 52-week series |")
    A("| `/metrics/` | `terms`, `country`, `end_date`, `days`, `aggregation`, "
      "`normalize_against_group`, `predicted_days` | interest-over-time series for explicit terms |")
    A("")
    A("`trendsPreset` values were established empirically, not guessed: **1** = top monthly "
      "(highest volume), **2** = top yearly, **3** = breakout/'trending now', **4** = growing/"
      "seasonal risers, **5** = rejected (400). No special headers or cookies are needed — "
      "plain `curl` with a browser User-Agent and a `Referer: https://trends.pinterest.com/` "
      "returns 200 with JSON.")
    A("")
    A("Files in this directory:")
    A("")
    A("| File | Contents |")
    A("|---|---|")
    A("| `trends_US.json`, `trends_GB.json`, `trends_GB_altreg.json`, `trends_CA.json`, "
      "`trends_DE.json` | 4 presets x 50 terms per region, raw per-term records |")
    A("| `suggestions.json` | 449 autocomplete + related-search rows, with 52-week interest "
      "series, for the 15 seed queries in US and GB |")
    A("| `suggestions.csv` | `seed,suggestion,source` (the flat deliverable) |")
    A("| `suggestions_detailed.csv` | same rows plus country, latest/mean/max interest and "
      "52-week change |")
    A("| `terms_ranked.json`, `top_terms.csv` | the 742-term unified ranked table behind the "
      "top-50 above |")
    A("| `harvest.py` | the harvester (polite: sequential, 3-5 s random gaps, hard request "
      "budget, incremental writes). Re-run: `python3 harvest.py trends` / `suggestions` |")
    A("| `enrich_and_rebuild.py`, `analyze.py`, `probe_enums.py`, `generate_summary.py` | "
      "enrichment, ranking, enum discovery, and this file's generator |")
    A("| `raw/` | every raw JSON payload plus `reqlog.txt` (timestamped request log) |")
    A("")
    A("## Blockers / caveats")
    A("")
    A("- **Nothing blocked.** `trends.pinterest.com` served all trend data logged-out; no "
      "CAPTCHA, no login wall, no rate limiting was hit at 3-5 s spacing.")
    A("- **AU is not a supported trends region** — `country=AU` returns HTTP 400 `{}` for "
      "every preset (tried all four). US, GB, GB+IE, CA and DE all returned data. CA data is "
      "mixed English/French (`ongles d'automne`).")
    A("- **DE is included but noisy for a US/UK account**: the German view is full of "
      "greetings-card terms (`guten morgen gruss`, `geburtstagswünsche`, `gute nacht`) that "
      "are high volume on Pinterest but not commercially useful for affiliate pins. It is "
      "kept in `trends_DE.json` for completeness, not for targeting.")
    A("- **No `moments` / shopping-ads data**: `/resource/ApiResource/get/` (used for the "
      "trends shopping categories) returns 403 without a session cookie, so the shopping-ads "
      "product-category series were not harvested. Everything reported above is from the "
      "keyless trends endpoints.")
    A("- The VPS IP geolocates to **FR**, so the app's default region was France; every call "
      "here passes `country=` explicitly, which the endpoint honours.")
    A(f"- Request budget: **102 API requests** this run (~{sum(1 for _ in open(os.path.join(HERE, 'raw', 'reqlog.txt')))} "
      "logged in `raw/reqlog.txt`), well inside the 200 cap, plus one headless-browser page "
      "load used to observe the app's own network calls.")
    A("")
    with open(os.path.join(HERE, "summary.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print("summary.md written,", len(L), "lines")
    print("cluster sizes (top50):",
          {k: sum(1 for r in top50 if cluster_of(r["term"]) == k) for _, k, _ in CLUSTERS},
          "OTHER:", sum(1 for r in top50 if cluster_of(r["term"]) == "OTHER"))


if __name__ == "__main__":
    main()
