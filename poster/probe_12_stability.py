#!/usr/bin/env python3
"""Is the composer ACTUALLY unstable (explaining ElementNotStableError), or is the
stability check misfiring? Sample the element rect over time in JS. Plus full page state."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

TEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
pid = open(os.path.join(TEST, "last_page_id.txt")).read().strip()

STABILITY = r"""(() => new Promise(resolve => {
  const sel = '#storyboard-selector-title';
  const rects = [];
  let n = 0;
  const tick = () => {
    const el = document.querySelector(sel);
    if (el) { const r = el.getBoundingClientRect();
      rects.push([+r.x.toFixed(3), +r.y.toFixed(3), +r.width.toFixed(3), +r.height.toFixed(3)]); }
    if (++n < 12) requestAnimationFrame(tick); else resolve(JSON.stringify({samples: rects}));
  };
  requestAnimationFrame(tick);
}))()"""

ANIM = r"""(() => {
  const out = [];
  document.querySelectorAll('*').forEach(e => {
    try {
      const s = getComputedStyle(e);
      if (s.animationName && s.animationName !== 'none') out.push({tag: e.tagName, testid: e.getAttribute('data-test-id'), anim: s.animationName, dur: s.animationDuration});
      else if (s.transitionDuration && s.transitionDuration !== '0s' && s.transitionProperty !== 'all') { /* ignore transitions */ }
    } catch (err) {}
  });
  return JSON.stringify({animatedCount: out.length, animated: out.slice(0, 12),
    bodyText: (document.body.innerText || '').slice(0, 900)});
})()"""


async def main():
    async with AsyncRig() as rig:
        log("== A: rAF rect sampling of the Title input ==")
        r = await rig.evaluate_json(pid, STABILITY)
        samples = r.get("samples") or []
        uniq = {json.dumps(s) for s in samples}
        print("samples:", json.dumps(samples))
        print(f"distinct rects: {len(uniq)} of {len(samples)} ->",
              "STABLE in JS" if len(uniq) <= 2 else "GENUINELY MOVING")

        log("== B: CSS animations running on the page ==")
        r = await rig.evaluate_json(pid, ANIM)
        print("animatedCount:", r.get("animatedCount"))
        print("animated:", json.dumps(r.get("animated"))[:500])
        print("BODY TEXT:", (r.get("bodyText") or "")[:900])

        log("== C: screenshot ==")
        s = await rig.screenshot(pid)
        print(s[:200])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
