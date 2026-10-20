"""Color Adjustment recipe: brightness / contrast / saturation.

Params:
    brightness : -100..100
    contrast   : -100..100
    saturation : -100..100
"""
from __future__ import annotations

from .. import selectors as S
from . import recipe


@recipe("color_adjustment")
def color_adjustment(session, params: dict, log) -> None:
    brightness = params.get("brightness", 0)
    contrast = params.get("contrast", 0)
    log("info", f"Color Adjustment: brightness={brightness} contrast={contrast}")

    # ================= TODO: PASTE RECORDED SELECTORS =================
    # Fill in selectors.py: S.ADJUSTMENTS_MENU, S.BRIGHTNESS_CONTRAST_ITEM,
    # S.BRIGHTNESS_INPUT, S.CONTRAST_INPUT, S.ADJUSTMENT_OK
    #
    # Reference flow once selectors exist:
    #
    #   session._resolve(S.ADJUSTMENTS_MENU).first.click()
    #   session._resolve(S.BRIGHTNESS_CONTRAST_ITEM).first.click()
    #   session.wait_for_text("Brightness")            # explicit condition
    #   session.debug_shot("brightness_dialog")
    #
    #   session._resolve(S.BRIGHTNESS_INPUT).first.fill(str(brightness))
    #   session._resolve(S.CONTRAST_INPUT).first.fill(str(contrast))
    #   session._resolve(S.ADJUSTMENT_OK).first.click()
    #   log("success", "Applied brightness/contrast")
    #   session.debug_shot("adjustment_applied")
    # ==================================================================

    _unimplemented(log)


def _unimplemented(log) -> None:
    msg = (
        "Color Adjustment selectors not recorded yet. Fill the TODO block in "
        "recipes/color_adjustment.py + selectors.py, or use DEMO_MODE=1."
    )
    log("error", msg)
    raise NotImplementedError(msg)
