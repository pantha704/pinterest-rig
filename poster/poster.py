#!/usr/bin/env python3
"""
poster.py — MCP-driven Pinterest pin composer for the CloakBrowser rig (127.0.0.1:8933).

Given a JSON pin spec, drives Pinterest's *web* pin builder to COMPOSE a pin:
opens the composer, injects the image (there is no file-upload MCP tool, so the image
is injected as a JS File object through a DataTransfer), fills Title / Description /
Link, selects the target board — then STOPS.

SAFETY CONTRACT (hard-coded, not configurable):
  * This tool never clicks Publish / Done / Post / Save (i.e. never creates a live
    public pin). `assert_not_publish_control()` runs before every click.
  * The composer is Pinterest's drafts-backed "storyboard" builder: the in-progress
    pin is auto-saved as a DRAFT by Pinterest itself, which is the preferred
    "save as draft" behaviour.
  * No navigation is performed if the page is already on the builder URL (so a run
    never re-opens a fresh composer unnecessarily).

Usage:
  poster.py --spec specs/example.json            # compose, stop before Publish
  poster.py --spec specs/example.json --dry-run  # validate spec + print the plan, no browser
  poster.py --spec specs/example.json --page-id page_xxxx --force-upload

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
from mcp_client import ARTIFACTS, AsyncRig, MCPError, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(HERE, "test")

BUILDER_URL = "https://in.pinterest.com/pin-creation-tool/"
UPLOAD_INPUT = "#storyboard-upload-input"

# ---------------------------------------------------------------- safety guard ---
# Any control whose accessible text matches this is off-limits. Publish/Done/Post
# create a live public pin; "Save" is included because on some Pinterest surfaces the
# primary submit button is labelled "Save" (save-to-board == publish).
FORBIDDEN_CLICK = re.compile(
    r"\b(publish|done|post|save|submit|create pin)\b", re.IGNORECASE)


def assert_not_publish_control(label: str) -> None:
    """Refuse to click anything that could publish the pin."""
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
        # relative paths resolve against the spec file's directory, then the rig root
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
COMPOSER_READY_JS = r"""(() => {
  const g = (s) => document.querySelector(s);
  const imgs = Array.from(document.querySelectorAll('img')).map(i => ({
    src: (i.currentSrc || i.src || '').slice(0, 90), w: i.naturalWidth, h: i.naturalHeight,
    box: [Math.round(i.getBoundingClientRect().width), Math.round(i.getBoundingClientRect().height)] }));
  const boardBtn = g('[data-test-id="board-dropdown-select-button"]');
  const board = boardBtn ? {text: (boardBtn.innerText||'').replace(/\s+/g,' ').trim(),
                            disabled: boardBtn.closest('button,[role=button]') ? !!boardBtn.closest('button,[role=button]').disabled : null} : null;
  const title = g('#storyboard-selector-title');
  const link = g('#WebsiteField');
  const descCont = g('[data-test-id="storyboard-description-field-container"]');
  const descEditable = document.querySelector('[data-test-id="editor-with-mentions"],[contenteditable="true"][role="textbox"]');
  return JSON.stringify({
    url: location.href,
    composerReady: !!g('#storyboard-selector-title') && !!g('[data-test-id="storyboard-selector-board"]'),
    uploadInput: !!g('#storyboard-upload-input'),
    uploadInputFiles: (() => { const f = g('#storyboard-upload-input'); return f && f.files ? f.files.length : null; })(),
    previewImages: imgs.filter(i => i.w > 200 && i.h > 200).slice(0, 5),
    titleValue: title ? title.value : null,
    titleDisabled: title ? !!title.disabled : null,
    linkValue: link ? link.value : null,
    linkDisabled: link ? !!link.disabled : null,
    descText: descCont ? (descCont.innerText || '').replace(/\s+/g,' ').trim().slice(0, 200) : null,
    descEditable: !!descEditable,
    board: board,
    draftsSidebar: !!g('[data-test-id="storyboard-drafts-sidebar"]'),
    publishControls: Array.from(document.querySelectorAll('button,[role=button],a[role=button]'))
      .map(e => ({testid: e.getAttribute('data-test-id'),
                  txt: (e.innerText || '').replace(/\s+/g,' ').trim().slice(0, 30),
                  aria: (e.getAttribute('aria-label') || '').slice(0, 40),
                  disabled: e.disabled === true}))
      .filter(b => /(publish|\bdone\b|\bpost\b|\bsave\b)/i.test((b.txt || '') + ' ' + (b.aria || ''))),
    uploading: /upload(ing)?\.\.\.|processing|preparing your/i.test(document.body ? document.body.innerText : ''),
    savingStatus: (() => { const el = document.querySelector('[data-test-id^="saving-status"]'); return el ? (el.innerText || '').trim().slice(0, 60) : null; })(),
    bodyHasCaptcha: /captcha|verify you are human|unusual traffic|blocked/i.test(document.body ? document.body.innerText : ''),
  });
})()"""

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
    nativeSet.call(input, dt.files);          // bypass React's value tracker
    if (TECHNIQUE === 'change') {
      input.dispatchEvent(new Event('input', {bubbles: true}));
      input.dispatchEvent(new Event('change', {bubbles: true}));
    } else if (TECHNIQUE === 'drop') {
      for (const type of ['dragenter', 'dragover', 'drop']) {
        const ev = new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt});
        input.dispatchEvent(ev);
        const zone = input.closest('[data-test-id="drag-behavior-container"]') || input.parentElement;
        if (zone) zone.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: dt}));
      }
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }
    return JSON.stringify({ok: true, technique: TECHNIQUE,
      files: Array.from(input.files).map(f => f.name + ':' + f.size + ':' + f.type)});
  } catch (e) { return JSON.stringify({ok: false, err: String((e && e.message) || e)}); }
})()"""

