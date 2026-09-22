#!/usr/bin/env python3
"""Description editor anatomy: find the real editable target.
The container is a Gestalt role=button that opens the editor; .click() alone didn't mount it,
so try the full pointer/mouse sequence + focus, and hunt for the mentions editor."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()

ANATOMY = r"""(() => {
  const d = (e) => e ? {tag: e.tagName, testid: e.getAttribute('data-test-id'), id: e.id || null,
    role: e.getAttribute('role'), ce: e.getAttribute('contenteditable'),
    aria: (e.getAttribute('aria-label')||'').slice(0,60), cls: (typeof e.className==='string'?e.className.slice(0,50):''),
    vis: e.offsetParent !== null, html: (e.outerHTML||'').slice(0, 420)} : null;
  const tb = document.querySelector('[role="textbox"]');
  const chain = []; let n = tb; let i = 0;
  while (n && i < 7) { chain.push(d(n)); n = n.parentElement; i++; }
  // hunt for anything referencing the mentions/comment editor
  const hits = [];
  document.querySelectorAll('*').forEach(e => {
    for (const a of e.attributes || []) {
      if (/comment-editor|mentions/i.test(a.name + '=' + a.value)) {
        hits.push({tag: e.tagName, attr: a.name, val: a.value.slice(0, 90)});
      }
    }
  });
  return JSON.stringify({textbox: d(tb), chain: chain, commentEditorHits: hits.slice(0, 12),
    descContainer: d(document.querySelector('[data-test-id="storyboard-description-field-container"]')),
    allEditable: Array.from(document.querySelectorAll('[contenteditable],[role="textbox"],textarea'))
      .map(e => d(e))});
})()"""


async def main():
    async with AsyncRig() as rig:
        log("== before ==")
        r = await rig.evaluate_json(pid, ANATOMY)
        print(json.dumps(r, indent=2)[:4000])

        log("== dispatch full pointer/mouse sequence on the description control ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          if (!c) return JSON.stringify({ok:false});
          const target = c.querySelector('[role="button"]') || c;
          const opts = {bubbles: true, cancelable: true, composed: true, view: window, button: 0, buttons: 1};
          for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
            const Ctor = t.startsWith('pointer') ? PointerEvent : MouseEvent;
            target.dispatchEvent(new Ctor(t, opts));
          }
          target.setAttribute('tabindex', '0');
          target.focus();
          return JSON.stringify({ok:true, active: document.activeElement ? (document.activeElement.getAttribute('data-test-id') || document.activeElement.tagName) : null});
        })()""")
        print("pointer seq:", json.dumps(r))
        await asyncio.sleep(5)
        r = await rig.evaluate_json(pid, ANATOMY)
        tb = r.get("textbox") or {}
        log("after pointer seq -> textbox:", json.dumps({k: tb.get(k) for k in
            ("tag", "testid", "id", "role", "ce", "vis", "html")})[:600])
        log("allEditable:", json.dumps(r.get("allEditable"))[:900])

        log("== try writing into the role=textbox directly ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const tb = document.querySelector('[role="textbox"]');
          if (!tb) return JSON.stringify({ok:false, err:'none'});
          tb.focus();
          if (tb.isContentEditable) { document.execCommand('insertText', false, 'PROBE_TEXTBOX'); }
          else { tb.textContent = 'PROBE_TEXTBOX'; }
          tb.dispatchEvent(new InputEvent('input', {bubbles:true, data:'PROBE_TEXTBOX'}));
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          return JSON.stringify({ok:true, tbText:(tb.innerText||tb.textContent||'').slice(0,60),
            containerNow: c ? (c.innerText||'').slice(0,80) : null, isCE: tb.isContentEditable});
        })()""")
        print("write attempt:", json.dumps(r))
        await asyncio.sleep(3)
        r = await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          return JSON.stringify({containerText: c ? (c.innerText||'').slice(0,120) : null,
            containerHTML: c ? c.innerHTML.slice(0,600) : null});
        })()""")
        print("after write:", json.dumps(r, indent=2)[:1200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
