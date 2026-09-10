"""CredentialMiddleware: missing header -> 401; present header -> request-scoped
ContextVar populated correctly, and reset afterwards (SS3.3)."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from voipms_mcp.server import CredentialMiddleware, current_credentials


async def _echo_credentials(request: Request) -> JSONResponse:
    creds = current_credentials()
    return JSONResponse({"credentials": list(creds) if creds else None})


def _build_test_app():
    async def asgi_app(scope, receive, send):
        request = Request(scope, receive)
        response = await _echo_credentials(request)
        await response(scope, receive, send)

    return CredentialMiddleware(asgi_app, mcp_path="/mcp")


def test_missing_both_headers_returns_401_listing_both() -> None:
    client = TestClient(_build_test_app())
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert "X-Voipms-Api-Username" in body["error"]["message"]
    assert "X-Voipms-Api-Password" in body["error"]["message"]
    assert body["error"]["retryable"] is False


def test_missing_password_only_is_listed() -> None:
    client = TestClient(_build_test_app())
    response = client.post("/mcp", json={}, headers={"X-Voipms-Api-Username": "u"})
    assert response.status_code == 401
    body = response.json()
    assert "X-Voipms-Api-Password" in body["error"]["message"]
    assert "X-Voipms-Api-Username" not in body["error"]["message"]


def test_valid_headers_populate_context_var() -> None:
    client = TestClient(_build_test_app())
    response = client.post(
        "/mcp",
        json={},
        headers={"X-Voipms-Api-Username": "acct-1", "X-Voipms-Api-Password": "secret-1"},
    )
    assert response.status_code == 200
    assert response.json() == {"credentials": ["acct-1", "secret-1"]}


def test_context_var_is_reset_after_request() -> None:
    client = TestClient(_build_test_app())
    client.post(
        "/mcp",
        json={},
        headers={"X-Voipms-Api-Username": "acct-1", "X-Voipms-Api-Password": "secret-1"},
    )
    # Outside of any request, the ContextVar must not still carry the
    # previous request's credentials (SS3.3: reset in `finally`).
    assert current_credentials() is None


def test_non_mcp_path_is_not_gated_by_credentials() -> None:
    client = TestClient(_build_test_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"credentials": None}