# Installed before injection so the upload's API call is observable (no network tool exists).
NETLOG_JS = r"""(() => {
  if (window.__netlog) return 'already';
  window.__netlog = [];
  const origFetch = window.fetch;
  window.fetch = function (...a) {
    try {
      const url = (typeof a[0] === 'string') ? a[0] : (a[0] && a[0].url);
      window.__netlog.push({t: Date.now(), m: 'fetch', url: String(url).slice(0, 160)});
    } catch (e) {}
    return origFetch.apply(this, a);
  };
  const O = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u, ...r) {
    try { window.__netlog.push({t: Date.now(), m: m, url: String(u).slice(0, 160)}); } catch (e) {}
    return O.call(this, m, u, ...r);
  };
  return 'installed';
})()"""

# ------------------------------------------------------------------ the driver ----
class Composer:
    def __init__(self, rig: AsyncRig, page_id: str, spec: dict, shots: list):
        self.rig, self.pid, self.spec, self.shots = rig, page_id, spec, shots

    async def read(self) -> dict:
        s = await self.rig.evaluate_json(self.pid, COMPOSER_READY_JS)
        if s.get("bodyHasCaptcha"):
            raise SystemExit("STOP: captcha / 'verify you are human' / blocked text detected on the "
                             "composer. No retries. Investigate manually.")
        return s

    async def wait_fields_enabled(self, timeout=150):
        """THE critical gate. The preview <img> (blob: URL) appears the instant the File is
        injected, but Pinterest only re-enables Title/Description/Link/Board once its own
        upload+processing finishes. Filling before that silently no-ops, so wait for the
        form to be genuinely enabled (and report the draft save state seen on the way)."""
        last = None
        for i in range(max(1, timeout // 5)):
            st = await self.read()
            last = st
            title_ok = st.get("titleDisabled") is False
            board_ok = (st.get("board") or {}).get("disabled") is False
            if title_ok and board_ok and st.get("previewImages"):
                log(f"  fields enabled after ~{(i + 1) * 5}s "
                    f"(savingStatus={st.get('savingStatus')!r}, uploading={st.get('uploading')})")
                return st
            if i % 4 == 3:
                log(f"  waiting for the form to enable… {i * 5}s "
                    f"(titleDisabled={st.get('titleDisabled')}, boardDisabled={(st.get('board') or {}).get('disabled')}, "
                    f"preview={len(st.get('previewImages') or [])})")
            await asyncio.sleep(5)
        raise SystemExit("STOP: composer form never enabled after upload — leaving the draft as-is")

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
        else:
            log(f"  screenshot (artifact path unresolved: {r[:120]})")
        self.shots.append(dst)
        return dst

    # -- refs from the accessibility snapshot ------------------------------------
    async def snapshot_lines(self):
        raw = await self.rig.snapshot(self.pid)
        try:
            return json.loads(raw).get("snapshot", "")
        except Exception:
            return raw

    async def ref_matching(self, pattern: str, exclude_disabled: bool = False):
        lines = await self.snapshot_lines()
        rx = re.compile(pattern)
        for line in lines.splitlines():
            if rx.search(line) and (not exclude_disabled or "[disabled]" not in line):
                m = re.search(r"\[(@e\d+)\]", line)
                if m:
                    return m.group(1), line.strip()
        return None, None

    async def click_ref(self, ref: str, label: str):
        assert_not_publish_control(label)
        log(f"  cloak_click {ref} :: {label!r}")
        return await self.rig.call("cloak_click", {"page_id": self.pid, "ref": ref})

    async def type_ref(self, ref: str, text: str, label: str):
        assert_not_publish_control(label)
        log(f"  cloak_type {ref} ({len(text)} chars)")
        return await self.rig.call("cloak_type",
                                   {"page_id": self.pid, "ref": ref, "text": text, "clear": True})

    # -- steps -------------------------------------------------------------------
    async def step_open_composer(self):
        pages = (await self.rig.list_pages()) or {}
        plist = pages.get("pages", pages if isinstance(pages, list) else [])
        cur = next((p for p in plist if p.get("page_id") == self.pid), None)
        cur_url = (cur or {}).get("url", "")
        if "pin-creation-tool" in cur_url or "pin-builder" in cur_url:
            log("  already on the builder URL — no navigation (avoids a second composer visit)")
        else:
            log(f"  navigating to {BUILDER_URL}")
            await self.rig.navigate(self.pid, BUILDER_URL)
        # poll for the composer shell
        for i in range(40):
            await asyncio.sleep(3)
            st = await self.read()
            if st.get("composerReady"):
                log(f"  composer ready after ~{(i + 1) * 3}s")
                return st
        raise SystemExit("STOP: composer did not render within 120s")

    async def step_upload(self):
        st = await self.read()
        if st.get("titleValue") is None:
            raise SystemExit("STOP: composer lost (#storyboard-selector-title missing)")
        already = bool(st.get("previewImages")) or (st.get("uploadInputFiles") or 0) > 0
        if already and not self.spec.get("force_upload"):
            log(f"  image already present in this draft ({len(st.get('previewImages') or [])} preview img) "
                "— skipping injection to keep the visit count/idempotent re-runs clean")
            return st

        img = self.spec["image_path"]
        ext = os.path.splitext(img)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
                "tiff": "image/tiff"}.get(ext, "image/png")
        b64 = base64.b64encode(open(img, "rb").read()).decode()
        name = os.path.basename(img)
        log(f"  injecting {name} ({os.path.getsize(img) / 1024:.0f} KB) as image/{ext}")

        log("  netlog:", await self.rig.evaluate(self.pid, NETLOG_JS))

        # Approach 1 (primary): native `files` setter via DataTransfer + input/change events.
        # Approach 2: same File, but dispatched as a drag-and-drop sequence.
        # Approach 3: pull the data: URL back out of the page and retry on a re-queried
        #             input (covers React remounting the node mid-flight).
        for attempt, technique in enumerate(("change", "drop", "change"), start=1):
            js = INJECT_JS % {"b64": b64, "name": name, "mime": mime, "technique": technique}
            res = await self.rig.evaluate_json(self.pid, js)
            log(f"  approach {attempt} ({technique}): {json.dumps(res)[:220]}")
            if not res.get("ok"):
                if attempt == 3:
                    return {"uploaded": False, "error": res.get("err")}
                continue
            for _ in range(10):                      # poll up to ~30s for the preview to render
                await asyncio.sleep(3)
                st = await self.read()
                if st.get("previewImages"):
                    log(f"  UPLOAD OK — preview rendered: {json.dumps(st['previewImages'])[:200]}")
                    net = await self.rig.evaluate_json(
                        self.pid, "(()=>JSON.stringify((window.__netlog||[]).slice(-12)))()")
                    self.netlog = net
                    # preview != usable: gate on the form actually being enabled
                    return await self.wait_fields_enabled()
            log(f"  approach {attempt} ({technique}) did not render a preview")
            if attempt >= 3:
                return {"uploaded": False, "error": "3 approaches tried, no preview rendered"}
        return {"uploaded": False, "error": "exhausted"}

    async def step_fill_fields(self):
        st = await self.wait_fields_enabled()   # never type into a disabled form
        # Title — real typing through the MCP ref (React-safe), JS setter as fallback.
        if (st.get("titleValue") or "").strip() != self.spec["title"].strip():
            ref, line = await self.ref_matching(r"input\[text\] \"Title\"")
            if ref:
                await self.click_ref(ref, line)
                await self.type_ref(ref, self.spec["title"], line)
            else:
                log("  title ref not found — JS fallback")
                await self.rig.evaluate_json(self.pid, r"""(() => {
                  const el = document.querySelector('#storyboard-selector-title'); if (!el) return '{}';
                  el.focus();
                  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el, %s);
                  el.dispatchEvent(new Event('input',{bubbles:true}));
                  el.dispatchEvent(new Event('change',{bubbles:true}));
                  return JSON.stringify({value: el.value});
                })()""" % json.dumps(self.spec["title"]))
            await asyncio.sleep(1)

        # Description — rich-text editor (#mweb-comment-editor-container). Activate it with a
        # real click, then write the text; verify and fall back across mechanisms.
        if self.spec["description"]:
            want = self.spec["description"].strip()
            st = await self.read()
            if want not in (st.get("descText") or ""):
                ref, line = await self.ref_matching(r"button \"Description", exclude_disabled=True)
                if ref:
                    await self.click_ref(ref, "description-field-activate")
                    await asyncio.sleep(2)
                self.rig_result = None
                # mechanism 1: JS insertText straight into the mounted contenteditable
                r1 = await self.rig.evaluate_json(self.pid, r"""(() => {
                  const ce = document.querySelector('[data-test-id="editor-with-mentions"][contenteditable="true"]')
                          || document.querySelector('[contenteditable="true"][role="textbox"]')
                          || document.querySelector('[contenteditable="true"]');
                  if (!ce) return JSON.stringify({ok:false, err:'no contenteditable'});
                  ce.focus();
                  const sel = window.getSelection();
                  sel.removeAllRanges();
                  const range = document.createRange();
                  range.selectNodeContents(ce);
                  sel.addRange(range);
                  document.execCommand('insertText', false, %s);
                  if (!(ce.innerText || '').trim()) { ce.textContent = %s; }
                  ce.dispatchEvent(new InputEvent('input', {bubbles: true, data: %s}));
                  return JSON.stringify({ok:true, testid: ce.getAttribute('data-test-id'),
                                         text: (ce.innerText || '').slice(0, 120)});
                })()""" % (json.dumps(want), json.dumps(want), json.dumps(want)))
                log(f"  desc via JS insertText: {json.dumps(r1)[:220]}")
                await asyncio.sleep(2)
                st = await self.read()
                if want not in (st.get("descText") or ""):
                    # mechanism 2: real keyboard typing into the editor's ref
                    eref, eline = None, None
                    for pat in (r"\"Description", r"\"Describe your Pin", r"(textbox|contenteditable)"):
                        cand, cline = await self.ref_matching(pat, exclude_disabled=True)
                        if cand and "search" not in (cline or "").lower() \
                                and "tag" not in (cline or "").lower() \
                                and "Title" not in (cline or ""):
                            eref, eline = cand, cline
                            break
                    if eref:
                        await self.click_ref(eref, "description-editor")
                        await self.type_ref(eref, want, "description-editor")
                        await asyncio.sleep(2)
                        st = await self.read()
                self.desc_mechanism = ("js-insertText" if want in (st.get("descText") or "")
                                       else "FAILED")
                log(f"  description mechanism: {self.desc_mechanism} -> {(st.get('descText') or '')[:80]!r}")
            await asyncio.sleep(1)

        # Link (optional)
        if self.spec.get("link"):
            st = await self.read()
            if (st.get("linkValue") or "").strip() != self.spec["link"].strip():
                ref, line = await self.ref_matching(r"input\[url\] \"Link\"")
                if ref:
                    await self.click_ref(ref, line)
                    await self.type_ref(ref, self.spec["link"], line)
                else:
                    await self.rig.evaluate_json(self.pid, r"""(() => {
                      const el = document.querySelector('#WebsiteField'); if (!el) return '{}';
                      el.focus();
                      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el, %s);
                      el.dispatchEvent(new Event('input',{bubbles:true}));
                      el.dispatchEvent(new Event('change',{bubbles:true}));
                      return JSON.stringify({value: el.value});
                    })()""" % json.dumps(self.spec["link"]))
                await asyncio.sleep(1)
        return await self.read()

    async def step_select_board(self):
        """Open the board dropdown, capture the full inventory, then click the target board.

        Choosing a board is part of composing — it is not a publish control, so this is safe.
        The dropdown inventory is recorded so the README's selector map stays truthful even
        when the target board happens to already be selected.
        """
        st = await self.read()
        cur = re.sub(r"^Board\s*", "", (st.get("board") or {}).get("text") or "").strip()
        want = self.spec["board_name"].strip()
        ref, line = await self.ref_matching(r"button \"Board", exclude_disabled=True)
        if not ref:
            log("  board selector ref not found (field still disabled?) — board NOT changed")
            return st, {"current": cur, "inventory": [], "changed": False}
        await self.click_ref(ref, "board-dropdown-open")
        await asyncio.sleep(3)
        lines = await self.snapshot_lines()

        # The dropdown is a panel that mounts at the TOP of the accessibility tree: a
        # "Search through your boards" box, then one button per board, ending with
        # "Create board". Anchor on that search box so page chrome (Publish, etc.) can
        # never be mistaken for a board entry.
        inventory, target = [], None
        rows = lines.splitlines()
        start = next((i for i, ln in enumerate(rows)
                      if "search through your boards" in ln.lower()), None)
        if start is None:
            log("  board dropdown did not open (no 'Search through your boards' row) — Escape")
            await self.rig.call("cloak_press_key", {"page_id": self.pid, "key": "Escape"})
            return st, {"current": cur, "inventory": [], "changed": False}
        for ln in rows[start + 1:]:
            m = re.match(r'\s*\[(@e\d+)\]\s*button\s+"([^"]+)"', ln)
            if not m:
                break
            label = m.group(2).strip()
            inventory.append({"ref": m.group(1), "label": label})
            if label.lower() == want.lower() and target is None:
                target = (m.group(1), label)
        log(f"  board inventory ({len(inventory)}): {json.dumps(inventory)[:600]}")
        if not target:
            log(f"  board '{want}' not in the open dropdown — pressing Escape, leaving selection untouched")
            await self.rig.call("cloak_press_key", {"page_id": self.pid, "key": "Escape"})
            return st, {"current": cur, "inventory": inventory, "changed": False}
        await self.click_ref(target[0], f"board-select:{target[1]}")
        await asyncio.sleep(4)
        st2 = await self.read()
        now = re.sub(r"^Board\s*", "", (st2.get("board") or {}).get("text") or "").strip()
        log(f"  board now: {now!r} (was {cur!r})")
        return st2, {"current": now, "previous": cur, "inventory": inventory,
                     "changed": now.lower() != cur.lower()}


async def compose(spec: dict, page_id=None, dry_run=False) -> dict:
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
        report = {"page_id": pid, "spec": spec, "steps": {}, "screenshots": shots}

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
            report["notes"] = ("Navigation + composer verified. Image injection failed after 3 "
                               "approaches — this is the single remaining gap.")
            await drv.shoot("11_upload_failed.png")
            report["screenshots"] = shots
            return report
        await drv.shoot("11_image_uploaded.png")

        log("[3/5] fill title / description / link")
        st = await drv.step_fill_fields()
        report["steps"]["fields"] = {"title": st.get("titleValue"), "link": st.get("linkValue"),
                                     "description": (st.get("descText") or "")[:200],
                                     "descEditable": st.get("descEditable"),
                                     "desc_mechanism": getattr(drv, "desc_mechanism", None)}

        log("[4/5] select board")
        st, binfo = await drv.step_select_board()
        report["steps"]["board"] = binfo

        log("[5/5] final state + STOP (publish never clicked)")
        st = await drv.read()
        report["steps"]["final"] = {k: st.get(k) for k in
                                    ("url", "titleValue", "linkValue", "descText", "descEditable", "board")}
        await drv.shoot("12_fields_filled_composer_preview.png")
        report["screenshots"] = shots
        report["status"] = "COMPOSED_NOT_PUBLISHED"
        report["notes"] = ("Pin left composed in Pinterest's drafts-backed builder. Publish/Done was "
                           "never clicked, so no live public pin exists.")
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
        print(json.dumps({"spec": spec,
                          "planned_actions": [
                              f"attach to the builder page (or cloak_new_page {BUILDER_URL})",
                              f"inject {os.path.basename(spec['image_path'])} into {UPLOAD_INPUT} via JS File+DataTransfer",
                              f"fill Title ({len(spec['title'])} chars)",
                              f"fill Description ({len(spec['description'])} chars)",
                              f"fill Link ({spec['link']})" if spec.get("link") else "link: none",
                              f"select board {spec['board_name']!r} (skip if already selected)",
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
