#!/usr/bin/env python3
"""Inventory tools + schemas of the cloakbrowsermcp server on :8932."""
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8932/mcp"


async def main():
    async with streamable_http_client(URL) as ctx:
        r, w = ctx[0], ctx[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            for t in getattr(tools, "tools", []):
                nm = getattr(t, "name", "?")
                schema = getattr(t, "inputSchema", {}) or {}
                props = list((schema.get("properties") or {}).keys())
                print(f"{nm}  ->  {props}")


asyncio.run(main())
