#!/usr/bin/env python3
"""Inspect the description container after the paste activation, then write the real
description through whatever editor mounted."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()
DESC = ("Small studio apartment? These 7 renter-friendly habits make a tiny space feel twice "
        "as big - no drilling, no damage-deposit drama.")

DUMP = r"""(() => {
  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
  const inner = Array.from(document.querySelectorAll('[data-test-id="storyboard-description-field-container"] *'))
    .map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'), id: e.id || null,
                role: e.getAttribute('role'), ce: e.getAttribute('contenteditable'),
                cls: typeof e.className === 'string' ? e.className.slice(0,58) : null,
                txt: (e.innerText||'').slice(0,50), vis: e.offsetParent !== null,
                html: (e.outerHTML||'').slice(0,300)}));
  return JSON.stringify({containerHTML: c ? c.innerHTML.slice(0, 900) : null,
    containerText: c ? (c.innerText||'').slice(0,200) : null,
    descendants: inner,
    globalEditables: Array.from(document.querySelectorAll('[contenteditable="true"]'))
      .map(e => ({tag: e.TagName || e.tagName, testid: e.getAttribute('data-test-id'),
                  cls: typeof e.className === 'string' ? e.className.slice(0,50) : null}))});
})()"""


async def main():
    async with AsyncRig() as rig:
        r = await rig.evaluate_json(pid, DUMP)
        print("CONTAINER:", json.dumps(r, indent=2)[:3500])

        log("== write the description into the mounted editor ==")
        for mech in ("ce-insertText", "ce-textContent", "role-textbox"):
            js = {
                "ce-insertText": r"""(() => {
                  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
                  const ce = c.querySelector('[contenteditable="true"]') || c.querySelector('[contenteditable]');
                  if (!ce) return JSON.stringify({ok:false, err:'no ce'});
                  ce.focus();
                  const sel = window.getSelection(); sel.removeAllRanges();
                  const rg = document.createRange(); rg.selectNodeContents(ce); sel.addRange(rg);
                  document.execCommand('insertText', false, %s);
                  ce.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:%s}));
                  return JSON.stringify({ok:true, text:(ce.innerText||'').slice(0,80)});
                })()""" % (json.dumps(DESC), json.dumps(DESC)),
                "ce-textContent": r"""(() => {
                  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
                  const ce = c.querySelector('[contenteditable="true"]') || c.querySelector('[contenteditable]');
                  if (!ce) return JSON.stringify({ok:false, err:'no ce'});
                  ce.focus(); ce.textContent = %s;
                  ce.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:%s}));
                  return JSON.stringify({ok:true, text:(ce.innerText||'').slice(0,80)});
                })()""" % (json.dumps(DESC), json.dumps(DESC)),
                "role-textbox": r"""(() => {
                  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
                  const tb = c.querySelector('[role="textbox"]');
                  if (!tb) return JSON.stringify({ok:false, err:'no textbox'});
                  tb.focus();
                  if (tb.isContentEditable) { document.execCommand('insertText', false, %s); }
                  else { tb.textContent = %s; }
                  tb.dispatchEvent(new InputEvent('input', {bubbles:true, data:%s}));
                  return JSON.stringify({ok:true, text:(tb.innerText||tb.textContent||'').slice(0,80)});
                })()""" % (json.dumps(DESC), json.dumps(DESC), json.dumps(DESC)),
            }[mech]
            r2 = await rig.evaluate_json(pid, js)
            log(f"  {mech}: {json.dumps(r2)[:260]}")
            await asyncio.sleep(3)
            chk = await rig.evaluate_json(pid, r"""(() => {
              const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
              return JSON.stringify({text: c ? (c.innerText||'').slice(0,180) : null,
                                     len: c ? c.innerHTML.length : null});
            })()""")
            log(f"  -> container: {json.dumps(chk)[:300]}")
            if DESC[:40] in (chk.get("text") or ""):
                log("  DESCRIPTION WRITTEN")
                break
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
