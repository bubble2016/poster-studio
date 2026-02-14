import importlib
import sys

import pytest


def test_production_requires_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTER_DATA_DIR", str(tmp_path / "web_data"))
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("POSTER_APP_SECRET", raising=False)

    if "app" in sys.modules:
        del sys.modules["app"]

    with pytest.raises(RuntimeError, match="POSTER_APP_SECRET"):
        importlib.import_module("app")

    if "app" in sys.modules:
        del sys.modules["app"]


def test_login_rate_limit_on_wrong_password(app_module):
    app_module.LOGIN_MAX_ATTEMPTS = 2
    app_module.LOGIN_LOCK_SECONDS = 120
    app_module.LOGIN_WINDOW_SECONDS = 600
    app_module._LOGIN_FAIL_BUCKETS.clear()

    client = app_module.app.test_client()

    create_resp = client.post("/api/login", json={"user_id": "user_a", "password": "pass-1234"})
    assert create_resp.status_code == 200

    wrong1 = client.post("/api/login", json={"user_id": "user_a", "password": "bad-1"})
    assert wrong1.status_code == 401

    wrong2 = client.post("/api/login", json={"user_id": "user_a", "password": "bad-2"})
    assert wrong2.status_code == 401

    locked = client.post("/api/login", json={"user_id": "user_a", "password": "bad-3"})
    assert locked.status_code == 429
    payload = locked.get_json()
    assert payload and "秒后重试" in payload.get("error", "")


def test_login_success_clears_failure_counter(app_module):
    app_module.LOGIN_MAX_ATTEMPTS = 2
    app_module.LOGIN_LOCK_SECONDS = 120
    app_module.LOGIN_WINDOW_SECONDS = 600
    app_module._LOGIN_FAIL_BUCKETS.clear()

    client = app_module.app.test_client()

    create_resp = client.post("/api/login", json={"user_id": "user_a", "password": "pass-1234"})
    assert create_resp.status_code == 200

    wrong = client.post("/api/login", json={"user_id": "user_a", "password": "bad-1"})
    assert wrong.status_code == 401

    ok = client.post("/api/login", json={"user_id": "user_a", "password": "pass-1234"})
    assert ok.status_code == 200

    wrong_after_reset = client.post("/api/login", json={"user_id": "user_a", "password": "bad-2"})
    assert wrong_after_reset.status_code == 401
