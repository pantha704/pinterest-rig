#!/usr/bin/env python3
"""Rebrand v2: pfp (Change -> inject -> modal confirm) + name + username (inline validation w/ fallback) + page save (parsed refs).

Usage: rebrand2.py <image_path> <display_name> <username1> <username2_or_'-'>
"""
import asyncio
import base64
import json
import os
import re
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


def get_snap(resp_text):
    """If JSON-wrapped, pull the 'snapshot' string; else return as-is."""
    try:
        obj = json.loads(resp_text)
        if isinstance(obj, dict) and "snapshot" in obj:
            return obj["snapshot"]
    except Exception:
        pass
    return resp_text


def find_ref(resp_text, *labels):
    snap = get_snap(resp_text)
    for lab in labels:
        m = re.search(r'\[(@e\d+)\]\s+(?:button|link)\s+"' + re.escape(lab) + r'"', snap)
        if m:
            return m.group(1), snap
    return None, snap


def all_buttons(snap):
    return re.findall(r'\[(@e\d+)\]\s+button\s+"([^"]{0,30})"', snap)


async def main():
    image_path, display_name, uname1, uname2 = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    img_b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    fname = os.path.basename(image_path)
    async with streamable_http_client(URL) as ctx:
        r, w = ctx[0], ctx[1]
        async with ClientSession(r, w) as s:
            await s.initialize()
            r1 = await call(s, "cloak_new_page", {"url": "about:blank"})
            page_id = json.loads(r1).get("page_id")
            print("PAGE:", page_id, flush=True)

            print("---- goto settings ----", flush=True)
            await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/settings/edit-profile/", "timeout": 90000})
            await asyncio.sleep(7)

            # ---------- PFP ----------
            print("---- pfp: click Change ----", flush=True)
            r3 = await call(s, "cloak_snapshot", {"page_id": page_id})
            change_ref, snap0 = find_ref(r3, "Change")
            page_save_ref, _ = find_ref(r3, "Save")
            print("change_ref:", change_ref, "| page_save_ref:", page_save_ref, flush=True)
            if change_ref:
                r4 = await call(s, "cloak_click", {"page_id": page_id, "ref": change_ref})
                print("CHANGE CLICK:", r4[:160], flush=True)
                await asyncio.sleep(3)

            print("---- pfp: inject ----", flush=True)
            r5 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": f"""(async () => {{
              try {{
                let inputs = Array.from(document.querySelectorAll('input[type=file]'));
                if (!inputs.length) {{
                  inputs = Array.from(document.querySelectorAll('input[accept*="image"], input[accept*="png"]'));
                }}
                const mk = () => {{
                  const bin = atob("{img_b64}");
                  const bytes = new Uint8Array(bin.length);
                  for (let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
                  return new File([bytes], "{fname}", {{type:"image/png"}});
                }};
                const dt = new DataTransfer(); dt.items.add(mk());
                if (inputs.length) {{
                  const inp = inputs[0];
                  inp.files = dt.files;
                  inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                  inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                  return 'INJECTED_INPUT ' + (inp.accept||'?');
                }}
                // fallback: drop on a dialog/dropzone
                const dz = document.querySelector('[role="dialog"]') || document.querySelector('[data-test-id*="upload"]') || document.querySelector('[class*="drop" i]');
                if (dz) {{
                  const ev = new DragEvent('drop', {{bubbles:true, cancelable:true, dataTransfer:dt}});
                  dz.dispatchEvent(ev);
                  const ev2 = new DragEvent('dragover', {{bubbles:true, cancelable:true, dataTransfer:dt}});
                  dz.dispatchEvent(ev2);
                  dz.dispatchEvent(new DragEvent('drop', {{bubbles:true, cancelable:true, dataTransfer:dt}}));
                  return 'DROPPED_ON ' + dz.tagName + '/' + (dz.className||'').toString().slice(0,40);
                }}
                return 'NO_TARGET (inputs=0, dz=0)';
              }} catch(e) {{ return 'ERR ' + e; }}
            }})()"""})
            print("UPLOAD:", r5[:300], flush=True)
            await asyncio.sleep(5)

            print("---- pfp: modal check ----", flush=True)
            r6 = await call(s, "cloak_snapshot", {"page_id": page_id})
            snap6 = get_snap(r6)
            btns = all_buttons(snap6)
            print("buttons now:", btns[:25], flush=True)
            has_cancel = any(b[1].strip().lower() in ("cancel", "delete") for b in btns)
            modal_save = None
            if has_cancel:
                # photo modal is open; its Save is the LAST save-ish button
                cands = [b for b in btns if b[1].strip().lower() in ("save", "done", "apply", "next")]
                if cands:
                    modal_save = cands[-1][0]
                    print("modal confirm:", cands[-1], flush=True)
                    r7 = await call(s, "cloak_click", {"page_id": page_id, "ref": modal_save})
                    print("MODAL CLICK:", r7[:160], flush=True)
                    await asyncio.sleep(4)
            else:
                print("no modal detected after upload", flush=True)

            # ---------- FIELDS ----------
            print("---- fields ----", flush=True)

            # capture current username for safe revert / fallback
            orig_uname = None
            try:
                r_cur = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => { const un = document.querySelector('input[id="username"],input[name="username"]'); return un ? un.value : ''; })()"""})
                obj_cur = json.loads(r_cur)
                val_cur = obj_cur.get("result", "") if isinstance(obj_cur, dict) else str(obj_cur)
                mm = re.search(r"[A-Za-z0-9_]{3,}", str(val_cur))
                if mm:
                    orig_uname = mm.group(0)
            except Exception as e:
                print("username capture failed:", str(e)[:100], flush=True)
            print("current username captured:", orig_uname, flush=True)

            async def set_uname(u):
                r = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
                  const setVal = (el, v) => {
                    const proto = Object.getPrototypeOf(el);
                    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                    desc.set.call(el, v);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                  };
                  const fn = document.querySelector('input[id="first_name"],input[name="first_name"]');
                  if (fn) setVal(fn, "DISPLAY_NAME_PLACEHOLDER");
                  const un = document.querySelector('input[id="username"],input[name="username"]');
                  if (un) setVal(un, "UNAME_PLACEHOLDER");
                  return 'set';
                })()""".replace("DISPLAY_NAME_PLACEHOLDER", display_name).replace("UNAME_PLACEHOLDER", u)})
                await asyncio.sleep(4)
                rchk = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
                  const un = document.querySelector('input[id="username"],input[name="username"]');
                  if (!un) return 'NO_FIELD';
                  const cont = un.closest('div');
                  const txt = cont ? cont.innerText : '';
                  return JSON.stringify({val: un.value, hint: txt.slice(0,220), invalid: /isn.?t available|not available|already (in use|taken)|can only contain|too (long|short)/i.test(txt)});
                })()"""})
                return rchk

            final_uname = None
            for idx, u in enumerate([uname1, uname2]):
                if not u or u == "-":
                    continue
                print(f"-- trying username {idx+1}: {u}", flush=True)
                rchk = await set_uname(u)
                print("uname check:", rchk[:400], flush=True)
                so = rchk.replace('\\"', '"')
                invalid = '"invalid":true' in so or "invalid\":true" in so
                if not invalid:
                    final_uname = u
                    print("username accepted:", u, flush=True)
                    break
                print(f"username {u} rejected by validation", flush=True)
            if final_uname is None:
                print("no username accepted — reverting to current value", flush=True)
                if orig_uname:
                    await set_uname(orig_uname)
                else:
                    print("no captured username — leaving field untouched", flush=True)

            await asyncio.sleep(3)
            # ---------- SAVE ----------
            print("---- save ----", flush=True)
            r8 = await call(s, "cloak_snapshot", {"page_id": page_id})
            save_ref, snap8 = find_ref(r8, "Save")
            print("save ref:", save_ref, flush=True)
            if not save_ref:
                r8b = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
                  const cands = Array.from(document.querySelectorAll('button,[role=button]'));
                  const b = cands.find(x => (x.innerText||'').trim().toLowerCase() === 'save');
                  if (b) { b.click(); return 'JS_CLICKED_SAVE'; }
                  return 'NO_SAVE_BUTTON';
                })()"""})
                print("js fallback:", r8b[:200], flush=True)
            else:
                r9 = await call(s, "cloak_click", {"page_id": page_id, "ref": save_ref})
                print("SAVE CLICK:", r9[:200], flush=True)
            await asyncio.sleep(6)

            # ---------- VERIFY ----------
            print("---- verify (reload) ----", flush=True)
            await call(s, "cloak_navigate", {"page_id": page_id, "url": "https://www.pinterest.com/settings/edit-profile/", "timeout": 90000})
            await asyncio.sleep(7)
            r10 = await call(s, "cloak_evaluate", {"page_id": page_id, "expression": """(() => {
              const un = document.querySelector('input[id="username"],input[name="username"]');
              const fn = document.querySelector('input[id="first_name"],input[name="first_name"]');
              return JSON.stringify({url: location.href, username: un ? un.value : null, first_name: fn ? fn.value : null});
            })()"""})
            print("VERIFY:", r10[:400], flush=True)

            # profile page screenshot
            profile_user = final_uname or orig_uname
            target = f"https://www.pinterest.com/{profile_user}/" if profile_user else "https://www.pinterest.com/settings/edit-profile/"
            await call(s, "cloak_navigate", {"page_id": page_id, "url": target, "timeout": 90000})
            await asyncio.sleep(8)
            r11 = await call(s, "cloak_screenshot", {"page_id": page_id})
            print("PROFILE SHOT:", r11[:300], flush=True)
            print("FINAL:", json.dumps({"page_id": page_id, "username": final_uname}), flush=True)
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
