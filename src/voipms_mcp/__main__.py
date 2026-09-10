"""Entry point: run the Starlette app (health + MCP) under uvicorn."""

from __future__ import annotations

import uvicorn

from voipms_mcp.config import settings
from voipms_mcp.server import create_app


def main() -> None:
    uvicorn.run(create_app(), host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
