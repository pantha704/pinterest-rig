#!/usr/bin/env python3
"""STAGE 1b: re-probe the SAME page (no reload) with a much broader dump + full-page shot."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test")

BROAD = r"""(() => {
  const q = (s) => Array.from(document.querySelectorAll(s));
  const inner = () => {
    const roots = [];
    const push = (r) => { if (r) roots.push(r); };
    push(document.body);
    q('*').forEach(e => { if (e.shadowRoot) push(e.shadowRoot); });
    return roots;
  };
  const roots = inner();
  const all = [];
  roots.forEach(r => { try { all.push(...q.call(null, '*').length ? Array.from(r.querySelectorAll('*')) : []); } catch (e) {} });
  const seen = new Set(); const uniq = [];
  all.forEach(e => { if (!seen.has(e)) { seen.add(e); uniq.push(e); } });
  const testids = Array.from(new Set(uniq.map(e => e.getAttribute && e.getAttribute('data-test-id')).filter(Boolean)));
  const roles = Array.from(new Set(uniq.map(e => e.getAttribute && e.getAttribute('role')).filter(Boolean)));
  const ce = uniq.filter(e => e.isContentEditable).map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'), aria: e.getAttribute('aria-label'), ph: e.getAttribute('placeholder')}));
  const files = uniq.filter(e => e.tagName === 'INPUT' && e.type === 'file').map(e => ({testid: e.getAttribute('data-test-id'), accept: e.accept, name: e.name, id: e.id, w: Math.round(e.getBoundingClientRect().width), hidden: e.offsetParent === null}));
  const inputs = uniq.filter(e => ['INPUT','TEXTAREA'].includes(e.tagName)).map(e => ({tag: e.tagName, type: e.type, testid: e.getAttribute('data-test-id'), ph: e.placeholder, aria: e.getAttribute('aria-label'), id: e.id, w: Math.round(e.getBoundingClientRect().width)}));
  const buttons = uniq.filter(e => ['BUTTON'].includes(e.tagName) || e.getAttribute('role') === 'button').map(e => ({tag: e.tagName, testid: e.getAttribute('data-test-id'), txt: (e.innerText||'').trim().slice(0,40), aria: e.getAttribute('aria-label'), disabled: e.disabled === true}));
  const html = document.documentElement.outerHTML;
  return JSON.stringify({
    url: location.href,
    bodyText: (document.body ? document.body.innerText : '').slice(0, 3000),
    htmlLen: html.length,
    rootChildren: document.body ? Array.from(document.body.children).map(c => c.tagName + '#' + (c.id||'') + '.' + (typeof c.className === 'string' ? c.className.slice(0,60) : '')).slice(0,20) : [],
    elementCount: uniq.length,
    testids: testids.slice(0, 250),
    roles: roles.slice(0, 60),
    contentEditables: ce,
    fileInputs: files,
    inputs: inputs.slice(0, 40),
    buttons: buttons.slice(0, 60),
  });
})()"""


async def main():
    pid = open(os.path.join(TEST, "page_id.txt")).read().strip()
    async with AsyncRig() as rig:
        await asyncio.sleep(10)
        p = await rig.evaluate_json(pid, BROAD)
        with open(os.path.join(TEST, "02_builder_broad.json"), "w") as f:
            json.dump(p, f, indent=2)
        for k in ("url", "htmlLen", "elementCount", "bodyText", "rootChildren"):
            log(k, ":", json.dumps(p.get(k))[:900])
        for k in ("fileInputs", "contentEditables", "testids", "roles", "inputs", "buttons"):
            log(k, ":", json.dumps(p.get(k))[:1200])
        s = await rig.screenshot(pid, full_page=False)
        log("shot:", s[:200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
