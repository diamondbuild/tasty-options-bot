"""Binary STL file generation using numpy."""
import struct
import numpy as np


def compute_normals(triangles: np.ndarray) -> np.ndarray:
    """Compute per-face normals. triangles: (N, 3, 3) → (N, 3)"""
    e1 = triangles[:, 1] - triangles[:, 0]
    e2 = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(e1, e2)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms = np.where(norms < 1e-10, 1.0, norms)
    return normals / norms


def triangles_to_stl_bytes(triangles: np.ndarray) -> bytes:
    """Convert (N, 3, 3) triangle array to binary STL bytes.

    Binary STL: 80B header, uint32 count, then per-triangle:
      float32[3] normal + float32[3]*3 verts + uint16 attr = 50 bytes
    """
    tris = np.asarray(triangles, dtype=np.float32)
    normals = compute_normals(tris)
    n = len(tris)

    # Build (N, 12) float32: [nx,ny,nz, v0x,v0y,v0z, v1x,v1y,v1z, v2x,v2y,v2z]
    flat = np.concatenate(
        [normals, tris[:, 0], tris[:, 1], tris[:, 2]], axis=1
    ).astype(np.float32)  # (N, 12)

    # Structured dtype: 12 floats (48 bytes) + uint16 (2 bytes) = 50 bytes, no padding
    rec_dtype = np.dtype([("data", "<f4", (12,)), ("attr", "<u2")])
    assert rec_dtype.itemsize == 50, f"unexpected itemsize {rec_dtype.itemsize}"

    records = np.zeros(n, dtype=rec_dtype)
    records["data"] = flat

    header = b"\x00" * 80
    count = struct.pack("<I", n)
    return header + count + records.tobytes()
