#!/usr/bin/env python3
"""Diagnose why Title/Description won't accept text. Same open composer, no reload.

Stage A: click the Title ref, print the RAW MCP response, inspect document.activeElement
Stage B: type a short marker via cloak_type, print RAW response, re-read the value
Stage C: JS native-setter path (React value-tracker bypass) + persistence re-check
Stage D: description editor discovery — what the container actually mounts
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()

ACTIVE_JS = r"""(() => {
  const a = document.activeElement;
  const d = (e) => e ? {tag: e.tagName, id: e.id || null, testid: e.getAttribute('data-test-id'),
                         aria: e.getAttribute('aria-label'), ce: e.isContentEditable,
                         val: (e.value !== undefined ? String(e.value).slice(0,40) : null)} : null;
  const t = document.querySelector('#storyboard-selector-title');
  return JSON.stringify({active: d(a), titleValue: t ? t.value : null,
                         titleDisabled: t ? !!t.disabled : null,
                         titleRect: t ? (r => [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)])(t.getBoundingClientRect()) : null,
                         titleReadonly: t ? t.readOnly : null});
})()"""

DESC_JS = r"""(() => {
  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
  const ce = Array.from(document.querySelectorAll('[contenteditable]')).map(e => ({
    testid: e.getAttribute('data-test-id'), ce: e.getAttribute('contenteditable'),
    cls: typeof e.className === 'string' ? e.className.slice(0, 60) : null,
    inner: (e.innerText || '').slice(0, 60)}));
  const tas = Array.from(document.querySelectorAll('textarea')).map(e => ({
    testid: e.getAttribute('data-test-id'), id: e.id, ph: e.placeholder,
    vis: e.offsetParent !== null, cls: typeof e.className === 'string' ? e.className.slice(0, 50) : null}));
  return JSON.stringify({descContainerText: c ? (c.innerText||'').slice(0,120) : null,
                         contentEditables: ce, textareas: tas,
                         editorWithMentions: !!document.querySelector('[data-test-id="editor-with-mentions"]'),
                         commentEditor: !!document.querySelector('#mweb-comment-editor-container'),
                         commentEditorIds: Array.from(document.querySelectorAll('[id*=comment-editor]')).map(e => e.id).slice(0,5),
                         composerTextareas: Array.from(document.querySelectorAll('textarea')).length});
})()"""


async def main():
    async with AsyncRig() as rig:
        log("== state before ==")
        print(json.dumps(await rig.evaluate_json(pid, ACTIVE_JS), indent=2))

        snap = await rig.snapshot(pid)
        try:
            snap = json.loads(snap).get("snapshot", "")
        except Exception:
            pass
        ref = None
        for ln in snap.splitlines():
            if re.search(r'input\[text\] "Title"', ln):
                m = re.search(r"\[(@e\d+)\]", ln)
                if m:
                    ref = m.group(1)
                    log("title ref:", ref, "::", ln.strip())
                    break

        log("== STAGE A: cloak_click title ==")
        r = await rig.call("cloak_click", {"page_id": pid, "ref": ref}, raw=True)
        print("RAW CLICK:", str(r)[:900])
        await asyncio.sleep(2)
        print(json.dumps(await rig.evaluate_json(pid, ACTIVE_JS), indent=2))

        log("== STAGE B: cloak_type 12 chars ==")
        r = await rig.call("cloak_type", {"page_id": pid, "ref": ref, "text": "DIAGNOSTIC1", "clear": True}, raw=True)
        print("RAW TYPE:", str(r)[:900])
        await asyncio.sleep(2)
        print(json.dumps(await rig.evaluate_json(pid, ACTIVE_JS), indent=2))

        log("== STAGE C: JS native setter ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const el = document.querySelector('#storyboard-selector-title');
          if (!el) return JSON.stringify({ok:false});
          el.focus();
          const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          set.call(el, 'JSSETTER_TITLE');
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
          return JSON.stringify({ok:true, immediate: el.value});
        })()""")
        print("JS set:", json.dumps(r))
        await asyncio.sleep(6)
        print(json.dumps(await rig.evaluate_json(pid, ACTIVE_JS), indent=2))

        log("== STAGE D: description editor anatomy ==")
        print(json.dumps(await rig.evaluate_json(pid, DESC_JS), indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
