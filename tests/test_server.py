"""Server-level tests: modes, workspace headers, throttle, key endpoint."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine  # noqa: E402  pylint: disable=wrong-import-position
import server  # noqa: E402  pylint: disable=wrong-import-position

WS = "12345678-abcd-4abc-8def-123456789012"


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    """Flask test client with an isolated data dir and clean rate buckets."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    server.app.config["TESTING"] = True
    server._rate_hits.clear()  # pylint: disable=protected-access
    with server.app.test_client() as test_client:
        yield test_client


def test_config_reports_local_mode(client) -> None:
    """Local mode is the default and is reported to the UI."""
    body = client.get("/api/config").get_json()
    assert body["mode"] == "local"
    assert "has_env_key" in body


def test_local_mode_defaults_to_default_workspace(client) -> None:
    """No workspace header locally -> the default (legacy) workspace."""
    assert client.get("/api/library").get_json() == {"documents": []}


def test_online_mode_requires_workspace(client, monkeypatch) -> None:
    """Online, a missing workspace header is a loud 400 — never a shared library."""
    monkeypatch.setattr(server, "ONLINE", True)
    response = client.get("/api/library")
    assert response.status_code == 400
    assert "workspace" in response.get_json()["error"].lower()


def test_online_mode_seeds_new_workspace(client, monkeypatch) -> None:
    """First touch of a new online workspace loads the demo corpus."""
    monkeypatch.setattr(server, "ONLINE", True)
    body = client.get("/api/library", headers={"X-Workspace": WS}).get_json()
    assert len(body["documents"]) == len(engine.DEMO_DOCS)


def test_invalid_workspace_rejected(client, monkeypatch) -> None:
    """Traversal attempts in the header are refused."""
    monkeypatch.setattr(server, "ONLINE", True)
    response = client.get("/api/library", headers={"X-Workspace": "../evil"})
    assert response.status_code == 400


def test_ask_throttle(client, monkeypatch) -> None:
    """Per-workspace ask throttle returns 429 past the limit."""
    monkeypatch.setattr(server, "RATE_LIMITS", {"ask": (2, 60.0), "upload": (20, 60.0)})
    monkeypatch.setattr(engine, "ask", lambda *a, **k: {"ok": True})
    headers = {"X-Workspace": WS}
    for _ in range(2):
        assert client.post("/api/ask", json={"question": "x"}, headers=headers).status_code == 200
    response = client.post("/api/ask", json={"question": "x"}, headers=headers)
    assert response.status_code == 429


def test_key_save_forbidden_online(client, monkeypatch) -> None:
    """The online server must never store user keys."""
    monkeypatch.setattr(server, "ONLINE", True)
    response = client.post("/api/config/key", json={"key": "sk-ant-test"})
    assert response.status_code == 403


def test_ask_passes_request_key_to_engine(client, monkeypatch) -> None:
    """The X-Api-Key header reaches the engine untouched."""
    captured = {}

    def fake_ask(question, include_superseded=False, workspace="default", api_key=None):
        captured["api_key"] = api_key
        captured["workspace"] = workspace
        assert question and include_superseded is False
        return {"ok": True}

    monkeypatch.setattr(engine, "ask", fake_ask)
    client.post("/api/ask", json={"question": "x"},
                headers={"X-Workspace": WS, "X-Api-Key": "sk-ant-abc"})
    assert captured["api_key"] == "sk-ant-abc"
    assert captured["workspace"] == WS
