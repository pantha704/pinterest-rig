#!/usr/bin/env bash
# Start the Pinterest rig: MCP server (systemd) + browser launch + login verify.
set -u
PY=/home/ubuntu/.local/share/uv/tools/cloakbrowsermcp/bin/python

echo "== starting MCP server (:8933) =="
sudo -n systemctl start pinterest-rig-mcp.service 2>/dev/null || {
  # fallback: start ad-hoc if systemd unavailable
  if ! pgrep -f "mcp/pinterest_mcp_server.py" > /dev/null; then
    setsid nohup $PY /home/ubuntu/pinterest-rig/mcp/pinterest_mcp_server.py >> /home/ubuntu/pinterest-rig/mcp/server.log 2>&1 < /dev/null &
  fi
}
sleep 4
if ss -tln 2>/dev/null | grep -q ":8933"; then
  echo "server up on 8933"
else
  echo "WARN: server not listening yet"
fi

echo "== launching browser + verifying login =="
$PY /home/ubuntu/pinterest-rig/mcp/pinterest_launch.py
echo "rig UP"
