"""One-time Adobe login detector for the CDP-attached Chrome.

Adobe uses captcha / 2FA, so login is NEVER automated and NO credentials are
ever stored. This script just watches the Chrome you started yourself until it
sees you are signed in, then exits.

Flow:
    1. Run start_chrome.bat (or start_chrome.ps1) first. That launches your real
       Chrome with remote debugging on 127.0.0.1:9222 and a dedicated profile
       in ./chrome_profile, opened on photoshop.adobe.com.
    2. Run:  python login_once.py
    3. Log in by hand in that Chrome window.
    4. This script polls every 2s (up to 10 minutes). As soon as the logged-in
       state is detected it prints a confirmation and exits — no Enter needed.

The session lives entirely inside Chrome's own profile (./chrome_profile), which
is gitignored. This script writes nothing sensitive anywhere.
"""
from __future__ import annotations

import sys
import time

from app.config import PHOTOSHOP_URL, PS_CDP_URL, PS_PROFILE_DIR
from app.photoshop.session import (
    cdp_endpoint_up,
    is_logged_in,
    _find_photoshop_page,
)

POLL_INTERVAL_SECONDS = 2
MAX_WAIT_SECONDS = 10 * 60


def main() -> int:
    print(f"Checking for Chrome debugging endpoint at {PS_CDP_URL} ...")
    if not cdp_endpoint_up(PS_CDP_URL):
        print()
        print("=" * 72)
        print("Chrome is not reachable over CDP.")
        print("Run start_chrome.bat (Windows) or ./start_chrome.ps1 first,")
        print("then run this script again.")
        print("=" * 72)
        return 1

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = None
    try:
        browser = pw.chromium.connect_over_cdp(PS_CDP_URL)
        if not browser.contexts:
            print("Connected to Chrome but no window/context is open.")
            print("Make sure the Chrome window from start_chrome.bat is open.")
            return 1
        context = browser.contexts[0]

        # Reuse the Photoshop tab if start_chrome.bat already opened it;
        # otherwise open one. This page belongs to the user's Chrome — we leave
        # it open on exit.
        page = _find_photoshop_page(context)
        if page is None:
            page = context.new_page()
            page.goto(PHOTOSHOP_URL, wait_until="domcontentloaded")
        else:
            try:
                page.bring_to_front()
            except Exception:
                pass

        print("Connected. Watching for sign-in — log in in the Chrome window.")
        deadline = time.time() + MAX_WAIT_SECONDS
        while time.time() < deadline:
            try:
                if is_logged_in(page):
                    print()
                    print(f"Logged in as detected, session saved in {PS_PROFILE_DIR}")
                    return 0
            except Exception:
                # Page may be mid-navigation during login; keep polling.
                pass
            remaining = int(deadline - time.time())
            print(f"  not signed in yet… retrying in {POLL_INTERVAL_SECONDS}s "
                  f"({remaining}s left)")
            time.sleep(POLL_INTERVAL_SECONDS)

        print()
        print("Timed out after 10 minutes without detecting a signed-in state.")
        print("If you ARE signed in, the login markers in "
              "app/photoshop/selectors.py may need updating "
              "(see tools/dump_ui.py).")
        return 1
    finally:
        # Detach from CDP WITHOUT closing the user's Chrome.
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
