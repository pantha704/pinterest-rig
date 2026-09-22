#!/usr/bin/env python3
"""Probe Cromite on the phone over CDP: tabs + key cookies (google/pinterest state)."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        print("connecting to phone CDP...", flush=True)
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=20000)
        print("contexts:", len(b.contexts), flush=True)
        ctx = b.contexts[0]
        for pg in ctx.pages:
            print("  tab:", pg.url[:110], flush=True)
        ck = await ctx.cookies()
        print("total cookies:", len(ck), flush=True)
        goog = [c for c in ck if "google" in c["domain"]]
        pin = [c for c in ck if "pinterest" in c["domain"]]
        print("google.com cookies:", len(goog), flush=True)
        for c in goog[:25]:
            print("   G:", c["domain"], c["name"], "len", len(c["value"]), flush=True)
        print("pinterest cookies:", len(pin), flush=True)
        for c in pin[:25]:
            print("   P:", c["domain"], c["name"], "len", len(c["value"]), flush=True)


asyncio.run(main())
