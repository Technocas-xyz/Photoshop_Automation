"""Record Photoshop Web selectors in the SAME Chrome the app drives.

This attaches over CDP to the Chrome you started with start_chrome.bat and opens
Playwright's Inspector on the Photoshop tab via page.pause(). You then click
around in that exact browser/profile; the Inspector shows you codegen-style
locators to copy into app/photoshop/selectors.py.

Usage:
    1. start_chrome.bat        (and log in to Adobe)
    2. python tools/record_selectors.py

Because we attach to YOUR Chrome, the recorded locators are produced against the
real, logged-in session — not a throwaway browser — so they match what the app
sees at runtime.

Nothing is closed on exit except our CDP connection; your Chrome stays open.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python tools/record_selectors.py` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PHOTOSHOP_URL, PS_CDP_URL  # noqa: E402
from app.photoshop.session import cdp_endpoint_up, _find_photoshop_page  # noqa: E402


def main() -> int:
    if not cdp_endpoint_up(PS_CDP_URL):
        print(f"Chrome not reachable at {PS_CDP_URL}.")
        print("Run start_chrome.bat first, then re-run this script.")
        return 1

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = None
    try:
        browser = pw.chromium.connect_over_cdp(PS_CDP_URL)
        if not browser.contexts:
            print("Chrome has no open window/context. Open it with start_chrome.bat.")
            return 1
        context = browser.contexts[0]

        page = _find_photoshop_page(context)
        if page is None:
            print("No Photoshop tab found; opening one.")
            page = context.new_page()
            page.goto(PHOTOSHOP_URL, wait_until="domcontentloaded")
        else:
            try:
                page.bring_to_front()
            except Exception:
                pass

        print("=" * 72)
        print("Opening Playwright Inspector on the Photoshop tab.")
        print("Use 'Explore'/'Record' in the Inspector to capture locators,")
        print("then paste them into app/photoshop/selectors.py.")
        print("Close the Inspector (or press Resume) when you're done.")
        print("=" * 72)

        # Blocks until you resume/close the Inspector.
        page.pause()
        return 0
    finally:
        try:
            if browser is not None:
                browser.close()  # CDP: detaches only, leaves Chrome open
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
