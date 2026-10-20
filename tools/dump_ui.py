"""Dump the Photoshop Web UI's real labels so you don't guess selectors.

Attaches over CDP to the Chrome you started with start_chrome.bat, then writes
the accessibility info (role + accessible name) of visible buttons, menu items
and dialogs to ./data/ui_dump/<timestamp>.json, plus a screenshot alongside it.

Usage:
    python tools/dump_ui.py
    python tools/dump_ui.py --after-click "Select"
    python tools/dump_ui.py --steps "button:Main menu > menuitem:Select"

--after-click <name>: click one visible control (role from --role, default
button) whose accessible name EXACTLY (case-sensitive) matches <name>, THEN
dump — handy to open a single menu or dialog.

--steps "role:name > role:name > ...": navigate a multi-level menu, clicking
each step in order with ~500ms between steps. Each step is matched EXACTLY and
case-sensitively via get_by_role(role, name=name, exact=True). For menuitem /
menuitemcheckbox / menuitemradio the match is against the FIRST LINE of the
accessible name only, because menu names often carry a shortcut on a second
line (e.g. "Export as...\\nAlt + Shift + Ctrl + W"). First-line matching is
still exact, so "Select" never matches "Select subject".

If any step has no exact visible match, the closest visible names are printed
and navigation aborts without clicking. If a paywall dialog appears at any
step, "PAYWALL hit" is printed, Escape is pressed, and navigation aborts.

After the last step the dump captures menuitem/menuitemcheckbox/menuitemradio
entries plus dialog contents (buttons, radios, checkboxes, comboboxes,
textboxes — with names and checked state) and saves a screenshot.

Nothing is closed on exit except our CDP connection; your Chrome stays open.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR, PHOTOSHOP_URL, PS_CDP_URL  # noqa: E402
from app.photoshop import selectors as S  # noqa: E402
from app.photoshop.session import cdp_endpoint_up, _find_photoshop_page  # noqa: E402

# Roles worth capturing when hunting for selectors.
INTERESTING_ROLES = {
    "button",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "link",
    "tab",
    "dialog",
    "textbox",
    "slider",
    "combobox",
    "checkbox",
    "radio",
}


def _collect(page) -> list[dict]:
    """Return [{role, name, visible}] for interesting, visible controls."""
    out: list[dict] = []
    for role in sorted(INTERESTING_ROLES):
        try:
            loc = page.get_by_role(role)
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 100)):  # cap to keep dumps readable
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                name = (item.get_attribute("aria-label")
                        or item.inner_text(timeout=500)
                        or "").strip()
            except Exception:
                name = ""
            out.append({"role": role, "name": name[:120]})
    # De-duplicate while preserving order.
    seen = set()
    unique = []
    for d in out:
        key = (d["role"], d["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def _visible_names_for_role(page, role: str) -> list[str]:
    """Collect visible accessible names for one role (for suggestions)."""
    names: list[str] = []
    try:
        loc = page.get_by_role(role)
        count = loc.count()
    except Exception:
        return names
    for i in range(min(count, 100)):
        item = loc.nth(i)
        try:
            if not item.is_visible():
                continue
            name = (item.get_attribute("aria-label")
                    or item.inner_text(timeout=500)
                    or "").strip()
        except Exception:
            name = ""
        if name:
            names.append(name[:120])
    return names


def _closest_names(page, role: str, target: str, limit: int = 10) -> list[str]:
    """Return the closest visible names to `target` for the given role."""
    import difflib

    candidates = sorted(set(_visible_names_for_role(page, role)))
    if not candidates:
        return []
    ranked = difflib.get_close_matches(target, candidates, n=limit, cutoff=0.0)
    return ranked or candidates[:limit]


def _paywall_visible(page) -> bool:
    """True if a 'Start free trial' / 'Buy now' upsell dialog is showing."""
    for sel in S.PAYWALL_MARKERS:
        if sel.get("role"):
            role, name = sel["role"]
            loc = page.get_by_role(role, name=name)
        elif sel.get("text"):
            loc = page.get_by_text(sel["text"], exact=False)
        else:
            continue
        try:
            if loc.first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


# Menu-ish roles whose accessible names may carry a shortcut on a 2nd line.
_MENU_ROLES = {"menuitem", "menuitemcheckbox", "menuitemradio"}


def _first_line(name: str) -> str:
    """First line of an accessible name, trimmed (drops shortcut suffix)."""
    return (name or "").split("\n", 1)[0].strip()


def _parse_steps(raw: str) -> list[tuple[str, str]]:
    """Parse 'role:name > role:name' into [(role, name), ...].

    Only the first ':' splits role from name, so names may contain colons.
    """
    steps: list[tuple[str, str]] = []
    for chunk in raw.split(">"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(
                f"Bad step '{chunk}'. Use role:name, e.g. 'menuitem:Select'."
            )
        role, name = chunk.split(":", 1)
        steps.append((role.strip(), name.strip()))
    return steps


def _find_step_locator(page, role: str, name: str):
    """Return a visible locator for (role, name) using exact matching.

    For menu roles the match is on the FIRST LINE of the name only (names can
    include a shortcut on a second line), but still exact — so "Select" does
    not match "Select subject". For other roles, Playwright's exact match is
    used directly.
    """
    if role in _MENU_ROLES:
        try:
            loc = page.get_by_role(role)
            count = loc.count()
        except Exception:
            return None
        for i in range(min(count, 200)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                acc = (item.get_attribute("aria-label")
                       or item.inner_text(timeout=500)
                       or "")
            except Exception:
                continue
            if _first_line(acc) == name:  # exact first-line match
                return item
        return None

    # Non-menu roles: rely on Playwright's own exact matching.
    loc = page.get_by_role(role, name=name, exact=True)
    try:
        if loc.first.is_visible(timeout=1500):
            return loc.first
    except Exception:
        return None
    return None


def _closest_step_names(page, role: str, target: str, limit: int = 10) -> list[str]:
    """Closest visible names for a step, first-line-aware for menu roles."""
    import difflib

    raw = _visible_names_for_role(page, role)
    if role in _MENU_ROLES:
        candidates = sorted({_first_line(n) for n in raw if _first_line(n)})
    else:
        candidates = sorted(set(raw))
    if not candidates:
        return []
    ranked = difflib.get_close_matches(target, candidates, n=limit, cutoff=0.0)
    return ranked or candidates[:limit]


def _dump_menus_and_dialogs(page) -> dict:
    """Capture open menu entries and dialog contents after navigation."""
    menu_items: list[dict] = []
    for role in ("menuitem", "menuitemcheckbox", "menuitemradio"):
        try:
            loc = page.get_by_role(role)
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 200)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                name = (item.get_attribute("aria-label")
                        or item.inner_text(timeout=500)
                        or "").strip()
            except Exception:
                name = ""
            entry = {"role": role, "name": name[:160]}
            if role in ("menuitemcheckbox", "menuitemradio"):
                entry["checked"] = _checked_state(item)
            menu_items.append(entry)

    dialog = _dump_dialog(page)

    # De-dup menu items while preserving order.
    seen = set()
    unique_items = []
    for d in menu_items:
        key = (d["role"], d["name"], d.get("checked"))
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(d)

    return {"menu_items": unique_items, "dialog": dialog}


def _dump_dialog(page) -> dict | None:
    """Capture controls inside the open dialog, if any."""
    try:
        dlg = page.get_by_role("dialog").first
        if not dlg.is_visible(timeout=800):
            return None
    except Exception:
        return None

    controls: list[dict] = []
    for role in ("button", "radio", "checkbox", "combobox", "textbox"):
        try:
            loc = dlg.get_by_role(role)
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 100)):
            item = loc.nth(i)
            try:
                if not item.is_visible():
                    continue
                name = (item.get_attribute("aria-label")
                        or item.inner_text(timeout=500)
                        or "").strip()
            except Exception:
                name = ""
            entry = {"role": role, "name": name[:160]}
            if role in ("radio", "checkbox"):
                entry["checked"] = _checked_state(item)
            controls.append(entry)

    name = ""
    try:
        name = (dlg.get_attribute("aria-label") or "").strip()
    except Exception:
        name = ""
    return {"name": name[:160], "controls": controls}


def _checked_state(item):
    """Return True/False/None for a control's checked state."""
    try:
        return item.is_checked()
    except Exception:
        pass
    try:
        val = item.get_attribute("aria-checked")
        if val in ("true", "false"):
            return val == "true"
    except Exception:
        pass
    return None


