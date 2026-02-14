import json
from pathlib import Path

import poster_engine


def test_app_atomic_write_users_and_output_index(app_module):
    app_module._save_users({"user_a": "hash-a"})
    app_module._save_output_index({"web_data/outputs/user_a/a.png": {"user_id": "user_a"}})

    users = json.loads(Path(app_module.USERS_PATH).read_text(encoding="utf-8"))
    idx = json.loads(Path(app_module.OUTPUT_META_PATH).read_text(encoding="utf-8"))

    assert users["user_a"] == "hash-a"
    assert idx["web_data/outputs/user_a/a.png"]["user_id"] == "user_a"


def test_app_atomic_write_cleans_temp_file_on_replace_error(app_module, monkeypatch):
    users_path = Path(app_module.USERS_PATH)
    users_path.parent.mkdir(parents=True, exist_ok=True)

    def boom(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(app_module.os, "replace", boom)

    try:
        app_module._save_users({"user_a": "hash-a"})
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")

    tmp_files = list(users_path.parent.glob(".tmp_*.json"))
    assert tmp_files == []


def test_poster_engine_save_config_atomic_and_readable(tmp_path):
    cfg_path = tmp_path / "config.json"
    poster_engine.save_config(str(cfg_path), {"shop_name": "A店"})

    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["shop_name"] == "A店"
