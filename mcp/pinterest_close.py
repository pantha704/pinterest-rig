#!/usr/bin/env python3
"""Ask the Pinterest MCP server (:8933) to close its browser gracefully (flushes profile state)."""
import asyncio
import traceback

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8933/mcp"


async def main():
    async with streamable_http_client(URL) as ctx:
        r, w = ctx[0], ctx[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("cloak_close", {})
            parts = []
            for c in getattr(res, "content", []) or []:
                parts.append(getattr(c, "text", None) or str(c))
            print("cloak_close:", "\n".join(parts)[:200])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
