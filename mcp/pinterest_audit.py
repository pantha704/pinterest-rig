#!/usr/bin/env python3
"""Audit the logged-in Pinterest account via MCP :8933 (profile stats + boards)."""
import asyncio
import json
import traceback

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8933/mcp"


async def call(s, name, args=None):
    res = await s.call_tool(name, args or {})
    parts = []
    for c in getattr(res, "content", []) or []:
        parts.append(getattr(c, "text", None) or str(c))
    return "\n".join(parts)


async def main():
    async with streamable_http_client(URL) as ctx:
        r, w = ctx[0], ctx[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            rp = await call(s, "cloak_list_pages", {})
            pages = json.loads(rp)
            if isinstance(pages, dict):
                pages = pages.get("pages", [])
            page_id = pages[0]["page_id"] if pages else None
            print("PAGE:", page_id, flush=True)
            if not page_id:
                return 2

            print("---- profile page ----", flush=True)
            r2 = await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/panther704/", "timeout": 90000})
            print("NAV:", r2[:260], flush=True)
            await asyncio.sleep(8)

            expr = """(() => {
              const body = document.body ? document.body.innerText : '';
              const nums = body.match(/(\\d+(?:\\.\\d+)?[KkMm]?)\\s*(followers|following)/g) || [];
              return JSON.stringify({url: location.href, stats: nums, head: body.slice(0, 700)});
            })()"""
            r3 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": expr})
            print("PROFILE:", r3[:1100], flush=True)

            print("---- home feed sanity ----", flush=True)
            r4 = await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/", "timeout": 90000})
            print("NAV2:", r4[:200], flush=True)
            await asyncio.sleep(5)
            r5 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": "(() => { const b = document.body ? document.body.innerText.slice(0,150) : ''; return JSON.stringify({url: location.href, head: b}); })()"})
            print("HOME:", r5[:400], flush=True)

            r6 = await call(s, "cloak_screenshot", {"page_id": page_id})
            print("SHOT:", r6[:300], flush=True)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
