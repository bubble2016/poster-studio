import io
import json
import zipfile
from pathlib import Path

from werkzeug.security import check_password_hash


def _auth_headers(token):
    return {"X-Admin-Token": token}


def test_admin_users_requires_token(app_module):
    client = app_module.app.test_client()
    page = client.get("/admin")
    assert page.status_code == 200
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


def test_admin_users_export_and_backup(app_module, monkeypatch):
    token = "admin-secret"
    monkeypatch.setenv("POSTER_ADMIN_TOKEN", token)

    app_module._save_users({"user_a": "hash-a", "user_b": "hash-b"})
    app_module.save_config(app_module._get_user_config_path("user_a"), {"shop_name": "A"})
    app_module.save_config(app_module._get_user_config_path("user_b"), {"shop_name": "B"})

    out_file = Path(app_module.OUTPUT_DIR) / "user_a" / "demo.png"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(b"fake-image")
    app_module._record_output_owner(app_module._public_path(str(out_file)), "user_a")

    client = app_module.app.test_client()

    users_resp = client.get("/api/admin/users", headers=_auth_headers(token))
    assert users_resp.status_code == 200
    users_payload = users_resp.get_json()
    assert users_payload["total"] >= 2
    ids = {row["user_id"] for row in users_payload["users"]}
    assert "user_a" in ids and "user_b" in ids

    export_resp = client.get("/api/admin/export", headers=_auth_headers(token))
    assert export_resp.status_code == 200
    export_payload = export_resp.get_json()
    assert "users" in export_payload
    assert "user_configs" in export_payload
    assert "output_index" in export_payload

    backup_resp = client.get("/api/admin/backup", headers=_auth_headers(token))
    assert backup_resp.status_code == 200
    assert backup_resp.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(backup_resp.data), "r") as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "users.json" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "generated_at" in manifest


def test_admin_update_password_and_config(app_module, monkeypatch):
    token = "admin-secret"
    monkeypatch.setenv("POSTER_ADMIN_TOKEN", token)
    app_module._save_users({"user_a": "old-hash"})

    client = app_module.app.test_client()
    pwd_resp = client.post(
        "/api/admin/users/user_a/password",
        headers=_auth_headers(token),
        json={"password": "new-pass-123"},
    )
    assert pwd_resp.status_code == 200
    users = app_module._load_users()
    assert check_password_hash(users["user_a"], "new-pass-123")

    cfg_resp = client.patch(
        "/api/admin/users/user_a/config",
        headers=_auth_headers(token),
        json={"mode": "merge", "config": {"shop_name": "new name"}},
    )
    assert cfg_resp.status_code == 200
    cfg = app_module.load_config(app_module._get_user_config_path("user_a"))
    assert cfg.get("shop_name") == "new name"


def test_admin_delete_user_and_cleanup_guests(app_module, monkeypatch):
    token = "admin-secret"
    monkeypatch.setenv("POSTER_ADMIN_TOKEN", token)

    app_module._save_users({"user_a": "hash-a"})
    app_module.save_config(app_module._get_user_config_path("user_a"), {"shop_name": "A"})
    app_module.save_config(app_module._get_user_config_path("guest_old"), {"shop_name": "G"})

    out_file = Path(app_module.OUTPUT_DIR) / "user_a" / "demo.png"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(b"fake-image")
    app_module._record_output_owner(app_module._public_path(str(out_file)), "user_a")

    client = app_module.app.test_client()

    del_resp = client.delete("/api/admin/users/user_a?include_outputs=1", headers=_auth_headers(token))
    assert del_resp.status_code == 200
    assert "user_a" not in app_module._load_users()
    assert not Path(app_module._get_user_config_path("user_a")).exists()

    cleanup_resp = client.post(
        "/api/admin/guests/cleanup",
        headers=_auth_headers(token),
        json={"days": 0, "include_outputs": False},
    )
    assert cleanup_resp.status_code == 200
    payload = cleanup_resp.get_json()
    assert payload["removed_count"] >= 1
    assert "guest_old" in payload["removed_user_ids"]


def test_admin_cleanup_guests_accepts_string_false_for_include_outputs(app_module, monkeypatch):
    token = "admin-secret"
    monkeypatch.setenv("POSTER_ADMIN_TOKEN", token)

    app_module.save_config(app_module._get_user_config_path("guest_old"), {"shop_name": "G"})
    out_file = Path(app_module.OUTPUT_DIR) / "guest_old" / "demo.png"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(b"fake-image")
    app_module._record_output_owner(app_module._public_path(str(out_file)), "guest_old")

    client = app_module.app.test_client()
    cleanup_resp = client.post(
        "/api/admin/guests/cleanup",
        headers=_auth_headers(token),
        json={"days": 0, "include_outputs": "false"},
    )
    assert cleanup_resp.status_code == 200
    payload = cleanup_resp.get_json()
    assert "guest_old" in payload["removed_user_ids"]
    assert out_file.exists()
