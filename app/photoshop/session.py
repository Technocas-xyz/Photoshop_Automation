"""Photoshop Web browser session lifecycle (Playwright, sync API).

Two connection modes (config.PS_CONNECT_MODE):

  "cdp"    -- Attach over the DevTools protocol to a normal Chrome the user
              started themselves via start_chrome.bat. Adobe behaves far better
              in a real, user-launched Chrome than in Playwright's own browser
              (no "--no-sandbox" warning bar, correct layout, working login).
              We reuse the existing browser context and NEVER close the user's
              browser or context on job end — only pages this job opened.

  "launch" -- Fallback: Playwright launches its own persistent Chrome with a
              maximized real window (no fixed viewport) and the sandbox warning
              suppressed.

Everything here runs on a worker thread (the queue uses run_in_executor), so
the SYNC Playwright API is used — it must not run on the asyncio loop thread.

Selectors live in selectors.py. The helper `_resolve` turns a selector dict
into a Playwright Locator by trying role/text/test_id/css in order.
"""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from ..config import (
    DEBUG_DIR,
    PHOTOSHOP_URL,
    PS_CDP_URL,
    PS_CONNECT_MODE,
    PS_DOWNLOAD_DIR,
    PS_MIN_WINDOW_HEIGHT,
    PS_MIN_WINDOW_WIDTH,
    PS_PROFILE_DIR,
    PW_CHANNEL,
)
from . import selectors as S

LogFn = Callable[[str, str], None]


class AdobeSessionExpired(RuntimeError):
    """Raised when the connected Chrome is no longer logged in to Adobe."""


class CdpUnreachable(RuntimeError):
    """Raised when we cannot attach to Chrome over CDP."""


class PaywallHit(RuntimeError):
    """Raised when Adobe shows a 'Start free trial' / 'Buy now' upsell."""


# ---------------------------------------------------------------------------
# Standalone helpers (used by session, login_once.py, tools, and /status)
# ---------------------------------------------------------------------------
def cdp_endpoint_up(cdp_url: str = PS_CDP_URL, timeout: float = 2.0) -> bool:
    """Return True if a Chrome DevTools endpoint answers at cdp_url.

    Checks GET <cdp_url>/json/version, which every Chrome debug endpoint serves.
    """
    url = cdp_url.rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_logged_in(page) -> bool:
    """Best-effort check of Adobe login state for an open Photoshop page.

    Returns True if any LOGGED_IN marker is visible, False if any LOGGED_OUT
    marker is visible. When neither resolves (markers not recorded yet, or the
    page is mid-load) we default to True so a correctly-logged-in session is
    not blocked by missing selectors — the recipe will still fail later with a
    clear error if the page is actually unusable.
    """
    # Logged-out markers take precedence: an explicit "Sign in" means out.
    for sel in S.LOGGED_OUT_MARKERS:
        loc = _resolve_on(page, sel)
        if loc is None:
            continue
        try:
            if loc.first.is_visible(timeout=1500):
                return False
        except Exception:
            pass

    for sel in S.LOGGED_IN_MARKERS:
        loc = _resolve_on(page, sel)
        if loc is None:
            continue
        try:
            if loc.first.is_visible(timeout=1500):
                return True
        except Exception:
            pass

    # Neither matched; assume logged in rather than hard-blocking.
    return True


def _resolve_on(page, sel: dict):
    """Resolve a selector dict against an arbitrary page (not bound to self)."""
    if not sel:
        return None
    if sel.get("role"):
        role, name = sel["role"]
        return page.get_by_role(role, name=name)
    if sel.get("test_id"):
        return page.get_by_test_id(sel["test_id"])
    if sel.get("text"):
        return page.get_by_text(sel["text"], exact=False)
    if sel.get("css"):
        return page.locator(sel["css"])
    return None


def _window_size(page) -> Optional[dict]:
    """Return the inner viewport size of the page's window, or None."""
    try:
        size = page.evaluate(
            "() => ({width: window.innerWidth, height: window.innerHeight})"
        )
        if size and size.get("width"):
            return {"width": int(size["width"]), "height": int(size["height"])}
    except Exception:
        pass
    return None


def _find_photoshop_page(context):
    """Return an existing page whose URL contains photoshop.adobe.com, or None."""
    for p in context.pages:
        try:
            if "photoshop.adobe.com" in (p.url or ""):
                return p
        except Exception:
            continue
    return None


