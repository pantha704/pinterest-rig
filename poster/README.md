# poster/ — MCP-driven Pinterest pin poster

Drives the **running CloakBrowser MCP rig** (`http://127.0.0.1:8933/mcp`, headless, logged-in
`the rig account` / `in.pinterest.com`) to compose a Pinterest pin from a JSON spec, and
**stops before Publish**. There is no file-upload MCP tool, so the image is injected as a JS
`File` — that mechanism is the heart of this tool and is documented in full below.

```
poster.py --spec specs/example-sage-bold-title.json            # compose, stop before Publish
poster.py --spec specs/example-sage-bold-title.json --dry-run  # validate + print plan, no browser
python = /home/ubuntu/.local/share/uv/tools/cloakbrowsermcp/bin/python
```

## Verified status (single composer run, 2026-09-22)

| Step | Status | Evidence |
|---|---|---|
| Open builder / attach to page | ✅ works | `in.pinterest.com/pin-creation-tool/` renders the builder in place |
| **Upload image (JS File injection)** | ✅ **works, approach 1 on first try** | preview went `blob:` → `https://i.pinimg.com/736x/d6/7c/dd/…jpg` = real server-side upload |
| Fill **Title** | ✅ works + persists | value re-read after 6s and again minutes later |
| Draft auto-save | ✅ works | sidebar entry `pinDraft-3879710469468073280`, `saving-status` = `Changes stored!` |
| Select board | ⚠️ selector map verified; JS click path implemented | dropdown inventory captured live; only the composer's default board was used |
| Fill **Description** | ❌ **single remaining gap** | see "Description field" below |
| **Never published** | ✅ enforced | `Publish` button exists and was never clicked; guard blocks it in code |

The composer left behind is a **draft**, not a public pin. No Publish/Done/Save/P was ever clicked.

## The exact UI flow discovered

1. **`https://in.pinterest.com/pin-creation-tool/`** loads the builder *in place* — no need to
   click the header `Create` button first. (Open it in your own page via `cloak_new_page`.)
2. **The builder mounts late.** At ~12 s the page is only a nav shell; at ~25 s the full
   builder is present. Do **not** trust a fixed sleep — poll for `#storyboard-selector-title`.
3. **The whole form is DISABLED until media uploads.** `Title`, `Description`, `Board`,
   `Add products` all carry `[disabled]` and there is no `Publish` button at all.
4. **The preview `<img>` appears before the form is usable.** Right after injection the preview
   is a `blob:` URL and the form is still disabled; Pinterest then uploads to its CDN and
   re-enables the form. Filling during that window **silently no-ops** — this was the first bug
   found. Gate on `#storyboard-selector-title` + board button `disabled === false`.
5. **The builder auto-saves a draft** ("Pin drafts" right sidebar, `Changes stored!`). This is
   the built-in "save as draft" behaviour — no separate control is needed.
6. **`Publish` appears after upload**, top-right, next to the save status. Never touch it here.

## Selector map (live DOM — Pinterest's `data-test-id` layer is stable, hashed CSS classes are not)

| Purpose | Selector | Notes |
|---|---|---|
| Composer ready | `#storyboard-selector-title` | exists only once the builder mounts |
| **File input** | `#storyboard-upload-input` | also `[data-test-id="storyboard-upload-input"]`; `accept="image/bmp,…,video/quicktime"`, `multiple`, `required`, `opacity:0` overlay covering the drop zone |
| Title | `#storyboard-selector-title` | `input[text]`, placeholder *"Tell everyone what your Pin is about"* |
| Description container | `[data-test-id="storyboard-description-field-container"]` | a Gestalt `role=button`, **no editor mounted** — see gap below |
| Link | `#WebsiteField` | `input[url]`, placeholder *"Add a link"* |
| Board display | `[data-test-id="board-dropdown-select-button"]` / `[data-test-id="board-dropdown-item-selected"]` | accessible name is the board text |
| Board dropdown panel | `[data-test-id="board-picker-flyout"]` | `role=dialog`; **open only after a click** |
| Board search | `[data-test-id="search-boards-field-container"]` | the anchor for parsing the open panel |
| **Board rows** | `[data-test-id="board-row-<Board Name>"]` | e.g. `board-row-Programmer humor` — the exact, only reliable way to pick a board |
| Create board | `[data-test-id="create-board-button"]` | last row of the open dropdown |
| Drafts sidebar | `[data-test-id="storyboard-drafts-sidebar"]`, `[data-test-id^="pinDraft-"]` | one `pinDraft-<id>` node per draft |
| Save state | `[data-test-id^="saving-status"]` | e.g. `Changes stored!` |
| **Publish (forbidden)** | `button` with text `Publish` | also guarded by name match |
| Canvas text layer | `[data-test-id="storyboard-editor-canvas-text"]` | a `role=textbox` with `contenteditable="false"` — **not** the description field; don't be fooled |

Boards seen on this account: `Birthday cakes for babies` (default), `First birthday themes`,
`Programmer humor`.

## Image-upload injection technique (the core trick that worked)

No MCP tool uploads files, so the image is turned into a JS `File` inside the page and pushed
through the input React is listening to:

