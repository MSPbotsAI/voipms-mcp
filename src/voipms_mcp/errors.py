"""Structured error envelope shared by all tools.

Per vendor-mcp-development-sop.md SS4.2: tools never raise -- they return a
JSON string on both success and failure, so the calling Agent can branch on
`error.code` and decide whether `retryable` justifies a retry. The code
vocabulary is fixed; nothing here invents a new code.
"""

from __future__ import annotations

import json

ERROR_CODES = frozenset(
    {
        "not_configured",
        "unauthorized",
        "not_found",
        "invalid_argument",
        "rate_limited",
        "upstream_error",
    }
)


def error_envelope(code: str, message: str, retryable: bool) -> str:
    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code: {code!r}")
    payload = {"error": {"code": code, "message": message, "retryable": retryable}}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def map_status_code(status_code: int) -> tuple[str, bool]:
    """Map a vendor HTTP-ish status code to (error code, retryable)."""
    if status_code in (401, 403):
        return "unauthorized", False
    if status_code == 404:
        return "not_found", False
    if status_code in (400, 422):
        return "invalid_argument", False
    if status_code == 429:
        return "rate_limited", True
    # 5xx, timeouts (599) and anything unrecognized: fail safe as retryable.
    return "upstream_error", True
