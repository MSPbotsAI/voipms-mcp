"""Unit tests for the four voipms_* tools, mocking the vendor API over HTTP.

Test IDs (TCn) match docs/tickets/PRD-18607.md "测试用例" / PRD-18607.ac.json.
TC12 (multi-tenant isolation) and TC13 (Library/registry deployment) are
manual per that document -- they need a live gateway and two real tenants,
which is not something a unit test can exercise.
"""

from __future__ import annotations

import httpx
import pytest

from conftest import build_mcp, make_client, tool_result_json, tool_result_text, vendor_json_handler

SUBACCOUNT_OPS = {
    "account": "100001_ops",
    "description": "Ops line",
    "internal_voicemail": "200",
    "callerid_number": "+15551234567",
}

VOICEMAIL_BOXES = [
    {"mailbox": "200", "description": "Ops voicemail"},
    {"mailbox": "201", "description": "Support voicemail"},
]


def _accounts_and_boxes(accounts: list[dict], boxes: list[dict]):
    def responder(method: str, params: dict) -> dict:
        if method == "getSubAccounts":
            wanted = params.get("account")
            matches = [a for a in accounts if a["account"] == wanted] if wanted else list(accounts)
            return {"status": "success", "accounts": matches}
        if method == "getVoicemails":
            return {"status": "success", "voicemails": list(boxes)}
        if method == "setSubAccount":
            return {"status": "success"}
        raise AssertionError(f"unexpected method {method}")

    return responder


@pytest.mark.asyncio
async def test_tools_list_snapshot() -> None:
    mcp = build_mcp(None)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "voipms_find_subaccount",
        "voipms_get_subaccount",
        "voipms_list_voicemail_boxes",
        "voipms_set_voicemail_redirect",
    }
    required = {t.name: set(t.inputSchema.get("required", [])) for t in tools}
    assert required["voipms_find_subaccount"] == {"query"}
    assert required["voipms_get_subaccount"] == {"account"}
    assert required["voipms_list_voicemail_boxes"] == {"account"}
    assert required["voipms_set_voicemail_redirect"] == {"account", "target_mailbox"}
    annotations = {t.name: t.annotations for t in tools}
    assert annotations["voipms_get_subaccount"].readOnlyHint is True
    assert annotations["voipms_set_voicemail_redirect"].destructiveHint is True
    assert annotations["voipms_set_voicemail_redirect"].idempotentHint is False


@pytest.mark.asyncio
async def test_tc1_find_subaccount_match() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_find_subaccount", {"query": "ops"})
    body = tool_result_json(result)
    assert body["matches"] == [{"account": "100001_ops", "description": "Ops line"}]


@pytest.mark.asyncio
async def test_tc2_find_subaccount_no_match_returns_empty_not_error() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_find_subaccount", {"query": "nonexistent"})
    body = tool_result_json(result)
    assert body == {"matches": []}


@pytest.mark.asyncio
async def test_tc3_get_subaccount_includes_current_voicemail() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_get_subaccount", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert body["internal_voicemail"] == "200"


@pytest.mark.asyncio
async def test_tc4_get_subaccount_not_found() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_get_subaccount", {"account": "missing_account"})
    body = tool_result_json(result)
    assert body == {
        "error": {
            "code": "not_found",
            "message": "sub-account missing_account not found",
            "retryable": False,
        }
    }


@pytest.mark.asyncio
async def test_tc5_list_voicemail_boxes_returns_entries() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_list_voicemail_boxes", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert len(body["mailboxes"]) == 2


@pytest.mark.asyncio
async def test_tc6_list_voicemail_boxes_empty_is_not_an_error() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], [])))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_list_voicemail_boxes", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert body == {"mailboxes": []}


@pytest.mark.asyncio
async def test_tc7_set_voicemail_redirect_reports_before_after() -> None:
    client = make_client(vendor_json_handler(_accounts_and_boxes([SUBACCOUNT_OPS], VOICEMAIL_BOXES)))
    mcp = build_mcp(client)
    result = await mcp.call_tool(
        "voipms_set_voicemail_redirect", {"account": "100001_ops", "target_mailbox": "201"}
    )
    body = tool_result_json(result)
    assert body == {
        "account": "100001_ops",
        "field": "internal_voicemail",
        "before": "200",
        "after": "201",
    }


