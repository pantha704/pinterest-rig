#!/usr/bin/env python3
"""Probe logged-in state of the pinterest-profile chrome over CDP. Granular steps, hard timeouts."""
import asyncio, os
from playwright.async_api import async_playwright

CDP = "http://127.0.0.1:9444"
ACC = "/home/ubuntu/pinterest-rig/account"


async def main():
    os.makedirs(ACC, exist_ok=True)
    async with async_playwright() as p:
        print("step1: connect", flush=True)
        browser = await p.chromium.connect_over_cdp(CDP, timeout=15000)
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(20000)
        print("step2: goto /settings/", flush=True)
        try:
            await page.goto("https://www.pinterest.com/settings/", wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            print("goto err:", str(e)[:200], flush=True)
        await page.wait_for_timeout(9000)
        print("URL:", page.url, flush=True)
        print("TITLE:", await page.title(), flush=True)
        shot = os.path.join(ACC, "pinterest_settings.png")
        try:
            await page.screenshot(path=shot, timeout=25000)
            print("shot ok:", shot, flush=True)
        except Exception as e:
            print("shot err:", str(e)[:200], flush=True)
        try:
            txt = await page.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText.slice(0,700) : 'NOBODY'")
            print("BODY:", txt.replace("\n", " | ")[:700], flush=True)
        except Exception as e:
            print("eval err:", str(e)[:200], flush=True)
        print("DONE", flush=True)


asyncio.run(main())
