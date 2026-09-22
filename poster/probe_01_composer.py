#!/usr/bin/env python3
"""STAGE 1 of the single composer run: open MY OWN page on the pin builder and dump the DOM.

Creates a fresh page via cloak_new_page (never reuses another actor's page), navigates to the
Pinterest pin-creation flow, waits for the composer, then dumps every candidate selector:
file inputs, drop zones, contenteditables, textareas, buttons, data-test-id inventory.

Read-only w.r.t. account state: no clicks that submit, no upload yet.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test")

# Candidate composer entry points, tried in order. Pinterest redirects to the real builder.
CANDIDATE_URLS = [
    "https://in.pinterest.com/pin-creation-tool/",
]

PROBE_JS = r"""(() => {
  const q = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const info = (el) => ({
    tag: el.tagName.toLowerCase(),
    testid: el.getAttribute('data-test-id') || null,
    id: el.id || null,
    name: el.getAttribute('name') || null,
    type: el.getAttribute('type') || null,
    aria: el.getAttribute('aria-label') || null,
    ph: el.getAttribute('placeholder') || null,
    accept: el.getAttribute('accept') || null,
    multiple: el.hasAttribute('multiple') ? true : null,
    role: el.getAttribute('role') || null,
    ce: el.isContentEditable === true ? true : null,
    cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 90) : null,
    text: (el.innerText || el.textContent || '').trim().slice(0, 70) || null,
    w: Math.round(el.getBoundingClientRect().width),
    h: Math.round(el.getBoundingClientRect().height),
  });
  const testids = Array.from(new Set(q('[data-test-id]').map(e => e.getAttribute('data-test-id')))).slice(0, 300);
  const inputButtons = Array.from(new Set(q('input[type=button],input[type=submit]').map(e => (e.value||'') + '|' + (e.getAttribute('data-test-id')||''))));
  return JSON.stringify({
    url: location.href,
    title: document.title,
    ready: document.readyState,
    bodyText: (document.body ? document.body.innerText : '').slice(0, 2500),
    fileInputs: q('input[type=file]').map(info),
    textareas: q('textarea').map(info),
    textInputs: q('input:not([type=file]):not([type=hidden])').map(info),
    contentEditables: q('[contenteditable="true"],[contenteditable=""]').map(info),
    dropZones: q('[class*=ropzone],[class*=rop-zone],[data-test-id*=drop],[data-test-id*=upload],[class*=upload]').map(info).slice(0, 30),
    images: q('img').map(e => ({alt: e.getAttribute('alt'), testid: e.getAttribute('data-test-id'), src: (e.getAttribute('src')||'').slice(0, 90)})).slice(0, 25),
    testids: testids,
    inputButtons: inputButtons,
    buttonTexts: Array.from(new Set(q('button,[role=button],a[role=button]').map(e => (e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,50)).filter(Boolean))).slice(0, 80),
  });
})()"""


async def main():
    async with AsyncRig() as rig:
        pages = await rig.list_pages()
        log("pages before:", json.dumps(pages)[:500])

        log("---- cloak_new_page (my own page) ----")
        r = await rig.call("cloak_new_page", {"url": CANDIDATE_URLS[0]})
        log("new_page:", r[:500])
        try:
            pid = json.loads(r).get("page_id")
        except Exception:
            pid = None
        if not pid:
            j = await rig.list_pages()
            pl = j.get("pages", j if isinstance(j, list) else [])
            # pick the page that is on the builder URL
            pid = next((p.get("page_id") for p in pl if "pin-creation" in (p.get("url") or "")
                        or "pin-builder" in (p.get("url") or "")), None)
        if not pid:
            log("FAILED to get a page_id")
            return 2
        log("MY PAGE_ID:", pid)
        with open(os.path.join(TEST, "page_id.txt"), "w") as f:
            f.write(pid)

        # Let the SPA boot and redirect.
        await asyncio.sleep(12)
        await rig.call("cloak_wait", {"page_id": pid, "timeout_ms": 3000})

        probe = await rig.evaluate_json(pid, PROBE_JS)
        with open(os.path.join(TEST, "01_builder_probe.json"), "w") as f:
            json.dump(probe, f, indent=2)
        log("PROBE url:", probe.get("url"))
        log("PROBE bodyText:", (probe.get("bodyText") or "")[:1200])
        log("fileInputs:", json.dumps(probe.get("fileInputs")))
        log("contentEditables:", json.dumps(probe.get("contentEditables"))[:800])
        log("textInputs:", json.dumps(probe.get("textInputs"))[:800])
        log("dropZones:", json.dumps(probe.get("dropZones"))[:900])
        log("inputButtons:", json.dumps(probe.get("inputButtons"))[:400])
        log("buttonTexts:", json.dumps(probe.get("buttonTexts"))[:600])
        tid = probe.get("testids") or []
        interesting = [t for t in tid if any(k in t.lower() for k in
                       ("pin-builder", "publish", "draft", "board", "upload", "drop", "title",
                        "description", "link", "save", "create", "story", "pin-draft"))]
        log("testids(interesting):", json.dumps(interesting)[:1500])

        shot = await rig.screenshot(pid)
        log("screenshot:", shot[:300])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
