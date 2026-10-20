"""Pixel-level image operations (Pillow + NumPy + OpenCV).

These run locally and never touch Photoshop. They back three UI operations
(Ghost Pixel Removal, Transparent Pixel Cleanup, Semi-Pixel Cleanup) and
provide a reference Pillow implementation of Blackout so its output can be
compared against the Photoshop-driven version.

All functions take and return RGBA numpy arrays unless noted. Helpers are
provided to load/save PNGs with transparency preserved.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------
def load_rgba(path: str | Path) -> np.ndarray:
    """Load an image as an H x W x 4 uint8 RGBA array."""
    img = Image.open(path).convert("RGBA")
    return np.array(img, dtype=np.uint8)


def save_rgba(arr: np.ndarray, path: str | Path) -> None:
    """Save an RGBA array as a PNG, preserving transparency."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8), mode="RGBA").save(path, format="PNG")


# ---------------------------------------------------------------------------
# Blackout reference (color-to-alpha)
# ---------------------------------------------------------------------------
def blackout_color_to_alpha(
    arr: np.ndarray,
    softness: int = 20,
) -> np.ndarray:
    """Make black areas transparent, mimicking a 'color to alpha' on black.

    The alpha for each pixel becomes max(R, G, B) scaled to 0..255: a fully
    black pixel disappears, a bright pixel stays opaque, and dark/greyish
    pixels become partially transparent. Colours are then "un-premultiplied"
    so surviving pixels keep their true hue instead of looking washed out.

    `softness` (0..60) widens the near-black band that is pulled toward
    transparency, which helps swallow JPG compression artifacts around edges.
    It maps to a small threshold below which pixels are forced fully clear and
    a smoothstep ramp above it.
    """
    rgba = arr.astype(np.float32)
    rgb = rgba[..., :3]
    orig_alpha = rgba[..., 3:4] / 255.0

    # Base alpha from brightness: brightest channel drives opacity.
    max_c = rgb.max(axis=2, keepdims=True) / 255.0  # 0..1

    softness = int(max(0, min(60, softness)))
    # Map softness to a 0..~0.35 cutoff; near-black pixels below `lo` go clear.
    lo = (softness / 60.0) * 0.35
    hi = max(lo + 1e-3, lo + 0.15)  # ramp width above the cutoff

    # Smoothstep from lo..hi so the transition is soft, not a hard key.
    t = np.clip((max_c - lo) / (hi - lo), 0.0, 1.0)
    smooth = t * t * (3.0 - 2.0 * t)
    new_alpha = smooth  # 0..1

    # Respect any pre-existing transparency in the source.
    new_alpha = new_alpha * orig_alpha

    # Un-premultiply: recover true colour where the key darkened it.
    safe_alpha = np.clip(new_alpha, 1e-4, 1.0)
    unmult = np.clip(rgb / (safe_alpha * 255.0) * 255.0, 0, 255)
    # Only un-premultiply where alpha is partial; keep original where opaque.
    out_rgb = np.where(new_alpha < 1.0, unmult, rgb)

    out = np.concatenate([out_rgb, new_alpha * 255.0], axis=2)
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Semi-pixel cleanup
# ---------------------------------------------------------------------------
def semi_pixel_cleanup(
    arr: np.ndarray,
    low: int = 40,
    high: int = 215,
) -> np.ndarray:
    """Harden fuzzy alpha: push low alpha to 0 and high alpha to 255.

    Pixels with alpha < `low` become fully transparent, pixels with alpha >
    `high` become fully opaque, and values in between are left untouched so
    genuine anti-aliasing survives.
    """
    out = arr.copy()
    alpha = out[..., 3].astype(np.int32)
    alpha = np.where(alpha < low, 0, alpha)
    alpha = np.where(alpha > high, 255, alpha)
    out[..., 3] = alpha.astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Ghost pixel removal
# ---------------------------------------------------------------------------
def ghost_pixel_removal(
    arr: np.ndarray,
    min_area: int = 12,
    alpha_threshold: int = 10,
) -> np.ndarray:
    """Remove tiny isolated specks of visible pixels via connected components.

    Any connected blob of visible pixels (alpha > `alpha_threshold`) whose
    area is smaller than `min_area` is cleared to transparent. This wipes the
    stray 1-3px "ghosts" left behind by keying.
    """
    out = arr.copy()
    mask = (out[..., 3] > alpha_threshold).astype(np.uint8)

    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    # label 0 is the background; iterate real components.
    remove = np.zeros(mask.shape, dtype=bool)
    for label in range(1, num):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
            remove |= labels == label

    out[remove, 3] = 0
    return out


