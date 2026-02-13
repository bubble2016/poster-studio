from pathlib import Path
from urllib.parse import quote

from PIL import Image


def _set_user(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _fake_poster(*_args, **_kwargs):
    return Image.new("RGB", (1080, 1920), "white")


def test_download_only_owner_can_access_generated_file(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "draw_poster", _fake_poster)

    owner_client = app_module.app.test_client()
    other_client = app_module.app.test_client()
    _set_user(owner_client, "user_a")
    _set_user(other_client, "user_b")

    resp = owner_client.post(
        "/api/generate",
        json={
            "title": "notice",
            "date": "2026-02-13",
            "content": "【工厂黄板】：1000 元/吨",
            "config": {},
            "export_format": "PNG",
        },
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload and payload.get("file")
    relpath = payload["file"]
    assert "/outputs/user_a/" in relpath.replace("\\", "/")

    owner_download = owner_client.get(f"/download/{quote(relpath, safe='/')}")
    assert owner_download.status_code == 200

    other_download = other_client.get(f"/download/{quote(relpath, safe='/')}")
    assert other_download.status_code == 403


def test_download_rejects_non_output_files(app_module):
    client = app_module.app.test_client()
    _set_user(client, "user_a")

    fake_upload = Path(app_module.UPLOAD_DIR) / "x.png"
    fake_upload.write_bytes(b"not-an-image")
    relpath = app_module._public_path(str(fake_upload))

    resp = client.get(f"/download/{quote(relpath, safe='/')}")
    assert resp.status_code == 403


def test_validate_and_batch_adjust_api_smoke(app_module):
    client = app_module.app.test_client()
    _set_user(client, "user_a")

    validate_resp = client.post("/api/validate", json={"content": "【工厂黄板】：0 元/吨"})
    assert validate_resp.status_code == 200
    validate_payload = validate_resp.get_json()
    assert validate_payload["valid"] is False
    assert any("0 元" in w for w in validate_payload["warnings"])

    batch_resp = client.post("/api/batch-adjust", json={"content": "【工厂黄板】：1000 元/吨", "amount": 50})
    assert batch_resp.status_code == 200
    batch_payload = batch_resp.get_json()
    assert "1050" in batch_payload["content"]

