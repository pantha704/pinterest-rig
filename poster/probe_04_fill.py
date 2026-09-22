#!/usr/bin/env python3
"""STAGE 2 of the single composer run — the real test.

1. Inject the sample PNG into #storyboard-upload-input via a JS-built File + DataTransfer
   (approach 1). No file-upload MCP tool exists, so this is the whole mechanism.
2. Wait for the image to render in the composer; screenshot.
3. Fill Title, Description, Link; select the board from its dropdown; screenshot.
4. STOP. Never touch a Publish/Done control.

Page is the one created in stage 1 — no reload anywhere, so the composer session is preserved.
"""
import asyncio
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test")
SPEC_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "specs", "example-sage-bold-title.json")
ARTS = "/home/ubuntu/.cloakbrowser/artifacts"

STATE_JS = r"""(() => {
  const g = (s) => document.querySelector(s);
  const imgs = Array.from(document.querySelectorAll('img')).map(i => ({
    src: (i.currentSrc || i.src || '').slice(0, 80), w: i.naturalWidth, h: i.naturalHeight,
    testid: i.getAttribute('data-test-id'), alt: i.getAttribute('alt'),
    box: [Math.round(i.getBoundingClientRect().width), Math.round(i.getBoundingClientRect().height)] }));
  const btns = Array.from(document.querySelectorAll('button,[role=button]')).map(e => ({
    testid: e.getAttribute('data-test-id'),
    txt: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,40),
    aria: e.getAttribute('aria-label'), disabled: e.disabled === true }))
    .filter(b => b.txt || b.aria || b.testid);
  return JSON.stringify({
    url: location.href,
    fileInputCount: document.querySelectorAll('input[type=file]').length,
    fileInputFiles: (() => { const f = g('#storyboard-upload-input'); return f && f.files ? Array.from(f.files).map(x => x.name + ':' + x.size + ':' + x.type) : null; })(),
    bigImages: imgs.filter(i => i.w > 200 || i.h > 200).slice(0, 6),
    titleValue: (g('#storyboard-selector-title') || {}).value ?? null,
    linkValue: (g('#WebsiteField') || {}).value ?? null,
    descriptionText: (g('[data-test-id="storyboard-description-field-container"]') || {}).innerText ?? null,
    boardText: (g('[data-test-id="board-dropdown-select-button"]') || {}).innerText ?? null,
    publishLike: btns.filter(b => /publish|^done$|save draft|post\b/i.test((b.txt||'') + ' ' + (b.aria||''))),
    allButtons: btns,
    bodyHas: (document.body.innerText || '').slice(0, 900),
  });
})()"""


async def state(rig, pid, tag):
    p = await rig.evaluate_json(pid, STATE_JS)
    log(f"--- STATE {tag} ---")
    log("  fileInputFiles:", json.dumps(p.get("fileInputFiles")))
    log("  bigImages:", json.dumps(p.get("bigImages"))[:400])
    log("  title:", json.dumps(p.get("titleValue")), "link:", json.dumps(p.get("linkValue")))
    log("  desc:", json.dumps((p.get("descriptionText") or "")[:160]))
    log("  board:", json.dumps((p.get("boardText") or "")[:80]))
    log("  publishLike:", json.dumps(p.get("publishLike")))
    return p


def injection_js(b64, filename):
    """Approach 1: JS File from base64 + DataTransfer + change event on the visible file input."""
    return r"""(() => {
  const B64 = "%s";
  const NAME = "%s";
  try {
    const bin = atob(B64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const file = new File([u8], NAME, { type: 'image/png', lastModified: Date.now() });
    const dt = new DataTransfer();
    dt.items.add(file);
    const input = document.querySelector('#storyboard-upload-input')
      || document.querySelector('input[type=file]');
    if (!input) return JSON.stringify({ok: false, err: 'no file input'});
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'files');
    // React-controlled inputs: write through the native setter so the tracker sees a change.
    if (desc && desc.set) { desc.set.call(input, dt.files); } else { input.files = dt.files; }
    input.dispatchEvent(new Event('input',  { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return JSON.stringify({
      ok: true,
      injected: Array.from(input.files).map(f => f.name + ':' + f.size + ':' + f.type),
      dtFiles: dt.files.length,
    });
  } catch (e) {
    return JSON.stringify({ok: false, err: String(e && e.message || e)});
  }
})()""" % (b64, filename)


