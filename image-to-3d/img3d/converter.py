"""Core image-to-3D conversion logic.

Modes:
  lithophane — grayscale relief panel; bright pixels become thin so light passes through.
               Print in white/translucent PLA, hold up to a light source.
  relief     — foreground object raised above a flat base.
  emboss     — same as relief (foreground raised); kept for naming symmetry.
"""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .stl_writer import triangles_to_stl_bytes


@dataclass
class ConvertSettings:
    mode: str = "relief"            # lithophane | relief | emboss
    base_shape: str = "rectangle"   # rectangle | circle
    width_mm: float = 100.0
    resolution: int = 150
    remove_bg: bool = True          # detect background by corners, raise foreground only
    # lithophane
    min_thickness_mm: float = 0.8
    max_thickness_mm: float = 3.0
    # relief / emboss
    base_mm: float = 1.0
    relief_height_mm: float = 3.5
    smooth: bool = True


# ---------------------------------------------------------------------------
# Image loaders
# ---------------------------------------------------------------------------

def _load_grayscale(image_data: bytes, target_width: int) -> tuple[np.ndarray, float]:
    """Load as grayscale, flip Y so image appears right-side-up in the mesh."""
    img = Image.open(io.BytesIO(image_data)).convert("L")
    w, h = img.size
    aspect = h / w
    new_h = max(2, int(target_width * aspect))
    img = img.resize((target_width, new_h), Image.LANCZOS)
    pixels = np.array(img, dtype=np.float32) / 255.0
    return np.flipud(pixels), aspect


