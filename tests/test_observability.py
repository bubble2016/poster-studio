def test_request_id_header_is_attached(app_module):
    client = app_module.app.test_client()
    resp = client.get("/api/me", headers={"X-Request-Id": "rid-123456"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "rid-123456"


def test_request_id_header_is_generated_when_missing(app_module):
    client = app_module.app.test_client()
    resp = client.get("/api/me")
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-Id")
    assert isinstance(req_id, str)
    assert len(req_id) >= 8


def test_preview_response_contains_request_id(app_module, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(app_module, "draw_poster", lambda *_args, **_kwargs: Image.new("RGB", (8, 8), "white"))
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "user_obs"
    payload = {"title": "obs", "date": "2026-02-14", "content": "x", "config": {}}
    resp = client.post("/api/preview", json=payload, headers={"X-Request-Id": "rid-preview-1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("request_id") == "rid-preview-1"
    assert resp.headers.get("X-Request-Id") == "rid-preview-1"
