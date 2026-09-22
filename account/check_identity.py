#!/usr/bin/env python3
"""Connect to the dedicated pinterest-profile chrome over CDP, verify WHICH account is logged in, dump session cookies."""
import asyncio, json, os
from playwright.async_api import async_playwright

CDP = "http://127.0.0.1:9444"
ACC = "/home/ubuntu/pinterest-rig/account"


async def main():
    os.makedirs(ACC, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        cookies = await ctx.cookies("https://www.pinterest.com")
        out = os.path.join(ACC, "pinterest_session_cookies.json")
        with open(out, "w") as f:
            json.dump(cookies, f, indent=1)
        os.chmod(out, 0o600)
        print("cookies:", len(cookies))
        for c in cookies:
            if c["name"] in ("_auth", "csrftoken", "_pinterest_sess", "_b"):
                print(f'  {c["name"]}: len={len(c["value"])} httpOnly={c.get("httpOnly")}')

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        print("URL:", page.url)
        print("TITLE:", await page.title())

        try:
            who = await page.evaluate("""async () => {
              try {
                const m = document.cookie.match(/csrftoken=([^;]+)/);
                const csrf = m ? m[1] : '';
                const q = '/resource/UserSessionResource/get/?source_url=%2F&data=%7B%22options%22%3A%7B%7D%2C%22context%22%3A%7B%7D%7D';
                const r = await fetch(q, {headers: {'x-csrftoken': csrf, 'x-requested-with': 'XMLHttpRequest'}});
                const t = await r.text();
                return t.slice(0, 1500);
              } catch (e) { return 'ERR ' + e; }
            }""")
            print("UserSession:", who)
        except Exception as e:
            print("UserSession fetch failed:", e)

        try:
            links = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            prof, seen = [], set()
            for h in links:
                if not h or not h.startswith("/"):
                    continue
                parts = [x for x in h.split("/") if x]
                if len(parts) == 1 and parts[0] not in seen and parts[0] not in (
                    "search", "ideas", "pin", "settings", "business", "today", "explore", "news", ""):
                    seen.add(parts[0])
                    prof.append(h)
            print("profile-ish links:", prof[:25])
        except Exception as e:
            print("link scan failed:", e)

        shot = os.path.join(ACC, "pinterest_home.png")
        await page.screenshot(path=shot)
        print("screenshot:", shot)
        # NOTE: deliberately no browser.close() — close() would kill the shared chrome over CDP.


asyncio.run(main())