def probe_status(cdp_url: str = PS_CDP_URL) -> dict:
    """Lightweight status probe for the /photoshop/status endpoint.

    Connects over CDP (if reachable), inspects the Photoshop tab, and returns
    {connected, logged_in, window_size, url}. Opens NO new tabs and closes
    nothing belonging to the user. Safe to call repeatedly.
    """
    result = {"connected": False, "logged_in": False, "window_size": None, "url": None}
    if not cdp_endpoint_up(cdp_url):
        return result

    from playwright.sync_api import sync_playwright

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(cdp_url)
        result["connected"] = True
        if not browser.contexts:
            return result
        context = browser.contexts[0]
        page = _find_photoshop_page(context)
        if page is None:
            return result
        result["url"] = page.url
        result["window_size"] = _window_size(page)
        result["logged_in"] = is_logged_in(page)
        return result
    except Exception:
        return result
    finally:
        # Disconnect WITHOUT closing the user's browser/pages.
        try:
            if browser is not None:
                browser.close()  # for CDP this only detaches the connection
        except Exception:
            pass
        try:
            if pw is not None:
                pw.stop()
        except Exception:
            pass


class PhotoshopSession:
    """Context manager that connects to Chrome (CDP or launch) for one job."""

    def __init__(self, job_id: str, log: Optional[LogFn] = None) -> None:
        self.job_id = job_id
        self._log: LogFn = log or (lambda level, msg: None)
        self._pw = None
        self._browser = None          # set in CDP mode
        self._context = None
        self.page = None
        self._mode = PS_CONNECT_MODE
        self._owns_page = False        # True only if this job opened the tab
        self._owns_context = False     # True only in launch mode
        self._step = 0
        self._debug_dir = DEBUG_DIR / job_id
        self._debug_dir.mkdir(parents=True, exist_ok=True)

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "PhotoshopSession":
        if self._mode == "cdp":
            self._enter_cdp()
        else:
            self._enter_launch()
        self._ensure_photoshop_open()
        self._check_window_size()
        self._ensure_logged_in()
        self.debug_shot("app_ready")
        return self

    def _enter_cdp(self) -> None:
        from playwright.sync_api import sync_playwright

        self._log("info", f"Connecting to Chrome over CDP at {PS_CDP_URL}")
        if not cdp_endpoint_up(PS_CDP_URL):
            raise CdpUnreachable(
                f"Cannot reach Chrome on {PS_CDP_URL}. Run start_chrome.bat first."
            )
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(PS_CDP_URL)
        except Exception as exc:
            # Clean up the Playwright driver, then surface a clear message.
            try:
                self._pw.stop()
            except Exception:
                pass
            raise CdpUnreachable(
                f"Cannot reach Chrome on {PS_CDP_URL}. Run start_chrome.bat first."
            ) from exc

        if not self._browser.contexts:
            raise CdpUnreachable(
                "Connected to Chrome but it has no open context/window. "
                "Run start_chrome.bat first."
            )
        # Reuse the real browser's existing context — do NOT create our own.
        self._context = self._browser.contexts[0]
        self._owns_context = False
        self._log("success", "Attached to your Chrome (CDP)")

    def _enter_launch(self) -> None:
        from playwright.sync_api import sync_playwright

        self._log(
            "info",
            "Launching Playwright-managed Chrome (fallback 'launch' mode)",
        )
        PS_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        # no_viewport=True keeps a real, resizable, maximized window instead of
        # the cramped fixed viewport that made Adobe's layout cut off.
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PS_PROFILE_DIR),
            channel=PW_CHANNEL,
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
            ignore_default_args=["--no-sandbox"],
            accept_downloads=True,
        )
        self._owns_context = True

    def _ensure_photoshop_open(self) -> None:
        """Point self.page at a Photoshop tab, reusing one if it exists."""
        existing = _find_photoshop_page(self._context)
        if existing is not None:
            self.page = existing
            self._owns_page = False
            self._log("info", "Reusing existing Photoshop tab")
            try:
                self.page.bring_to_front()
            except Exception:
                pass
            return

        self._log("info", "Opening a new Photoshop tab")
        self.page = self._context.new_page()
        self._owns_page = True
        self.page.goto(PHOTOSHOP_URL, wait_until="domcontentloaded")

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.debug_shot("failure")
            self._log("error", f"Session failed: {exc}")
        try:
            if self._mode == "cdp":
                # Only close the tab WE opened; never the user's tabs/browser.
                if self._owns_page and self.page is not None:
                    try:
                        self.page.close()
                        self._log("info", "Closed the tab this job opened")
                    except Exception:
                        pass
                # Detach the CDP connection without closing the user's Chrome.
                if self._browser is not None:
                    try:
                        self._browser.close()
                        self._log("info", "Disconnected from Chrome (left it running)")
                    except Exception:
                        pass
            else:
                # launch mode: we own everything, tear it down.
                if self._context is not None:
                    try:
                        self._context.close()
                    except Exception:
                        pass
        finally:
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception:
                    pass

    # -- readiness / health checks ----------------------------------------
    def _check_window_size(self) -> None:
        """Confirm the canvas/toolbar is visible and log the window size.

        If the window is smaller than the configured minimum, warn the user to
        maximize or zoom out — a small window cuts off Adobe's layout.
        """
        size = _window_size(self.page)
        if size is None:
            self._log("info", "Could not read the Chrome window size")
            return
        self._log("info", f"Chrome window size: {size['width']}x{size['height']}")
        if (
            size["width"] < PS_MIN_WINDOW_WIDTH
            or size["height"] < PS_MIN_WINDOW_HEIGHT
        ):
            self._log(
                "error",
                "Window is smaller than "
                f"{PS_MIN_WINDOW_WIDTH}x{PS_MIN_WINDOW_HEIGHT}. The Photoshop "
                "layout may be cut off — maximize the window or zoom out "
                "(Ctrl + -).",
            )

    def _ensure_logged_in(self) -> None:
        """Fail clearly (with a screenshot) if not signed in to Adobe."""
        if not is_logged_in(self.page):
            self.debug_shot("logged_out")
            raise AdobeSessionExpired(
                "Adobe session expired. Log in again in the Chrome window "
                "opened by start_chrome.bat"
            )
        self._log("success", "Adobe session is logged in")

    # -- high level actions ------------------------------------------------
    def open_image(self, image_path: str) -> None:
        """Open a local image through Photoshop's file chooser.

        TODO: paste the real OPEN_IMAGE_TRIGGER selector from codegen. The
        file-chooser handling below is correct once the trigger resolves.
        """
        self._log("info", f"Opening image: {Path(image_path).name}")
        trigger = self._resolve(S.OPEN_IMAGE_TRIGGER)
        if trigger is None:
            raise NotImplementedError(
                "OPEN_IMAGE_TRIGGER selector not set — record it with "
                "tools/record_selectors.py and paste into selectors.py"
            )
        with self.page.expect_file_chooser() as fc_info:
            trigger.first.click()
        fc_info.value.set_files(image_path)
        self._wait_editor_ready()
        self.debug_shot("image_opened")
        self._log("success", "Image opened in Photoshop")

    def export_png(self, dest_path: str) -> None:
        """Export the current document as a transparent PNG and save it.

        Capturing the download is tricky in CDP mode: the download may be driven
        by the real browser and never surface as a Playwright `download` event.
        So we try BOTH:
          1. page.expect_download() around the export click.
          2. A fallback that watches PS_DOWNLOAD_DIR for the newest *.png that
             appears after the click.
        Whichever yields a file first wins, and we log which method worked.

        TODO: paste real EXPORT_* selectors from codegen. The plumbing below is
        correct once the selectors resolve.
        """
        self._log("info", "Exporting result as PNG")
        trigger = self._resolve(S.EXPORT_MENU_TRIGGER)
        png_item = self._resolve(S.EXPORT_AS_PNG)
        if trigger is None or png_item is None:
            raise NotImplementedError(
                "EXPORT_* selectors not set — record them with "
                "tools/record_selectors.py and paste into selectors.py"
            )

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Snapshot the download folder so the fallback can spot new files.
        before = _png_snapshot(PS_DOWNLOAD_DIR)
        click_time = time.time()

        trigger.first.click()
        png_item.first.click()
        confirm = self._resolve(S.EXPORT_CONFIRM)

        # --- Method 1: Playwright download event -------------------------
        try:
            with self.page.expect_download(timeout=15000) as dl_info:
                if confirm is not None:
                    confirm.first.click()
            download = dl_info.value
            download.save_as(str(dest))
            self.debug_shot("exported")
            self._log("success", f"Saved PNG via Playwright download → {dest}")
            return
        except Exception as exc:
            self._log(
                "info",
                f"Playwright download event not captured ({exc}); "
                "watching the download folder instead",
            )
            # If we did not already click confirm (because expect_download
            # raised before the click), make sure the export was triggered.
            if confirm is not None:
                try:
                    confirm.first.click()
                except Exception:
                    pass

        # --- Method 2: watch the download folder -------------------------
        new_png = _wait_for_new_png(
            PS_DOWNLOAD_DIR, before, since=click_time, timeout=60.0
        )
        if new_png is None:
            self.debug_shot("export_failed")
            raise RuntimeError(
                "Export did not produce a PNG. Checked the Playwright download "
                f"event and the folder {PS_DOWNLOAD_DIR}. Set PS_DOWNLOAD_DIR to "
                "Chrome's actual download location if it differs."
            )
        # Copy (not move) so we don't disturb the user's Downloads.
        dest.write_bytes(new_png.read_bytes())
        self.debug_shot("exported")
        self._log(
            "success",
            f"Saved PNG via download-folder fallback ({new_png.name}) → {dest}",
        )

    # -- waiting / conditions ---------------------------------------------
    def _wait_editor_ready(self, timeout_ms: int = 30000) -> None:
        ready = self._resolve(S.EDITOR_READY)
        if ready is None:
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return
        ready.first.wait_for(state="visible", timeout=timeout_ms)

    def wait_for_text(self, text: str, timeout_ms: int = 15000) -> None:
        """Explicit condition helper for recipes: wait for visible text."""
        self._check_paywall()
        self.page.get_by_text(text, exact=False).first.wait_for(
            state="visible", timeout=timeout_ms
        )

    # -- paywall ----------------------------------------------------------
    def _check_paywall(self) -> None:
        """Fail clearly if an Adobe upsell ('Start free trial' / 'Buy now').

        Called before every recipe step (via debug_shot / wait_for_text). Saves
        a screenshot and raises PaywallHit so the job stops with a useful log
        line instead of silently waiting on an unreachable feature.
        """
        if self.page is None:
            return
        for sel in S.PAYWALL_MARKERS:
            loc = _resolve_on(self.page, sel)
            if loc is None:
                continue
            try:
                if loc.first.is_visible(timeout=800):
                    # Screenshot straight to the debug dir (bypass debug_shot to
                    # avoid recursing back into this check).
                    self._step += 1
                    shot = self._debug_dir / f"step_{self._step}_paywall.png"
                    try:
                        self.page.screenshot(path=str(shot), full_page=False)
                    except Exception:
                        pass
                    raise PaywallHit(
                        "Adobe paywall hit ('Start free trial' / 'Buy now'). "
                        "This feature needs a paid plan or the free quota is "
                        "exhausted — the job cannot continue."
                    )
            except PaywallHit:
                raise
            except Exception:
                # Marker not present / not resolvable -> no paywall.
                continue

    # -- debug -------------------------------------------------------------
    def debug_shot(self, label: str = "") -> Path:
        """Save a numbered screenshot into ./data/debug/{job_id}/.

        Also acts as the per-step checkpoint: before saving it verifies no Adobe
        paywall has appeared (recipes call debug_shot at every step).
        """
        if label != "paywall":
            self._check_paywall()
        self._step += 1
        suffix = f"_{label}" if label else ""
        path = self._debug_dir / f"step_{self._step}{suffix}.png"
        try:
            if self.page is not None:
                self.page.screenshot(path=str(path), full_page=False)
        except Exception as exc:  # pragma: no cover - best effort
            self._log("error", f"Could not save screenshot: {exc}")
        return path

    def shortcut(self, name: str) -> None:
        """Press a named keyboard shortcut from selectors.SHORTCUTS."""
        combo = S.SHORTCUTS.get(name)
        if not combo:
            raise KeyError(f"Unknown shortcut '{name}'")
        self.page.keyboard.press(combo)

    # -- selector resolution ----------------------------------------------
    def _resolve(self, sel: dict):
        """Turn a selector dict into a Locator, trying each form in order."""
        return _resolve_on(self.page, sel)


