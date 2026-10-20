"""The /photoshop/status endpoint must work in DEMO_MODE with no Chrome.

We set DEMO_MODE before importing the app so the endpoint takes the demo
short-circuit and never imports/launches Playwright.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def demo_client():
    import os

    prev = os.environ.get("DEMO_MODE")
    os.environ["DEMO_MODE"] = "1"
    # Reload config + main so DEMO_MODE is picked up at import time. Done ONCE
    # per module so the global job-queue manager's event loop stays consistent
    # across the TestClient lifespan (reloading per-test rebinds it and the
    # shutdown then fails on a different loop).
    import app.config as config
    import app.main as main

    importlib.reload(config)
    importlib.reload(main)
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        if prev is None:
            os.environ.pop("DEMO_MODE", None)
        else:
            os.environ["DEMO_MODE"] = prev
        importlib.reload(config)
        importlib.reload(main)


def test_status_demo_mode_no_chrome(demo_client):
    resp = demo_client.get("/photoshop/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo_mode"] is True
    assert body["connected"] is False
    assert body["logged_in"] is False
    assert body["window_size"] is None
    assert body["url"] is None


def test_config_exposes_connect_mode(demo_client):
    body = demo_client.get("/config").json()
    assert body["demo_mode"] is True
    assert "connect_mode" in body
