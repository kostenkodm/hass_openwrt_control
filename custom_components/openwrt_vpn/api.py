"""HTTPS ubus client. No shell, generic UCI, service or network APIs."""
from __future__ import annotations

import asyncio
import itertools
import json
import ssl
import time
from urllib.parse import urlsplit
import uuid

import aiohttp

from .const import OBJECT, READ_METHODS, WRITE_METHODS


class ControllerError(Exception):
    """An error safe to show without credentials or raw RPC bodies."""


class AuthenticationError(ControllerError):
    pass


class ProtocolError(ControllerError):
    pass


class RemoteError(ControllerError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class OutcomeUnknown(ControllerError):
    def __init__(self, request_id):
        self.request_id = request_id
        super().__init__(f"Operation outcome unknown; request_id={request_id}")


def tls_context(ca_pem=""):
    """Called in an executor by HA: loading system CAs can perform file I/O."""
    ctx = ssl.create_default_context()
    if ca_pem.strip():
        ctx.load_verify_locations(cadata=ca_pem)
    return ctx


def validate_endpoint(endpoint):
    parts = urlsplit(endpoint)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise ProtocolError("Use an HTTPS endpoint without credentials, query or fragment")
    return endpoint.rstrip("/")


def validate_snapshot(data, controller_id=None, protected_interfaces=()):
    if not isinstance(data, dict) or data.get("api_version") != 1:
        raise ProtocolError("Unsupported controller snapshot")
    if not isinstance(data.get("controller_id"), str) or not data["controller_id"]:
        raise ProtocolError("Missing controller identity")
    if controller_id and data["controller_id"] != controller_id:
        raise ProtocolError("Controller identity changed")
    if type(data.get("revision")) is not int or type(data.get("latest_event_id")) is not int:
        raise ProtocolError("Invalid snapshot revision")
    protected = frozenset(protected_interfaces)
    for key in ("sections", "vpns"):
        if not isinstance(data.get(key), dict):
            raise ProtocolError(f"Invalid {key}")
        for ident, resource in data[key].items():
            if not isinstance(resource, dict) or resource.get("id") != ident or (key == "vpns" and ident in protected):
                raise ProtocolError("Invalid or protected resource in snapshot")
    for section in data["sections"].values():
        if section.get("connection_type") != "vpn" or not isinstance(section.get("policy"), dict):
            raise ProtocolError("Invalid managed section")
        if section.get("applied_vpn") in protected:
            raise ProtocolError("Protected interface was assigned")
    return data


class UbusClient:
    def __init__(self, session, endpoint, username, password, context):
        self.session = session
        self.endpoint = validate_endpoint(endpoint)
        if context is None or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ProtocolError("Server certificate and hostname verification are required")
        self.context, self.username, self.password = context, username, password
        self._sid, self._expires = None, 0
        self._ids = itertools.count(1)
        self._login_lock = asyncio.Lock()

    async def _rpc(self, sid, obj, method, args):
        ident = next(self._ids)
        body = {"jsonrpc": "2.0", "id": ident, "method": "call",
                "params": [sid, obj, method, args]}
        try:
            async with self.session.post(
                self.endpoint, json=body, ssl=self.context, allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise ProtocolError(f"HTTP status {response.status}")
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise ProtocolError("RPC response too large")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError) as err:
                    raise ProtocolError("Invalid RPC JSON") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            # Never include the URL, request body, password, session or raw server error.
            raise ControllerError("HTTPS request failed") from err
        if (not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0"
                or type(payload.get("id")) is not int or payload["id"] != ident):
            raise ProtocolError("RPC response does not match request")
        if "error" in payload:
            error = payload["error"]
            if isinstance(error, dict) and type(error.get("code")) is int and error["code"] in (-32001, -32002):
                raise AuthenticationError("RPC session expired or permission denied")
            raise ProtocolError("JSON-RPC error")
        result = payload.get("result")
        if not isinstance(result, list) or len(result) not in (1, 2) or type(result[0]) is not int:
            raise ProtocolError("Invalid ubus result")
        if result[0] == 6:
            raise AuthenticationError("RPC credentials expired or permission denied")
        if result[0] != 0:
            raise RemoteError(f"ubus_{result[0]}", "Controller RPC failed")
        value = result[1] if len(result) == 2 else None
        if isinstance(value, dict) and value.get("ok") is False:
            error = value.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if not isinstance(code, str):
                raise ProtocolError("Invalid application error")
            # Messages are mapped locally rather than showing an arbitrary server string.
            raise RemoteError(code, {
                "conflict": "Configuration changed; refresh and retry with a new request",
                "unavailable": "VPN is not confirmed available",
                "recovery_required": "Controller requires recovery",
                "invalid_argument": "Controller rejected the arguments",
            }.get(code, "Controller rejected the request"))
        return value

    async def _ensure_session(self):
        async with self._login_lock:
            if self._sid and time.monotonic() < self._expires - 5:
                return
            login = await self._rpc("0" * 32, "session", "login",
                                    {"username": self.username, "password": self.password})
            if not isinstance(login, dict) or not isinstance(login.get("ubus_rpc_session"), str):
                raise ProtocolError("Invalid login response")
            ttl = login.get("timeout")
            if type(ttl) not in (int, float) or not 10 <= ttl <= 86400:
                raise ProtocolError("Invalid session duration")
            self._sid, self._expires = login["ubus_rpc_session"], time.monotonic() + ttl

    async def read(self, method, args=None):
        if method not in READ_METHODS:
            raise ProtocolError("Read method not allowed")
        await self._ensure_session()
        try:
            return await self._rpc(self._sid, OBJECT, method, args or {})
        except AuthenticationError:
            self._sid = None
            await self._ensure_session()
            return await self._rpc(self._sid, OBJECT, method, args or {})

    async def mutate(self, method, values, revision):
        if method not in WRITE_METHODS:
            raise ProtocolError("Write method not allowed")
        await self._ensure_session()
        request_id = str(uuid.uuid4())
        args = {**values, "request_id": request_id, "expected_revision": revision}
        try:
            outcome = await self._rpc(self._sid, OBJECT, method, args)
        except (AuthenticationError, RemoteError):
            raise
        except ControllerError as err:
            # A dropped response is never evidence the write failed. Do not replay it.
            try:
                outcome = await self.read("operation", {"request_id": request_id})
            except ControllerError:
                raise OutcomeUnknown(request_id) from err
            if isinstance(outcome, dict) and outcome.get("status") != "unknown":
                return await self._finish_operation(outcome, request_id)
            raise OutcomeUnknown(request_id) from err
        return await self._finish_operation(outcome, request_id)

    async def _finish_operation(self, outcome, request_id):
        # Poll the durable operation, never replay a mutation. Probes/rendering
        # run in the native worker, so HTTP reads remain responsive.
        deadline = time.monotonic() + 180
        while isinstance(outcome, dict) and outcome.get("status") == "pending":
            if time.monotonic() >= deadline:
                raise OutcomeUnknown(request_id)
            await asyncio.sleep(1)
            try:
                outcome = await self.read("operation", {"request_id": request_id})
            except ControllerError as err:
                raise OutcomeUnknown(request_id) from err
            if not isinstance(outcome, dict) or outcome.get("status") == "unknown":
                raise OutcomeUnknown(request_id)
        if isinstance(outcome, dict) and outcome.get("status") == "rejected":
            error = outcome.get("error", {})
            code = error.get("code", "rejected") if isinstance(error, dict) else "rejected"
            raise RemoteError(code, "Controller rejected the operation")
        return outcome

    async def close(self):
        if self._sid:
            try:
                await self._rpc(self._sid, "session", "destroy", {"ubus_rpc_session": self._sid})
            except ControllerError:
                pass
            self._sid = None
