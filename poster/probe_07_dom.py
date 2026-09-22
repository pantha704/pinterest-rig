#!/usr/bin/env python3
"""Discover the description editor + board dropdown DOM (they mount on click), using the
JS path that works on this rig. Also restores the real Title value. No reload, no publish."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()
TITLE = "Make Your Studio Feel Twice as Big: 7 Renter-Friendly Habits"


async def main():
    async with AsyncRig() as rig:
        log("== A: set real Title via JS native setter ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const el = document.querySelector('#storyboard-selector-title');
          if (!el) return JSON.stringify({ok:false});
          el.focus();
          const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          set.call(el, %s);
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
          return JSON.stringify({ok:true, value: el.value});
        })()""" % json.dumps(TITLE))
        print("title:", json.dumps(r))

        log("== B: click the description activation control via JS ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          if (!c) return JSON.stringify({ok:false, err:'no container'});
          const before = c.innerHTML.length;
          const btn = c.querySelector('[role="button"]') || c.querySelector('button') || c;
          btn.click();
          return JSON.stringify({ok:true, clickedTag: btn.tagName, beforeLen: before,
                                 html: c.innerHTML.slice(0, 700)});
        })()""")
        print("desc activation:", json.dumps(r)[:1400])
        await asyncio.sleep(4)
        r = await rig.evaluate_json(pid, r"""(() => {
          const c = document.querySelector('[data-test-id="storyboard-description-field-container"]');
          const eds = Array.from(document.querySelectorAll(
            '[data-test-id="editor-with-mentions"], [contenteditable="true"], #mweb-comment-editor-container, [role="textbox"]'));
          return JSON.stringify({
            containerHTMLLen: c ? c.innerHTML.length : null,
            containerHTML: c ? c.innerHTML.slice(0, 900) : null,
            editors: eds.map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'),
              id: e.id || null, role: e.getAttribute('role'), ce: e.getAttribute('contenteditable'),
              ph: e.getAttribute('data-placeholder') || e.getAttribute('placeholder'),
              vis: e.offsetParent !== null, cls: typeof e.className === 'string' ? e.className.slice(0,60) : null})),
            commentEditorIds: Array.from(document.querySelectorAll('[id*="comment-editor"]')).map(e => e.id),
            draftTextAttrs: Array.from(document.querySelectorAll('[data-draft-text]')).map(e => e.id || e.tagName),
            focus: document.activeElement ? (document.activeElement.getAttribute('data-test-id') || document.activeElement.id || document.activeElement.tagName) : null,
          });
        })()""")
        print("desc after mount:", json.dumps(r, indent=2)[:2600])

        log("== C: open board dropdown via JS click and dump items ==")
        r = await rig.evaluate_json(pid, r"""(() => {
          const b = document.querySelector('[data-test-id="board-dropdown-select-button"]');
          if (!b) return JSON.stringify({ok:false, err:'no board button'});
          b.click();
          return JSON.stringify({ok:true});
        })()""")
        print("board open:", json.dumps(r))
        await asyncio.sleep(4)
        r = await rig.evaluate_json(pid, r"""(() => {
          const testids = Array.from(new Set(Array.from(document.querySelectorAll('[data-test-id]'))
            .map(e => e.getAttribute('data-test-id')))).filter(t => /board|dropdown|item/i.test(t));
          const btns = Array.from(document.querySelectorAll('button,[role="button"]'))
            .filter(e => /birthday|programmer|create board|search through/i.test(e.innerText || ''))
            .map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'),
                        txt: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,50),
                        vis: e.offsetParent !== null,
                        rect: (r => [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)])(e.getBoundingClientRect())}));
          const panel = document.querySelector('[data-test-id*="board-dropdown"]');
          return JSON.stringify({boardTestIds: testids, candidateItems: btns,
            panelHTML: panel ? panel.outerHTML.slice(0, 1400) : null});
        })()""")
        print("board dropdown:", json.dumps(r, indent=2)[:3200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
