"""Async wrapper around the VOIP.ms REST API.

Method names and required fields were verified 2026-09-10 against the public
python-voipms wrapper (https://github.com/4doom4/python-voipms,
voipms/entities/accountsget.py, accountsset.py, voicemailget.py) rather than
taken on faith from the ticket's Interview Log:

- ``getSubAccounts`` (optional ``account`` filter) lists sub-accounts.
- ``setSubAccount`` is confirmed to require the *entire* record (id, password,
  auth_type, device_type, lock_international, international_route,
  music_on_hold, allowed_codecs, dtmf_mode, nat, ...) -- sending only
  ``internal_voicemail`` would drop every other field to its vendor default.
  This is exactly the risk PRD-18607 was filed to prevent, and it is now
  confirmed rather than assumed. See docs/tickets/PRD-18607.md "Open
  Questions" / "风险与依赖" for the design-time assumption this resolves.
- ``getVoicemails`` (optional ``mailbox`` filter) lists voicemail mailboxes;
  mailboxes belong to the whole VOIP.ms account, not to one sub-account, so
  ``account`` is accepted by our tool for interface symmetry but not sent to
  this vendor call.

The exact shape of a vendor error response (which field carries the failure
reason) is not independently verified against a live account -- that requires
the customer's API credentials, which are a known open dependency (see
docs/tickets/PRD-18607.md, "风险与依赖" § 依赖 1). ``_call`` treats any
non-"success" ``status`` field as an error and maps it conservatively.
"""

from __future__ import annotations

import asyncio

import httpx

DEFAULT_BASE_URL = "https://voip.ms/api/v1/rest.php"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
_MAX_ATTEMPTS = 3


class VoipmsApiError(Exception):
    """Raised for any non-success outcome; carries an HTTP-ish status_code.

    ``errors.map_status_code`` turns ``status_code`` into the tool-facing
    error envelope, so this is the only vocabulary that crosses that
    boundary.
    """

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _status_to_http(status: str) -> int:
    s = (status or "").lower()
    if "auth" in s or "credential" in s or "invalid_api" in s:
        return 401
    if "not_found" in s or "no_client" in s or "no_account" in s or "invalid_account" in s or "invalid_mailbox" in s:
        return 404
    if "limit" in s:
        return 429
    if "invalid" in s or "missing" in s:
        return 400
    return 500


class VoipmsClient:
    """One instance per request -- constructed from the per-tenant Header
    credentials in server.py's ContextVar, never shared or cached across
    requests (vendor-mcp-development-sop.md SS3.3/SS3.4)."""

    def __init__(
        self,
        api_username: str,
        api_password: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_username = api_username
        self._api_password = api_password
        self._base_url = base_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "VoipmsClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _call(self, method: str, params: dict[str, object]) -> dict:
        query: dict[str, object] = {
            "api_username": self._api_username,
            "api_password": self._api_password,
            "method": method,
            "content_type": "json",
        }
        query.update({k: v for k, v in params.items() if v is not None})

        last_error: VoipmsApiError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await self._client.get(self._base_url, params=query)
            except httpx.TimeoutException as exc:
                last_error = VoipmsApiError(599, f"timeout calling {method}: {exc}")
                await self._backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = VoipmsApiError(599, f"network error calling {method}: {exc}")
                await self._backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = VoipmsApiError(response.status_code, f"{method} returned HTTP {response.status_code}")
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise VoipmsApiError(response.status_code, f"{method} returned HTTP {response.status_code}")

            body = response.json()
            status = body.get("status")
            if status and status != "success":
                raise VoipmsApiError(_status_to_http(status), f"{method} vendor status={status}")
            return body

        assert last_error is not None
        raise last_error

    @staticmethod
    async def _backoff(attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.5 * (2**attempt)
        else:
            delay = 0.5 * (2**attempt)
        await asyncio.sleep(delay)

    async def get_subaccounts(self, account: str | None = None) -> list[dict]:
        body = await self._call("getSubAccounts", {"account": account})
        return body.get("accounts") or []

    async def get_voicemails(self, mailbox: str | None = None) -> list[dict]:
        body = await self._call("getVoicemails", {"mailbox": mailbox})
        return body.get("voicemails") or []

    async def set_subaccount(self, fields: dict[str, object]) -> dict:
        return await self._call("setSubAccount", fields)
