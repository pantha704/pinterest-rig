#!/usr/bin/env python3
"""FINAL capture (single pass, no exploration): screenshot the composer as it stands +
record the final field state into test/final_state.json."""
import asyncio
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()

STATE = r"""(() => {
  const g = (s) => document.querySelector(s);
  const board = g('[data-test-id="board-dropdown-select-button"]');
  const c = g('[data-test-id="storyboard-description-field-container"]');
  const drafts = Array.from(document.querySelectorAll('[data-test-id^="pinDraft-"]'))
    .map(e => ({testid: e.getAttribute('data-test-id'), txt: (e.innerText||'').replace(/\s+/g,' ').trim().slice(0,80)}));
  return JSON.stringify({
    url: location.href,
    titleValue: (g('#storyboard-selector-title')||{}).value ?? null,
    linkValue: (g('#WebsiteField')||{}).value ?? null,
    descText: c ? (c.innerText||'').slice(0,150) : null,
    descHTMLLen: c ? c.innerHTML.length : null,
    board: board ? (board.innerText||'').replace(/\s+/g,' ').trim() : null,
    previewImgs: Array.from(document.querySelectorAll('img')).filter(i => i.naturalWidth > 200)
      .map(i => ({src: (i.currentSrc||i.src||'').slice(0,90), w: i.naturalWidth, h: i.naturalHeight})),
    draftEntries: drafts,
    savingStatus: (() => { const s = g('[data-test-id^="saving-status"]'); return s ? (s.innerText||'').trim().slice(0,40) : null; })(),
    publishButtonPresent: !!Array.from(document.querySelectorAll('button'))
      .find(e => /^publish$/i.test((e.innerText||'').trim())),
  });
})()"""


async def main():
    async with AsyncRig() as rig:
        st = await rig.evaluate_json(pid, STATE)
        with open(os.path.join(TEST, "final_state.json"), "w") as f:
            json.dump(st, f, indent=2)
        print(json.dumps(st, indent=2)[:2000])
        try:
            r = await rig.screenshot(pid)
            src = json.loads(r).get("path")
            if src and os.path.exists(src):
                dst = os.path.join(TEST, "13_final_composed_state.png")
                shutil.copyfile(src, dst)
                print("SHOT ->", dst)
        except Exception as e:
            print("screenshot failed:", e)
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
