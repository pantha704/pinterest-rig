#!/usr/bin/env python3
"""Can a TRUSTED input reach the composer? cloak_press_key sends real key events and is not
subject to the element-stability check that blocks cloak_click/cloak_type. Also retry
cloak_click now that the page has settled."""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()

STATE = r"""(() => {
  const t = document.querySelector('#storyboard-selector-title');
  const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
  const eds = Array.from(document.querySelectorAll('[contenteditable="true"], [role="textbox"], #mweb-comment-editor-container'))
    .filter(e => !/Text field Blank/.test(e.getAttribute('aria-label') || ''))
    .map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'), id: e.id || null,
                role: e.getAttribute('role'), ce: e.getAttribute('contenteditable'),
                aria: (e.getAttribute('aria-label')||'').slice(0,50),
                txt: (e.innerText||'').slice(0,50), vis: e.offsetParent !== null}));
  return JSON.stringify({titleValue: t ? t.value : null,
    descText: c ? (c.innerText||'').slice(0,140) : null,
    descHTMLLen: c ? c.innerHTML.length : null,
    editors: eds,
    active: document.activeElement ? (document.activeElement.getAttribute('data-test-id') || document.activeElement.id || document.activeElement.tagName) : null});
})()"""


async def main():
    async with AsyncRig() as rig:
        log("== A: retry cloak_click on the Title input ==")
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
                    break
        log("title ref:", ref)
        r = await rig.call("cloak_click", {"page_id": pid, "ref": ref}, raw=True)
        print("RAW CLICK:", str(r)[:500])
        st = await rig.evaluate_json(pid, STATE)
        log("active after click:", st.get("active"))

        log("== B: focus title via JS then cloak_press_key a single char ==")
        await rig.evaluate_json(pid, "(()=>{const t=document.querySelector('#storyboard-selector-title');if(t){t.focus();}return '1'})()")
        before = (await rig.evaluate_json(pid, STATE)).get("titleValue")
        r = await rig.call("cloak_press_key", {"page_id": pid, "key": "Z"}, raw=True)
        print("RAW PRESS:", str(r)[:400])
        await asyncio.sleep(1)
        st = await rig.evaluate_json(pid, STATE)
        log(f"title before={before!r} after={st.get('titleValue')!r}")

        log("== C: focus the description control, press Enter, look for a mounted editor ==")
        await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          const btn = c && (c.querySelector('[role="button"]') || c);
          if (btn) { btn.setAttribute('tabindex','0'); btn.focus(); }
          return JSON.stringify({focused: document.activeElement === btn});
        })()""")
        for key in ("Enter", " "):
            r = await rig.call("cloak_press_key", {"page_id": pid, "key": key}, raw=True)
            log(f"pressed {key!r}: {str(r)[:200]}")
            await asyncio.sleep(4)
            st = await rig.evaluate_json(pid, STATE)
            log(f"  descText={st.get('descText')!r} descHTMLLen={st.get('descHTMLLen')} "
                f"editors={json.dumps(st.get('editors'))[:300]} active={st.get('active')}")
            if st.get("editors"):
                break

        log("== D: type into whatever is focused now (trusted keys) ==")
        for ch in ("H", "e", "l", "l", "o"):
            await rig.call("cloak_press_key", {"page_id": pid, "key": ch})
        await asyncio.sleep(2)
        st = await rig.evaluate_json(pid, STATE)
        print("STATE:", json.dumps(st, indent=2)[:1200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
