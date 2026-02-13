import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app_module(monkeypatch, tmp_path):
    data_dir = tmp_path / "web_data"
    monkeypatch.setenv("POSTER_DATA_DIR", str(data_dir))
    monkeypatch.setenv("POSTER_APP_SECRET", "test-secret")

    if "app" in sys.modules:
        del sys.modules["app"]
    module = importlib.import_module("app")
    module.app.config["TESTING"] = True
    return module

