"""The four voipms_* tools (PRD-18607 docs/tickets/PRD-18607.md "数据与接口契约").

``voipms_set_voicemail_redirect`` is the safety-critical one: it always reads
the full current sub-account record, validates the target mailbox exists,
then writes the full record back with only ``internal_voicemail`` changed --
never a single-field blind write (this is the whole point of the ticket; see
api_client.py's module docstring for why ``setSubAccount`` requiring the full
record is a confirmed vendor behavior, not an assumption).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from voipms_mcp.api_client import VoipmsApiError, VoipmsClient
from voipms_mcp.errors import error_envelope, map_status_code

ClientFactory = Callable[[], "VoipmsClient | None"]


def _dumps(obj: object) -> str:
    # vendor-mcp-development-sop.md SS2.5: no indent, ensure_ascii=False -- both
    # are pure token cost with no benefit to the Agent consuming this.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


async def _fetch_one(client: VoipmsClient, account: str) -> dict | str | None:
    """Return the sub-account dict, an error-envelope string, or None if absent."""
    try:
        accounts = await client.get_subaccounts(account=account)
    except VoipmsApiError as exc:
        code, retryable = map_status_code(exc.status_code)
        return error_envelope(code, exc.message, retryable)
    for entry in accounts:
        if entry.get("account") == account:
            return entry
    return None


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(
        name="voipms_find_subaccount",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )
    async def voipms_find_subaccount(query: str) -> str:
        """Find VOIP.ms sub-accounts whose account name or description matches a keyword.

        Args:
            query: Account name or description substring to search for.
        """
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "voipms client is not configured", False)
        try:
            accounts = await client.get_subaccounts()
        except VoipmsApiError as exc:
            code, retryable = map_status_code(exc.status_code)
            return error_envelope(code, exc.message, retryable)

        needle = query.strip().lower()
        matches = [
            {"account": entry.get("account"), "description": entry.get("description")}
            for entry in accounts
            if needle in (entry.get("account") or "").lower() or needle in (entry.get("description") or "").lower()
        ]
        return _dumps({"matches": matches})

    @mcp.tool(
        name="voipms_get_subaccount",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )
    async def voipms_get_subaccount(account: str) -> str:
        """Get the full current configuration of one VOIP.ms sub-account.

        Args:
            account: Sub-account name, e.g. '100001_ops'.
        """
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "voipms client is not configured", False)
        record = await _fetch_one(client, account)
        if record is None:
            return error_envelope("not_found", f"sub-account {account} not found", False)
        if isinstance(record, str):
            return record
        return _dumps(record)

    @mcp.tool(
        name="voipms_list_voicemail_boxes",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )
    async def voipms_list_voicemail_boxes(account: str) -> str:
        """List voicemail mailboxes that a redirect target can be validated against.

        Args:
            account: Sub-account name; accepted for interface symmetry with the
                other tools. VOIP.ms voicemail mailboxes belong to the whole
                account rather than to one sub-account, so every sub-account
                under the same credentials sees the same mailbox list.
        """
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "voipms client is not configured", False)
        try:
            boxes = await client.get_voicemails()
        except VoipmsApiError as exc:
            code, retryable = map_status_code(exc.status_code)
            return error_envelope(code, exc.message, retryable)
        mailboxes = [{"mailbox": box.get("mailbox"), "description": box.get("description")} for box in boxes]
        return _dumps({"mailboxes": mailboxes})

    @mcp.tool(
        name="voipms_set_voicemail_redirect",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    )
    async def voipms_set_voicemail_redirect(account: str, target_mailbox: str) -> str:
        """Redirect a sub-account's voicemail to a different mailbox.

        Reads the sub-account's full current configuration, checks that
        target_mailbox is a real mailbox on this account, then writes the full
        configuration back with only the voicemail field changed -- every other
        field (caller ID, codecs, etc.) is preserved exactly. Not idempotent:
        the reported "before" value reflects whatever the last call left behind.

        Args:
            account: Sub-account name to update.
            target_mailbox: Mailbox id to redirect voicemail to; must appear in
                voipms_list_voicemail_boxes' result for this call to succeed.
        """
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "voipms client is not configured", False)

        record = await _fetch_one(client, account)
        if record is None:
            return error_envelope("not_found", f"sub-account {account} not found", False)
        if isinstance(record, str):
            return record

        try:
            boxes = await client.get_voicemails()
        except VoipmsApiError as exc:
            code, retryable = map_status_code(exc.status_code)
            return error_envelope(code, exc.message, retryable)

        valid_ids = {str(box.get("mailbox")) for box in boxes}
        if str(target_mailbox) not in valid_ids:
            # Reject before any write is attempted -- AC5 requires no vendor
            # write call happens for an invalid target.
            return error_envelope(
                "invalid_argument",
                f"target_mailbox {target_mailbox} is not a voicemail box on this account",
                False,
            )

        before = record.get("internal_voicemail")
        updated_record = dict(record)
        updated_record["internal_voicemail"] = target_mailbox

        try:
            await client.set_subaccount(updated_record)
        except VoipmsApiError as exc:
            code, retryable = map_status_code(exc.status_code)
            return error_envelope(code, exc.message, retryable)

        return _dumps(
            {
                "account": account,
                "field": "internal_voicemail",
                "before": before,
                "after": target_mailbox,
            }
        )
