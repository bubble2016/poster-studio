import io
from pathlib import Path

from PIL import Image


def _png_bytes(size=(32, 32), color="white"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_accepts_valid_image(app_module):
    client = app_module.app.test_client()
    data = {"file": (io.BytesIO(_png_bytes()), "ok.png")}
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload and payload.get("path")


def test_upload_rejects_fake_image_and_cleans_file(app_module):
    client = app_module.app.test_client()
    data = {"file": (io.BytesIO(b"not-a-real-png"), "fake.png")}
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload and "无效" in payload.get("error", "")
    files = list(Path(app_module.UPLOAD_DIR).glob("*"))
    assert files == []


def test_upload_rejects_too_many_pixels(app_module):
    app_module.MAX_UPLOAD_IMAGE_PIXELS = 1000
    client = app_module.app.test_client()
    data = {"file": (io.BytesIO(_png_bytes(size=(100, 100))), "big.png")}
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload and "像素过大" in payload.get("error", "")
    files = list(Path(app_module.UPLOAD_DIR).glob("*"))
    assert files == []
