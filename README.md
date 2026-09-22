# Pinterest Growth Rig

A self-hosted rig for operating a Pinterest account as a search-traffic engine: an
original pin-design factory, live trend/keyword harvesting, stealth-browser automation
via MCP, and a research-backed posting playbook.

**Niche-agnostic by design.** Point it at any niche/vertical — swap the keyword seeds,
board map, and monetization targets; the pipeline (research → design → post → measure)
stays the same.

## What it can do

- **Trend & keyword harvesting** — pulls Pinterest Trends data (top monthly/yearly/
  breakout/growing terms per region, with relative volume, seasonality score, MoM/WoW/YoY
  change) plus autocomplete + related-search harvesting seeded from arbitrary queries,
  each with 52-week interest series. Keyless (logged-out), polite rate (3–5 s spacing).
  Output: ranked term tables + thematic cluster summaries. See `keywords/`.
- **Original pin design factory** — JSON spec → 1000×1500 PNG. Six template families
  (bold title, pastel gradient, quote, listicle, photo frame, editorial minimal),
  parametric palettes, text auto-fit/wrap, WCAG contrast enforcement, 2× render +
  LANCZOS downscale, built-in audit tooling (bounds/overlap/contrast/distinctness).
  See `factory/`.
- **Stealth browser control via MCP** — CloakBrowser (source-patched Chromium) driven
  through `cloakbrowsermcp` over streamable HTTP: navigate, snapshot→refs, click, type,
  scroll, evaluate, screenshot; persistent profiles, fingerprint seeds, humanized
  input, proxy support. See `mcp/`.
- **Logged-in session logistics** — harvest a login from a phone browser over CDP
  (adb + `connect_over_cdp`), import into the rig's persistent profile, and keep egress
  on a residential IP (phone SOCKS tunnel) so the platform sees a trusted network.
  See `account/`.
- **Pin composition via the web UI** — composer automation: open the pin builder,
  inject image uploads (File/DataTransfer for hidden inputs), fill title/description,
  pick the board, screenshot the preview — and stop before publish. Upload-injection
  technique documented in `poster/`.
- **Affiliate research pipeline** — program shortlist with per-country payout rails,
  signup runbook, and platform-policy traps (dated + sourced). See
  `research/affiliate-programs.md`.
- **Content batches** — render specs + rendered pins + a manifest (board, title,
  description, alt text, target keyword) ready for a poster to consume. See `content/`.

## Architecture

```
phone (login + residential network)              design pipeline
  │  Cromite + adb CDP (:9222)                     factory/  (JSON spec → PNG)
  │  ssh -D → local SOCKS (:1080)                      │
  ▼                                                    ▼
cloakbrowser profile ── MCP server (:8933) ──── scripts (launch / audit / poster)
  (headless, fingerprint,        (cloak_* tools)       │
   persistent cookies)                                 ▼
                                               content batches → manifest
```

One browser per MCP server instance. Run separate servers for separate
accounts/brands — never share a profile or server between them.

## Prerequisites

- Linux host, Python 3.11+, Pillow + numpy
- **CloakBrowser** stealth Chromium + **cloakbrowsermcp** (HTTP MCP server +
  Playwright bridge). On the reference box this lives under
  `~/.local/share/uv/tools/cloakbrowsermcp/` with the browser in `~/.cloakbrowser/`.
- An Android phone with an SSH daemon (for SOCKS egress) and adb access
  (for CDP session harvest)
- A Pinterest account
- Optional: systemd (unit template under `mcp/`), `gh` for repo operations

## Quick start

1. Install CloakBrowser + cloakbrowsermcp; create a browser profile.
2. Bring up the phone SOCKS tunnel; point the browser at it.
3. Log in on the phone and harvest the session into the rig profile
   (`account/harvest_import.py`) — or log in once inside the rig browser directly.
4. Start the MCP server (`mcp/pinterest_mcp_server.py` or the systemd unit) and
   launch + verify the login (`mcp/pinterest_launch.py`).
5. Harvest trends/keywords (`keywords/harvest.py`), design pins
   (`factory/pin_factory.py`), assemble batches (`content/`).
6. Compose pins via `poster/` — review the preview, publish deliberately.

Full walkthrough: [`docs/setup.md`](docs/setup.md).

## Posting rules of engagement (2026-verified)

- **Fresh pins only** — new image + title + description each time; recycled designs
  get throttled by the ranking system.
- **Volume envelope:** ramp 1–2 pins/day → 2–5/day steady. Bursts and >15/day risk
  spam filters. Space posting hours apart.
- **Money pins ≤ 20%** of output; `#affiliate` disclosure; no link shorteners;
  links go to product pages.
- **Content mix:** original designs majority; any third-party imagery must be
  transformed (composited/cropped/overlaid) and kept minority; respect
  rights-holders — DMCA risk is real.
- **Pinterest pays nothing directly** — revenue comes from affiliate commissions,
  brand deals, or your own products.

## Layout

```
account/    session harvest/import + profile-edit tooling
content/    content batches: specs + rendered pins + manifest.csv
docs/       setup guide
factory/    pin design factory (templates, fonts, audits, samples)
keywords/   trend + keyword harvesters, harvested data, summaries
mcp/        MCP server, launch/audit/close scripts, rig-up / rig-down
poster/     pin composer automation
research/   affiliate & platform research (dated, sourced)
```

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Pinterest. You are responsible for
the content you publish and the accounts you operate.
