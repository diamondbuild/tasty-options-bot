"""Core image-to-3D conversion logic.

Modes:
  lithophane — grayscale relief panel; bright pixels become thin so light passes through.
               Print in white/translucent PLA, hold up to a light source.
  relief     — image brightness drives raised height above a flat base.
  emboss     — inverted relief; dark areas become raised.
"""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .stl_writer import triangles_to_stl_bytes


@dataclass
class ConvertSettings:
    mode: str = "lithophane"        # lithophane | relief | emboss
    width_mm: float = 100.0         # physical width of the print
    resolution: int = 150           # pixel width used for the mesh
    # lithophane
    min_thickness_mm: float = 0.8   # thinnest point (bright pixels)
    max_thickness_mm: float = 3.0   # thickest point (dark pixels)
    # relief / emboss
    base_mm: float = 1.0            # flat base height
    relief_height_mm: float = 3.0   # max raised height above base
    smooth: bool = True             # Gaussian blur before meshing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_grayscale(image_data: bytes, target_width: int) -> tuple[np.ndarray, float]:
    """Load image, resize to target_width, return (H×W float32 0-1, aspect_ratio)."""
    img = Image.open(io.BytesIO(image_data)).convert("L")
    w, h = img.size
    aspect = h / w
    new_h = max(2, int(target_width * aspect))
    img = img.resize((target_width, new_h), Image.LANCZOS)
    return np.array(img, dtype=np.float32) / 255.0, aspect


def _smooth(pixels: np.ndarray) -> np.ndarray:
    img = Image.fromarray((pixels * 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    return np.array(img, dtype=np.float32) / 255.0


def _build_mesh(z_grid: np.ndarray, x_scale: float, y_scale: float) -> np.ndarray:
    """Build a watertight mesh from a height grid.

    Returns (N, 3, 3) triangle array covering:
      - top surface (variable height)
      - flat bottom at z=0
      - four side walls
    """
    rows, cols = z_grid.shape

    x = np.arange(cols, dtype=np.float32) * x_scale
    y = np.arange(rows, dtype=np.float32) * y_scale
    xx, yy = np.meshgrid(x, y)

    # --- top surface ---
    v00 = np.stack([xx[:-1, :-1], yy[:-1, :-1], z_grid[:-1, :-1]], axis=-1)
    v10 = np.stack([xx[1:,  :-1], yy[1:,  :-1], z_grid[1:,  :-1]], axis=-1)
    v01 = np.stack([xx[:-1, 1:],  yy[:-1, 1:],  z_grid[:-1, 1:] ], axis=-1)
    v11 = np.stack([xx[1:,  1:],  yy[1:,  1:],  z_grid[1:,  1:] ], axis=-1)

    top_t1 = np.stack([v00, v01, v11], axis=2).reshape(-1, 3, 3)
    top_t2 = np.stack([v00, v11, v10], axis=2).reshape(-1, 3, 3)
    top = np.concatenate([top_t1, top_t2], axis=0)

    # --- flat bottom at z=0 ---
    b00 = np.stack([xx[:-1, :-1], yy[:-1, :-1], np.zeros_like(xx[:-1, :-1])], axis=-1)
    b10 = np.stack([xx[1:,  :-1], yy[1:,  :-1], np.zeros_like(xx[1:,  :-1])], axis=-1)
    b01 = np.stack([xx[:-1, 1:],  yy[:-1, 1:],  np.zeros_like(xx[:-1, 1:]) ], axis=-1)
    b11 = np.stack([xx[1:,  1:],  yy[1:,  1:],  np.zeros_like(xx[1:,  1:]) ], axis=-1)

    # Reversed winding for downward-facing normal
    bot_t1 = np.stack([b00, b10, b11], axis=2).reshape(-1, 3, 3)
    bot_t2 = np.stack([b00, b11, b01], axis=2).reshape(-1, 3, 3)
    bottom = np.concatenate([bot_t1, bot_t2], axis=0)

    # --- four side walls (connect top edge to bottom edge) ---
    max_x = x[-1]
    max_y = y[-1]

    def _side_quad(ax, ay, az, bx, by, bz):
        """Two triangles for a quad, with bz=0 bottom counterpart."""
        a_top = np.array([ax, ay, az], dtype=np.float32)
        b_top = np.array([bx, by, bz], dtype=np.float32)
        a_bot = np.array([ax, ay, 0.0], dtype=np.float32)
        b_bot = np.array([bx, by, 0.0], dtype=np.float32)
        return np.array([
            [a_top, b_top, b_bot],
            [a_top, b_bot, a_bot],
        ], dtype=np.float32)

    sides = []

    # Front edge (y=0): x from 0→max_x
    for c in range(cols - 1):
        sides.append(_side_quad(x[c], 0, z_grid[0, c], x[c+1], 0, z_grid[0, c+1]))

    # Back edge (y=max_y): x from max_x→0 (reversed for correct normal)
    for c in range(cols - 1, 0, -1):
        sides.append(_side_quad(x[c], max_y, z_grid[-1, c], x[c-1], max_y, z_grid[-1, c-1]))

    # Left edge (x=0): y from max_y→0
    for r in range(rows - 1, 0, -1):
        sides.append(_side_quad(0, y[r], z_grid[r, 0], 0, y[r-1], z_grid[r-1, 0]))

    # Right edge (x=max_x): y from 0→max_y
    for r in range(rows - 1):
        sides.append(_side_quad(max_x, y[r], z_grid[r, -1], max_x, y[r+1], z_grid[r+1, -1]))

    side_tris = np.concatenate(sides, axis=0)

    return np.concatenate([top, bottom, side_tris], axis=0)


# ---------------------------------------------------------------------------
# Public converters
# ---------------------------------------------------------------------------

def convert_image(image_data: bytes, settings: ConvertSettings) -> bytes:
    """Convert image bytes to binary STL bytes."""
    pixels, aspect = _load_grayscale(image_data, settings.resolution)

    if settings.smooth:
        pixels = _smooth(pixels)

    if settings.mode == "lithophane":
        # Invert: bright → thin (more translucent), dark → thick
        z_grid = settings.min_thickness_mm + (1.0 - pixels) * (
            settings.max_thickness_mm - settings.min_thickness_mm
        )
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

    triangles = _build_mesh(z_grid, x_scale, y_scale)
    return triangles_to_stl_bytes(triangles)