@pytest.mark.asyncio
async def test_tc8_set_voicemail_redirect_preserves_other_fields() -> None:
    captured: dict = {}

    def responder(method: str, params: dict) -> dict:
        if method == "getSubAccounts":
            return {"status": "success", "accounts": [SUBACCOUNT_OPS]}
        if method == "getVoicemails":
            return {"status": "success", "voicemails": VOICEMAIL_BOXES}
        if method == "setSubAccount":
            captured.update(params)
            return {"status": "success"}
        raise AssertionError(f"unexpected method {method}")

    client = make_client(vendor_json_handler(responder))
    mcp = build_mcp(client)
    await mcp.call_tool("voipms_set_voicemail_redirect", {"account": "100001_ops", "target_mailbox": "201"})

    assert captured["internal_voicemail"] == "201"
    # Everything else present on the original record must be sent back
    # unchanged -- this is the read-modify-write contract PRD-18607 exists
    # to enforce (setSubAccount is a full-record write, verified against
    # python-voipms; see api_client.py's module docstring).
    assert captured["description"] == SUBACCOUNT_OPS["description"]
    assert captured["callerid_number"] == SUBACCOUNT_OPS["callerid_number"]
    assert captured["account"] == SUBACCOUNT_OPS["account"]


@pytest.mark.asyncio
async def test_tc9_invalid_target_rejected_without_vendor_write() -> None:
    write_attempted = False

    def responder(method: str, params: dict) -> dict:
        nonlocal write_attempted
        if method == "getSubAccounts":
            return {"status": "success", "accounts": [SUBACCOUNT_OPS]}
        if method == "getVoicemails":
            return {"status": "success", "voicemails": VOICEMAIL_BOXES}
        if method == "setSubAccount":
            write_attempted = True
            return {"status": "success"}
        raise AssertionError(f"unexpected method {method}")

    client = make_client(vendor_json_handler(responder))
    mcp = build_mcp(client)
    result = await mcp.call_tool(
        "voipms_set_voicemail_redirect", {"account": "100001_ops", "target_mailbox": "999"}
    )
    body = tool_result_json(result)
    assert body["error"]["code"] == "invalid_argument"
    assert write_attempted is False


@pytest.mark.asyncio
async def test_tc10_vendor_unauthorized_maps_and_hides_credentials() -> None:
    def responder(_method: str, _params: dict) -> dict:
        return {"status": "invalid_credentials"}

    client = make_client(vendor_json_handler(responder))
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_get_subaccount", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["retryable"] is False
    text = tool_result_text(result)
    assert "test-pass" not in text
    assert "test-user" not in text


@pytest.mark.asyncio
async def test_tc11_upstream_5xx_exhausts_retries_then_upstream_error() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="temporarily unavailable")

    client = make_client(handler)
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_get_subaccount", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert body["error"]["code"] == "upstream_error"
    assert body["error"]["retryable"] is True
    assert attempts == 3  # SS5: limited retries, not infinite


@pytest.mark.asyncio
async def test_not_configured_when_no_credentials() -> None:
    mcp = build_mcp(None)
    calls = (
        ("voipms_find_subaccount", {"query": "x"}),
        ("voipms_get_subaccount", {"account": "x"}),
        ("voipms_list_voicemail_boxes", {"account": "x"}),
        ("voipms_set_voicemail_redirect", {"account": "x", "target_mailbox": "1"}),
    )
    for tool_name, args in calls:
        result = await mcp.call_tool(tool_name, args)
        body = tool_result_json(result)
        assert body == {
            "error": {
                "code": "not_configured",
                "message": "voipms client is not configured",
                "retryable": False,
            }
        }


@pytest.mark.asyncio
async def test_timeout_maps_to_retryable_upstream_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out")

    client = make_client(handler)
    mcp = build_mcp(client)
    result = await mcp.call_tool("voipms_get_subaccount", {"account": "100001_ops"})
    body = tool_result_json(result)
    assert body["error"]["code"] == "upstream_error"
    assert body["error"]["retryable"] is True
