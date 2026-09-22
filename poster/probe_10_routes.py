#!/usr/bin/env python3
"""Remaining unknowns:
  1. clean the stray 'Z' off the Title,
  2. does a JS click actually SELECT a board row (i.e. do untrusted clicks reach React)?,
  3. what mounts when the description control is activated (full testid/dialog inventory),
  4. does a paste/InputEvent path reach the description editor?"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()
TITLE = "Make Your Studio Feel Twice as Big: 7 Renter-Friendly Habits"
DESC = ("Small studio apartment? These 7 renter-friendly habits make a tiny space feel twice "
        "as big - no drilling, no damage-deposit drama.")

ALL_IDS = r"""(() => {
  const ids = Array.from(new Set(Array.from(document.querySelectorAll('[data-test-id]'))
    .map(e => e.getAttribute('data-test-id'))));
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"],[role="menu"],[role="listbox"]'))
    .map(e => ({role: e.getAttribute('role'), testid: e.getAttribute('data-test-id'),
                txt: (e.innerText||'').replace(/\s+/g,' ').slice(0,70), vis: e.offsetParent !== null}));
  const interesting = ids.filter(t => /editor|modal|flyout|dialog|desc|comment|mention|picker|draft|text/i.test(t));
  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
  return JSON.stringify({interestingIds: interesting, allIdsCount: ids.length, dialogs: dialogs,
    descHTMLLen: c ? c.innerHTML.length : null,
    descPlaceholderVisible: c ? /Describe your Pin/.test(c.textContent || '') : null,
    saving: (() => { const s = document.querySelector('[data-test-id^="saving-status"]'); return s ? (s.innerText||'').trim().slice(0,40) : null; })(),
    titleValue: (document.querySelector('#storyboard-selector-title')||{}).value ?? null,
    boardText: (() => { const b = document.querySelector('[data-test-id="board-dropdown-select-button"]'); return b ? (b.innerText||'').replace(/\s+/g,' ').trim() : null; })()});
})()"""


async def main():
    async with AsyncRig() as rig:
        log("== 1: clean the Title via JS setter (known-good mechanism) ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const el = document.querySelector('#storyboard-selector-title');
          el.focus();
          Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(el, %s);
          el.dispatchEvent(new Event('input',{bubbles:true}));
          el.dispatchEvent(new Event('change',{bubbles:true}));
          return JSON.stringify({value: el.value});
        })()""" % json.dumps(TITLE))
        log("title:", json.dumps(r)[:200])

        log("== 2: JS click a board row and see whether the selection changes ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const b = document.querySelector('[data-test-id="board-dropdown-select-button"]');
          if (b) b.click();
          return JSON.stringify({opened: !!b});
        })()""")
        log("dropdown open:", json.dumps(r))
        await asyncio.sleep(4)
        r = await rig.evaluate_json(pid, r"""(() => {
          const rows = Array.from(document.querySelectorAll('[data-test-id^="board-row-"]'))
            .map(e => ({testid: e.getAttribute('data-test-id'), vis: e.offsetParent !== null,
                        txt: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,40)}));
          return JSON.stringify({rows: rows, flyout: !!document.querySelector('[data-test-id="board-picker-flyout"]')});
        })()""")
        log("board rows:", json.dumps(r)[:600])

        log("== 3: full testid/dialog inventory ==")
        r = await rig.evaluate_json(pid, ALL_IDS)
        log("interesting ids:", json.dumps(r.get("interestingIds"))[:700])
        log("dialogs/menus:", json.dumps(r.get("dialogs"))[:500])
        log("allIdsCount:", r.get("allIdsCount"), "descHTMLLen:", r.get("descHTMLLen"),
            "saving:", r.get("saving"), "board:", json.dumps(r.get("boardText"))[:60])

        log("== 4: paste / beforeinput routes into the description control ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          const inner = c.querySelector('[role="button"] > div') || c.querySelector('[role="button"]') || c;
          inner.setAttribute('tabindex','0');
          inner.focus();
          const dt = new DataTransfer();
          dt.setData('text/plain', %s);
          inner.dispatchEvent(new ClipboardEvent('paste', {bubbles:true, cancelable:true, clipboardData: dt}));
          inner.dispatchEvent(new InputEvent('beforeinput', {bubbles:true, cancelable:true, inputType:'insertText', data:%s}));
          return JSON.stringify({focused: document.activeElement === inner, innerTag: inner.tagName,
            innerCls: typeof inner.className === 'string' ? inner.className.slice(0,50) : null});
        })()""" % (json.dumps(DESC), json.dumps(DESC)))
        log("paste attempt:", json.dumps(r))
        await asyncio.sleep(3)
        r = await rig.evaluate_json(pid, ALL_IDS)
        log("after paste -> interesting:", json.dumps(r.get("interestingIds"))[:500])
        log("after paste -> descHTMLLen:", r.get("descHTMLLen"), "descText:",
            json.dumps(r.get("descPlaceholderVisible")))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
