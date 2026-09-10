"""Non-credential runtime configuration.

Per vendor-mcp-development-sop.md SS1.2/SS3.1: credentials are never configured
here -- they arrive per-request in HTTP headers (see server.py). This model
must tolerate unknown environment variables (extra="ignore"), otherwise the
runtime injecting an undeclared variable would crash the container on boot.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"
    base_url: str = "https://voip.ms/api/v1/rest.php"


settings = Settings()
