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
