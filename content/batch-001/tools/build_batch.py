#!/usr/bin/env python3
"""Build batch-001: 20 pin specs + a self-contained manifest.csv.

Writes, relative to ../ (content/batch-001/):
    specs/<stem>.json     one pin_factory spec per pin
    manifest.csv          file, template, board, title, description, alt_text, target_keyword
    data/target-keywords.csv  the cited harvest row for every target keyword

Everything is validated before anything is written:
  * title <= 100 chars, description 150-400 chars with <= 3 hashtags and no URL
  * every target_keyword resolves to a real harvested row (and the row is printed)
  * all six factory templates used, every board used, palettes from the factory list

    python3 tools/build_batch.py            # write
    python3 tools/build_batch.py --check    # validate only
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH = HERE.parent
SPECS = BATCH / "specs"
KW = Path("/home/ubuntu/pinterest-rig/keywords")
DATA = Path("/home/ubuntu/pinterest-rig/content/batch-001/data")
ASSETS = "/home/ubuntu/pinterest-rig/content/batch-001/assets"

BRAND = "Amber Hollow"
HANDLE = "@panther704"

BOARDS = {
    "decor": "Cozy Home Decor & Aesthetic Room Ideas",
    "wallpaper": "Wallpaper & Accent Wall Inspiration",
    "desk": "Desk Setup & Study Aesthetic",
    "planner": "Planner, Journal & Study Printables",
    "autumn": "Cozy Autumn Home & Fall Decor",
    "christmas": "Christmas Home Decor & Festive Ideas",
    "printables": "Printable Wall Art & Coloring Pages",
    "gifting": "Gift Ideas & Small Joys",
}

# --------------------------------------------------------------------------- #
# The 20 pins
# --------------------------------------------------------------------------- #
PINS = [
    {
        "stem": "pin-001-cozy-bedroom-renter",
        "board": "decor", "template": "bold_title", "palette": "terracotta",
        "target_keyword": "cozy bedroom ideas",
        "title": "Cozy Bedroom Ideas: Make a Small Room Feel Warm and Grown-Up",
        "description": "Cozy bedroom ideas for small, rented rooms: swap cool white bulbs for warm ones, layer a wool throw over a linen duvet, and let one textured wall carry the whole scheme. Nothing here needs a drill or costs you a deposit. Save it for your next room refresh. #cozybedroomideas #smallbedroom #homedecor",
        "alt_text": "Terracotta text pin reading 'Make a Small Bedroom Feel Warm and Grown-Up' with the label 'Renter-Friendly Changes' on a cream background",
        "spec": {
            "kicker": "COZY BEDROOM IDEAS",
            "title": "Make a Small Bedroom Feel Warm and Grown-Up",
            "label": "RENTER-FRIENDLY CHANGES",
            "subtitle": "Warm bulbs, layered texture and one wall that does the heavy lifting — no drilling, no deposit drama.",
        },
    },
    {
        "stem": "pin-002-calm-rooms-quiet-edit",
        "board": "decor", "template": "editorial_minimal", "palette": "sage",
        "target_keyword": "home decor aesthetic",
        "title": "Home Decor Aesthetic: Why Calm Rooms Have Less in Them",
        "description": "Home decor aesthetic, edited down: take five things out before you add one, match textures before colors, warm every bulb, and leave one surface completely empty. It takes an afternoon and makes a rented room feel considered instead of cluttered. #homedecoraesthetic #interiortips #rentedhome",
        "alt_text": "Editorial-style pin on pale sage with a serif headline about the calmest rooms and four numbered home decor tips",
        "spec": {
            "kicker": "THE QUIET EDIT",
            "issue": "No. 01 · Autumn",
            "title": "The calmest rooms have the least in them",
            "deck": "A five-minute edit for a warmer, quieter room: take things out first, then soften the light, then add one thing you love.",
            "entries": ["Remove five things before adding one",
                        "Match textures before colors",
                        "Warm every bulb in the room",
                        "Leave one surface empty"],
        },
    },
    {
        "stem": "pin-003-small-space-storage",
        "board": "decor", "template": "listicle", "palette": "sunset",
        "target_keyword": "small room ideas",
        "title": "Small Room Ideas: 5 Storage Fixes for Rented Rooms",
        "description": "Small room ideas for hiding clutter without a single drill hole: baskets in your wall color, a slim over-door rack, one tray for the small things, under-bed boxes with labels you can read, and a drop zone by the door. Every one of them lifts out again when you move. #smallroomideas #storageideas #rentedhome",
        "alt_text": "Numbered listicle pin headed '5 small-space storage ideas' with five renter-friendly tips on a warm amber background",
        "spec": {
            "count": "5",
            "headline": "small-space\nstorage ideas",
            "title": "Renter-friendly ways to hide clutter without drilling a single hole.",
            "items": ["Baskets in your wall color disappear at a glance",
                      "A slim over-door rack turns one door into real storage",
                      "Group small things on one tray instead of scattering them",
                      "Under-bed boxes with labels you can actually read",
                      "One drop zone by the door ends the daily pile-up"],
        },
    },
    {
        "stem": "pin-004-heritage-stripe-wallpaper",
        "board": "wallpaper", "template": "photo_frame", "palette": "terracotta",
        "target_keyword": "wallpaper ideas",
        "title": "Wallpaper Ideas: Warm Heritage Stripes for a Cozy Hallway",
        "description": "Wallpaper ideas for warm, layered rooms: heritage stripes in rust, olive and cream soften a hallway, bedroom or reading nook instantly. Renter-friendly versions exist too, so nothing has to be permanent. Save this for your next room update. #wallpaperideas #accentwall #hallwaydecor",
        "alt_text": "Illustrated wallpaper study of cream, rust and olive heritage stripes with a caption bar reading 'Heritage Stripe Wallpaper'",
        "spec": {
            "photo": f"{ASSETS}/autumn-stripe-wallpaper.png",
            "fit": "cover",
            "kicker": "WALLPAPER IDEAS",
            "badge": "PATTERN STUDY",
            "title": "Heritage Stripe Wallpaper",
            "subtitle": "Warm rust and olive stripes for hallways, bedrooms and reading nooks — no paste, no commitment.",
        },
    },
    {
        "stem": "pin-005-accent-wall-one-wall",
        "board": "wallpaper", "template": "editorial_minimal", "palette": "mono",
        "target_keyword": "wallpaper dark",
        "title": "Wallpaper Ideas for One Accent Wall, Four Ways That Work",
        "description": "Accent wall ideas for small rooms and rentals: stripe one wall low and dark, paper just the wall behind the bed, paint the alcoves and keep the rest pale, or use self-adhesive panels that lift off cleanly. Pick one wall, commit to it, and leave the others quiet. #accentwall #wallpaperdark #rentedhome",
        "alt_text": "Minimal editorial pin titled 'One wall can carry the whole room' listing four numbered accent wall ideas",
        "spec": {
            "kicker": "ACCENT WALL GUIDE",
            "issue": "Guide 02",
            "title": "One wall can carry the whole room. Choose it properly.",
            "deck": "You do not need to paper a whole room. Pick the wall you look at most, then commit to one idea — these four work hardest.",
            "entries": ["Stripe it low and dark for a snug feel",
                        "Paper only the wall behind the bed",
                        "Paint the alcoves, keep the rest pale",
                        "Try self-adhesive panels if you rent"],
        },
    },
    {
        "stem": "pin-006-corner-desk-setup",
        "board": "desk", "template": "bold_title", "palette": "sage",
        "target_keyword": "desk setup ideas",
        "title": "Desk Setup Ideas: How to Make a Small Corner Workspace",
        "description": "Desk setup ideas for small rooms: use the corner you already have, light it with one warm lamp instead of the ceiling, keep only what you reach for daily on the surface, and add a plant or a print for company. Calmer to work at, and an hour to set up. #desksetupideas #smallspaces #workfromhome",
        "alt_text": "Sage green text pin reading 'Turn a Corner Into a Desk You Want to Sit At' with the label 'Small-Space Friendly'",
        "spec": {
            "kicker": "DESK SETUP IDEAS",
            "title": "Turn a Corner Into a Desk You Want to Sit At",
            "label": "SMALL-SPACE FRIENDLY",
            "subtitle": "A warm lamp, one plant and everything within arm's reach — the setup that makes working feel calmer.",
        },
    },
    {
        "stem": "pin-007-cozy-desk-upgrades",
        "board": "desk", "template": "listicle", "palette": "mint",
        "target_keyword": "cozy desk setup",
        "title": "Cozy Desk Setup: 6 Small Upgrades That Warm Up a Workspace",
        "description": "Cozy desk setup upgrades that cost very little: one warm lamp, a tray for the small things, a screen riser, one texture you can see and touch, a notebook that stays open, and a two-minute reset before you log off. Try two of them tonight. #cozydesk #desksetupideas #studygram",
        "alt_text": "Mint green listicle pin headed '6 cozy desk upgrades' with six short workspace tips in numbered rows",
        "spec": {
            "count": "6",
            "headline": "cozy desk\nupgrades",
            "title": "Small changes that make a workspace feel warm instead of fluorescent.",
            "items": ["Swap the ceiling light for one warm desk lamp",
                      "Put a tray under the small stuff so it stops drifting",
                      "Raise the screen — your neck will thank you by Friday",
                      "Add one texture: wool, wood or a linen pinboard",
                      "Keep a real notebook open for the ideas you would forget",
                      "Tidy for two minutes before you log off, not after"],
        },
    },
    {
        "stem": "pin-008-tidy-desk-quote",
        "board": "desk", "template": "quote_card", "palette": "sky",
        "target_keyword": "study era",
        "title": "Study Aesthetic: A Tidy Desk Makes Starting Less of a Fight",
        "description": "Study aesthetic, minus the expensive stationery: clear the surface, keep one warm light on, and set out only tonight's task. Motivation usually turns up about ten minutes after you start, not before. Save this for the evenings you cannot face the reading list. #studyaesthetic #studyinspo #productivity",
        "alt_text": "Quote card reading 'A tidy desk will not do the work for you' with the handwritten accent line 'start small, start now'",
        "spec": {
            "quote": "A tidy desk will not do the work for you. It just makes starting less of a fight.",
            "accent_line": "start small, start now",
            "attribution": BRAND,
            "role": "study notes",
        },
    },
    {
        "stem": "pin-009-weekly-planner-template",
        "board": "planner", "template": "pastel_gradient", "palette": "lavender",
        "target_keyword": "weekly planner template",
        "title": "Weekly Planner Template: The One That Actually Sticks",
        "description": "A weekly planner template that survives past week three: one page, five lines a day and a single must-happen box. Fill it in on Sunday night, leave it open on the desk, and stop rewriting the same list in three places. Undated, printable and guilt-free. #weeklyplanner #plannerprintable #productivity",
        "alt_text": "Lavender gradient pin with a frosted card, a 'Printable Planner' chip and the title 'The Weekly Planner That Finally Stuck'",
        "spec": {
            "chip": "PRINTABLE PLANNER",
            "kicker": "WEEKLY PLANNER TEMPLATE",
            "title": "The Weekly Planner That Finally Stuck",
            "subtitle": "One page, five lines a day and a single must-happen box — the reason it survives past week three.",
        },
    },
    {
        "stem": "pin-010-planner-week-three",
        "board": "planner", "template": "editorial_minimal", "palette": "blush",
        "target_keyword": "planner inspiration",
        "title": "Planner Ideas: How to Still Be Using It in Week Six",
        "description": "Planner ideas for people who abandon theirs by week three: one must-happen per day instead of ten, plan in pencil, leave Friday afternoon empty, and review the week for five minutes every Sunday. Simple enough to actually keep up with. #plannerideas #weeklyplanner #planningtips",
        "alt_text": "Pale editorial pin titled 'Most planners fail in week three' with four numbered planner rules",
        "spec": {
            "kicker": "PLANNER SYSTEM",
            "issue": "Method 03",
            "title": "Most planners fail in week three. Here is how to get past it.",
            "deck": "A planner is a decision tool, not a diary. Decide what the week has to contain before you decorate a single box.",
            "entries": ["Write one must-happen per day, not ten",
                        "Plan in pencil so reality can edit it",
                        "Leave Friday afternoon completely empty",
                        "Review it for five minutes every Sunday"],
        },
    },
    {
        "stem": "pin-011-journal-prompts",
        "board": "planner", "template": "listicle", "palette": "lavender",
        "target_keyword": "journal ideas prompts",
        "title": "Journal Ideas: 5 Prompts for Quiet Autumn Evenings",
        "description": "Journal ideas for the nights you want to write but nothing comes: three small things that went right, one line about the weather, what you are saving up for, the conversation you keep replaying, and something you would tell yourself a year ago. Five minutes, no perfect handwriting required. #journalideas #journaling #autumnjournal",
        "alt_text": "Lavender listicle pin headed '5 journal page ideas' with five short journaling prompts in numbered rows",
        "spec": {
            "count": "5",
            "headline": "journal\npage ideas",
            "title": "For the nights you want to write but have nothing to say.",
            "items": ["Three things that went right, however small",
                      "One sentence about the weather out of the window",
                      "A list of what you are saving up for",
                      "The last conversation you keep thinking about",
                      "Something you would tell yourself a year ago"],
        },
    },
    {
        "stem": "pin-012-autumn-home-refresh",
        "board": "autumn", "template": "bold_title", "palette": "sunset",
        "target_keyword": "fall home decor ideas",
        "title": "Fall Home Decor Ideas: Warm Every Room Without Buying Anything",
        "description": "Fall home decor ideas that need no shopping trip: warm the bulbs, bring the wool throws back out, gather dried stems on a walk, and keep the candles where you actually sit. Autumn warmth is mostly light and texture, not new furniture. #fallhomedecor #autumnhome #cozyhome",
        "alt_text": "Warm amber text pin reading 'Warm Your Home for Autumn Without Buying Anything' with the label 'Five-Minute Changes'",
        "spec": {
            "kicker": "FALL HOME DECOR",
            "title": "Warm Your Home for Autumn Without Buying Anything",
            "label": "FIVE-MINUTE CHANGES",
            "subtitle": "Amber bulbs, the wool throws you packed away and one bowl of dried stems — the cheapest autumn refresh there is.",
        },
    },
    {
        "stem": "pin-013-autumn-evenings-quote",
        "board": "autumn", "template": "quote_card", "palette": "terracotta",
        "target_keyword": "autumn decor ideas",
        "title": "Autumn Decor Ideas for Slow Evenings at Home",
        "description": "Autumn decor ideas for slow evenings in: switch off the big light, put a candle where you sit, and make something warm to drink before you start scrolling. Autumn is the season for staying in — a few small habits make it feel deliberate rather than lazy. #autumndecor #cozyautumn #slowliving",
        "alt_text": "Terracotta quote card reading 'Autumn asks very little of us' with the script accent line 'and stay in tonight'",
        "spec": {
            "quote": "Autumn asks very little of us. Warmer light, slower evenings, one more candle than usual.",
            "accent_line": "and stay in tonight",
            "attribution": BRAND,
            "role": "autumn notes",
        },
    },
    {
        "stem": "pin-014-rainy-window-print",
        "board": "autumn", "template": "photo_frame", "palette": "editorial",
        "target_keyword": "autumn room decor",
        "title": "Autumn Room Decor: A Rainy Window Print in Amber and Cream",
        "description": "Autumn room decor without the clutter: the cozy bits worth having are the ones you touch — a wool throw, a lamp with a warm bulb, and a print that makes a corner feel finished. This rainy window print is built for the desk corner or the wall you look at while the kettle boils. #autumnroomdecor #printableart #wallart",
        "alt_text": "Illustrated print of a rainy window with a warm lamp glow, captioned 'Rainy Window, Warm Light', with a 'Printable Art' badge",
        "spec": {
            "photo": f"{ASSETS}/cozy-window-rain.png",
            "fit": "cover",
            "kicker": "AUTUMN PRINT",
            "badge": "PRINTABLE ART",
            "title": "Rainy Window, Warm Light",
            "subtitle": "A cozy print for the desk corner or the wall you look at while the kettle boils — print at home in four sizes.",
        },
    },
    {
        "stem": "pin-015-printable-wall-art-guide",
        "board": "printables", "template": "pastel_gradient", "palette": "blush",
        "target_keyword": "printable wall art",
        "title": "Printable Wall Art: How to Hang a Gallery Wall That Moves With You",
        "description": "Printable wall art makes a gallery wall cheap and reversible: measure the wall, pick one size and repeat it, keep the gaps even, and hang the middle row at eye level. When you move, swap the prints and keep the frames. #printablewallart #gallerywall #wallartideas",
        "alt_text": "Blush gradient pin with a 'Printable Wall Art' chip and the title 'Five Prints, One Wall, No Hanging Stress'",
        "spec": {
            "chip": "PRINTABLE WALL ART",
            "kicker": "GALLERY WALL",
            "title": "Five Prints, One Wall, No Hanging Stress",
            "subtitle": "How to size, space and hang a gallery wall that still looks good when you move out.",
        },
    },
    {
        "stem": "pin-016-coloring-pages-printables",
        "board": "printables", "template": "pastel_gradient", "palette": "mint",
        "target_keyword": "coloring pages for kids",
        "title": "Coloring Pages for Kids and Grown-Ups: Autumn Printables",
        "description": "Coloring pages that earn their printer ink: simple autumn scenes for kids, and more detailed leaves and windows for adults who want something to do with their hands. Print a few, keep them with the crayons, and save the set for rainy afternoons. #coloringpages #printablesforkids #autumnactivities",
        "alt_text": "Soft green gradient pin with a 'Free Printables' chip and the title 'Rainy-Day Coloring Pages for Every Age'",
        "spec": {
            "chip": "FREE PRINTABLES",
            "kicker": "COLORING PAGES",
            "title": "Rainy-Day Coloring Pages for Every Age",
            "subtitle": "Simple autumn scenes for kids, more detailed ones for grown-ups — print, color, repeat.",
        },
    },
    {
        "stem": "pin-017-christmas-living-room",
        "board": "christmas", "template": "bold_title", "palette": "navy",
        "target_keyword": "christmas living room ideas",
        "title": "Christmas Home Decor Ideas: A Cozy Living Room, Nothing Overdone",
        "description": "Christmas home decor that stays cozy instead of cluttered: warm white lights only, one tree you actually have space for, greenery along the mantel rather than in every corner, and a throw ready for the evenings in. Start planning in autumn — December goes fast. #christmasdecor #cozyhome #christmashome",
        "alt_text": "Deep green and navy text pin reading 'A Cozy Christmas Living Room, Nothing Overdone' with the label 'Warm and Understated'",
        "spec": {
            "kicker": "CHRISTMAS HOME DECOR",
            "title": "A Cozy Christmas Living Room, Nothing Overdone",
            "label": "WARM AND UNDERSTATED",
            "subtitle": "Warm white lights, one tree you have space for and greenery that lasts — the calm version of December.",
            "colors": {"block_color": "#1E3A2F", "block_ink": "#F7F2E8"},
        },
    },
    {
        "stem": "pin-018-christmas-table",
        "board": "christmas", "template": "listicle", "palette": "sage",
        "target_keyword": "christmas table decor",
        "title": "Christmas Table Decor: Five Ideas You Can Set Up in an Hour",
        "description": "Christmas table decor you can set up in an hour: one long runner instead of placemats everywhere, candles at three heights, greenery cut from the garden, plain plates so the food does the talking, and dessert staged on a side table. Nothing precious, nothing breakable. #christmastable #christmasdecor #tablesetting",
        "alt_text": "Sage green listicle pin headed '5 christmas table ideas' with five numbered table-setting ideas",
        "spec": {
            "count": "5",
            "headline": "christmas\ntable ideas",
            "title": "Set the table once, then actually sit down with everyone.",
            "items": ["One long runner instead of placemats everywhere",
                      "Candles at three heights, all warm white",
                      "Greenery from the garden, not the plastic aisle",
                      "Keep the plates plain so the food stands out",
                      "Dessert and the good glasses on a side table"],
        },
    },
    {
        "stem": "pin-019-christmas-tree-print",
        "board": "christmas", "template": "photo_frame", "palette": "navy",
        "target_keyword": "christmas home decor ideas",
        "title": "Christmas Wall Art: A Minimal Tree Print for Quiet Decor",
        "description": "Christmas wall art for people who like their decor quiet: one minimal tree, one star and a lot of space around it, printed at home in four sizes. It sits happily next to your usual pictures instead of fighting them for attention. #christmasprint #printableart #christmasdecor",
        "alt_text": "Illustrated minimal Christmas tree print with a single star, captioned 'Minimal Christmas Tree Print', with a 'Printable Art' badge",
        "spec": {
            "photo": f"{ASSETS}/christmas-tree-minimal.png",
            "fit": "cover",
            "kicker": "CHRISTMAS PRINT",
            "badge": "PRINTABLE ART",
            "title": "Minimal Christmas Tree Print",
            "subtitle": "One tree, one star and a lot of quiet space — a festive print that works with your decor, not against it.",
            "colors": {"caption_color": "#1E3A2F", "caption_ink": "#F7F2E8"},
        },
    },
    {
        "stem": "pin-020-gift-quote-small-joys",
        "board": "gifting", "template": "quote_card", "palette": "blush",
        "target_keyword": "small gift ideas",
        "title": "Small Gift Ideas That Do Not Feel Like an Afterthought",
        "description": "Small gift ideas that do not feel like a last-minute panic: write down what they mention through the year, buy the upgrade of something they already use daily, and give it with a note explaining why. Attention is the whole gift. #smallgiftideas #giftideas #christmasgifts",
        "alt_text": "Blush quote card reading 'A good gift is just attention, wrapped up.' with the script line 'notice what they mention'",
        "spec": {
            "quote": "A good gift is just attention, wrapped up.",
            "accent_line": "notice what they mention",
            "attribution": BRAND,
            "role": "gift notes",
        },
    },
]

TEMPLATES = ["bold_title", "pastel_gradient", "quote_card", "listicle", "photo_frame", "editorial_minimal"]
PALETTES = ["sage", "blush", "navy", "lavender", "terracotta", "editorial", "sunset", "mint", "mono", "sky"]

MANIFEST_COLS = ["file", "template", "board", "title", "description", "alt_text", "target_keyword"]


# --------------------------------------------------------------------------- #
# keyword citation lookup
# --------------------------------------------------------------------------- #
def load_keyword_index() -> dict[str, dict]:
    """term -> citation dict, merged from the main harvest + the supplement."""
    idx: dict[str, dict] = {}

    def keep(term: str, cite: dict, priority: int) -> None:
        cur = idx.get(term)
        if cur is None or priority > cur["_priority"]:
            idx[term] = {**cite, "_priority": priority}

    for row in csv.DictReader(open(KW / "suggestions_detailed.csv")):
        term = (row["suggestion"] or "").strip()
        if not term:
            continue
        keep(term, {
            "term": term, "source": f"suggestions_detailed.csv ({row['source']}, seed '{row['seed']}')",
            "region": row["country"], "latest": row["latest_interest"],
            "mean": row["mean_interest"], "max": row["max_interest"],
            "trend_52w": row["trend_52w"], "note": "",
        }, priority=3)

    for row in csv.DictReader(open(KW / "top_terms.csv")):
        term = (row["term"] or "").strip()
        if not term:
            continue
        keep(term, {
            "term": term, "source": "top_terms.csv (trends table)",
            "region": "US/GB/CA", "latest": f"US {row['us_interest'] or '-'} / GB {row['gb_interest'] or '-'}",
            "mean": "", "max": "", "trend_52w": row["us_yoy_change"],
            "note": f"seasonality {row['us_seasonality'] or '-'}, MoM {row['us_mom_change'] or '-'}",
        }, priority=2)

    supp = DATA / "supplement_keywords.csv"
    if supp.exists():
        for row in csv.DictReader(open(supp)):
            term = (row["suggestion"] or "").strip()
            if not term:
                continue
            keep(term, {
                "term": term, "source": f"supplement_keywords.csv ({row['source']}, seed '{row['seed']}')",
                "region": row["country"], "latest": row["latest"], "mean": row["mean"],
                "max": row["max"], "trend_52w": row["trend_52w"], "note": "gap-fill harvest 2026-09-22",
            }, priority=3)
    return idx


def validate(idx: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    tpl, pal, boards = set(), set(), set()
    for pin in PINS:
        t = pin["title"]
        d = pin["description"]
        if len(t) > 100:
            problems.append(f"{pin['stem']}: title {len(t)} chars > 100")
        if not (150 <= len(d) <= 400):
            problems.append(f"{pin['stem']}: description {len(d)} chars not in 150-400")
        tags = [w for w in d.split() if w.startswith("#")]
        if len(tags) > 3:
            problems.append(f"{pin['stem']}: {len(tags)} hashtags > 3")
        if "http" in d or "www." in d:
            problems.append(f"{pin['stem']}: description contains a link")
        if not all(w.startswith("#") for w in d.split()[-len(tags):]) and tags:
            problems.append(f"{pin['stem']}: hashtags are not all at the end")
        if not pin["alt_text"].strip():
            problems.append(f"{pin['stem']}: empty alt_text")
        if pin["template"] not in TEMPLATES:
            problems.append(f"{pin['stem']}: bad template {pin['template']}")
        if pin["palette"] not in PALETTES:
            problems.append(f"{pin['stem']}: bad palette {pin['palette']}")
        if pin["board"] not in BOARDS:
            problems.append(f"{pin['stem']}: bad board {pin['board']}")
        if pin["target_keyword"] not in idx:
            problems.append(f"{pin['stem']}: target keyword {pin['target_keyword']!r} not found in harvest data")
        tpl.add(pin["template"])
        pal.add(pin["palette"])
        boards.add(pin["board"])
    missing = set(TEMPLATES) - tpl
    if missing:
        problems.append(f"templates unused: {sorted(missing)}")
    unused_boards = set(BOARDS) - boards
    if unused_boards:
        problems.append(f"boards without pins: {sorted(unused_boards)}")
    return problems


def main() -> int:
    check_only = "--check" in sys.argv
    idx = load_keyword_index()
    problems = validate(idx)
    if problems:
        print("VALIDATION PROBLEMS:")
        for p in problems:
            print("  !", p)
        return 1

    for pin in PINS:
        cite = idx[pin["target_keyword"]]
        print(f"OK {pin['stem']:34s} {pin['template']:17s} {pin['board']:11s} "
              f"kw={pin['target_keyword']!r} [{cite['source']}, {cite['region']}, latest={cite['latest']}] "
              f"title={len(pin['title'])}c desc={len(pin['description'])}c")

    if check_only:
        print(f"\nvalidated {len(PINS)} pins (no files written)")
        return 0

    SPECS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    cite_rows = []
    for pin in PINS:
        spec = {"template": pin["template"], "palette": pin["palette"],
                "brand": BRAND, "handle": HANDLE, **pin["spec"]}
        (SPECS / f"{pin['stem']}.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n")
        manifest_rows.append({
            "file": f"rendered/{pin['stem']}.png",
            "template": pin["template"],
            "board": BOARDS[pin["board"]],
            "title": pin["title"],
            "description": pin["description"],
            "alt_text": pin["alt_text"],
            "target_keyword": pin["target_keyword"],
        })
        cite = idx[pin["target_keyword"]]
        cite_rows.append({"file": f"rendered/{pin['stem']}.png", "board": BOARDS[pin["board"]],
                          **{k: cite.get(k, "") for k in
                             ("term", "source", "region", "latest", "mean", "max", "trend_52w", "note")}})

    with open(BATCH / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        w.writeheader()
        w.writerows(manifest_rows)

    with open(DATA / "target-keywords.csv", "w", newline="") as f:
        cols = ["file", "board", "term", "source", "region", "latest", "mean", "max", "trend_52w", "note"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(cite_rows)

    with open(DATA / "target-keywords.md", "w") as f:
        f.write("# Batch-001 target keywords — every row cited from the harvest\n\n")
        f.write("`latest` is Pinterest's own 0-100 relative interest for the newest week in the "
                "52-week series; `max` is the series peak (so a term can be quiet in September and "
                "still peak at 100 in season); `52w` is the change across the harvested year.\n\n")
        f.write("| pin | board | target keyword | source | region | latest | mean | max | 52w |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in cite_rows:
            f.write(f"| {Path(r['file']).stem} | {r['board']} | `{r['term']}` | {r['source']} | "
                    f"{r['region']} | {r['latest']} | {r['mean']} | {r['max']} | {r['trend_52w']} |\n")

    print(f"\nwrote {len(PINS)} specs -> {SPECS}")
    print(f"wrote {BATCH / 'manifest.csv'}")
    print(f"wrote {DATA / 'target-keywords.csv'} and target-keywords.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