def _load_foreground(image_data: bytes, target_width: int) -> tuple[np.ndarray, float]:
    """Per-pixel color distance from the background (sampled from corners).

    Returns a heightmap where 0 = background, 1 = maximally different from bg.
    This raises the subject regardless of whether it's dark or light.
    """
    img = Image.open(io.BytesIO(image_data)).convert("RGB")
    w, h = img.size
    aspect = h / w
    new_h = max(2, int(target_width * aspect))
    img = img.resize((target_width, new_h), Image.LANCZOS)

    arr = np.array(img, dtype=np.float32) / 255.0  # (H, W, 3)
    H, W = arr.shape[:2]

    # Estimate background from the four corners
    corners = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]])
    bg = np.median(corners, axis=0)  # (3,) median RGB

    # Euclidean distance from bg color per pixel
    dist = np.sqrt(np.sum((arr - bg) ** 2, axis=2))  # (H, W)

    max_d = dist.max()
    height = dist / max_d if max_d > 1e-6 else np.zeros_like(dist)

    return np.flipud(height), aspect  # flip Y so image is right-side-up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _smooth(pixels: np.ndarray) -> np.ndarray:
    img = Image.fromarray((pixels * 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    return np.array(img, dtype=np.float32) / 255.0


def _apply_circle_mask(pixels: np.ndarray, fill_value: float) -> np.ndarray:
    rows, cols = pixels.shape
    cy, cx = (rows - 1) / 2.0, (cols - 1) / 2.0
    r = min(cy, cx)
    y_idx = np.arange(rows, dtype=np.float32)[:, np.newaxis]
    x_idx = np.arange(cols, dtype=np.float32)[np.newaxis, :]
    inside = ((y_idx - cy) ** 2 + (x_idx - cx) ** 2) <= r ** 2
    return np.where(inside, pixels, fill_value)


def _build_mesh(z_grid: np.ndarray, x_scale: float, y_scale: float) -> np.ndarray:
    """Build a watertight mesh from a height grid (top + bottom + four walls)."""
    rows, cols = z_grid.shape
    x = np.arange(cols, dtype=np.float32) * x_scale
    y = np.arange(rows, dtype=np.float32) * y_scale
    xx, yy = np.meshgrid(x, y)

    # Top surface
    v00 = np.stack([xx[:-1, :-1], yy[:-1, :-1], z_grid[:-1, :-1]], axis=-1)
    v10 = np.stack([xx[1:,  :-1], yy[1:,  :-1], z_grid[1:,  :-1]], axis=-1)
    v01 = np.stack([xx[:-1, 1:],  yy[:-1, 1:],  z_grid[:-1, 1:] ], axis=-1)
    v11 = np.stack([xx[1:,  1:],  yy[1:,  1:],  z_grid[1:,  1:] ], axis=-1)
    top = np.concatenate([
        np.stack([v00, v01, v11], axis=2).reshape(-1, 3, 3),
        np.stack([v00, v11, v10], axis=2).reshape(-1, 3, 3),
    ])

    # Flat bottom at z=0 (reversed winding for downward normal)
    b00 = np.stack([xx[:-1, :-1], yy[:-1, :-1], np.zeros_like(xx[:-1, :-1])], axis=-1)
    b10 = np.stack([xx[1:,  :-1], yy[1:,  :-1], np.zeros_like(xx[1:,  :-1])], axis=-1)
    b01 = np.stack([xx[:-1, 1:],  yy[:-1, 1:],  np.zeros_like(xx[:-1, 1:]) ], axis=-1)
    b11 = np.stack([xx[1:,  1:],  yy[1:,  1:],  np.zeros_like(xx[1:,  1:]) ], axis=-1)
    bottom = np.concatenate([
        np.stack([b00, b10, b11], axis=2).reshape(-1, 3, 3),
        np.stack([b00, b11, b01], axis=2).reshape(-1, 3, 3),
    ])

    max_x, max_y = x[-1], y[-1]

    def _wall(ax, ay, az, bx, by, bz):
        a_top = np.array([ax, ay, az], dtype=np.float32)
        b_top = np.array([bx, by, bz], dtype=np.float32)
        a_bot = np.array([ax, ay, 0.0], dtype=np.float32)
        b_bot = np.array([bx, by, 0.0], dtype=np.float32)
        return np.array([[a_top, b_top, b_bot], [a_top, b_bot, a_bot]], dtype=np.float32)

    sides = []
    for c in range(cols - 1):
        sides.append(_wall(x[c], 0, z_grid[0, c], x[c+1], 0, z_grid[0, c+1]))
    for c in range(cols - 1, 0, -1):
        sides.append(_wall(x[c], max_y, z_grid[-1, c], x[c-1], max_y, z_grid[-1, c-1]))
    for r in range(rows - 1, 0, -1):
        sides.append(_wall(0, y[r], z_grid[r, 0], 0, y[r-1], z_grid[r-1, 0]))
    for r in range(rows - 1):
        sides.append(_wall(max_x, y[r], z_grid[r, -1], max_x, y[r+1], z_grid[r+1, -1]))

    return np.concatenate([top, bottom, np.concatenate(sides)])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_image(image_data: bytes, settings: ConvertSettings) -> bytes:
    """Convert image bytes to binary STL bytes."""
    use_fg = settings.remove_bg and settings.mode != "lithophane"

    if use_fg:
        # Color-distance heightmap: bg=0 (flat), subject=1 (raised)
        pixels, aspect = _load_foreground(image_data, settings.resolution)
    else:
        pixels, aspect = _load_grayscale(image_data, settings.resolution)

    if settings.smooth:
        pixels = _smooth(pixels)

    if settings.base_shape == "circle":
        fill = 1.0 if settings.mode == "lithophane" else 0.0
        pixels = _apply_circle_mask(pixels, fill)

    if settings.mode == "lithophane":
        z_grid = settings.min_thickness_mm + (1.0 - pixels) * (
            settings.max_thickness_mm - settings.min_thickness_mm
        )
    elif use_fg:
        # Both relief and emboss: foreground pixel = raised
        z_grid = settings.base_mm + pixels * settings.relief_height_mm
    elif settings.mode == "relief":
        z_grid = settings.base_mm + pixels * settings.relief_height_mm
    elif settings.mode == "emboss":
        z_grid = settings.base_mm + (1.0 - pixels) * settings.relief_height_mm
    else:
        raise ValueError(f"Unknown mode: {settings.mode!r}")

    rows, cols = z_grid.shape
    height_mm = settings.width_mm * aspect
    x_scale = settings.width_mm / (cols - 1)
    y_scale = height_mm / (rows - 1)

    return triangles_to_stl_bytes(_build_mesh(z_grid, x_scale, y_scale))
