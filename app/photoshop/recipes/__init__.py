"""Recipe registry.

Each operation that drives Photoshop lives in its own module in this package
and registers itself with the `@recipe("op_name")` decorator. The worker looks
a recipe up by op name via `get_recipe`.

A recipe is a callable:  recipe(session, params: dict, log) -> None
It performs the editing steps on the already-open document. Opening the image
and exporting the result are handled by PhotoshopSession around the call.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

RecipeFn = Callable[..., None]

_REGISTRY: Dict[str, RecipeFn] = {}


def recipe(op_name: str) -> Callable[[RecipeFn], RecipeFn]:
    """Decorator that registers a recipe function under an op name."""

    def _wrap(fn: RecipeFn) -> RecipeFn:
        _REGISTRY[op_name] = fn
        return fn

    return _wrap


def get_recipe(op_name: str) -> Optional[RecipeFn]:
    # Import recipe modules on first lookup so their decorators run.
    _ensure_loaded()
    return _REGISTRY.get(op_name)


_LOADED = False


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    # Importing each module triggers its @recipe registration.
    from . import blackout          # noqa: F401
    from . import remove_background  # noqa: F401
    from . import resolution         # noqa: F401
    from . import color_adjustment   # noqa: F401

    _LOADED = True
