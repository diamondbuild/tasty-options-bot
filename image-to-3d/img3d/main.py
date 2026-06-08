"""FastAPI app — image upload → STL download."""
import io
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .converter import ConvertSettings, convert_image

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Image to 3D Printer", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html, media_type="text/html; charset=utf-8")


@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    mode: str = Form("relief"),
    base_shape: str = Form("rectangle"),
    width_mm: float = Form(100.0),
    resolution: int = Form(150),
    min_thickness: float = Form(0.8),
    max_thickness: float = Form(3.0),
    base_mm: float = Form(1.0),
    relief_height_mm: float = Form(3.5),
    smooth: bool = Form(True),
    remove_bg: bool = Form(True),
) -> StreamingResponse:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    image_data = await file.read()
    if len(image_data) > MAX_SIZE_BYTES:
        raise HTTPException(400, "File too large (max 20 MB)")

    # Clamp to safe ranges
    width_mm = max(20.0, min(300.0, width_mm))
    resolution = max(50, min(400, resolution))
    min_thickness = max(0.4, min(5.0, min_thickness))
    max_thickness = max(min_thickness + 0.4, min(10.0, max_thickness))
    base_mm = max(0.4, min(5.0, base_mm))
    relief_height_mm = max(0.4, min(10.0, relief_height_mm))

    if mode not in ("lithophane", "relief", "emboss"):
        raise HTTPException(400, f"Unknown mode: {mode!r}")
    if base_shape not in ("rectangle", "circle"):
        raise HTTPException(400, f"Unknown base_shape: {base_shape!r}")

    settings = ConvertSettings(
        mode=mode,
        base_shape=base_shape,
        width_mm=width_mm,
        resolution=resolution,
        remove_bg=remove_bg,
        min_thickness_mm=min_thickness,
        max_thickness_mm=max_thickness,
        base_mm=base_mm,
        relief_height_mm=relief_height_mm,
        smooth=smooth,
    )

    stl_data = convert_image(image_data, settings)

    # Safe filename: strip extension, keep alphanumeric+dash+underscore
    stem = Path(file.filename or "model").stem
    safe_stem = re.sub(r"[^\w\-]", "_", stem)[:40]
    filename = f"{safe_stem}_{mode}.stl"

    return StreamingResponse(
        io.BytesIO(stl_data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
