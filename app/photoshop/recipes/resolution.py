"""Resolution recipe: change image size / DPI via Image > Image size.

Params:
    width, height : target pixels (optional)
    scale         : percent scale (optional, overrides width/height)
    dpi           : output resolution
"""
from __future__ import annotations

from .. import selectors as S
from . import recipe


@recipe("resolution")
def resolution(session, params: dict, log) -> None:
    width = params.get("width")
    height = params.get("height")
    scale = params.get("scale")
    dpi = params.get("dpi")
    log(
        "info",
        f"Resolution: width={width} height={height} scale={scale} dpi={dpi}",
    )

    # ================= TODO: PASTE RECORDED SELECTORS =================
    # Fill in selectors.py: S.IMAGE_MENU, S.IMAGE_SIZE_MENU_ITEM,
    # S.IMAGE_SIZE_WIDTH_INPUT, S.IMAGE_SIZE_HEIGHT_INPUT,
    # S.IMAGE_SIZE_RESOLUTION_INPUT, S.IMAGE_SIZE_OK
    #
    # Reference flow once selectors exist:
    #
    #   session._resolve(S.IMAGE_MENU).first.click()
    #   session._resolve(S.IMAGE_SIZE_MENU_ITEM).first.click()
    #   session.wait_for_text("Image Size")            # explicit condition
    #   session.debug_shot("image_size_dialog")
    #
    #   if width:  session._resolve(S.IMAGE_SIZE_WIDTH_INPUT).first.fill(str(width))
    #   if height: session._resolve(S.IMAGE_SIZE_HEIGHT_INPUT).first.fill(str(height))
    #   if dpi:    session._resolve(S.IMAGE_SIZE_RESOLUTION_INPUT).first.fill(str(dpi))
    #
    #   session._resolve(S.IMAGE_SIZE_OK).first.click()
    #   log("success", "Applied new image size")
    #   session.debug_shot("image_size_applied")
    # ==================================================================

    _unimplemented(log)


def _unimplemented(log) -> None:
    msg = (
        "Resolution selectors not recorded yet. Fill the TODO block in "
        "recipes/resolution.py + selectors.py, or use DEMO_MODE=1."
    )
    log("error", msg)
    raise NotImplementedError(msg)
