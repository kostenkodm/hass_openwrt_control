"""Loopback HTTPS ubus simulator, with autonomous probe cycles."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import hmac
import json
from pathlib import Path
import secrets
import ssl
import time

from aiohttp import web

from .engine import Controller, ModelError, READ_METHODS, WRITE_METHODS

APP_KEY = web.AppKey("lab", object)


class Lab:
    def __init__(self, controller, credentials):
        self.controller, self.credentials = controller, credentials
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.probes = {v: {"successes": 3, "latency": 40 + i * 30, "egress": True}
                       for i, v in enumerate(controller.data["vpns"])}
        self.task = None

    def sample(self):
        for vpn, values in self.probes.items():
            self.controller.record_probe(vpn, **values)

    def sample_and_tick(self):
        self.sample()
        self.controller.tick()

    def dispatch(self, method, args):
        return (self.controller.read(method, args) if method in READ_METHODS
                else self.controller.mutate(method, args))

    async def cycle(self):
        while True:
            async with self.lock:
                await asyncio.to_thread(self.sample_and_tick)
                interval = self.controller.data["settings"]["probe_interval"]
            await asyncio.sleep(interval)

    async def rpc(self, request):
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            return web.json_response({"jsonrpc": "2.0", "id": None,
                                      "error": {"code": -32700, "message": "Parse error"}})
        ident = body.get("id") if isinstance(body, dict) else None
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or body.get("method") != "call":
            return web.json_response({"jsonrpc": "2.0", "id": ident,
                                      "error": {"code": -32600, "message": "Invalid request"}})
        params = body.get("params")
        if (not isinstance(params, list) or len(params) != 4 or
                not all(isinstance(p, str) for p in params[:3]) or not isinstance(params[3], dict)):
            return web.json_response({"jsonrpc": "2.0", "id": ident,
                                      "error": {"code": -32602, "message": "Invalid params"}})
        sid, obj, method, args = params
        result = [6]
        async with self.lock:
            if obj == "session" and method == "login":
                if (set(args) == {"username", "password"} and
                    isinstance(args["username"], str) and isinstance(args["password"], str) and
                    hmac.compare_digest(args["username"].encode(), self.credentials["username"].encode()) and
                    hmac.compare_digest(args["password"].encode(), self.credentials["password"].encode())):
                    sid = secrets.token_hex(16)
                    now = time.monotonic()
                    self.sessions = {k: v for k, v in self.sessions.items() if v > now}
                    if len(self.sessions) >= 64:
                        self.sessions.pop(next(iter(self.sessions)))
                    self.sessions[sid] = now + 300
                    result = [0, {"ubus_rpc_session": sid, "timeout": 300}]
            elif self.sessions.get(sid, 0) > time.monotonic():
                if obj == "session" and method == "destroy" and args == {"ubus_rpc_session": sid}:
                    self.sessions.pop(sid)
                    result = [0]
                elif obj == "vpn.controller" and method in READ_METHODS | WRITE_METHODS:
                    try:
                        if method == "diagnose":
                            self.sample()
                        value = await asyncio.to_thread(self.dispatch, method, args)
                        result = [0, value]
                    except ModelError as err:
                        result = [0, {"ok": False, "error": {"code": err.code}}]
                    except (TypeError, ValueError, KeyError):
                        result = [0, {"ok": False, "error": {"code": "invalid_argument"}}]
        return web.json_response({"jsonrpc": "2.0", "id": ident, "result": result})

    async def lab_control(self, request):
        """Out-of-band local test facility, never part of vpn.controller or its ACL."""
        supplied = request.headers.get("X-Lab-Token", "")
        if not hmac.compare_digest(supplied.encode(), self.credentials["lab_token"].encode()):
            raise web.HTTPForbidden()
        try:
            body = await request.json()
            async with self.lock:
                if "fault" in body:
                    if body["fault"] not in (None, "apply", "verify", "rollback", "conflict"):
                        raise ValueError
                    self.controller.fault = body["fault"]
                if "probes" in body:
                    for vpn, values in body["probes"].items():
                        if vpn not in self.probes:
                            raise ValueError
                        if set(values) - {"successes", "latency", "egress", "section_checks"}:
                            raise ValueError
                        self.probes[vpn].update(values)
                for _ in range(min(max(int(body.get("cycles", 0)), 0), 10)):
                    await asyncio.to_thread(self.sample_and_tick)
            return web.json_response({"simulated": True, "revision": self.controller.data["revision"]})
        except (ValueError, TypeError, KeyError, ModelError):
            raise web.HTTPBadRequest() from None


def create_app(controller, credentials, autonomous=True):
    lab = Lab(controller, credentials)
    app = web.Application(client_max_size=65536)
    app[APP_KEY] = lab
    app.router.add_post("/ubus", lab.rpc)
    app.router.add_post("/_lab", lab.lab_control)

    async def lifecycle(app):
        if autonomous:
            lab.task = asyncio.create_task(lab.cycle())
        yield
        if lab.task:
            lab.task.cancel()
            with suppress(asyncio.CancelledError):
                await lab.task
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, default=Path("work/lab"))
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()
    credentials = json.loads((args.lab / "credentials.json").read_text())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.lab / "server.pem", args.lab / "server.key")
    app = create_app(Controller(args.lab / "controller.json"), credentials)
    # Production or LAN binding is intentionally absent from this simulator.
    web.run_app(app, host="127.0.0.1", port=args.port, ssl_context=context, access_log=None)


if __name__ == "__main__":
    main()
