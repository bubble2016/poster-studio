from app import _sanitize_runtime_cfg, app
from poster_engine import DEFAULT_CONFIG, normalize_font_preset


def test_normalize_font_preset_accepts_known_values():
    assert normalize_font_preset("source_han_sans") == "source_han_sans"
    assert normalize_font_preset("lxgw_wenkai") == "lxgw_wenkai"


def test_legacy_font_preset_values_migrate_to_current_defaults():
    assert normalize_font_preset("default") == "source_han_sans"


def test_sanitize_runtime_cfg_falls_back_to_default_font_preset():
    cfg = _sanitize_runtime_cfg({"font_preset": "bad"})
    assert cfg["font_preset"] == DEFAULT_CONFIG["font_preset"]


def test_new_font_files_are_served():
    client = app.test_client()
    for filename in ["LXGWWenKai-Regular.ttf", "LXGWWenKai-Medium.ttf"]:
        response = client.get(f"/font/{filename}")
        assert response.status_code == 200
