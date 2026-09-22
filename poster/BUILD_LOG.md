# poster/ — BUILD LOG

Chronological record of building the MCP-driven Pinterest pin poster.
Rig: cloakbrowsermcp HTTP MCP on `http://127.0.0.1:8933/mcp` → headless CloakBrowser,
profile `/home/ubuntu/.cloakbrowser/profiles/pinterest`, egress `socks5://127.0.0.1:1080`.

## Constraint being respected

The account is fresh and must not look spammy → **exactly one composer visit / one composer
test run**. All discovery happens on that single open composer; the page is never reloaded
after the composer mounts, so nothing is re-opened and no extra drafts are created.

## Chronology

1. **Read-only state probe** (`probe_00_state.py`) — listed the 20 MCP tools + open pages.
   Found one pre-existing page (`page_a028832b`, `in.pinterest.com/`) belonging to another
   actor. **Per coordination instruction, it was never reused, navigated or closed.**
2. **Coordination note received** mid-build: another operator is editing the profile through
   the same MCP browser (display name → `Panther`, username → `panther704`). Adjusted: all
   work happens in a page created by me via `cloak_new_page`.
3. **`cloak_new_page https://in.pinterest.com/pin-creation-tool/`** → `page_1963f077`.
   This is the one and only composer open. `/settings/` pages were avoided entirely.
4. **Composer discovered**: `pin-creation-tool` renders the new **drafts-backed "storyboard"
   builder**. First probe at ~12s found an empty shell; at ~25s the full builder was mounted
   (`#storyboard-upload-input`, Title/Description/Link/Board, "Pin drafts" sidebar). Lesson:
   the builder mounts late — poll for `#storyboard-selector-title`, don't trust a fixed sleep.
5. **Selector map captured read-only** (`probe_03_map.py`, `probe_05_snapshot.py`). No clicks,
   no upload, no reload.
6. **Single live test run** = `poster.py --spec specs/example-sage-bold-title.json` against the
   already-open composer (so the run itself did not open a second composer).
   Result and artifacts: see `test/` and `test/last_run_report.json`.

## Outcome

See `test/last_run_report.json` for the mechanical result of the single run.

*(updated as the build progressed — final status in test/last_run_report.json)*
