#!/usr/bin/env python3
"""STAGE 1c: targeted selector map for the composer (read-only). Buttons, description editor,
board dropdown, drop zone ancestry. No clicks, no upload, no reload."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test")

JS = r"""(() => {
  const q = (s, r) => Array.from((r || document).querySelectorAll(s));
  const desc = (e) => ({
    tag: e.tagName.toLowerCase(),
    testid: e.getAttribute('data-test-id'),
    id: e.id || null,
    role: e.getAttribute('role'),
    aria: e.getAttribute('aria-label'),
    ce: e.isContentEditable === true,
    dd: e.getAttribute('data-draft-text') || null,
    txt: (e.innerText || '').replace(/\s+/g,' ').trim().slice(0, 60) || null,
    cls: typeof e.className === 'string' ? e.className.slice(0, 70) : null,
  });
  const buttons = q('button, [role=button], a[role=button]').map(e => ({
    tag: e.tagName, testid: e.getAttribute('data-test-id'), aria: e.getAttribute('aria-label'),
    txt: (e.innerText || '').replace(/\s+/g,' ').trim().slice(0, 45),
    disabled: e.disabled === true, type: e.getAttribute('type'),
  })).filter(b => b.testid || b.txt || b.aria);

  const descContainer = document.querySelector('[data-test-id="storyboard-description-field-container"]');
  const titleContainer = document.querySelector('[data-test-id="storyboard-title-field-container"]');
  const linkWrap = document.querySelector('[data-test-id="storyboard-selector-link"]');
  const boardWrap = document.querySelector('[data-test-id="storyboard-selector-board"]');
  const uploadWrap = document.querySelector('[data-test-id="storyboard-draft-upload-container"]');
  const dragWrap = document.querySelector('[data-test-id="drag-behavior-container"]');
  const fi = document.querySelector('#storyboard-upload-input');

  const tree = (el, depth, maxDepth) => {
    if (!el || depth > maxDepth) return null;
    return {
      ...desc(el),
      children: Array.from(el.children).slice(0, 10).map(c => tree(c, depth + 1, maxDepth)),
    };
  };
  const ancestry = (el) => { const out = []; let n = el; while (n && n !== document.body && out.length < 6) { out.push(desc(n)); n = n.parentElement; } return out; };

  return JSON.stringify({
    url: location.href,
    buttons: buttons,
    publishLike: buttons.filter(b => /publish|done|save|draft|create|post/i.test((b.txt||'') + ' ' + (b.aria||'') + ' ' + (b.testid||''))),
    descTree: tree(descContainer, 0, 3),
    titleTree: tree(titleContainer, 0, 2),
    linkTree: tree(linkWrap, 0, 2),
    boardTree: tree(boardWrap, 0, 3),
    uploadTree: tree(uploadWrap, 0, 2),
    dragTree: tree(dragWrap, 0, 2),
    fileInputAncestry: ancestry(fi),
    fileInputOuter: fi ? fi.outerHTML.slice(0, 500) : null,
    draftSavingStatus: (document.querySelector('[data-test-id^="saving-status"]') || {}).outerHTML ? document.querySelector('[data-test-id^="saving-status"]').outerHTML.slice(0,300) : null,
    draftsText: (document.querySelector('[data-test-id="drafts-container"]') || {}).innerText ? document.querySelector('[data-test-id="drafts-container"]').innerText.slice(0,400) : null,
    titleInputValue: (document.querySelector('#storyboard-selector-title')||{}).value ?? null,
    linkInputValue: (document.querySelector('#WebsiteField')||{}).value ?? null,
  });
})()"""


async def main():
    pid = open(os.path.join(TEST, "page_id.txt")).read().strip()
    async with AsyncRig() as rig:
        p = await rig.evaluate_json(pid, JS)
        with open(os.path.join(TEST, "03_composer_map.json"), "w") as f:
            json.dump(p, f, indent=2)
        for k in ("url", "publishLike", "fileInputOuter", "savingStatus", "draftsText",
                  "titleInputValue", "linkInputValue", "fileInputAncestry"):
            log(k, ":", json.dumps(p.get(k))[:700])
        log("ALL BUTTONS:", json.dumps(p.get("buttons"))[:2500])
        log("descTree:", json.dumps(p.get("descTree"))[:1500])
        log("boardTree:", json.dumps(p.get("boardTree"))[:1200])
        s = await rig.screenshot(pid)
        log("shot:", s[:200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
