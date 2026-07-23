import io

from PIL import Image

from app import _optimize_uploaded_image, app


def test_versioned_static_assets_are_cached_immutably():
    client = app.test_client()
    response = client.get("/static/app.js?v=20260723v3")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_unversioned_static_assets_use_short_cache():
    client = app.test_client()
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=3600"


def test_index_does_not_parser_block_on_sortable():
    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert "Sortable.min.js" not in html
    assert '<script defer src="/static/app.js?v=20260723v3"></script>' in html


def test_large_background_is_resized_and_converted_to_webp(tmp_path):
    source = tmp_path / "background.png"
    Image.new("RGB", (3200, 1800), "#446688").save(source, "PNG")

    optimized = _optimize_uploaded_image(str(source), "bg_image_path")

    assert optimized.endswith(".webp")
    assert not source.exists()
    with Image.open(optimized) as image:
        assert max(image.size) == 2560
        assert image.format == "WEBP"


def test_transparent_logo_keeps_alpha_when_optimized(tmp_path):
    source = tmp_path / "logo.png"
    image = Image.new("RGBA", (1600, 1600), (255, 0, 0, 0))
    image.paste((255, 0, 0, 255), (200, 200, 1400, 1400))
    image.save(source, "PNG")

    optimized = _optimize_uploaded_image(str(source), "logo_image_path")

    with Image.open(optimized) as result:
        assert max(result.size) == 1200
        assert result.mode == "RGBA"
        assert result.getchannel("A").getextrema() == (0, 255)


def test_upload_rejects_unknown_asset_type():
    client = app.test_client()
    payload = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(payload, "PNG")
    payload.seek(0)

    response = client.post(
        "/api/upload",
        data={"asset_type": "unknown", "file": (payload, "test.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "图片用途无效"