1. Python reads the PNG and base64-encodes it.
2. `cloak_evaluate` builds `Uint8Array → File([...], name, {type:'image/png'})`.
3. A `DataTransfer` is created and `dt.items.add(file)`.
4. The **native** `files` setter is used —
   `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'files').set.call(input, dt.files)` —
   so React's value tracker sees a real change (`input.files = dt.files` alone can be swallowed).
5. `input` and `change` events are dispatched with `bubbles: true`.

**Approach 1 (`change` events) succeeded on the first try.** Two fallbacks are implemented:
**approach 2** re-dispatches the same `DataTransfer` as a `dragenter/dragover/drop` sequence on
the input *and* its `[data-test-id="drag-behavior-container"]` ancestor; **approach 3** re-queries
the input and retries the `change` path (covers React remounting the node mid-flight).
Verification is by **effect, not by the return value**: the run only accepts success once a
preview `<img>` with `naturalWidth > 200` exists, and the strongest proof is that the preview's
`src` became `https://i.pinimg.com/736x/d6/7c/dd/d67cddbed35e84703f347cdc7dd3fce0.jpg` — Pinterest's
own CDN, i.e. the file really was uploaded server-side (not just a local `blob:`).

## Interaction layer: what actually works on this rig (read this before debugging)

* **`cloak_click` and `cloak_type` FAIL on this builder page** — and fail *silently*:
  `ElementNotStableError: Element '#storyboard-selector-title' failed stable check: element
  position is still changing`, returned with **`isError: false`** and
  `structuredContent.status == "error"`. `mcp_client.py` now converts that into a raised
  `MCPError`; without that check the caller believes the click worked. Each failed attempt also
  burns ~2 minutes, which is how a 5-minute run quietly produces empty fields.
  *Cause is a page-side condition (the builder never passes Playwright's stable check), not a
  wrong selector — the refs were correct every time (`[@e22] input[text] "Title"`).*
* **`cloak_evaluate` works** — use it for all field writes (native setter + `input`/`change`).
* **`cloak_press_key` works** (trusted key events, no stability check). Verified live: focusing
  the Title via JS and pressing `Z` appended `Z` to the value. Useful as a fallback for short
  text and for `Backspace`/`Escape` corrections.
* Net: `poster.py` drives fields through **JS**, not through `cloak_click`/`cloak_type`.

## Known gaps (open work for a follow-up session)

1. **Description field.** `[data-test-id="storyboard-description-field-container"]` is an empty
   Gestalt `role=button`; the mentions editor (`#mweb-comment-editor-container` — its id is even
   visible in the button's accessible name) **never mounts** in response to anything a
   non-trusted event can produce. Tried and failed: `.click()` on the button, a full
   `pointerdown/mousedown/pointerup/mouseup/click` sequence, `focus()` + `Enter`/`Space`,
   `paste` + `beforeinput` with a `DataTransfer`, and `execCommand('insertText')` (no
   editable target). A **trusted pointer click** is what's missing, and `cloak_click` cannot
   deliver one here because of the stability check. Next ideas: (a) find a page-state that makes
   the builder pass the stable check (e.g. a different viewport/`headless` combination, or
   `cloak_launch` without `humanize`) so `cloak_click` can be used for this one control;
   (b) check whether the description becomes an inline editor when the Pin has a text layer
   (`Edit Pin Design`); (c) accept a single human/VNC click to open the editor and finish the
   fill via JS.
2. **Board switching not observed live.** The dropdown opens and all rows are enumerated
   correctly, but the single test run targeted the board that was already selected, so the
   `board-row-*` click path is implemented but not yet proven to change the selection. Verify by
   pointing a spec at `Programmer humor` and re-reading `board-dropdown-select-button`.
3. **Link field** shares the proven Title mechanism (`#WebsiteField`, same native-setter path)
   and is implemented, but the test spec deliberately used `link: null` to keep the draft
   benign, so it was not exercised end-to-end.

## Safety contract

* `assert_not_publish_control()` runs before every click and refuses any control whose text
  matches `\b(publish|done|post|save|submit|create pin)\b`. There is no flag to disable it.
* A run **never navigates if the page is already on the builder URL**, and **never re-injects
  the image if the draft already has a preview** — so re-running is idempotent and does not
  open extra composers or create extra drafts.
* Any captcha / "verify you are human" / blocked text on the composer aborts the run
  immediately with no retry.

## Files

```
poster.py              the tool (CLI: --spec, --dry-run, --page-id, --force-upload)
mcp_client.py          thin async MCP client (+ the silent-error detection fix)
specs/                 example + template pin specs
test/                  verification screenshots, probe dumps, run reports
BUILD_LOG.md           chronological build record
probe_*.py             the discovery probes, kept as evidence (probe_00…probe_13)
```

`test/` highlights: `00_builder_before_mount.png` (bare shell at ~12 s — why you must poll),
`10_composer_open.png` (composer open, no media), `11_image_uploaded.png` (the injected PNG
rendering in the composer, `Pin drafts (1)`, Publish present but untouched),
`12_fields_filled_composer_preview.png` (final: image + Title filled, board selected, draft saved).
Also: `last_run_report.json`, `final_state.json`, `01_builder_probe.json`, `03_composer_map.json`,
`03b_composer_snapshot.txt`, and the raw stdout logs of each probe.
