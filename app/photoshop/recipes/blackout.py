"""Blackout recipe: make all black areas of the image transparent.

Photoshop approach:
    Select > Color Range (sampled color = black, fuzziness = Softness) >
    Delete the selection so black becomes transparent > export PNG.

The Softness slider (0..60) maps to Color Range "Fuzziness", widening how much
near-black (JPG artifacts) is swallowed.

Every step logs a line, waits for an explicit condition, and saves a debug
screenshot. The export is done by the session after this returns.
"""
from __future__ import annotations

from .. import selectors as S
from . import recipe


@recipe("blackout")
def blackout(session, params: dict, log) -> None:
    softness = int(params.get("softness", 20))
    softness = max(0, min(60, softness))
    log("info", f"Blackout: targeting black pixels with softness {softness}")

    # ================= TODO: PASTE RECORDED SELECTORS =================
    # Record this flow with `playwright codegen https://photoshop.adobe.com`
    # and fill the matching constants in selectors.py:
    #   S.SELECT_MENU, S.COLOR_RANGE_MENU_ITEM, S.COLOR_RANGE_SAMPLE_BLACK,
    #   S.COLOR_RANGE_FUZZINESS_INPUT, S.COLOR_RANGE_OK
    #
    # Reference flow once selectors exist:
    #
    #   select_menu = session._resolve(S.SELECT_MENU)
    #   select_menu.first.click()
    #   log("info", "Opened Select menu"); session.debug_shot("select_menu")
    #
    #   color_range = session._resolve(S.COLOR_RANGE_MENU_ITEM)
    #   color_range.first.click()
    #   session.wait_for_text("Color Range")       # explicit condition
    #   session.debug_shot("color_range_dialog")
    #
    #   # Sample black as the target color.
    #   session._resolve(S.COLOR_RANGE_SAMPLE_BLACK).first.click()
    #
    #   # Fuzziness driven by the Softness slider.
    #   fuzz = session._resolve(S.COLOR_RANGE_FUZZINESS_INPUT)
    #   fuzz.first.fill(str(softness))
    #   session.debug_shot("fuzziness_set")
    #
    #   session._resolve(S.COLOR_RANGE_OK).first.click()
    #   log("success", "Black range selected")
    #
    #   # Delete selection -> black becomes transparent.
    #   session.shortcut("delete_selection")
    #   session.shortcut("deselect")
    #   log("success", "Deleted black areas (now transparent)")
    #   session.debug_shot("blacked_out")
    # ==================================================================

    _unimplemented(log)


def _unimplemented(log) -> None:
    msg = (
        "Blackout Photoshop selectors not recorded yet. Fill the TODO block in "
        "recipes/blackout.py + selectors.py, or set BLACKOUT_ENGINE=pillow / "
        "DEMO_MODE=1 to use the local engine."
    )
    log("error", msg)
    raise NotImplementedError(msg)
