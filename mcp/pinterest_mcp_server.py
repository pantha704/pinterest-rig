#!/usr/bin/env python3
"""Serve cloakbrowsermcp over streamable HTTP on 127.0.0.1:8933 (Pinterest rig)."""
import sys


def main():
    from cloakbrowsermcp.server import create_server
    server = create_server(caps={"vision"})
    server.settings.host = "127.0.0.1"
    server.settings.port = 8933
    server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
