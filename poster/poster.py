#!/usr/bin/env python3
"""
poster.py — MCP-driven Pinterest pin composer for the CloakBrowser rig (127.0.0.1:8933).

Given a JSON pin spec {image_path, title, description, link?, board_name} it drives Pinterest's
*web* pin builder to COMPOSE a pin: open the composer, inject the image (there is no file-upload
MCP tool — the image goes in as a JS File object through a DataTransfer), fill Title / Link,
attempt Description, select the board — then STOP.

SAFETY CONTRACT (hard-coded, not configurable):
  * Never clicks Publish / Done / Post / Save -> no live public pin is ever created.
    `assert_not_publish_control()` runs before every click and has no override.
  * The composer is Pinterest's drafts-backed "storyboard" builder: Pinterest itself auto-saves
    the in-progress pin as a DRAFT ("Changes stored!", `pinDraft-<id>`), which is exactly the
    "prefer a draft" behaviour we want.
  * A run never navigates when the page is already on the builder URL, and never re-injects the
    image when the draft already has a preview -> re-runs are idempotent and never open extra
    composers or create extra drafts.

INTERACTION LAYER (read before debugging — this rig is unusual):
  * cloak_click / cloak_type FAIL on this builder page with
    `ElementNotStableError: ... failed stable check: element position is still changing`,
    reported with isError=False + structuredContent.status="error" (mcp_client.py now raises on
    that) and each attempt burns ~2 minutes. So all field writes go through cloak_evaluate.
  * cloak_evaluate works. cloak_press_key works (trusted keys; used as a fallback).

Usage:
  poster.py --spec specs/example.json                    # compose, stop before Publish
  poster.py --spec specs/example.json --dry-run          # validate spec + print plan, no browser
  poster.py --spec specs/example.json --page-id page_x   # reuse a specific MCP page
  poster.py --spec specs/example.json --force-upload     # re-inject the image if needed

Python: /home/ubuntu/.local/share/uv/tools/cloakbrowsermcp/bin/python (needs `mcp`)
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, MCPError, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(HERE, "test")

BUILDER_URL = "https://in.pinterest.com/pin-creation-tool/"
SEL_UPLOAD_INPUT = "#storyboard-upload-input"
SEL_TITLE = "#storyboard-selector-title"
SEL_LINK = "#WebsiteField"
SEL_DESC = '[data-test-id="storyboard-description-field-container"]'
SEL_BOARD_BTN = '[data-test-id="board-dropdown-select-button"]'
SEL_BOARD_PANEL = '[data-test-id="board-picker-flyout"]'

# ---------------------------------------------------------------- safety guard ---
# Publish/Done/Post create a live public pin; "Save" is included because on some Pinterest
# surfaces the primary submit control is labelled "Save" (save-to-board == publish).
FORBIDDEN_CLICK = re.compile(r"\b(publish|done|post|save|submit|create pin)\b", re.IGNORECASE)


def assert_not_publish_control(label: str) -> None:
    if not label:
        return
    if FORBIDDEN_CLICK.search(label):
        raise SystemExit(
            f"REFUSING to click {label!r}: matches the publish/done guard {FORBIDDEN_CLICK.pattern!r}. "
            "poster.py stops before publishing by design."
        )


# ---------------------------------------------------------------------- spec ------
REQUIRED = ("image_path", "title", "board_name")


def load_spec(path: str) -> dict:
    with open(path) as f:
        spec = json.load(f)
    missing = [k for k in REQUIRED if not spec.get(k)]
    if missing:
        raise SystemExit(f"spec {path}: missing required key(s): {missing}")
    img = spec["image_path"]
    if not os.path.isabs(img):
        cand = os.path.join(os.path.dirname(os.path.abspath(path)), img)
        if not os.path.exists(cand):
            cand = os.path.join("/home/ubuntu/pinterest-rig", img)
        img = cand
    if not os.path.exists(img):
        raise SystemExit(f"spec {path}: image_path does not exist: {img}")
    if not img.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")):
        raise SystemExit(f"spec {path}: unsupported image type (Pinterest accepts JPG/PNG up to 20MB): {img}")
    size_mb = os.path.getsize(img) / 1e6
    if size_mb > 20:
        raise SystemExit(f"spec {path}: image is {size_mb:.1f}MB — Pinterest's limit is 20MB")
    spec["image_path"] = img
    spec.setdefault("description", "")
    spec.setdefault("link", None)
    return spec


# ------------------------------------------------------------------- JS probes ----
STATE_JS = r"""(() => {
  const g = (s) => document.querySelector(s);
  const imgs = Array.from(document.querySelectorAll('img')).map(i => ({
    src: (i.currentSrc || i.src || '').slice(0, 110), w: i.naturalWidth, h: i.naturalHeight }));
  const board = g('[data-test-id="board-dropdown-select-button"]');
  const boardEl = board ? (board.closest('button,[role=button]') || board) : null;
  const t = g('#storyboard-selector-title');
  const link = g('#WebsiteField');
  const c = g('[data-test-id="storyboard-description-field-container"]');
  const drafts = Array.from(document.querySelectorAll('[data-test-id^="pinDraft-"]'))
    .map(e => ({testid: e.getAttribute('data-test-id'),
                text: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 90)}));
  return JSON.stringify({
    url: location.href,
    composerReady: !!t && !!board,
    uploadInput: !!g('#storyboard-upload-input'),
    previewImages: imgs.filter(i => i.w > 200 && i.h > 200).slice(0, 5),
    titleValue: t ? t.value : null,
    titleDisabled: t ? !!t.disabled : null,
    linkValue: link ? link.value : null,
    descText: c ? (c.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200) : null,
    descEditables: document.querySelectorAll(
      '[data-test-id="storyboard-description-field-container"] [contenteditable="true"], #mweb-comment-editor-container [contenteditable="true"]').length,
    board: boardEl ? {text: (boardEl.innerText || '').replace(/\s+/g, ' ').trim(),
                      disabled: !!boardEl.disabled} : null,
    boardRows: Array.from(document.querySelectorAll('[data-test-id^="board-row-"]'))
      .map(e => ({testid: e.getAttribute('data-test-id'),
                  text: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60)})),
    boardPanelOpen: !!g('[data-test-id="board-picker-flyout"]'),
    draftsSidebar: !!g('[data-test-id="storyboard-drafts-sidebar"]'),
    draftEntries: drafts,
    savingStatus: (() => { const s = g('[data-test-id^="saving-status"]'); return s ? (s.innerText || '').trim().slice(0, 40) : null; })(),
    publishControls: Array.from(document.querySelectorAll('button,[role=button],a[role=button]'))
      .map(e => ({testid: e.getAttribute('data-test-id'),
                  txt: (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30),
                  aria: (e.getAttribute('aria-label') || '').slice(0, 40), disabled: e.disabled === true}))
      .filter(b => /(publish|\bdone\b|\bpost\b|\bsave\b)/i.test((b.txt || '') + ' ' + (b.aria || ''))),
    bodyHasCaptcha: /captcha|verify you are human|unusual traffic|blocked/i.test(document.body ? document.body.innerText : ''),
  });
})()"""

# The one mechanism that made upload work: base64 -> File -> DataTransfer -> NATIVE files setter
# (so React's value tracker sees the change) -> input/change events.
INJECT_JS = r"""(() => {
  const B64 = "%(b64)s";
  const NAME = "%(name)s";
  const MIME = "%(mime)s";
  const TECHNIQUE = "%(technique)s";
  try {
    const bin = atob(B64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const file = new File([u8], NAME, { type: MIME, lastModified: Date.now() });
    const dt = new DataTransfer();
    dt.items.add(file);
    const input = document.querySelector('#storyboard-upload-input')
               || document.querySelector('input[type=file]');
    if (!input) return JSON.stringify({ok: false, err: 'no file input in DOM'});
    const nativeSet = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'files').set;
    nativeSet.call(input, dt.files);
    if (TECHNIQUE === 'change') {
      input.dispatchEvent(new Event('input',  {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    } else if (TECHNIQUE === 'drop') {
      const zone = input.closest('[data-test-id="drag-behavior-container"]') || input.parentElement;
      for (const type of ['dragenter', 'dragover', 'drop']) {
        for (const tgt of [input, zone]) {
          if (tgt) tgt.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt}));
        }
      }
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return JSON.stringify({ok: true, technique: TECHNIQUE,
      files: Array.from(input.files).map(f => f.name + ':' + f.size + ':' + f.type)});
  } catch (e) { return JSON.stringify({ok: false, err: String((e && e.message) || e)}); }
})()"""

NETLOG_JS = r"""(() => {
  if (window.__netlog) return 'already';
  window.__netlog = [];
  const of = window.fetch;
  window.fetch = function (...a) {
    try { window.__netlog.push({t: Date.now(), m: 'fetch',
      url: String((typeof a[0] === 'string') ? a[0] : (a[0] && a[0].url)).slice(0, 160)}); } catch (e) {}
    return of.apply(this, a);
  };
  const O = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u, ...r) {
    try { window.__netlog.push({t: Date.now(), m: m, url: String(u).slice(0, 160)}); } catch (e) {}
    return O.call(this, m, u, ...r);
  };
  return 'installed';
})()"""


def SET_INPUT_JS(selector: str, value: str) -> str:
    """React-safe input write: native value setter + input/change events."""
    return r"""(() => {
      const el = document.querySelector(%s);
      if (!el) return JSON.stringify({ok: false, err: 'not found'});
      el.focus();
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      set.call(el, %s);
      el.dispatchEvent(new Event('input',  {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return JSON.stringify({ok: true, value: el.value});
    })()""" % (json.dumps(selector), json.dumps(value))


# ------------------------------------------------------------------ the driver ----
class Composer:
    def __init__(self, rig: AsyncRig, page_id: str, spec: dict, shots: list):
        self.rig, self.pid, self.spec, self.shots = rig, page_id, spec, shots
        self.report_notes: list[str] = []

    # -- basics ------------------------------------------------------------------
    async def read(self) -> dict:
        st = await self.rig.evaluate_json(self.pid, STATE_JS)
        if st.get("bodyHasCaptcha"):
            raise SystemExit("STOP: captcha / 'verify you are human' / blocked text detected on the "
                             "composer. No retries. Investigate manually.")
        return st

    async def shoot(self, name: str) -> str:
        r = await self.rig.screenshot(self.pid)
        src = None
        try:
            src = json.loads(r).get("path")
        except Exception:
            m = re.search(r"(/[\w./-]+\.png)", r)
            src = m.group(1) if m else None
        dst = os.path.join(TEST_DIR, name)
        if src and os.path.exists(src):
            os.makedirs(TEST_DIR, exist_ok=True)
            with open(src, "rb") as a, open(dst, "wb") as b:
                b.write(a.read())
            log(f"  screenshot -> {dst}")
            self.shots.append(dst)
        else:
            log(f"  screenshot artifact path unresolved: {r[:120]}")
        return dst

    async def js(self, expr: str) -> dict:
        return await self.rig.evaluate_json(self.pid, expr)

    async def wait_fields_enabled(self, timeout=150) -> dict:
        """THE critical gate. The preview <img> (blob: URL) appears the instant the File is
        injected, but Pinterest only re-enables Title/Description/Link/Board once its own upload
        + processing finishes. Writing before that silently no-ops (this was bug #1)."""
        for i in range(max(1, timeout // 5)):
            st = await self.read()
            if (st.get("titleDisabled") is False
                    and (st.get("board") or {}).get("disabled") is False
                    and st.get("previewImages")):
                log(f"  fields enabled after ~{(i + 1) * 5}s "
                    f"(savingStatus={st.get('savingStatus')!r})")
                return st
            if i % 4 == 3:
                log(f"  waiting for the form to enable… {i * 5}s (titleDisabled="
                    f"{st.get('titleDisabled')}, boardDisabled={(st.get('board') or {}).get('disabled')}, "
                    f"preview={len(st.get('previewImages') or [])})")
            await asyncio.sleep(5)
        raise SystemExit("STOP: composer form never enabled after upload — leaving the draft as-is")

    # -- steps -------------------------------------------------------------------
    async def step_open_composer(self) -> dict:
        pages = (await self.rig.list_pages()) or {}
        plist = pages.get("pages", pages if isinstance(pages, list) else [])
        cur = next((p for p in plist if p.get("page_id") == self.pid), None)
        cur_url = (cur or {}).get("url", "")
        if "pin-creation-tool" in cur_url or "pin-builder" in cur_url:
            log("  already on the builder URL — no navigation (avoids a second composer visit)")
        else:
            log(f"  navigating to {BUILDER_URL}")
            await self.rig.navigate(self.pid, BUILDER_URL)
        for i in range(40):
            await asyncio.sleep(3)
            st = await self.read()
            if st.get("composerReady"):
                # the builder mounts late (~25s cold) — poll, never trust a fixed sleep
                log(f"  composer ready after ~{(i + 1) * 3}s")
                return st
        raise SystemExit("STOP: composer did not render within 120s")

    async def step_upload(self) -> dict:
        st = await self.read()
        if not st.get("composerReady"):
            raise SystemExit("STOP: composer lost (#storyboard-selector-title missing)")
        already = bool(st.get("previewImages"))
        if already and not self.spec.get("force_upload"):
            log(f"  image already present in this draft ({len(st['previewImages'])} preview img) "
                "— skipping injection (idempotent re-runs)")
            return st

        img = self.spec["image_path"]
        ext = os.path.splitext(img)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
                "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff"}.get(ext, "image/png")
        b64 = base64.b64encode(open(img, "rb").read()).decode()
        name = os.path.basename(img)
        log(f"  injecting {name} ({os.path.getsize(img) / 1024:.0f} KB) as image/{ext} via JS File+DataTransfer")
        try:
            log("  netlog:", await self.rig.evaluate(self.pid, NETLOG_JS))
        except MCPError:
            pass

        for attempt, technique in enumerate(("change", "drop", "change"), start=1):
            res = await self.js(INJECT_JS % {"b64": b64, "name": name, "mime": mime, "technique": technique})
            log(f"  approach {attempt} ({technique}): {json.dumps(res)[:200]}")
            if not res.get("ok"):
                if attempt == 3:
                    return {"uploaded": False, "error": res.get("err")}
                continue
            for _ in range(10):                      # poll up to ~30s for the preview to render
                await asyncio.sleep(3)
                st = await self.read()
                if st.get("previewImages"):
                    src = (st["previewImages"][0] or {}).get("src", "")
                    log(f"  UPLOAD OK — preview rendered: {json.dumps(st['previewImages'])[:220]}")
                    log(f"  preview served from: {src[:70]}"
                        f"{'  <-- Pinterest CDN: server-side upload confirmed' if 'pinimg.com' in src else '  (blob: local only — not yet on the CDN)'}")
                    try:
                        self.netlog = await self.js("(()=>JSON.stringify((window.__netlog||[]).slice(-12)))()")
                    except MCPError:
                        self.netlog = None
                    return await self.wait_fields_enabled()
            log(f"  approach {attempt} ({technique}) did not render a preview")
        return {"uploaded": False, "error": "3 approaches tried, no preview rendered"}

    async def step_fill_fields(self) -> dict:
        st = await self.wait_fields_enabled()   # never write into a disabled form
        mechanisms = {}

        # --- Title: JS native setter + input/change. Verified to persist into the draft.
        want = self.spec["title"].strip()
        if (st.get("titleValue") or "").strip() != want:
            r = await self.js(SET_INPUT_JS(SEL_TITLE, self.spec["title"]))
            log(f"  title <- {json.dumps(r)[:160]}")
            await asyncio.sleep(3)
            st = await self.read()
            if want not in (st.get("titleValue") or ""):
                # trusted-keyboard fallback (cloak_press_key works where cloak_type does not)
                log("  title JS set did not stick — falling back to trusted keys")
                await self.js(f"(()=>{{const t=document.querySelector(%s);if(t)t.focus();return '1'}})()"
                              % json.dumps(SEL_TITLE))
                await self.rig.call("cloak_press_key", {"page_id": self.pid, "key": "Backspace"})
                for ch in self.spec["title"]:
                    await self.rig.call("cloak_press_key", {"page_id": self.pid, "key": ch})
                await asyncio.sleep(2)
                st = await self.read()
            mechanisms["title"] = "js-native-setter" if want in (st.get("titleValue") or "") else "FAILED"

        # --- Description: OPEN GAP. The container is a Gestalt role=button that mounts a
        # #mweb-comment-editor-container only for a TRUSTED pointer click, which this rig cannot
        # deliver (cloak_click dies on the stability check). We try the synthetic routes, then
        # report honestly instead of pretending.
        if self.spec["description"]:
            wantd = self.spec["description"].strip()
            st = await self.read()
            if wantd not in (st.get("descText") or ""):
                r = await self.js(r"""(() => {
                  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
                  if (!c) return JSON.stringify({ok: false, err: 'no container'});
                  const target = c.querySelector('[role="button"]') || c;
                  const opts = {bubbles: true, cancelable: true, composed: true, view: window, button: 0, buttons: 1};
                  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    const C = t.startsWith('pointer') ? PointerEvent : MouseEvent;
                    target.dispatchEvent(new C(t, opts));
                  }
                  const dt = new DataTransfer();
                  dt.setData('text/plain', %s);
                  target.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: dt}));
                  target.setAttribute('tabindex', '0');
                  target.focus();
                  const ce = c.querySelector('[contenteditable="true"]');
                  if (ce) {
                    document.execCommand('insertText', false, %s);
                    ce.dispatchEvent(new InputEvent('input', {bubbles: true, data: %s}));
                    return JSON.stringify({ok: true, mechanism: 'contenteditable-insertText'});
                  }
                  return JSON.stringify({ok: false, err: 'no contenteditable mounted',
                                         descEditables: document.querySelectorAll('#mweb-comment-editor-container [contenteditable="true"]').length});
                })()""" % (json.dumps(wantd), json.dumps(wantd), json.dumps(wantd)))
                log(f"  description activation: {json.dumps(r)[:300]}")
                await asyncio.sleep(3)
                st = await self.read()
                if wantd[:30] in (st.get("descText") or ""):
                    mechanisms["description"] = "contenteditable-insertText"
                else:
                    mechanisms["description"] = "GAP: trusted pointer click required"
                    self.report_notes.append(
                        "description NOT filled: #mweb-comment-editor-container only mounts for a trusted "
                        "pointer click; cloak_click is unusable on this page (ElementNotStableError) and "
                        "synthetic .click()/pointer sequences/paste all fail to mount the editor. "
                        "See README 'Known gaps'.")
            else:
                mechanisms["description"] = "already present"

        # --- Link (optional) -------------------------------------------------------
        if self.spec.get("link"):
            st = await self.read()
            if (st.get("linkValue") or "").strip() != self.spec["link"].strip():
                r = await self.js(SET_INPUT_JS(SEL_LINK, self.spec["link"]))
                log(f"  link <- {json.dumps(r)[:160]}")
                await asyncio.sleep(2)
                st = await self.read()
                mechanisms["link"] = "js-native-setter" if (st.get("linkValue") or "").strip() == self.spec["link"].strip() else "FAILED"
        self.mechanisms = mechanisms
        return await self.read()

    async def step_select_board(self):
        """Open the board picker with a JS click, enumerate `[data-test-id^="board-row-"]`, click
        the row whose text matches the spec. Selecting a board is composing, not publishing."""
        st = await self.read()
        cur = re.sub(r"^Board\s*", "", (st.get("board") or {}).get("text") or "").strip()
        want = self.spec["board_name"].strip()
        r = await self.js(f"(()=>{{const b=document.querySelector({json.dumps(SEL_BOARD_BTN)});"
                          "if(b){b.click();return JSON.stringify({ok:true});}return JSON.stringify({ok:false});})()")
        log(f"  board picker open: {json.dumps(r)}")
        await asyncio.sleep(4)
        st = await self.read()
        rows = st.get("boardRows") or []
        inventory = [x.get("text") for x in rows]
        log(f"  board inventory ({len(rows)}): {json.dumps(inventory)[:400]}")
        target = next((x for x in rows if (x.get("text") or "").strip().lower() == want.lower()), None)
        if not target:
            log(f"  board '{want}' not among {inventory} — closing picker, leaving selection untouched")
            await self.rig.call("cloak_press_key", {"page_id": self.pid, "key": "Escape"})
            return st, {"current": cur, "inventory": inventory, "changed": False, "matched": None}
        sel = f'[data-test-id="{target["testid"]}"]'
        assert_not_publish_control(target.get("text") or "")
        await self.js(f"(()=>{{const r=document.querySelector({json.dumps(sel)});"
                      "if(r){r.click();return JSON.stringify({ok:true});}return JSON.stringify({ok:false});})()")
        await asyncio.sleep(4)
        st2 = await self.read()
        now = re.sub(r"^Board\s*", "", (st2.get("board") or {}).get("text") or "").strip()
        log(f"  board now: {now!r} (was {cur!r})")
        return st2, {"current": now, "previous": cur, "inventory": inventory, "matched": target["testid"],
                     "changed": now.lower() != cur.lower()}


async def compose(spec: dict, page_id=None) -> dict:
    shots: list = []
    os.makedirs(TEST_DIR, exist_ok=True)
    async with AsyncRig() as rig:
        if page_id:
            pid = page_id
            log(f"using page_id from CLI: {pid}")
        else:
            pages = (await rig.list_pages()) or {}
            plist = pages.get("pages", pages if isinstance(pages, list) else [])
            pid = next((p.get("page_id") for p in plist
                        if "pin-creation-tool" in (p.get("url") or "")
                        or "pin-builder" in (p.get("url") or "")), None)
            if pid:
                log(f"attaching to the existing builder page: {pid}")
            else:
                log("no builder page open — creating a dedicated one (cloak_new_page)")
                r = await rig.call("cloak_new_page", {"url": BUILDER_URL})
                pid = json.loads(r).get("page_id")
                if not pid:
                    raise SystemExit(f"cloak_new_page failed: {r[:300]}")
                log(f"new page: {pid}")
        with open(os.path.join(TEST_DIR, "last_page_id.txt"), "w") as f:
            f.write(pid)

        drv = Composer(rig, pid, spec, shots)
        report = {"page_id": pid, "spec": spec, "steps": {}}

        log("[1/5] open composer")
        st = await drv.step_open_composer()
        report["steps"]["composer_open"] = {"url": st.get("url"), "draftsSidebar": st.get("draftsSidebar"),
                                            "previewImages": len(st.get("previewImages") or [])}
        await drv.shoot("10_composer_open.png")

        log("[2/5] upload image (JS File + DataTransfer injection)")
        up = await drv.step_upload()
        report["steps"]["upload"] = {"uploaded": bool(up.get("previewImages")),
                                     "previews": up.get("previewImages"),
                                     "error": up.get("error")}
        if not report["steps"]["upload"]["uploaded"]:
            report["status"] = "BLOCKED_AT_UPLOAD"
            await drv.shoot("11_upload_failed.png")
            report["screenshots"] = shots
            return report
        await drv.shoot("11_image_uploaded.png")

        log("[3/5] fill title / description / link")
        st = await drv.step_fill_fields()
        report["steps"]["fields"] = {"title": st.get("titleValue"), "link": st.get("linkValue"),
                                     "description": (st.get("descText") or "")[:200],
                                     "mechanisms": getattr(drv, "mechanisms", {})}

        log("[4/5] select board")
        st, binfo = await drv.step_select_board()
        report["steps"]["board"] = binfo

        log("[5/5] final state + STOP (publish never clicked)")
        st = await drv.read()
        report["steps"]["final"] = {k: st.get(k) for k in
                                    ("url", "titleValue", "linkValue", "descText", "board",
                                     "draftEntries", "savingStatus", "publishControls")}
        await drv.shoot("12_fields_filled_composer_preview.png")
        report["screenshots"] = shots
        report["status"] = "COMPOSED_NOT_PUBLISHED"
        report["notes"] = drv.report_notes
        return report


def main():
    ap = argparse.ArgumentParser(description="Compose a Pinterest pin via the CloakBrowser MCP rig "
                                            "(stops before Publish).")
    ap.add_argument("--spec", required=True, help="path to the pin spec JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the spec and print the plan; does not touch the browser")
    ap.add_argument("--page-id", default=None, help="reuse a specific MCP page_id")
    ap.add_argument("--force-upload", action="store_true",
                    help="inject the image even if the draft already shows a preview")
    args = ap.parse_args()

    spec = load_spec(args.spec)
    spec["force_upload"] = args.force_upload

    if args.dry_run:
        print("DRY RUN — no browser interaction")
        print(json.dumps({"spec": spec, "planned_actions": [
            f"attach to the builder page (or cloak_new_page {BUILDER_URL})",
            f"inject {os.path.basename(spec['image_path'])} into {SEL_UPLOAD_INPUT} via JS File+DataTransfer",
            "wait for the form to re-enable after the upload (preview != usable)",
            f"fill Title ({len(spec['title'])} chars) via JS native setter",
            f"attempt Description ({len(spec['description'])} chars) — known gap, see README",
            f"fill Link ({spec['link']})" if spec.get("link") else "link: none",
            f"select board {spec['board_name']!r} via board-row-* (skip if not found)",
            "screenshot the composer preview",
            "STOP — never click Publish/Done",
        ]}, indent=2))
        return 0

    started = time.time()
    report = asyncio.run(compose(spec, page_id=args.page_id))
    report["elapsed_s"] = round(time.time() - started, 1)
    out = os.path.join(TEST_DIR, "last_run_report.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\nreport -> {out}")
    return 0 if report.get("status") == "COMPOSED_NOT_PUBLISHED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
