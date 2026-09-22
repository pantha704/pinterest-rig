# Setup Guide

Reference deployment: Ubuntu VPS + Android phone + CloakBrowser MCP rig.
Adapt paths as needed; everything below is the exact flow this repo was built and
verified with.

## 0. Components

| Piece | Role |
|---|---|
| CloakBrowser (stealth Chromium) | the browser that talks to Pinterest |
| cloakbrowsermcp | HTTP MCP server exposing `cloak_*` page tools |
| phone (Android) | login origin + residential-IP egress + session source |
| Python 3.11+ | runs all scripts (Pillow, numpy, mcp client) |
| factory/ | renders pin images from JSON specs |
| keywords/ | harvests Pinterest trends + autocomplete |

## 1. Host prep

```bash
python3 -m pip install pillow numpy
# MCP client scripts use the cloakbrowsermcp venv python, e.g.:
#   ~/.local/share/uv/tools/cloakbrowsermcp/bin/python   (has `mcp` libs)
```

## 2. Install CloakBrowser + cloakbrowsermcp

Install per their docs. Verify:

```bash
ls ~/.cloakbrowser/                     # browser binary + profiles dir
~/.local/share/uv/tools/cloakbrowsermcp/bin/python -c "import cloakbrowsermcp; print('ok')"
```

## 3. Phone setup (egress + login)

1. SSH server on the phone (Termux/dropbear), reachable over your network
   (tailnet/LAN). 
2. Start a SOCKS tunnel from the host:
   ```bash
   ssh -D 1080 -N -o ServerAliveInterval=30 root@<PHONE_HOST> -p <PHONE_SSH_PORT>
   # verify:  curl -s --socks5-hostname 127.0.0.1:1080 https://icanhazip.com
   # → should print the phone's carrier IP
   ```
3. adb access for CDP harvesting:
   ```bash
   adb connect <PHONE_HOST>:5555
   adb -s <PHONE_HOST>:5555 shell pm list packages | grep -i cromite
   ```

## 4. Browser profile

- Persistent profile dir e.g. `~/.cloakbrowser/profiles/<brand>`.
- Launch params used everywhere: `headless`, `fingerprint_seed=<fixed>`,
  `fingerprint-platform=windows`, `proxy=socks5://127.0.0.1:1080`,
  `user_data_dir=<profile>`.
- Keep ONE profile per account/brand. Fingerprint seed must stay fixed for the
  account's lifetime.

## 5. Logging in / session harvest

Preferred: log in on the phone (Google/email), then harvest cookies into the rig:

```bash
# 1) point a local TCP port at the phone browser's devtools socket
adb -s <PHONE_HOST>:5555 forward tcp:9222 localabstract:chrome_devtools_remote
# 2) inspect:    python3 account/phone_probe.py
# 3) import:     python3 account/harvest_import.py
#    (harvest_import connects: phone CDP :9222 → rig chrome CDP :9444 and
#     add_cookies() everything pinterest-domain)
```

For the import step the rig chrome must expose a debugging port, e.g.:

```bash
~/.cloakbrowser/chromium-*/chrome --user-data-dir=$PROFILE \
  --remote-debugging-port=9444 --remote-allow-origins='*' \
  --proxy-server="socks5://127.0.0.1:1080" --headless about:blank
```

Alternative: log in inside the rig browser directly (same profile), once.

## 6. MCP server

```bash
# ad-hoc:
~/.local/share/uv/tools/cloakbrowsermcp/bin/python mcp/pinterest_mcp_server.py
# or systemd (template: mcp/pinterest-rig-mcp.service → /etc/systemd/system/)
```

Bring the rig up / down:

```bash
bash mcp/rig-up.sh      # server + launch browser + verify login
bash mcp/rig-down.sh    # graceful close + stop server
```

## 7. Content pipeline

```bash
# trends + keywords (keyless, polite)
python3 keywords/harvest.py
# design pins from specs
python3 factory/pin_factory.py render --spec factory/specs/<spec>.json --out out.png
python3 factory/pin_factory.py audit --all
# batches: see content/batch-*/manifest.csv for the poster's input format
```

## 8. Poster

`poster/poster.py --spec <pin.json>` drives the composer via MCP:
navigate → upload (File/DataTransfer injection) → fill fields → select board →
screenshot preview → **stop before Publish**. Publish is a deliberate manual step.

## 9. Operations

- Backups: tar the repo dir + `~/.cloakbrowser/profiles/<brand>` (state only,
  exclude caches). The cookie DB is the account's keys — treat as a secret.
- Never run two MCP servers against the same profile; one server ↔ one browser ↔
  one profile.
- Keep egress on the same network the session was born on (phone SOCKS here).
