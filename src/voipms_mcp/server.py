"""FastMCP factory + per-request credential middleware.

Follows vendor-mcp-development-sop.md SS9's recommended module split:
credentials come only from headers (SS3.1), are stored in a
``contextvars.ContextVar`` and reset in a ``finally`` so two concurrent
tenants' requests can never see each other's credentials (SS3.3), and the
service never falls back to an environment variable if a header is missing
(SS3.1's explicit prohibition).
"""

from __future__ import annotations

import contextvars

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from voipms_mcp.api_client import VoipmsClient
from voipms_mcp.config import settings
from voipms_mcp.tools.subaccounts import register as register_subaccount_tools

API_USERNAME_HEADER = "x-voipms-api-username"
API_PASSWORD_HEADER = "x-voipms-api-password"

INSTRUCTIONS = (
    "VOIP.ms sub-account and voicemail redirect management. Use "
    "voipms_find_subaccount to locate a sub-account, voipms_get_subaccount to "
    "inspect its current configuration, voipms_list_voicemail_boxes to see "
    "valid redirect targets, then voipms_set_voicemail_redirect to safely "
    "change the redirect -- it always reads the full record first so other "
    "fields are never reset."
)

_credentials: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "voipms_credentials", default=None
)


def current_credentials() -> tuple[str, str] | None:
    return _credentials.get()


def client_factory() -> VoipmsClient | None:
    """Build a fresh, request-scoped client from whatever credentials the
    current request's middleware put in the ContextVar. Returns None if
    called outside a request that carried valid headers (surfaced by tools
    as the `not_configured` error, per vendor-mcp-development-sop.md SS9)."""
    creds = current_credentials()
    if creds is None:
        return None
    username, password = creds
    return VoipmsClient(api_username=username, api_password=password, base_url=settings.base_url)


def create_mcp() -> FastMCP:
    mcp = FastMCP(
        "voipms-mcp",
        instructions=INSTRUCTIONS,
        host=settings.mcp_http_host,
        port=settings.mcp_http_port,
        # SS1.3: must be truly stateless, not merely "doesn't rely on stickiness".
        stateless_http=True,
        # SS7: service sits behind a reverse proxy/internal network, so the
        # Host header is never localhost -- DNS-rebinding protection would
        # reject every real call with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_subaccount_tools(mcp, client_factory)
    return mcp


class CredentialMiddleware:
    """Extracts VOIP.ms credentials from headers on the MCP path; 401s if
    either is missing. Only wraps the MCP path -- /health must stay a pure
    local probe per SS1.1, not fail because of missing tenant headers."""

    def __init__(self, app: ASGIApp, mcp_path: str) -> None:
        self._app = app
        self._mcp_path = mcp_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != self._mcp_path:
            await self._app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        username = headers.get(API_USERNAME_HEADER)
        password = headers.get(API_PASSWORD_HEADER)
        if not username or not password:
            missing = [
                name
                for name, value in (
                    ("X-Voipms-Api-Username", username),
                    ("X-Voipms-Api-Password", password),
                )
                if not value
            ]
            response = JSONResponse(
                {
                    "error": {
                        "code": "unauthorized",
                        "message": f"missing required header(s): {', '.join(missing)}",
                        "retryable": False,
                    }
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token = _credentials.set((username, password))
        try:
            await self._app(scope, receive, send)
        finally:
            _credentials.reset(token)


async def health(_: Request) -> JSONResponse:
    # SS1.1: pure local probe, must never depend on the vendor API being up.
    return JSONResponse({"status": "ok"})


def create_app() -> ASGIApp:
    mcp = create_mcp()
    # Calling this now (rather than lazily) is what makes `mcp.session_manager`
    # below non-None -- see FastMCP.streamable_http_app's lazy-init comment.
    mcp_app = mcp.streamable_http_app()

    app = Starlette(
        routes=[
            Route("/health", health),
            *mcp_app.routes,
        ],
        # SS7's lifespan pitfall: Mount() does not run a sub-app's lifespan, so
        # the outer app's lifespan must directly drive the same session
        # manager instance the routes above were built from.
        lifespan=lambda _app: mcp.session_manager.run(),
    )
    return CredentialMiddleware(app, mcp_path=mcp.settings.streamable_http_path)
