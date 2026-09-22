#!/usr/bin/env python3
"""Harvest Pinterest cookies from phone Cromite (CDP 9222) -> import into VPS chrome (CDP 9444) -> verify."""
import asyncio, json, os
from playwright.async_api import async_playwright

ACC = "/home/ubuntu/pinterest-rig/account"
RAW = os.path.join(ACC, "phone_pinterest_cookies.json")


async def main():
    async with async_playwright() as p:
        # ---- 1) harvest from phone
        print("harvest: connecting to phone CDP 9222...", flush=True)
        pb = await p.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=20000)
        pcookies = await pb.contexts[0].cookies()
        keep = [c for c in pcookies if "pinterest" in c["domain"]]
        print("phone pinterest cookies:", len(keep), flush=True)
        for c in keep:
            print("   ", c["domain"], c["name"], "len", len(c["value"]), flush=True)
        with open(RAW, "w") as f:
            json.dump(keep, f, indent=1)
        os.chmod(RAW, 0o600)

        # ---- sanitize for playwright add_cookies
        sanitized = []
        for c in keep:
            e = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "secure": bool(c.get("secure", False)),
                "httpOnly": bool(c.get("httpOnly", False)),
            }
            exp = c.get("expires", -1)
            e["expires"] = exp if (exp and exp > 0) else -1
            ss = c.get("sameSite")
            if ss in ("Strict", "Lax", "None"):
                e["sameSite"] = ss
            sanitized.append(e)

        # ---- 2) import into VPS chrome
        print("import: connecting to VPS CDP 9444...", flush=True)
        vb = await p.chromium.connect_over_cdp("http://127.0.0.1:9444", timeout=20000)
        vctx = vb.contexts[0]
        await vctx.add_cookies(sanitized)
        print("imported", len(sanitized), "cookies", flush=True)

        page = vctx.pages[0] if vctx.pages else await vctx.new_page()
        page.set_default_timeout(25000)
        await page.goto("https://www.pinterest.com/settings/", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(9000)
        print("URL:", page.url, flush=True)
        print("TITLE:", await page.title(), flush=True)
        shot = os.path.join(ACC, "pinterest_after_import.png")
        try:
            await page.screenshot(path=shot, timeout=25000)
            print("shot:", shot, flush=True)
        except Exception as e:
            print("shot err:", str(e)[:150], flush=True)
        try:
            txt = await page.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText.slice(0,400) : 'NOBODY'")
            print("BODY:", txt.replace("\n", " | ")[:400], flush=True)
        except Exception as e:
            print("eval err:", str(e)[:150], flush=True)
        print("DONE (no close calls - don't kill either browser)", flush=True)


asyncio.run(main())
