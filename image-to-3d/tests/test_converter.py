import io, struct
import pytest
from PIL import Image
from img3d.converter import ConvertSettings, convert_image


def make_png(w=40, h=30):
    img = Image.new("L", (w, h))
    pixels = [int(255 * (i / (w * h))) for i in range(w * h)]
    img.putdata(pixels)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def parse_stl(data):
    assert len(data) >= 84
    n = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 80 + 4 + n * 50
    return n


@pytest.mark.parametrize("mode", ["lithophane", "relief", "emboss"])
def test_conversion_modes(mode):
    s = ConvertSettings(mode=mode, resolution=60, width_mm=60.0, smooth=False)
    stl = convert_image(make_png(), s)
    n = parse_stl(stl)
    assert n > 0


def test_lithophane_thickness_range():
    """Min/max thickness settings must produce different STL content."""
    data = make_png()
    thin = convert_image(data, ConvertSettings(mode="lithophane", min_thickness_mm=0.4, max_thickness_mm=1.0, resolution=40))
    thick = convert_image(data, ConvertSettings(mode="lithophane", min_thickness_mm=1.0, max_thickness_mm=5.0, resolution=40))
    assert thin != thick


def test_resolution_affects_size():
    data = make_png()
    lo = convert_image(data, ConvertSettings(resolution=50, smooth=False))
    hi = convert_image(data, ConvertSettings(resolution=100, smooth=False))
    assert len(hi) > len(lo)