async def main():
    spec = json.load(open(SPEC_PATH))
    img = spec["image_path"]
    b64 = base64.b64encode(open(img, "rb").read()).decode()
    filename = os.path.basename(img)
    log("spec:", SPEC_PATH, "| image:", img, f"({len(b64)} b64 chars)")

    pid = open(os.path.join(TEST, "page_id.txt")).read().strip()
    log("page:", pid, "| mode:", "DRY-RUN" if os.environ.get("POSTER_DRY") else "LIVE")

    async with AsyncRig() as rig:
        await state(rig, pid, "before-upload")

        log("---- APPROACH 1: File + DataTransfer + change ----")
        r = await rig.evaluate_json(pid, injection_js(b64, filename))
        log("inject result:", json.dumps(r)[:400])

        await asyncio.sleep(10)
        s = await rig.screenshot(pid)
        log("shot after upload:", s[:200])
        p = await state(rig, pid, "after-upload")
        ok = bool(p.get("bigImages"))
        log("UPLOAD RENDERED:", ok)

        if not ok:
            log("!! upload injection did not render an image — stopping for diagnosis")
            return 3

        # ---- Title ----
        await rig.call("cloak_click", {"page_id": pid, "ref": "?"}) if False else None
        r = await rig.evaluate_json(pid, r"""(() => {
          const el = document.querySelector('#storyboard-selector-title');
          if (!el) return JSON.stringify({ok:false});
          el.focus();
          const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
          d.set.call(el, %s);
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
          el.dispatchEvent(new Event('blur', {bubbles:true}));
          return JSON.stringify({ok:true, value: el.value});
        })()""" % json.dumps(spec["title"]))
        log("title:", json.dumps(r)[:300])

        # ---- Description (rich-text editor container) ----
        desc_js = r"""(() => {
          const cont = document.querySelector('[data-test-id="storyboard-description-field-container"]')
                    || document.querySelector('[data-test-id="comment-editor-container"]');
          if (!cont) return JSON.stringify({ok:false, err:'no desc container'});
          const ce = cont.querySelector('[contenteditable="true"]');
          const target = ce || cont.querySelector('[role=textbox]') || cont.querySelector('[role=button]');
          if (!target) return JSON.stringify({ok:false, err:'no desc target'});
          if (target.isContentEditable) {
            target.focus();
            target.innerHTML = '';
            document.execCommand('insertText', false, %s);
            if (!target.innerText.trim()) { target.innerHTML = '<span>%s</span>'; }
            target.dispatchEvent(new InputEvent('input', {bubbles:true, data:%s}));
          } else {
            target.click();
          }
          return JSON.stringify({ok:true, mode: target.isContentEditable ? 'ce' : 'clicked-role-button',
                                 text: (cont.innerText||'').slice(0,120)});
        })()""" % (json.dumps(spec["description"]), spec["description"], json.dumps(spec["description"]))
        r = await rig.evaluate_json(pid, desc_js)
        log("desc attempt A:", json.dumps(r)[:400])
        await asyncio.sleep(2)
        # if the editor mounted after activating it, write through it
        r2 = await rig.evaluate_json(pid, r"""(() => {
          const ce = document.querySelector('[data-test-id="editor-with-mentions"], [contenteditable="true"][role=textbox], [contenteditable="true"]');
          if (!ce) return JSON.stringify({ok:false, err:'still no contenteditable'});
          ce.focus();
          if (!ce.innerText.includes(%s)) {
            document.execCommand('insertText', false, %s);
          }
          ce.dispatchEvent(new InputEvent('input', {bubbles:true}));
          return JSON.stringify({ok:true, text:(ce.innerText||'').slice(0,160), testid: ce.getAttribute('data-test-id')});
        })()""" % (json.dumps(spec["description"][:20]), json.dumps(spec["description"])))
        log("desc attempt B:", json.dumps(r2)[:400])

        # ---- Link (optional) ----
        if spec.get("link"):
            r = await rig.evaluate_json(pid, r"""(() => {
              const el = document.querySelector('#WebsiteField');
              if (!el) return JSON.stringify({ok:false});
              el.focus();
              const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
              d.set.call(el, %s);
              el.dispatchEvent(new Event('input', {bubbles:true}));
              el.dispatchEvent(new Event('change', {bubbles:true}));
              return JSON.stringify({ok:true, value: el.value});
            })()""" % json.dumps(spec["link"]))
            log("link:", json.dumps(r)[:300])

        s = await rig.screenshot(pid)
        log("shot after fill:", s[:200])
        p = await state(rig, pid, "after-fill")
        with open(os.path.join(TEST, "04_after_fill_state.json"), "w") as f:
            json.dump(p, f, indent=2)
        log("FINAL publishLike:", json.dumps(p.get("publishLike")))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