# ---------------------------------------------------------------------------
# Download-folder watch helpers
# ---------------------------------------------------------------------------
def _png_snapshot(folder: Path) -> set:
    """Return the set of *.png paths currently in folder (non-recursive)."""
    try:
        return {p.resolve() for p in folder.glob("*.png")}
    except Exception:
        return set()


def _wait_for_new_png(
    folder: Path, before: set, since: float, timeout: float = 60.0
) -> Optional[Path]:
    """Wait up to `timeout`s for a new, fully-written *.png to appear.

    A file counts only if it was not in `before` and its mtime is at/after the
    export click. We also skip Chrome's in-progress ".crdownload" temp files and
    wait until the file size is stable before returning it.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current = {p.resolve() for p in folder.glob("*.png")}
        except Exception:
            current = set()
        candidates = [
            p for p in (current - before)
            if p.exists() and p.stat().st_mtime >= since - 1
            and not p.name.endswith(".crdownload")
        ]
        if candidates:
            newest = max(candidates, key=lambda p: p.stat().st_mtime)
            if _file_is_stable(newest):
                return newest
        time.sleep(0.5)
    return None


def _file_is_stable(path: Path, checks: int = 2, interval: float = 0.4) -> bool:
    """Return True once the file size stops changing (download complete)."""
    try:
        last = -1
        for _ in range(checks + 1):
            size = path.stat().st_size
            if size == last and size > 0:
                return True
            last = size
            time.sleep(interval)
    except Exception:
        return False
    return False