# ---------------------------------------------------------------------------
# Transparent pixel cleanup
# ---------------------------------------------------------------------------
def transparent_pixel_cleanup(
    arr: np.ndarray,
    defringe: bool = True,
) -> np.ndarray:
    """Zero RGB where alpha == 0 and optionally defringe a 1px edge.

    Fully transparent pixels often carry leftover colour that bleeds when the
    image is scaled or composited. Zeroing their RGB removes that halo. When
    `defringe` is set, a 1px rim just inside the edge is replaced with the
    colour of its nearest fully-opaque neighbour to kill matte fringing.
    """
    out = arr.copy()
    alpha = out[..., 3]

    # Zero RGB where fully transparent.
    fully_clear = alpha == 0
    out[fully_clear, 0] = 0
    out[fully_clear, 1] = 0
    out[fully_clear, 2] = 0

    if defringe:
        # Opaque core mask; erode to find a 1px rim of edge pixels.
        opaque = (alpha > 0).astype(np.uint8)
        kernel = np.ones((3, 3), np.uint8)
        eroded = cv2.erode(opaque, kernel, iterations=1)
        rim = (opaque == 1) & (eroded == 0)

        if rim.any():
            # Inpaint the rim's RGB from the solid interior using nearest
            # opaque colour. Use OpenCV's dilation of the interior colours.
            interior = (eroded == 1).astype(np.uint8)
            # Nearest-neighbour fill: iteratively dilate interior colours.
            filled = out[..., :3].copy()
            known = interior.copy()
            for _ in range(2):
                dilated_known = cv2.dilate(known, kernel, iterations=1)
                new_edge = (dilated_known == 1) & (known == 0)
                if not new_edge.any():
                    break
                for c in range(3):
                    chan = filled[..., c]
                    blurred = cv2.dilate(chan * known, kernel, iterations=1)
                    chan[new_edge] = blurred[new_edge]
                    filled[..., c] = chan
                known = dilated_known
            out[rim, :3] = filled[rim, :3]

    return out


# ---------------------------------------------------------------------------
# Dispatch helper used by the worker in DEMO_MODE / Pillow engine
# ---------------------------------------------------------------------------
def run_pillow_op(
    op: str,
    src_path: str | Path,
    dst_path: str | Path,
    params: Optional[dict] = None,
) -> None:
    """Run a local pixel op end to end: load, process, save PNG.

    Supports every operation the UI can request. Photoshop-only ops fall back
    to a sensible local approximation so DEMO_MODE always produces output.
    """
    params = params or {}
    arr = load_rgba(src_path)

    if op == "blackout":
        softness = int(params.get("softness", 20))
        arr = blackout_color_to_alpha(arr, softness=softness)
    elif op == "semi_pixel_cleanup":
        arr = semi_pixel_cleanup(
            arr,
            low=int(params.get("low", 40)),
            high=int(params.get("high", 215)),
        )
    elif op == "ghost_pixel_removal":
        arr = ghost_pixel_removal(
            arr,
            min_area=int(params.get("min_area", 12)),
            alpha_threshold=int(params.get("alpha_threshold", 10)),
        )
    elif op == "transparent_pixel_cleanup":
        arr = transparent_pixel_cleanup(
            arr,
            defringe=bool(params.get("defringe", True)),
        )
    elif op == "remove_background":
        # Local approximation: treat near-black OR near-uniform border as bg.
        # Real version is Photoshop-driven; this keeps DEMO_MODE useful.
        arr = blackout_color_to_alpha(arr, softness=int(params.get("softness", 20)))
    elif op == "resolution":
        arr = _resize(arr, params)
    elif op == "color_adjustment":
        arr = _color_adjust(arr, params)
    else:
        # Unknown op: pass through unchanged rather than failing hard.
        pass

    save_rgba(arr, dst_path)


def _resize(arr: np.ndarray, params: dict) -> np.ndarray:
    h, w = arr.shape[:2]
    scale = params.get("scale")
    if scale:
        new_w = max(1, int(round(w * float(scale) / 100.0)))
        new_h = max(1, int(round(h * float(scale) / 100.0)))
    else:
        new_w = int(params.get("width") or w)
        new_h = int(params.get("height") or h)
    resized = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized


def _color_adjust(arr: np.ndarray, params: dict) -> np.ndarray:
    brightness = float(params.get("brightness", 0))  # -100..100
    contrast = float(params.get("contrast", 0))      # -100..100
    saturation = float(params.get("saturation", 0))  # -100..100

    rgb = arr[..., :3].astype(np.float32)
    alpha = arr[..., 3:4]

    # Brightness as additive, contrast as a pivot around 128.
    rgb = rgb + (brightness / 100.0) * 255.0
    c = 1.0 + (contrast / 100.0)
    rgb = (rgb - 128.0) * c + 128.0
    rgb = np.clip(rgb, 0, 255)

    if saturation != 0:
        hsv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[..., 1] *= 1.0 + (saturation / 100.0)
        hsv[..., 1] = np.clip(hsv[..., 1], 0, 255)
        rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

    return np.concatenate([rgb, alpha], axis=2).astype(np.uint8)
