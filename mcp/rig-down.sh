#!/usr/bin/env bash
# Stop the Pinterest rig: graceful browser close, then stop the MCP server.
set -u
PY=/home/ubuntu/.local/share/uv/tools/cloakbrowsermcp/bin/python

echo "== graceful browser close =="
$PY /home/ubuntu/pinterest-rig/mcp/pinterest_close.py 2>/dev/null || true
sleep 2

echo "== stopping MCP server =="
if pkill -f "mcp/pinterest_mcp_server.py"; then
  echo "server stopped"
else
  echo "server was not running"
fi
sleep 2

echo "== checks =="
if ss -tln 2>/dev/null | grep -q ":8933"; then
  echo "WARN: port 8933 still busy"
else
  echo "port 8933 free"
fi
if ps -C chrome -o args= 2>/dev/null | grep -q "profiles/pinterest"; then
  echo "chrome procs still winding down (will self-exit shortly)"
else
  echo "chrome gone"
fi
echo "rig DOWN — restart with: bash /home/ubuntu/pinterest-rig/mcp/rig-up.sh"
