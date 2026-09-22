#!/usr/bin/env python3
"""Retry proving the imported session is live in the VPS chrome."""
import asyncio, os
from playwright.async_api import async_playwright

ACC = "/home/ubuntu/pinterest-rig/account"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9444", timeout=15000)
        ctx = b.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(30000)
        for attempt in (1, 2):
            try:
                print(f"attempt {attempt}: goto settings", flush=True)
                await page.goto("https://www.pinterest.com/settings/", wait_until="commit", timeout=90000)
                print("committed ok", flush=True)
                break
            except Exception as e:
                print("err:", str(e)[:180], flush=True)
        await page.wait_for_timeout(10000)
        print("URL:", page.url, flush=True)
        print("TITLE:", await page.title(), flush=True)
        shot = os.path.join(ACC, "pinterest_after_import.png")
        try:
            await page.screenshot(path=shot, timeout=30000)
            print("shot:", shot, flush=True)
        except Exception as e:
            print("shot err:", str(e)[:150], flush=True)
        try:
            txt = await page.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText.slice(0,500) : 'NOBODY'")
            print("BODY:", txt.replace(chr(10), " | ")[:500], flush=True)
        except Exception as e:
            print("eval err:", str(e)[:150], flush=True)


asyncio.run(main())
