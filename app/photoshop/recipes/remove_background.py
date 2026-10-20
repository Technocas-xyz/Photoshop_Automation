"""Remove Background recipe (Photoshop Web Quick Action).

Photoshop approach:
    Use the "Remove background" quick action, wait for the mask to apply,
    then export as a transparent PNG.
"""
from __future__ import annotations

from .. import selectors as S
from . import recipe


@recipe("remove_background")
def remove_background(session, params: dict, log) -> None:
    log("info", "Remove Background: invoking Photoshop quick action")

    # ================= TODO: PASTE RECORDED SELECTORS =================
    # Fill S.REMOVE_BG_TRIGGER in selectors.py from `playwright codegen`.
    #
    # Reference flow once selectors exist:
    #
    #   trigger = session._resolve(S.REMOVE_BG_TRIGGER)
    #   trigger.first.click()
    #   log("info", "Triggered Remove background")
    #   session.debug_shot("remove_bg_started")
    #
    #   # Explicit condition: wait for the action to finish. Pick a stable
    #   # marker recorded from codegen (e.g. a "Background removed" toast or
    #   # the layer mask thumbnail appearing).
    #   session.wait_for_text("Background removed", timeout_ms=60000)
    #   log("success", "Background removed")
    #   session.debug_shot("remove_bg_done")
    # ==================================================================

    _unimplemented(log)


def _unimplemented(log) -> None:
    msg = (
        "Remove Background selectors not recorded yet. Fill the TODO block in "
        "recipes/remove_background.py + selectors.py, or use DEMO_MODE=1."
    )
    log("error", msg)
    raise NotImplementedError(msg)
