import base64
import re

from PIL import Image


def _set_user(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


class FakePreviewCache:
    def __init__(self):
        self.store = {}

    def get(self, user_id, cache_id):
        return self.store.get((user_id, cache_id))

    def set(self, user_id, cache_id, data):
        self.store[(user_id, cache_id)] = data


def test_preview_cache_hit_skips_rerender(app_module, monkeypatch):
    call_count = {"n": 0}

    def fake_draw(*_args, **_kwargs):
        call_count["n"] += 1
        return Image.new("RGB", (32, 32), "white")

    monkeypatch.setattr(app_module, "draw_poster", fake_draw)
    monkeypatch.setattr(app_module, "PREVIEW_CACHE", FakePreviewCache())

    client = app_module.app.test_client()
    _set_user(client, "user_a")
    payload = {"title": "notice", "date": "2026-02-13", "content": "test content", "config": {}}

    first = client.post("/api/preview", json=payload)
    assert first.status_code == 200
    first_data = first.get_json()
    assert first_data["cache_hit"] is False
    assert re.match(r"^/api/preview-image/[0-9a-f]{64}$", first_data["image_url"])

    second = client.post("/api/preview", json=payload)
    assert second.status_code == 200
    second_data = second.get_json()
    assert second_data["cache_hit"] is True
    assert second_data["image_url"] == first_data["image_url"]
    assert call_count["n"] == 1

    image_resp = client.get(second_data["image_url"])
    assert image_resp.status_code == 200
    assert image_resp.mimetype == "image/png"


def test_preview_returns_inline_image_data(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "draw_poster", lambda *_args, **_kwargs: Image.new("RGB", (24, 24), "white"))
    monkeypatch.setattr(app_module, "PREVIEW_CACHE", FakePreviewCache())

    client = app_module.app.test_client()
    _set_user(client, "user_inline")
    payload = {"title": "notice", "date": "2026-02-13", "content": "test content", "config": {}}

    resp = client.post("/api/preview", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["image_data"].startswith("data:image/png;base64,")
    png_bytes = base64.b64decode(data["image_data"].split(",", 1)[1])
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_preview_invalid_numeric_config_is_sanitized(app_module, monkeypatch):
    def fake_draw(_content, _date, _title, cfg):
        assert isinstance(cfg["bg_blur_radius"], int)
        assert 0 <= cfg["bg_blur_radius"] <= 80
        assert isinstance(cfg["bg_brightness"], float)
        assert 0.2 <= cfg["bg_brightness"] <= 3.0
        assert isinstance(cfg["card_opacity"], float)
        assert 0.05 <= cfg["card_opacity"] <= 1.0
        assert isinstance(cfg["stamp_opacity"], float)
        assert 0.05 <= cfg["stamp_opacity"] <= 1.0
        assert isinstance(cfg["watermark_density"], float)
        assert 0.5 <= cfg["watermark_density"] <= 2.0
        assert isinstance(cfg["jpeg_quality"], int)
        assert 1 <= cfg["jpeg_quality"] <= 100
        return Image.new("RGB", (16, 16), "white")

    monkeypatch.setattr(app_module, "draw_poster", fake_draw)
    monkeypatch.setattr(app_module, "PREVIEW_CACHE", FakePreviewCache())

    client = app_module.app.test_client()
    _set_user(client, "user_sanitize")
    payload = {
        "title": "notice",
        "date": "2026-02-13",
        "content": "test content",
        "config": {
            "bg_blur_radius": "abc",
            "bg_brightness": "NaN",
            "card_opacity": None,
            "stamp_opacity": "-9",
            "watermark_density": "Infinity",
            "jpeg_quality": "0",
            "watermark_enabled": "false",
        },
    }

    resp = client.post("/api/preview", json=payload)
    assert resp.status_code == 200
    assert resp.get_json()["image_data"].startswith("data:image/png;base64,")


def test_preview_image_is_user_scoped(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "draw_poster", lambda *_args, **_kwargs: Image.new("RGB", (16, 16), "white"))
    monkeypatch.setattr(app_module, "PREVIEW_CACHE", FakePreviewCache())

    owner = app_module.app.test_client()
    other = app_module.app.test_client()
    _set_user(owner, "user_a")
    _set_user(other, "user_b")

    payload = {"title": "A", "date": "2026-02-13", "content": "only owner can read", "config": {}}
    preview = owner.post("/api/preview", json=payload)
    assert preview.status_code == 200
    image_url = preview.get_json()["image_url"]

    owner_get = owner.get(image_url)
    assert owner_get.status_code == 200

    other_get = other.get(image_url)
    assert other_get.status_code == 404
