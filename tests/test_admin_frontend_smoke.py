from pathlib import Path


def test_admin_page_contains_required_elements(app_module):
    client = app_module.app.test_client()
    resp = client.get("/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "管理后台" in html
    assert 'id="tokenInput"' in html
    assert 'id="loadUsersBtn"' in html
    assert 'id="usersBody"' in html
    assert "/static/admin.js" in html


def test_admin_assets_are_utf8_and_have_core_handlers():
    html_text = Path("templates/admin.html").read_text(encoding="utf-8")
    js_text = Path("static/admin.js").read_text(encoding="utf-8")

    assert "管理后台" in html_text
    assert "刷新用户列表" in html_text
    assert "function adminFetch" in js_text
    assert "function refreshUsers" in js_text
    assert "请先输入管理员令牌" in js_text
