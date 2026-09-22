#!/usr/bin/env python3
"""Pull the logged-in account identity from the VPS pinterest chrome."""
import asyncio, os, re
from playwright.async_api import async_playwright

ACC = "/home/ubuntu/pinterest-rig/account"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp("http://127.0.0.1:9444", timeout=15000)
        ctx = b.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(30000)

        await page.goto("https://www.pinterest.com/settings/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)

        # 1) UserSessionResource
        try:
            res = await page.evaluate("""async () => {
              try {
                const m = document.cookie.match(/csrftoken=([^;]+)/);
                const csrf = m ? m[1] : '';
                const q = '/resource/UserSessionResource/get/?source_url=%2Fsettings%2F&data=%7B%22options%22%3A%7B%7D%2C%22context%22%3A%7B%7D%7D';
                const r = await fetch(q, {headers: {'x-csrftoken': csrf, 'x-requested-with': 'XMLHttpRequest'}});
                return (await r.text()).slice(0, 900);
              } catch (e) { return 'ERR ' + e; }
            }""")
            print("UserSession:", res, flush=True)
        except Exception as e:
            print("usersession err:", str(e)[:150], flush=True)

        # 2) input values on settings (first/last name etc.)
        try:
            vals = await page.evaluate("""() => Array.from(document.querySelectorAll('input')).map(i => [(i.name || i.id || '?'), (i.value || '').slice(0,40)]).slice(0, 25)""")
            print("inputs:", vals, flush=True)
        except Exception as e:
            print("inputs err:", str(e)[:150], flush=True)

        # 3) find profile link
        uname = None
        try:
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            for h in hrefs:
                if h and re.fullmatch(r"/[A-Za-z0-9_]{3,}/", h) and h not in ("/search/", "/ideas/"):
                    uname = h.strip("/")
                    break
        except Exception as e:
            print("href err:", str(e)[:150], flush=True)
        print("profile guess:", uname, flush=True)

        if uname:
            await page.goto(f"https://www.pinterest.com/{uname}/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)
            print("PROFILE URL:", page.url, flush=True)
            print("PROFILE TITLE:", await page.title(), flush=True)
            try:
                body = await page.evaluate("() => document.body.innerText.slice(0, 1200)")
                print("PROFILE BODY:", body.replace(chr(10), " | ")[:1200], flush=True)
            except Exception as e:
                print("body err:", str(e)[:150], flush=True)
            shot = os.path.join(ACC, "pinterest_profile.png")
            try:
                await page.screenshot(path=shot, timeout=30000)
                print("PROFILE SHOT:", shot, flush=True)
            except Exception as e:
                print("shot err:", str(e)[:150], flush=True)


asyncio.run(main())
