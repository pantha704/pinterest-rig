#!/usr/bin/env python3
"""Check what IP the VPS chrome (9444) egresses from."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9444", timeout=15000)
        page = await b.contexts[0].new_page()
        try:
            await page.goto("https://icanhazip.com", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            print("BODY:", (await page.evaluate("() => document.body.innerText")).strip(), flush=True)
        except Exception as e:
            print("ERR:", str(e)[:200], flush=True)
        await page.close()


asyncio.run(main())