def _navigate_steps(page, steps: list[tuple[str, str]]) -> bool:
    """Click each (role, name) step in order. Return True on success.

    Aborts (returns False) if a step has no exact visible match (printing the
    closest names) or if a paywall appears at any step.
    """
    for idx, (role, name) in enumerate(steps, start=1):
        # Paywall can appear before OR after a click; check at each step entry.
        if _paywall_visible(page):
            print("PAYWALL hit")
            _press_escape(page)
            return False

        print(f"Step {idx}/{len(steps)}: click role={role!r} name={name!r} "
              "(exact, case-sensitive)...")
        item = _find_step_locator(page, role, name)
        if item is None:
            print(f"  No exact, visible {role} named '{name}'. "
                  "Closest visible names:")
            for cand in _closest_step_names(page, role, name):
                print(f"    - {cand}")
            return False

        try:
            item.click()
        except Exception as exc:
            print(f"  Could not click step {idx} ({exc}).")
            return False

        time.sleep(0.5)  # let the next submenu / dialog animate open

        if _paywall_visible(page):
            print("PAYWALL hit")
            _press_escape(page)
            return False

    return True


def _press_escape(page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump Photoshop Web UI labels.")
    parser.add_argument(
        "--after-click",
        metavar="NAME",
        default=None,
        help="Click a control whose accessible name EXACTLY (case-sensitive) "
             "matches NAME before dumping.",
    )
    parser.add_argument(
        "--role",
        metavar="ROLE",
        default="button",
        help="ARIA role to match for --after-click (default: button).",
    )
    parser.add_argument(
        "--steps",
        metavar="PATH",
        default=None,
        help="Navigate a multi-level menu, e.g. "
             "'button:Main menu > menuitem:Select'. Each step is role:name, "
             "clicked in order with exact matching.",
    )
    args = parser.parse_args()

    steps = None
    if args.steps:
        try:
            steps = _parse_steps(args.steps)
        except ValueError as exc:
            print(str(exc))
            return 2
        if not steps:
            print("--steps was empty; nothing to navigate.")
            return 2

    if not cdp_endpoint_up(PS_CDP_URL):
        print(f"Chrome not reachable at {PS_CDP_URL}.")
        print("Run start_chrome.bat first, then re-run this script.")
        return 1

    from playwright.sync_api import sync_playwright

    out_dir = DATA_DIR / "ui_dump"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"{stamp}.json"
    png_path = out_dir / f"{stamp}.png"

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
            page = context.new_page()
            page.goto(PHOTOSHOP_URL, wait_until="domcontentloaded")
        else:
            try:
                page.bring_to_front()
            except Exception:
                pass

        if steps is not None:
            if not _navigate_steps(page, steps):
                return 1
        elif args.after_click:
            print(
                f"Clicking role={args.role!r} name={args.after_click!r} "
                "(exact, case-sensitive) before dumping..."
            )
            # Exact, case-sensitive match on the accessible name for the given
            # role. No substring / fuzzy matching.
            loc = page.get_by_role(args.role, name=args.after_click, exact=True)
            matched = False
            try:
                matched = loc.first.is_visible(timeout=1500)
            except Exception:
                matched = False

            if not matched:
                print(
                    f"  No exact, visible {args.role} named "
                    f"'{args.after_click}'. Closest visible names:"
                )
                for name in _closest_names(page, args.role, args.after_click):
                    print(f"    - {name}")
                return 1

            loc.first.click()
            time.sleep(0.6)  # let any menu/dialog animate open

            # If a paywall / upsell dialog appeared, bail out and dismiss it.
            if _paywall_visible(page):
                print("PAYWALL hit")
                _press_escape(page)
                return 1

        controls = _collect(page)
        payload = {
            "timestamp": stamp,
            "url": page.url,
            "after_click": args.after_click,
            "steps": [f"{r}:{n}" for r, n in steps] if steps else None,
            "count": len(controls),
            "controls": controls,
        }
        # After multi-step navigation, capture the opened menu / dialog in more
        # detail (checked state, dialog controls).
        if steps is not None:
            payload["navigation"] = _dump_menus_and_dialogs(page)

        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            page.screenshot(path=str(png_path), full_page=False)
        except Exception as exc:
            print(f"  (screenshot failed: {exc})")

        print(f"Wrote {len(controls)} controls to {json_path}")
        if steps is not None:
            nav = payload["navigation"]
            dlg = nav.get("dialog")
            print(f"  navigation: {len(nav['menu_items'])} menu items, "
                  f"dialog={'yes' if dlg else 'no'}")
        print(f"Screenshot: {png_path}")
        return 0
    finally:
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
