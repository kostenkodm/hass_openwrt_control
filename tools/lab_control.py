"""Inject synthetic probes and failures into the loopback-only laboratory."""
import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import ClientSession
from custom_components.openwrt_vpn.api import tls_context


async def run(args):
    credentials = json.loads((args.lab / "credentials.json").read_text())
    payload = {"cycles": args.cycles}
    if args.vpn:
        payload["probes"] = {args.vpn: {"successes": 0 if args.down else 3, "egress": not args.down}}
    if args.fault:
        payload["fault"] = args.fault
    async with ClientSession() as session:
        async with session.post(f"https://127.0.0.1:{args.port}/_lab", json=payload,
                headers={"X-Lab-Token": credentials["lab_token"]},
                ssl=tls_context((args.lab / "ca.pem").read_text())) as response:
            response.raise_for_status()
            print(json.dumps(await response.json()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path("work/lab"))
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--vpn")
    parser.add_argument("--down", action="store_true")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--fault", choices=["apply", "verify", "rollback", "conflict"])
    asyncio.run(run(parser.parse_args()))
