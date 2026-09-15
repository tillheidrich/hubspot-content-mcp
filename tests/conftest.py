from __future__ import annotations

import pytest

from hubspot_mcp.config import Settings
from hubspot_mcp.hubspot.client import HubSpotClient

API_BASE = "https://api.hubapi.com"


@pytest.fixture
def client() -> HubSpotClient:
    c = HubSpotClient(access_token="test-token", api_base=API_BASE, max_attempts=2)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("HUBSPOT_PORTAL_ID", "12345678")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DEFAULT_TIMEZONE", "Europe/Berlin")
    monkeypatch.chdir(tmp_path)
    return Settings.load()
