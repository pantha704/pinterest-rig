#!/usr/bin/env python3
"""Rebrand the Pinterest account via MCP :8933 — pfp upload + display name + username.

Usage: rebrand.py <image_path> <display_name> <username>
Steps: availability precheck -> settings/profile -> upload pfp (File injection) ->
set name/username -> save -> verify -> screenshots.
"""
import asyncio
import base64
import json
import os
import sys
import traceback

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8933/mcp"
ACC = "/home/ubuntu/pinterest-rig/account"


async def call(s, name, args=None):
    res = await s.call_tool(name, args or {})
    parts = []
    for c in getattr(res, "content", []) or []:
        parts.append(getattr(c, "text", None) or str(c))
    return "\n".join(parts)


async def main():
    image_path, display_name, username = sys.argv[1], sys.argv[2], sys.argv[3]
    img_b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    fname = os.path.basename(image_path)
    print(f"image: {fname} ({len(img_b64)} b64 chars)", flush=True)

    async with streamable_http_client(URL) as ctx:
        r, w = ctx[0], ctx[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            rp = await call(s, "cloak_list_pages", {})
            pages = json.loads(rp)
            if isinstance(pages, dict):
                pages = pages.get("pages", [])
            print("pages:", [(p.get("page_id"), p.get("url", "")[:60]) for p in pages], flush=True)
            # Always create our OWN fresh page so we never disturb other sessions' pages
            r1 = await call(s, "cloak_new_page", {"url": "about:blank"})
            print("new page:", r1[:200], flush=True)
            page_id = None
            try:
                page_id = json.loads(r1).get("page_id")
            except Exception:
                pass
            if not page_id:
                for p in pages:
                    if "/settings" not in (p.get("url") or "") and "pin-creation" not in (p.get("url") or ""):
                        page_id = p.get("page_id")
                        break
            print("PAGE:", page_id, flush=True)

            # 1) availability precheck
            print("---- username precheck ----", flush=True)
            r2 = await call(s, "cloak_navigate", {"page_id": page_id, "url": f"https://www.pinterest.com/{username}/", "timeout": 60000})
            print("NAV:", r2[:200], flush=True)
            await asyncio.sleep(5)
            r3 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
              const b = document.body ? document.body.innerText : '';
              const nf = /not found|doesn.t exist|couldn.t find|Page not found/i.test(b);
              return nf ? 'AVAILABLE' : ('TAKEN? ' + b.slice(0,120));
            })()"""})
            print("PRECHECK:", r3[:400], flush=True)
            uname_ok = "AVAILABLE" in r3

            # 2) settings profile page
            print("---- settings/profile ----", flush=True)
            r4 = await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/settings/profile/", "timeout": 80000})
            print("NAV2:", r4[:200], flush=True)
            await asyncio.sleep(8)
            r5 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
              const inputs = Array.from(document.querySelectorAll('input')).map(i => ({id: i.id, name: i.name, type: i.type, value: (i.value||'').slice(0,30)}));
              const fileInputs = Array.from(document.querySelectorAll('input[type=file]')).map(i => ({id: i.id, name: i.name, accept: i.accept}));
              const btns = Array.from(document.querySelectorAll('button,[role=button]')).map(b => (b.innerText||'').trim()).filter(Boolean).slice(0,25);
              const photoEls = Array.from(document.querySelectorAll('img')).filter(i => (i.src||'').includes('user')).length;
              return JSON.stringify({url: location.href, inputs: inputs.slice(0,15), fileInputs, buttons: btns, userImgs: photoEls});
            })()"""})
            print("FORM:", r5[:900], flush=True)

            # 3) upload pfp via File injection
            print("---- upload pfp ----", flush=True)
            r6 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": f"""(async () => {{
              try {{
                const b64 = "{img_b64}";
                const bin = atob(b64);
                const bytes = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                const file = new File([bytes], "{fname}", {{type: "image/png"}});
                const inputs = Array.from(document.querySelectorAll('input[type=file]'));
                if (!inputs.length) return 'NO_FILE_INPUT';
                const inp = inputs[0];
                const dt = new DataTransfer();
                dt.items.add(file);
                inp.files = dt.files;
                inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                return 'INJECTED size=' + file.size;
              }} catch (e) {{ return 'ERR ' + e; }}
            }})()"""})
            print("UPLOAD:", r6[:400], flush=True)
            await asyncio.sleep(6)

            # 4) set name + username (native setter + events; username only if precheck says available)
            print("---- set fields ----", flush=True)
            if uname_ok:
                uname_js = 'const un = document.querySelector(\'input[id="username"],input[name="username"]\'); if (un) { setVal(un, "' + username + '"); out.push("username OK"); } else out.push("no username");'
            else:
                uname_js = 'out.push("username SKIPPED (taken or unknown)");'
            r7 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": f"""(() => {{
              const setVal = (el, v) => {{
                const proto = Object.getPrototypeOf(el);
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                desc.set.call(el, v);
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
              }};
              const out = [];
              const fn = document.querySelector('input[id="first_name"],input[name="first_name"]');
              if (fn) {{ setVal(fn, "{display_name}"); out.push('first_name OK'); }} else out.push('no first_name');
              const ln = document.querySelector('input[id="last_name"],input[name="last_name"]');
              if (ln) {{ setVal(ln, ""); out.push('last_name cleared'); }} else out.push('no last_name');
              {uname_js}
              return JSON.stringify(out);
            }})()"""})
            print("FIELDS:", r7[:400], flush=True)
            await asyncio.sleep(4)

            # 5) check validation state, then find+click Save
            r8 = await call(s, "cloak_snapshot", {"page_id": page_id})
            print("SNAPSHOT(save button hunt):", r8[:1600], flush=True)
            save_ref = None
            try:
                for line in r8.splitlines():
                    if "] button" in line or "] link" in line:
                        if any(k in line.lower() for k in ("save", "submit")):
                            save_ref = line.split("]")[0].strip().lstrip("[").strip()
                            print("SAVE REF:", save_ref, "|", line[:160], flush=True)
                            break
            except Exception as e:
                print("ref parse err:", e, flush=True)

            if save_ref:
                r9 = await call(s, "cloak_click", {"page_id": page_id, "ref": save_ref})
                print("SAVE CLICK:", r9[:300], flush=True)
                await asyncio.sleep(6)
            else:
                print("no save ref parsed — trying JS click fallback", flush=True)
                r9b = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
                  const cands = Array.from(document.querySelectorAll('button,[role=button],div[role=button]'));
                  const b = cands.find(x => (x.innerText||'').trim().toLowerCase() === 'save');
                  if (b) { b.click(); return 'JS_CLICKED_SAVE'; }
                  return 'NO_SAVE_BUTTON ' + cands.map(x=>(x.innerText||'').trim()).filter(Boolean).slice(0,20).join('|');
                })()"""})
                print("JS FALLBACK:", r9b[:400], flush=True)
                await asyncio.sleep(6)

            # 6) verify (fresh reload so we see what actually persisted)
            print("---- verify (reload) ----", flush=True)
            r10a = await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/settings/profile/", "timeout": 80000})
            print("RELOAD:", r10a[:200], flush=True)
            await asyncio.sleep(7)
            r10 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
              const b = document.body ? document.body.innerText.slice(0,300) : '';
              const un = document.querySelector('input[id="username"],input[name="username"]');
              const fn = document.querySelector('input[id="first_name"],input[name="first_name"]');
              return JSON.stringify({url: location.href, username: un ? un.value : null, first_name: fn ? fn.value : null, head: b.slice(0,200)});
            })()"""})
            print("VERIFY:", r10[:600], flush=True)
            r11 = await call(s, "cloak_screenshot", {"page_id": page_id})
            print("SHOT:", r11[:300], flush=True)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
