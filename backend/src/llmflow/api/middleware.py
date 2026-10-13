"""Pure-ASGI middleware: request size cap, security headers, request ids."""

from __future__ import annotations

import json
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
    b"cross-origin-resource-policy": b"same-site",
    b"permissions-policy": b"geolocation=(), microphone=(), camera=()",
}


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Rejects requests whose declared or actual body exceeds ``max_bytes`` with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            {"error": {"type": "request_too_large", "message": "request body too large"}}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Adds hardening headers and a server-generated request id to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        headers_in = dict(scope["headers"])
        https = scope.get("scheme") == "https" or headers_in.get(b"x-forwarded-proto") == b"https"
        no_store = scope["path"].startswith(("/v1", "/admin"))

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[Any] = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in _SECURITY_HEADERS.items():
                    if k not in present:
                        headers.append((k, v))
                if https:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                if no_store:
                    headers.append((b"cache-control", b"no-store"))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)
