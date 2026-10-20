"""Config parsing tests.

Config is read at import time, so we reload the module under patched env vars
to assert the parsing/typing behaviour.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import app.config as config


def _reload(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return importlib.reload(config)


def test_defaults(monkeypatch):
    cfg = _reload(
        monkeypatch,
        PS_CONNECT_MODE=None,
        PS_CDP_URL=None,
        DEMO_MODE=None,
        JOB_TIMEOUT_SECONDS=None,
    )
    assert cfg.PS_CONNECT_MODE == "cdp"
    assert cfg.PS_CDP_URL == "http://127.0.0.1:9222"
    assert cfg.DEMO_MODE is False
    assert cfg.JOB_TIMEOUT_SECONDS == 180
    assert cfg.PS_MIN_WINDOW_WIDTH == 1280
    assert cfg.PS_MIN_WINDOW_HEIGHT == 720


def test_env_overrides(monkeypatch):
    cfg = _reload(
        monkeypatch,
        PS_CONNECT_MODE="LAUNCH",
        PS_CDP_URL="http://127.0.0.1:9333",
        DEMO_MODE="1",
        JOB_TIMEOUT_SECONDS="42",
    )
    assert cfg.PS_CONNECT_MODE == "launch"  # lower-cased
    assert cfg.PS_CDP_URL == "http://127.0.0.1:9333"
    assert cfg.DEMO_MODE is True
    assert cfg.JOB_TIMEOUT_SECONDS == 42


def test_bool_parsing(monkeypatch):
    cfg = _reload(monkeypatch, DEMO_MODE="yes")
    assert cfg.DEMO_MODE is True
    cfg = _reload(monkeypatch, DEMO_MODE="off")
    assert cfg.DEMO_MODE is False


def test_int_parsing_falls_back_on_garbage(monkeypatch):
    cfg = _reload(monkeypatch, JOB_TIMEOUT_SECONDS="not-a-number")
    assert cfg.JOB_TIMEOUT_SECONDS == 180


def test_paths_are_absolute(monkeypatch):
    cfg = _reload(monkeypatch, PS_PROFILE_DIR=None, PS_DOWNLOAD_DIR=None)
    assert Path(cfg.PS_PROFILE_DIR).is_absolute()
    assert Path(cfg.PS_DOWNLOAD_DIR).is_absolute()
    # Clean restore so later tests see defaults.
    importlib.reload(config)
