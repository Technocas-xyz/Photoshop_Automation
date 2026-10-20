"""Session tests that need NO real Chrome.

Covered:
  * cdp_endpoint_up returns False when nothing answers.
  * probe_status short-circuits to "not connected" when CDP is down (the
    unreachable error path), without importing/launching Playwright.
  * is_logged_in with a fully mocked page for logged-in / logged-out / unknown.
  * PhotoshopSession raises CdpUnreachable in cdp mode when the endpoint is down.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.photoshop import session as sess


# ---------------------------------------------------------------------------
# A tiny fake Playwright "page" + "locator" good enough for is_logged_in.
# ---------------------------------------------------------------------------
class FakeLocator:
    def __init__(self, visible: bool):
        self._visible = visible
        self.first = self

    def is_visible(self, timeout=None):
        return self._visible


class FakePage:
    """Resolves get_by_role/get_by_text to visible/invisible locators by name.

    `visible_names` is the set of accessible-names / texts that should report
    visible; everything else is invisible.
    """

    def __init__(self, visible_names: set[str]):
        self.visible_names = visible_names

    def get_by_role(self, role, name=None):
        return FakeLocator(name in self.visible_names)

    def get_by_text(self, text, exact=False):
        return FakeLocator(text in self.visible_names)

    def get_by_test_id(self, tid):
        return FakeLocator(tid in self.visible_names)

    def locator(self, css):
        return FakeLocator(css in self.visible_names)


def test_cdp_endpoint_up_false_when_down():
    # Nothing is listening on this port in the test environment.
    assert sess.cdp_endpoint_up("http://127.0.0.1:9", timeout=0.3) is False


def test_probe_status_not_connected_when_cdp_down(monkeypatch):
    # Force the endpoint check to report "down" so probe_status returns the
    # unreachable result WITHOUT touching Playwright at all.
    monkeypatch.setattr(sess, "cdp_endpoint_up", lambda *a, **k: False)
    result = sess.probe_status("http://127.0.0.1:9222")
    assert result == {
        "connected": False,
        "logged_in": False,
        "window_size": None,
        "url": None,
    }


def test_is_logged_in_true_when_account_marker_visible():
    # "Account" is one of the LOGGED_IN_MARKERS names.
    page = FakePage(visible_names={"Account"})
    assert sess.is_logged_in(page) is True


def test_is_logged_in_false_when_sign_in_visible():
    # "Sign in" is a LOGGED_OUT marker and takes precedence.
    page = FakePage(visible_names={"Sign in"})
    assert sess.is_logged_in(page) is False


def test_is_logged_in_defaults_true_when_nothing_matches():
    page = FakePage(visible_names=set())
    assert sess.is_logged_in(page) is True


def test_logged_out_precedence_over_logged_in():
    # If BOTH kinds of markers were visible, logged-out must win (safer).
    page = FakePage(visible_names={"Sign in", "Account"})
    assert sess.is_logged_in(page) is False


def test_session_cdp_unreachable(monkeypatch):
    monkeypatch.setattr(sess, "PS_CONNECT_MODE", "cdp", raising=False)
    monkeypatch.setattr(sess, "cdp_endpoint_up", lambda *a, **k: False)

    s = sess.PhotoshopSession(job_id="test_job")
    # Force cdp mode regardless of ambient config.
    s._mode = "cdp"
    with pytest.raises(sess.CdpUnreachable) as exc:
        s._enter_cdp()
    assert "Run start_chrome.bat first" in str(exc.value)
