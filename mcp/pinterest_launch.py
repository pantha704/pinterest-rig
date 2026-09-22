#!/usr/bin/env python3
"""Launch the Pinterest rig browser via cloakbrowsermcp :8933 (persistent profile + phone SOCKS) and verify the logged-in session."""
import asyncio
import json
import traceback

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8933/mcp"
PROFILE = "/home/ubuntu/.cloakbrowser/profiles/pinterest"
PROXY = "socks5://127.0.0.1:1080"


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
            print("---- cloak_launch ----", flush=True)
            r1 = await call(s, "cloak_launch", {
                "user_data_dir": PROFILE,
                "proxy": PROXY,
                "fingerprint_seed": "56789",
                "headless": True,
                "humanize": True,
            })
            print("LAUNCH:", r1[:600], flush=True)
            page_id = None
            try:
                page_id = json.loads(r1).get("page_id")
            except Exception:
                pass
            if not page_id:
                print("no page_id in launch response; trying cloak_list_pages", flush=True)
                rp = await call(s, "cloak_list_pages", {})
                print("PAGES:", rp[:400], flush=True)
                try:
                    pages = json.loads(rp)
                    if isinstance(pages, dict):
                        pages = pages.get("pages", [])
                    page_id = pages[0]["page_id"] if pages else None
                except Exception:
                    pass
            if not page_id:
                print("LAUNCH FAILED — no page", flush=True)
                return 2
            print("PAGE_ID:", page_id, flush=True)

            print("---- navigate settings ----", flush=True)
            r2 = await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/settings/", "timeout": 90000})
            print("NAV:", r2[:300], flush=True)
            await asyncio.sleep(8)

            print("---- verify ----", flush=True)
            expr = """(() => {
              const body = document.body ? document.body.innerText : '';
              const inputs = Array.from(document.querySelectorAll('input')).map(i => [(i.id||i.name||'?'), (i.value||'').slice(0,30)]);
              const logged = /Edit profile|Account management/.test(body);
              return JSON.stringify({url: location.href, logged: logged, inputs: inputs.slice(0,12), head: body.slice(0,200)});
            })()"""
            r3 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": expr})
            print("VERIFY:", r3[:900], flush=True)

            print("---- screenshot ----", flush=True)
            r4 = await call(s, "cloak_screenshot", {"page_id": page_id})
            print("SHOT:", r4[:400], flush=True)
            print("FINAL_PAGE_ID:", page_id, flush=True)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
