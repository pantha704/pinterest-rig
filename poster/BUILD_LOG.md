# poster/ — BUILD LOG

Chronological record of building the MCP-driven Pinterest pin poster.
Rig: cloakbrowsermcp HTTP MCP on `http://127.0.0.1:8933/mcp` → headless CloakBrowser,
profile `/home/ubuntu/.cloakbrowser/profiles/pinterest`, egress `socks5://127.0.0.1:1080`.
Operator note: **exactly one composer was opened and one draft created.**

## Constraint respected

The account is fresh and must not look spammy → **one composer visit / one composer test run**.
All discovery happened against that single open composer. The page was never reloaded after the
builder mounted, so no second composer was opened and no second draft was created. (Every
correction after the first run was applied *inside that same draft*, and `poster.py` is
idempotent: it skips navigation when already on the builder URL and skips image injection when
the draft already has a preview.)

Coordination: the pre-existing page `page_a028832b` belonged to the rig owner (they were editing
the profile through the same browser) — it was **never reused, navigated or closed**. All work
happened in `page_1963f077`, created by this workstream via `cloak_new_page`.

## Chronology

1. **Read-only state probe** (`probe_00_state.py`) — 20 MCP tools listed, open pages inspected.
2. **`cloak_new_page https://in.pinterest.com/pin-creation-tool/`** → `page_1963f077`.
   This is the single composer open. No `/settings/` page was ever touched.
3. **`probe_01_composer.py`** — at ~12 s the page was a bare nav shell (no builder).
   **`probe_02_broad.py`** at ~25 s found the fully mounted builder. *Lesson: the builder mounts
   late; poll for `#storyboard-selector-title` rather than sleeping a fixed time.*
4. **`probe_03_map.py` / `probe_05_snapshot.py`** — selector map + a11y refs captured read-only.
   No clicks, no upload, no reload.
5. **The one live run** — `poster.py --spec specs/example-sage-bold-title.json`.
   * **Upload: WORKED, approach 1 (DataTransfer + native `files` setter + `input`/`change`) on the
     first try.** Preview started as `blob:` and became `https://i.pinimg.com/736x/d6/7c/dd/…jpg`
     → Pinterest-side upload confirmed.
   * **Title/link/board: silently failed.** The run "succeeded" with empty fields.
6. **Root cause (`probe_06_diag.py`)** — the smoking gun:
   `ElementNotStableError: Element '#storyboard-selector-title' failed stable check: element
   position is still changing`, returned with **`isError=false`** and
   `structuredContent.status="error"`. `cloak_click`/`cloak_type` therefore can never work on
   this builder, and they fail *without raising* — so the first run filled nothing while looking
   green. **Fixed `mcp_client.call()` to raise on `status=error`.** Each failed attempt also costs
   ~2 minutes, which is why the first run took 5 minutes to do nothing.
7. **Working mechanisms established (`probe_06`–`probe_11`)**:
   * `cloak_evaluate` + JS native value setter → Title writes and **persists** (survived re-reads
     minutes later, and showed up in the draft sidebar entry).
   * `cloak_press_key` works (trusted keys, no stability check) — proven by appending `Z` to the
     focused Title. Used for `Backspace`/`Escape` and as the title fallback.
   * Board picker: JS click opens `[data-test-id="board-picker-flyout"]`; rows are
     `[data-test-id="board-row-<Board Name>"]` — the exact, unambiguous selector.
   * Description: container is an empty Gestalt `role=button`; `#mweb-comment-editor-container`
     never mounts for synthetic events (tried `.click()`, a full pointer/mouse sequence,
     `focus()`+`Enter`/`Space`, `paste`/`beforeinput`, `execCommand`). **Remaining gap.**
   * Beware: the page's `[role="textbox"]` is the *canvas text layer*
     (`storyboard-editor-canvas-text`, "Text field Blank…"), **not** the description field.
8. **Final state captured** (`probe_13_capture.py`, `test/final_state.json`):
   title persisted, `previewImgs` served from `i.pinimg.com`, draft
   `pinDraft-3879710469468073280` in the sidebar, `savingStatus: "Changes stored!"`,
   `publishButtonPresent: true` — **never clicked**.
9. **`poster.py` rewritten** to use only the mechanisms proven above (JS for field writes,
   `cloak_press_key` fallback, JS board selection), with the description gap reported honestly
   instead of silently producing an empty field.

## Final status

* Works end-to-end: navigation/attach, **image upload**, **title fill (persisted)**, draft
  auto-save, stop-before-Publish guard, screenshots.
* Open: **description fill** (needs a trusted pointer click the rig can't deliver here);
  board *switching* not observed live (selector map + JS path implemented, only the already
  selected board was targeted); link path implemented but not exercised (`link: null` in the spec).
* Detail and next ideas: `README.md` → "Known gaps".

## A shout-out to the next session

Do **not** reach for `cloak_click`/`cloak_type` on the pin builder without first checking the
`status=error` field — they will look like they worked. Run `probe_06_diag.py` to re-confirm.
