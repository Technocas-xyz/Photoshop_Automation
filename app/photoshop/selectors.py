"""Single source of truth for every Photoshop Web selector and label.

Adobe changes the Photoshop Web UI often. Keeping every locator string in one
place means that when something breaks you fix it HERE and nowhere else.

HOW TO FILL THESE IN
--------------------
1. Run `python login_once.py` and log in manually.
2. In a second terminal run:  playwright codegen https://photoshop.adobe.com
   (reusing the same profile with --load-storage if needed)
3. Click through the operation you want to script. Codegen prints the exact
   locators it recorded.
4. Paste those locators into the matching constant below.

Prefer, in order: role+name locators, visible text, stable test ids. Avoid
nth-child / absolute XPath / pixel coordinates — they rot fastest.

Each value is written as a dict so a recipe can try multiple candidate
locators in order until one resolves. Fill the lists with real values.
"""
from __future__ import annotations

# Generic app chrome ------------------------------------------------------
# A locator that is only present when a document is open and editable. Used
# to confirm the editor is ready after opening an image.
EDITOR_READY = {
    "role": None,            # e.g. ("button", "Export")
    "text": None,            # e.g. "Quick actions"
    "test_id": None,         # e.g. "ps-editor-root"
    "css": None,             # last-resort CSS fallback
}

# ---------------------------------------------------------------------------
# Login detection markers
# ---------------------------------------------------------------------------
# is_logged_in() checks these two lists. Prefer ROLE + accessible-name /
# aria-label locators (stable across Adobe redesigns); avoid CSS classes, which
# are generated and change constantly. Each entry is a selector dict understood
# by PhotoshopSession._resolve (role / text / test_id / css). Both lists are
# meant to be edited freely as the UI changes — add as many candidates as you
# like; the first that becomes visible wins.
#
# Record the real values with:  python tools/dump_ui.py   (see README).

# Any ONE of these being visible means we ARE signed in (e.g. the profile
# avatar / account button in the top-right).
LOGGED_IN_MARKERS = [
    {"role": ("button", "Account"), "text": None, "test_id": None, "css": None},
    {"role": ("button", "Profile"), "text": None, "test_id": None, "css": None},
    # aria-label on the avatar is often the user's name; match the generic
    # "Your profile" / account menu button by role when name is unknown:
    {"role": ("button", "Your account"), "text": None, "test_id": None, "css": None},
    # TODO: paste the real avatar/account button recorded via tools/dump_ui.py.
]

# Any ONE of these being visible means we are signed OUT.
LOGGED_OUT_MARKERS = [
    {"role": ("button", "Sign in"), "text": None, "test_id": None, "css": None},
    {"role": ("link", "Sign in"), "text": None, "test_id": None, "css": None},
    {"role": None, "text": "Sign in", "test_id": None, "css": None},
    {"role": None, "text": "Log in", "test_id": None, "css": None},
    # TODO: paste the real sign-in control recorded via tools/dump_ui.py.
]

# Backwards-compatible single marker (kept so nothing that imported the old
# name breaks). Points at the first logged-out candidate.
LOGGED_OUT_MARKER = LOGGED_OUT_MARKERS[0]

# ---------------------------------------------------------------------------
# Paywall / upsell markers
# ---------------------------------------------------------------------------
# When any ONE of these is visible, Adobe has thrown a "Start free trial" /
# "Buy now" upsell in front of the feature and the recipe cannot proceed. The
# session checks these before every recipe step and fails with a clear message
# so you don't get a silent, stuck job. Edit freely as Adobe changes wording.
PAYWALL_MARKERS = [
    {"role": None, "text": "Start free trial", "test_id": None, "css": None},
    {"role": None, "text": "Buy now", "test_id": None, "css": None},
    {"role": ("button", "Start free trial"), "text": None, "test_id": None, "css": None},
    {"role": ("button", "Buy now"), "text": None, "test_id": None, "css": None},
]

# Opening an image -------------------------------------------------------
# Entry point that triggers a file chooser (e.g. "Open image" / "Import").
OPEN_IMAGE_TRIGGER = {
    "role": None,            # e.g. ("button", "Open image")
    "text": None,
    "test_id": None,
    "css": None,
}

# Export / download ------------------------------------------------------
EXPORT_MENU_TRIGGER = {
    "role": None,            # e.g. ("button", "Export")
    "text": None,
    "test_id": None,
    "css": None,
}
EXPORT_AS_PNG = {
    "role": None,            # e.g. ("menuitem", "PNG")
    "text": "PNG",
    "test_id": None,
    "css": None,
}
EXPORT_CONFIRM = {
    "role": None,            # e.g. ("button", "Export") in the dialog
    "text": None,
    "test_id": None,
    "css": None,
}

# Keyboard shortcuts (preferred over clicking) ---------------------------
# Fill with real Photoshop Web shortcuts once confirmed.
SHORTCUTS = {
    "select_all": "Control+A",
    "deselect": "Control+D",
    "delete_selection": "Delete",
    "invert_selection": "Control+Shift+I",
}

# --- Select > Color Range (Blackout) ------------------------------------
SELECT_MENU = {"role": None, "text": "Select", "test_id": None, "css": None}
COLOR_RANGE_MENU_ITEM = {"role": None, "text": "Color Range", "test_id": None, "css": None}
COLOR_RANGE_FUZZINESS_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
COLOR_RANGE_SAMPLE_BLACK = {"role": None, "text": None, "test_id": None, "css": None}
COLOR_RANGE_OK = {"role": None, "text": "OK", "test_id": None, "css": None}

# --- Remove Background (Quick Action) -----------------------------------
REMOVE_BG_TRIGGER = {"role": None, "text": "Remove background", "test_id": None, "css": None}

# --- Image size / Resolution --------------------------------------------
IMAGE_MENU = {"role": None, "text": "Image", "test_id": None, "css": None}
IMAGE_SIZE_MENU_ITEM = {"role": None, "text": "Image size", "test_id": None, "css": None}
IMAGE_SIZE_WIDTH_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
IMAGE_SIZE_HEIGHT_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
IMAGE_SIZE_RESOLUTION_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
IMAGE_SIZE_OK = {"role": None, "text": "OK", "test_id": None, "css": None}

# --- Color adjustment (Brightness/Contrast, Hue/Saturation) -------------
ADJUSTMENTS_MENU = {"role": None, "text": "Adjustments", "test_id": None, "css": None}
BRIGHTNESS_CONTRAST_ITEM = {"role": None, "text": "Brightness/Contrast", "test_id": None, "css": None}
BRIGHTNESS_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
CONTRAST_INPUT = {"role": None, "text": None, "test_id": None, "css": None}
ADJUSTMENT_OK = {"role": None, "text": "OK", "test_id": None, "css": None}
