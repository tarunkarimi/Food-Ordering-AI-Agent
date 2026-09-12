from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add baseline browser security headers to HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(
            message: Message,
        ) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))

                security_headers = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": (
                        b"camera=(), microphone=(), geolocation=()"
                    ),
                    b"content-security-policy": (
                        b"default-src 'self'; "
                        b"frame-ancestors 'none'; "
                        b"base-uri 'self'; "
                        b"object-src 'none'"
                    ),
                }

                existing = {key.lower() for key, _ in headers}

                for key, value in security_headers.items():
                    if key not in existing:
                        headers.append((key, value))

                message["headers"] = headers

            await send(message)

        await self.app(scope, receive, send_with_security_headers)
