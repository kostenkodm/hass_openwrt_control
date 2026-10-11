"""Wire-level error handling, not mocked aiohttp responses."""
import json
import ssl

from aiohttp import ClientSession, web
import pytest

from custom_components.openwrt_vpn.api import ProtocolError, UbusClient, tls_context


@pytest.fixture
def response_case(request):
    return request.param


@pytest.mark.parametrize("response_case", [
    "wrong_id", "wrong_id_type", "invalid_json", "invalid_result", "http_500", "redirect", "oversize", "bad_application_error",
], indirect=True)
async def test_bad_rpc_responses_rejected(lab, response_case):
    async def handler(request):
        body = await request.json()
        if response_case == "http_500":
            return web.Response(status=500)
        if response_case == "redirect":
            return web.Response(status=302, headers={"Location": "/redirect-target"})
        if response_case == "invalid_json":
            return web.Response(text="<html>error</html>")
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": [0, {}]}
        if response_case == "wrong_id":
            payload["id"] += 1
        elif response_case == "wrong_id_type":
            payload["id"] = True
        elif response_case == "invalid_result":
            payload["result"] = {"unexpected": True}
        elif response_case == "oversize":
            payload["result"][1]["text"] = "x" * (1024 * 1024 + 1)
        elif response_case == "bad_application_error":
            payload["result"][1] = {"ok": False, "error": {"code": []}}
        return web.json_response(payload)

    app = web.Application()
    app.router.add_post("/ubus", handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(lab["folder"] / "server.pem", lab["folder"] / "server.key")
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ctx).start()
    try:
        async with ClientSession() as session:
            client = UbusClient(session, f"https://127.0.0.1:{runner.addresses[0][1]}/ubus",
                                "hass", "unused", tls_context(lab["ca"]))
            with pytest.raises(ProtocolError):
                await client._rpc("test", "vpn.controller", "status", {})
    finally:
        await runner.cleanup()


async def test_chunked_json_is_read_completely(lab):
    async def handler(request):
        body = await request.json()
        result = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": [0, {"message": "valid"}]}).encode()
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        for byte in result:
            await response.write(bytes([byte]))
        await response.write_eof()
        return response
    app = web.Application()
    app.router.add_post("/ubus", handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(lab["folder"] / "server.pem", lab["folder"] / "server.key")
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ctx).start()
    try:
        async with ClientSession() as session:
            client = UbusClient(session, f"https://127.0.0.1:{runner.addresses[0][1]}/ubus",
                                "hass", "unused", tls_context(lab["ca"]))
            assert await client._rpc("test", "vpn.controller", "status", {}) == {"message": "valid"}
    finally:
        await runner.cleanup()
