#!/usr/bin/env python3
"""STAGE 1d: accessibility snapshot of the open composer — learn the MCP ref IDs for
Title / Description / Link / Board / Publish so poster.py can use real clicks+typing."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import AsyncRig, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEST = os.path.join(HERE, "test")


async def main():
    pid = open(os.path.join(TEST, "page_id.txt")).read().strip()
    async with AsyncRig() as rig:
        snap = await rig.snapshot(pid)
        with open(os.path.join(TEST, "03b_composer_snapshot.txt"), "w") as f:
            f.write(snap)
        log("snapshot len:", len(snap))
        print(snap[:12000])
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
