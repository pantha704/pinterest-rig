#!/usr/bin/env python3
"""Read-only state probe: MCP tool schemas + open pages + current URL/text. NO navigation."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402


async def main():
    async with AsyncRig() as rig:
        tools = await rig.session.list_tools()
        schemas = {}
        for t in tools.tools:
            schemas[t.name] = t.inputSchema
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "mcp_tool_schemas.json"), "w") as f:
            json.dump(schemas, f, indent=2)
        print("TOOLS:", len(schemas))
        for n in ("cloak_launch", "cloak_evaluate", "cloak_screenshot", "cloak_navigate",
                  "cloak_snapshot", "cloak_click", "cloak_type", "cloak_select", "cloak_wait",
                  "cloak_press_key", "cloak_scroll", "cloak_list_pages", "cloak_new_page"):
            s = schemas.get(n, {})
            props = s.get("properties", {})
            print(f"  {n}: {list(props.keys())}")

        log("---- pages ----")
        raw = await rig.call("cloak_list_pages")
        print(raw[:2000])
        try:
            pages = json.loads(raw)
            if isinstance(pages, dict):
                pages = pages.get("pages", [])
        except Exception:
            pages = []
        for p in pages or []:
            pid = p.get("page_id") or p.get("id")
            log("page", pid, "url=", p.get("url"))
            if pid:
                r = await rig.evaluate_json(pid, """(() => JSON.stringify({
                  url: location.href, title: document.title,
                  text: (document.body ? document.body.innerText : '').slice(0, 600)
                }))()""")
                print(json.dumps(r, indent=2)[:1500])


if __name__ == "__main__":
    asyncio.run(main())
