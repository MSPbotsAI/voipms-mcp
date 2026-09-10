from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from voipms_mcp.api_client import VoipmsClient
from voipms_mcp.tools.subaccounts import register as register_subaccount_tools


def build_mcp(client: VoipmsClient | None) -> FastMCP:
    """A FastMCP wired to a caller-supplied client_factory -- exactly the
    seam voipms_mcp.tools.subaccounts.register() is designed around, so tests
    never need to go through server.py's header/ContextVar plumbing or hit
    the real network."""
    mcp = FastMCP("voipms-mcp-test")
    register_subaccount_tools(mcp, lambda: client)
    return mcp


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> VoipmsClient:
    transport = httpx.MockTransport(handler)
    return VoipmsClient(
        api_username="test-user",
        api_password="test-pass",
        client=httpx.AsyncClient(transport=transport),
    )


def vendor_json_handler(
    responder: Callable[[str, dict[str, str]], dict],
) -> Callable[[httpx.Request], httpx.Response]:
    """Wrap a (method, params) -> body function into an httpx MockTransport handler."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        method = params.get("method", "")
        body = responder(method, params)
        return httpx.Response(200, json=body)

    return handler


def tool_result_text(result: object) -> str:
    """call_tool() returns (content_blocks, structured_dict); we always want
    the single text block our tools produce."""
    content_blocks, _structured = result
    assert len(content_blocks) == 1
    block = content_blocks[0]
    return block.text


def tool_result_json(result: object) -> dict:
    return json.loads(tool_result_text(result))


@pytest.fixture(autouse=True)
def no_real_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries are exercised in test_tools.py; nothing there should need to
    actually sleep for exponential backoff."""

    async def _instant_backoff(_attempt: int, _retry_after: str | None = None) -> None:
        return None

    monkeypatch.setattr(VoipmsClient, "_backoff", staticmethod(_instant_backoff))
