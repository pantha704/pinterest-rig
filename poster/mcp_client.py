#!/usr/bin/env python3
"""Shared async MCP client shim for the Pinterest rig on http://127.0.0.1:8933/mcp.

Import from sibling scripts:

    from mcp_client import Rig
    rig = Rig().connect()          # sync context manager, auto-closes session only
    ...
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

URL = os.environ.get("PINTEREST_MCP_URL", "http://127.0.0.1:8933/mcp")
PROFILE = "/home/ubuntu/.cloakbrowser/profiles/pinterest"
PROXY = "socks5://127.0.0.1:1080"
FINGERPRINT_SEED = "56789"
ARTIFACTS = "/home/ubuntu/.cloakbrowser/artifacts"


class MCPError(RuntimeError):
    pass


class AsyncRig:
    """Thin wrapper: one call_tool helper that always flattens content to text."""

    def __init__(self, url=URL):
        self.url = url
        self.session = None
        self._stack = None

    async def __aenter__(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        self._stack = streamable_http_client(self.url)
        r, w, _ = await self._stack.__aenter__()
        self.session = ClientSession(r, w)
        await self.session.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        try:
            await self.session.__aexit__(*exc)
        finally:
            await self._stack.__aexit__(*exc)
        return False

    async def call(self, name, args=None, raw=False):
        res = await self.session.call_tool(name, args or {})
        parts = []
        for c in getattr(res, "content", []) or []:
            parts.append(getattr(c, "text", None) or str(c))
        text = "\n".join(parts)
        # CRITICAL: cloakbrowsermcp reports failures inside structuredContent with
        # isError=False (e.g. ElementNotStableError). A bare isError check misses them and
        # the caller believes the click/type worked. Surface it as a real error.
        sc = getattr(res, "structuredContent", None) or {}
        silent = None
        if isinstance(sc, dict) and sc.get("status") == "error":
            silent = sc.get("error") or text
        if silent is None:
            try:
                j = json.loads(text)
                if isinstance(j, dict) and j.get("status") == "error":
                    silent = j.get("error") or text
            except Exception:
                pass
        if silent:
            raise MCPError(f"{name} reported status=error (isError was False): {silent[:400]}")
        if getattr(res, "isError", False):
            raise MCPError(f"{name} failed: {text[:600]}")
        if raw:
            return res
        return text

    async def call_json(self, name, args=None):
        """Call a tool that returns JSON; tolerate plain-text returns (paths, strings)."""
        text = await self.call(name, args)
        try:
            return json.loads(text)
        except Exception:
            return {"_raw": text}

    # ---- convenience wrappers -------------------------------------------------
    async def evaluate(self, page_id, expression):
        return await self.call("cloak_evaluate", {"page_id": page_id, "expression": expression})

    async def evaluate_json(self, page_id, expression):
        """cloak_evaluate returns {"result": "<stringified value>"}; unwrap both layers."""
        text = await self.evaluate(page_id, expression)
        def _try(s):
            try:
                return json.loads(s)
            except Exception:
                return None
        val = _try(text)
        # unwrap {"result": "..."} envelope(s) produced by the MCP tool wrapper
        for _ in range(3):
            if isinstance(val, dict) and set(val.keys()) == {"result"} and isinstance(val["result"], str):
                inner = _try(val["result"])
                if inner is None:
                    return {"result": val["result"]}
                val = inner
            else:
                break
        if val is None:
            s, e = text.find("{"), text.rfind("}")
            if s != -1 and e > s:
                val = _try(text[s:e + 1])
        return val if val is not None else {"_raw": text}

    async def snapshot(self, page_id):
        return await self.call("cloak_snapshot", {"page_id": page_id})

    async def screenshot(self, page_id, full_page=False, label=None):
        args = {"page_id": page_id}
        if full_page:
            args["full_page"] = True
        if label:
            args["filename"] = label
        return await self.call("cloak_screenshot", args)

    async def navigate(self, page_id, url, timeout=90000):
        return await self.call("cloak_navigate", {"page_id": page_id, "url": url, "timeout": timeout})

    async def list_pages(self):
        return await self.call_json("cloak_list_pages", {})


def run(coro_factory):
    """Run an async main(coro_factory(rig)) with a connected rig."""
    async def _main():
        async with AsyncRig() as rig:
            return await coro_factory(rig)
    return asyncio.run(_main())


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def save_artifact(text, name, dest_dir=None):
    """Persist a probe/document dump next to the test artifacts."""
    d = dest_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p
