import base64
import datetime
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import shutil
import string
import tempfile
import threading
import time
import uuid
import zipfile

from flask import Flask, Response, g, has_request_context, jsonify, render_template, request, send_file, session
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from poster_engine import (
    DEFAULT_CONFIG,
    SYSTEM_TEMPLATE_META,
    SYSTEM_TEMPLATES,
    auto_format_content,
    batch_adjust_content,
    draw_poster,
    format_date_input,
    load_config,
    save_config,
    validate_content,
    PresetGenerator,
)

try:
    from redis import Redis
    from redis.exceptions import RedisError
except Exception:
    Redis = None

    class RedisError(Exception):
        pass


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("POSTER_DATA_DIR", os.path.join(BASE_DIR, "web_data"))
if not os.path.isabs(DATA_DIR):
    DATA_DIR = os.path.join(BASE_DIR, DATA_DIR)
DATA_DIR = os.path.abspath(DATA_DIR)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")
OUTPUT_META_PATH = os.path.join(DATA_DIR, "output_index.json")
USER_CONFIG_DIR = os.path.join(DATA_DIR, "user_configs")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
CONFIG_PATH = os.path.join(DATA_DIR, "web_config.json")
MAX_SAVED_OUTPUTS_PER_USER = max(1, int(os.environ.get("POSTER_MAX_SAVED_OUTPUTS_PER_USER", "3")))
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_CACHE_TTL_SECONDS = max(30, int(os.environ.get("POSTER_PREVIEW_CACHE_TTL", "300")))
PREVIEW_CACHE_PREFIX = os.environ.get("POSTER_PREVIEW_CACHE_PREFIX", "poster:preview")
PREVIEW_CACHE_MAX_LOCAL_ITEMS = max(16, int(os.environ.get("POSTER_PREVIEW_CACHE_LOCAL_MAX", "128")))
PREVIEW_ID_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
ADMIN_TOKEN = (os.environ.get("POSTER_ADMIN_TOKEN") or "").strip()
ENV_NAME = str(os.environ.get("POSTER_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower()
IS_PRODUCTION = ENV_NAME in {"prod", "production"}
DEV_AUTO_RELOAD = str(
    os.environ.get("POSTER_DEV_RELOAD", "0")
).strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SECURE = str(
    os.environ.get("POSTER_SESSION_COOKIE_SECURE", "1" if IS_PRODUCTION else "0")
).strip().lower() in {"1", "true", "yes", "on"}
LOGIN_WINDOW_SECONDS = max(60, int(os.environ.get("POSTER_LOGIN_WINDOW_SECONDS", "600")))
LOGIN_MAX_ATTEMPTS = max(3, int(os.environ.get("POSTER_LOGIN_MAX_ATTEMPTS", "8")))
LOGIN_LOCK_SECONDS = max(60, int(os.environ.get("POSTER_LOGIN_LOCK_SECONDS", "600")))
MAX_UPLOAD_IMAGE_PIXELS = max(1_000_000, int(os.environ.get("POSTER_UPLOAD_MAX_PIXELS", "40000000")))

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(USER_CONFIG_DIR, exist_ok=True)
_OUTPUT_META_LOCK = threading.Lock()
_LOGIN_FAIL_LOCK = threading.Lock()
_LOGIN_FAIL_BUCKETS = {}

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.secret_key = (os.environ.get("POSTER_APP_SECRET") or "").strip()
if IS_PRODUCTION and (not app.secret_key or app.secret_key == "replace-this-in-production"):
    raise RuntimeError("生产环境必须设置 POSTER_APP_SECRET，且不能使用默认值")
if not app.secret_key:
    app.secret_key = "replace-this-in-production"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)
LOGGER = logging.getLogger("poster_app")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
if Redis is None:
    LOGGER.warning("redis_not_available | %s", json.dumps({"cache": "local_only"}, ensure_ascii=False))


def _log_event(level, event, **context):
    payload = {}
    if has_request_context():
        payload["request_id"] = getattr(g, "request_id", "")
        payload["path"] = request.path
        payload["method"] = request.method
    payload.update(context)
    msg = f"{event} | {json.dumps(payload, ensure_ascii=False, default=str)}"
    LOGGER.log(level, msg)


def _log_exception(event, **context):
    payload = {}
    if has_request_context():
        payload["request_id"] = getattr(g, "request_id", "")
        payload["path"] = request.path
        payload["method"] = request.method
    payload.update(context)
    LOGGER.exception("%s | %s", event, json.dumps(payload, ensure_ascii=False, default=str))


class PreviewCache:
    def __init__(self):
        self._redis = None
        self._local = {}
        self._lock = threading.Lock()
        redis_url = (os.environ.get("POSTER_REDIS_URL") or "").strip()
        if not redis_url or Redis is None:
            return
        try:
            cli = Redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            cli.ping()
            self._redis = cli
        except Exception:
            self._redis = None
            _log_exception("preview_cache.redis_init_failed", redis_url=redis_url)

    def _key(self, user_id, cache_id):
        return f"{PREVIEW_CACHE_PREFIX}:{user_id}:{cache_id}"

    def get(self, user_id, cache_id):
        if self._redis is not None:
            try:
                data = self._redis.get(self._key(user_id, cache_id))
                if data:
                    return data
            except RedisError:
                _log_event(logging.WARNING, "preview_cache.redis_get_failed", user_id=user_id, cache_id=cache_id)
        local_key = (user_id, cache_id)
        now = time.time()
        with self._lock:
            entry = self._local.get(local_key)
            if not entry:
                return None
            expires_at, data = entry
            if expires_at <= now:
                self._local.pop(local_key, None)
                return None
            return data

    def set(self, user_id, cache_id, data):
        if self._redis is not None:
            try:
                self._redis.setex(self._key(user_id, cache_id), PREVIEW_CACHE_TTL_SECONDS, data)
            except RedisError:
                _log_event(logging.WARNING, "preview_cache.redis_set_failed", user_id=user_id, cache_id=cache_id)
        local_key = (user_id, cache_id)
        expires_at = time.time() + PREVIEW_CACHE_TTL_SECONDS
        with self._lock:
            self._local[local_key] = (expires_at, data)
            if len(self._local) <= PREVIEW_CACHE_MAX_LOCAL_ITEMS:
                return
            stale_keys = [k for k, v in self._local.items() if v[0] <= time.time()]
            for k in stale_keys:
                self._local.pop(k, None)
            while len(self._local) > PREVIEW_CACHE_MAX_LOCAL_ITEMS:
                self._local.pop(next(iter(self._local)))


PREVIEW_CACHE = PreviewCache()


@app.before_request
def _set_request_id():
    raw = (request.headers.get("X-Request-Id") or "").strip()
    g.request_id = raw[:64] if raw else uuid.uuid4().hex[:12]


@app.after_request
def _append_request_id(resp):
    req_id = getattr(g, "request_id", "")
    if req_id:
        resp.headers["X-Request-Id"] = req_id
    return resp


def _sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name) or "公告"


def _public_path(path):
    return os.path.relpath(path, BASE_DIR).replace("\\", "/")


def _resolve_asset_path(path):
    if not path:
        return ""
    path = str(path).strip()
    if not path:
        return ""
    ext = os.path.splitext(path)[1].lower()
    if ext and ext not in ALLOWED_IMAGE_EXTENSIONS:
        return ""
    target = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
    abs_path = os.path.abspath(target)
    allowed_roots = [os.path.abspath(UPLOAD_DIR), os.path.abspath(os.path.join(BASE_DIR, "presets"))]
    in_allowed = any(abs_path == root or abs_path.startswith(root + os.sep) for root in allowed_roots)
    return abs_path if in_allowed else ""


def _normalize_cfg_paths(cfg):
    out = dict(cfg)
    for key in ["bg_image_path", "logo_image_path", "stamp_image_path", "qrcode_image_path"]:
        out[key] = _resolve_asset_path(out.get(key, ""))
    return out



def _coerce_float(value, default, min_value=None, max_value=None):
    default_val = float(default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default_val
    if not math.isfinite(out):
        out = default_val
    if min_value is not None:
        out = max(float(min_value), out)
    if max_value is not None:
        out = min(float(max_value), out)
    return out


def _coerce_int(value, default, min_value=None, max_value=None):
    default_val = int(default)
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        out = default_val
    if min_value is not None:
        out = max(int(min_value), out)
    if max_value is not None:
        out = min(int(max_value), out)
    return out


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return bool(default)
    return bool(value)


def _coerce_request_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return bool(default)
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    return bool(value)


def _sanitize_runtime_cfg(raw_cfg):
    cfg = {**DEFAULT_CONFIG, **(raw_cfg or {})}
    cfg["bg_blur_radius"] = _coerce_int(cfg.get("bg_blur_radius"), DEFAULT_CONFIG["bg_blur_radius"], 0, 80)
    cfg["bg_brightness"] = _coerce_float(cfg.get("bg_brightness"), DEFAULT_CONFIG["bg_brightness"], 0.2, 3.0)
    cfg["card_opacity"] = _coerce_float(cfg.get("card_opacity"), DEFAULT_CONFIG["card_opacity"], 0.05, 1.0)
    cfg["stamp_opacity"] = _coerce_float(cfg.get("stamp_opacity"), DEFAULT_CONFIG["stamp_opacity"], 0.05, 1.0)
    cfg["watermark_opacity"] = _coerce_float(cfg.get("watermark_opacity"), DEFAULT_CONFIG["watermark_opacity"], 0.0, 0.8)
    cfg["watermark_density"] = _coerce_float(cfg.get("watermark_density"), DEFAULT_CONFIG["watermark_density"], 0.5, 2.0)
    cfg["jpeg_quality"] = _coerce_int(cfg.get("jpeg_quality"), DEFAULT_CONFIG["jpeg_quality"], 1, 100)
    cfg["watermark_enabled"] = _coerce_bool(cfg.get("watermark_enabled"), DEFAULT_CONFIG["watermark_enabled"])
    cfg["holiday_text_style"] = "festive"
    return cfg


def _normalize_hex_color(value, fallback="#B22222"):
    text = str(value or "").strip()
    if HEX_COLOR_RE.match(text):
        return text.upper()
    return fallback


def _mix_with_white(hex_color, ratio):
    color = _normalize_hex_color(hex_color)
    t = max(0.0, min(1.0, float(ratio)))
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    nr = round(r + (255 - r) * t)
    ng = round(g + (255 - g) * t)
    nb = round(b + (255 - b) * t)
    return f"#{nr:02X}{ng:02X}{nb:02X}"


def _sanitize_user_id(user_id):
    user_id = (user_id or "").strip()
    if not user_id:
        return ""
    user_id = re.sub(r"[^0-9A-Za-z_-]", "", user_id)
    return user_id[:64]


def _is_guest_user(user_id):
    return bool(user_id) and user_id.startswith("guest_")


def _display_user_id(user_id):
    if _is_guest_user(user_id):
        short = user_id[len("guest_"):]
        return short[:5] if short else user_id
    return user_id


def _set_session_user_id(user_id):
    session.permanent = True
    session["user_id"] = user_id


def _get_user_id():
    uid = _sanitize_user_id(session.get("user_id", ""))
    if uid and uid != session.get("user_id"):
        _set_session_user_id(uid)
    return uid


def _ensure_user_id():
    uid = _get_user_id()
    if uid:
        return uid
    short = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    uid = f"guest_{short}"
    _set_session_user_id(uid)
    return uid


def _get_user_config_path(user_id):
    return os.path.join(USER_CONFIG_DIR, f"{user_id}.json")


def _load_users():
    if not os.path.isfile(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        _log_exception("users.load_failed", path=USERS_PATH)
        return {}


def _save_users(users):
    _atomic_write_json(USERS_PATH, users)


def _load_output_index():
    if not os.path.isfile(OUTPUT_META_PATH):
        return {}
    try:
        with open(OUTPUT_META_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        _log_exception("output_index.load_failed", path=OUTPUT_META_PATH)
        return {}


def _save_output_index(data):
    _atomic_write_json(OUTPUT_META_PATH, data)


def _atomic_write_json(path, data):
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise


def _validate_uploaded_image(path):
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img2:
            width, height = img2.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return False, "图片文件无效或已损坏"
    except Exception:
        _log_exception("upload.image_verify_failed", path=path)
        return False, "图片校验失败，请重试"
    if width <= 0 or height <= 0:
        return False, "图片尺寸无效"
    if width * height > MAX_UPLOAD_IMAGE_PIXELS:
        return False, f"图片像素过大，最大支持 {MAX_UPLOAD_IMAGE_PIXELS} 像素"
    return True, ""


def _record_output_owner(relpath, user_id):
    rel = str(relpath or "").replace("\\", "/").strip()
    uid = _sanitize_user_id(user_id)
    if not rel or not uid:
        return
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
        idx[rel] = {"user_id": uid, "created_at": datetime.datetime.now().isoformat(timespec="seconds")}
        _save_output_index(idx)


def _parse_iso_timestamp(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _prune_old_outputs_for_user(user_id, keep=MAX_SAVED_OUTPUTS_PER_USER):
    uid = _sanitize_user_id(user_id)
    keep_count = max(1, int(keep or 1))
    if not uid:
        return {"removed_outputs": 0, "removed_index_entries": 0}

    removed_relpaths = []
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
        owned = []
        for rel, meta in idx.items():
            owner = _sanitize_user_id((meta or {}).get("user_id", ""))
            if owner != uid:
                continue
            created_at = _parse_iso_timestamp((meta or {}).get("created_at", ""))
            owned.append((created_at, str(rel), meta))
        if len(owned) <= keep_count:
            return {"removed_outputs": 0, "removed_index_entries": 0}
        owned.sort(key=lambda item: (item[0], item[1]), reverse=True)
        stale_relpaths = {rel for _, rel, _ in owned[keep_count:]}
        next_idx = {rel: meta for rel, meta in idx.items() if rel not in stale_relpaths}
        removed_relpaths = sorted(stale_relpaths)
        _save_output_index(next_idx)

    removed_outputs = 0
    for rel in removed_relpaths:
        abs_path = _safe_join_data_path(rel)
        if not abs_path or not os.path.isfile(abs_path):
            continue
        try:
            os.remove(abs_path)
            removed_outputs += 1
        except Exception:
            _log_exception("output_prune.remove_failed", user_id=uid, path=abs_path)

    user_output_dir = os.path.join(OUTPUT_DIR, uid)
    if os.path.isdir(user_output_dir):
        try:
            if not any(os.scandir(user_output_dir)):
                os.rmdir(user_output_dir)
        except Exception:
            _log_exception("output_prune.cleanup_dir_failed", user_id=uid, path=user_output_dir)

    return {"removed_outputs": removed_outputs, "removed_index_entries": len(removed_relpaths)}


def _load_user_config(user_id):
    user_path = _get_user_config_path(user_id)
    user_config_exists = os.path.isfile(user_path)
    if user_config_exists:
        cfg = load_config(user_path)
    else:
        cfg = load_config(CONFIG_PATH)
    changed = False
    default_logos = list(PresetGenerator.get_default_logos(BASE_DIR).values())
    if not user_config_exists:
        presets = list(PresetGenerator.get_presets(BASE_DIR).values())
        if presets:
            picked = random.choice(presets)
            cfg["bg_mode"] = "preset"
            cfg["bg_image_path"] = _public_path(picked)
            changed = True
        if default_logos:
            picked_logo = random.choice(default_logos)
            cfg["logo_image_path"] = _public_path(picked_logo)
            changed = True
    legacy_default_names = {"default_logo_kraft_stamp.png"}
    current_logo = str(cfg.get("logo_image_path") or "").strip()
    current_logo_name = os.path.basename(current_logo.replace("\\", "/"))
    current_logo_abs = _resolve_asset_path(current_logo) if current_logo else ""
    should_replace_default_logo = (not current_logo) or (current_logo_name in legacy_default_names) or (
        bool(current_logo) and (not current_logo_abs)
    )
    if should_replace_default_logo and default_logos:
        picked_logo = random.choice(default_logos)
        next_logo_path = _public_path(picked_logo)
        if cfg.get("logo_image_path") != next_logo_path:
            cfg["logo_image_path"] = next_logo_path
            changed = True
    if _is_guest_user(user_id):
        if cfg.get("stamp_image_path"):
            cfg["stamp_image_path"] = ""
            changed = True
        if cfg.get("qrcode_image_path"):
            cfg["qrcode_image_path"] = ""
            changed = True
    if (not user_config_exists) or changed:
        save_config(user_path, cfg)
    return cfg


def _safe_join_under(root_dir, relpath):
    root = os.path.abspath(root_dir)
    abs_path = os.path.abspath(os.path.join(root, relpath))
    if abs_path == root or abs_path.startswith(root + os.sep):
        return abs_path
    return ""


def _safe_join_data_path(relpath):
    rel = str(relpath or "").replace("\\", "/").lstrip("/")
    if not rel:
        return ""
    candidates = []
    data_dir_name = os.path.basename(DATA_DIR).replace("\\", "/").strip("/")
    if data_dir_name and rel == data_dir_name:
        candidates.append("")
    elif data_dir_name and rel.startswith(data_dir_name + "/"):
        # Backward compatibility: allow BASE_DIR-relative payload like web_data/outputs/...
        candidates.append(rel[len(data_dir_name) + 1 :])
    candidates.append(rel)
    for cand in candidates:
        abs_path = _safe_join_under(DATA_DIR, cand)
        if abs_path:
            return abs_path
    return ""


def _is_owned_output(relpath, abs_path, user_id):
    uid = _sanitize_user_id(user_id)
    if not uid:
        return False

    outputs_root = os.path.abspath(OUTPUT_DIR)
    if not (abs_path == outputs_root or abs_path.startswith(outputs_root + os.sep)):
        return False

    rel = str(relpath or "").replace("\\", "/").strip()
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
    owner = idx.get(rel, {}).get("user_id")
    if owner:
        return owner == uid

    try:
        outputs_rel = os.path.relpath(abs_path, outputs_root).replace("\\", "/")
    except Exception:
        return False
    parts = [p for p in outputs_rel.split("/") if p]
    return bool(parts) and parts[0] == uid


def _safe_join_base_path(relpath):
    return _safe_join_under(BASE_DIR, relpath)


def _json_body():
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("请求体必须是 JSON")
    if not isinstance(data, dict):
        raise ValueError("JSON 格式错误")
    return data


def _normalize_request_date_or_raise(raw_value):
    raw = str(raw_value or "").strip()
    if not raw:
        raise ValueError("日期不能为空，请输入 YYYY-MM-DD")
    if not DATE_YMD_RE.match(raw):
        raise ValueError("日期格式错误，请输入 YYYY-MM-DD")
    y, m, d = [int(part) for part in raw.split("-")]
    try:
        datetime.date(y, m, d)
    except ValueError:
        raise ValueError("日期无效，请输入真实存在的日期")
    return format_date_input(raw)


def _client_ip():
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:128]
    return (request.remote_addr or "unknown")[:128]


def _login_bucket_key(user_id):
    return f"{_sanitize_user_id(user_id)}|{_client_ip()}"


def _is_login_locked(user_id):
    now = time.time()
    key = _login_bucket_key(user_id)
    with _LOGIN_FAIL_LOCK:
        item = _LOGIN_FAIL_BUCKETS.get(key)
        if not item:
            return False, 0
        lock_until = float(item.get("lock_until", 0.0))
        if lock_until > now:
            wait = int(lock_until - now)
            return True, max(1, wait)
        if float(item.get("window_start", 0.0)) + LOGIN_WINDOW_SECONDS <= now:
            _LOGIN_FAIL_BUCKETS.pop(key, None)
    return False, 0


def _register_login_failure(user_id):
    now = time.time()
    key = _login_bucket_key(user_id)
    with _LOGIN_FAIL_LOCK:
        item = _LOGIN_FAIL_BUCKETS.get(key)
        if (not item) or float(item.get("window_start", 0.0)) + LOGIN_WINDOW_SECONDS <= now:
            item = {"window_start": now, "count": 0, "lock_until": 0.0}
        item["count"] = int(item.get("count", 0)) + 1
        if item["count"] >= LOGIN_MAX_ATTEMPTS:
            item["lock_until"] = now + LOGIN_LOCK_SECONDS
            item["window_start"] = now
            item["count"] = 0
        _LOGIN_FAIL_BUCKETS[key] = item


def _clear_login_failures(user_id):
    key = _login_bucket_key(user_id)
    with _LOGIN_FAIL_LOCK:
        _LOGIN_FAIL_BUCKETS.pop(key, None)


def _build_preview_cache_id(content, date_str, title, cfg):
    payload = {
        "content": content or "",
        "title": title or "",
        "date": date_str or "",
        "config": cfg or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_admin_token():
    return (os.environ.get("POSTER_ADMIN_TOKEN") or ADMIN_TOKEN or "").strip()


def _is_admin_request():
    token = _get_admin_token()
    if not token:
        return False, "管理员功能未启用，请先设置 POSTER_ADMIN_TOKEN"
    header_token = (request.headers.get("X-Admin-Token") or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    bearer = ""
    if auth.lower().startswith("bearer "):
        bearer = auth[7:].strip()
    provided = header_token or bearer
    if provided and provided == token:
        return True, ""
    return False, "管理员鉴权失败"


def _admin_guard():
    ok, msg = _is_admin_request()
    if ok:
        return None
    return jsonify({"error": msg}), 403


def _collect_all_user_ids():
    ids = set()
    users = _load_users()
    ids.update(_sanitize_user_id(uid) for uid in users.keys())
    if os.path.isdir(USER_CONFIG_DIR):
        for name in os.listdir(USER_CONFIG_DIR):
            if not name.lower().endswith(".json"):
                continue
            uid = _sanitize_user_id(os.path.splitext(name)[0])
            if uid:
                ids.add(uid)
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
    for meta in idx.values():
        uid = _sanitize_user_id((meta or {}).get("user_id", ""))
        if uid:
            ids.add(uid)
    ids.discard("")
    return sorted(ids)


def _collect_output_counts():
    counts = {}
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
    for meta in idx.values():
        uid = _sanitize_user_id((meta or {}).get("user_id", ""))
        if not uid:
            continue
        counts[uid] = counts.get(uid, 0) + 1
    return counts


def _user_last_active_timestamp(user_id):
    uid = _sanitize_user_id(user_id)
    if not uid:
        return 0.0
    ts = 0.0
    cfg_path = _get_user_config_path(uid)
    if os.path.isfile(cfg_path):
        try:
            ts = max(ts, os.path.getmtime(cfg_path))
        except Exception:
            _log_event(logging.WARNING, "user_last_active.mtime_failed", user_id=uid, path=cfg_path)
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
    for meta in idx.values():
        if _sanitize_user_id((meta or {}).get("user_id", "")) != uid:
            continue
        created = str((meta or {}).get("created_at", "")).strip()
        if not created:
            continue
        try:
            parsed = datetime.datetime.fromisoformat(created)
            ts = max(ts, parsed.timestamp())
        except Exception:
            _log_event(logging.WARNING, "user_last_active.parse_failed", user_id=uid, created_at=created)
    return ts


def _admin_delete_user_data(user_id, include_outputs=True):
    uid = _sanitize_user_id(user_id)
    if not uid:
        raise ValueError("用户ID无效")

    deleted = {
        "user_id": uid,
        "removed_user": False,
        "removed_config": False,
        "removed_outputs": 0,
        "removed_output_dir": False,
        "removed_index_entries": 0,
    }

    users = _load_users()
    if uid in users:
        users.pop(uid, None)
        _save_users(users)
        deleted["removed_user"] = True

    cfg_path = _get_user_config_path(uid)
    if os.path.isfile(cfg_path):
        try:
            os.remove(cfg_path)
            deleted["removed_config"] = True
        except Exception:
            _log_exception("admin_delete.remove_config_failed", user_id=uid, path=cfg_path)

    removed_relpaths = []
    with _OUTPUT_META_LOCK:
        idx = _load_output_index()
        kept = {}
        for rel, meta in idx.items():
            owner = _sanitize_user_id((meta or {}).get("user_id", ""))
            if owner == uid:
                removed_relpaths.append(str(rel))
            else:
                kept[rel] = meta
        if len(kept) != len(idx):
            _save_output_index(kept)
        deleted["removed_index_entries"] = len(idx) - len(kept)

    if include_outputs:
        for rel in removed_relpaths:
            abs_path = _safe_join_data_path(rel)
            if not abs_path or not os.path.isfile(abs_path):
                continue
            try:
                os.remove(abs_path)
                deleted["removed_outputs"] += 1
            except Exception:
                _log_exception("admin_delete.remove_output_failed", user_id=uid, path=abs_path)
        user_output_dir = os.path.join(OUTPUT_DIR, uid)
        if os.path.isdir(user_output_dir):
            try:
                shutil.rmtree(user_output_dir)
                deleted["removed_output_dir"] = True
            except Exception:
                _log_exception("admin_delete.remove_output_dir_failed", user_id=uid, path=user_output_dir)
    return deleted


def _export_all_data_snapshot():
    users = _load_users()
    user_ids = _collect_all_user_ids()
    output_counts = _collect_output_counts()
    user_configs = {}
    for uid in user_ids:
        cfg_path = _get_user_config_path(uid)
        if not os.path.isfile(cfg_path):
            continue
        user_configs[uid] = load_config(cfg_path)
    with _OUTPUT_META_LOCK:
        output_index = _load_output_index()
    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "data_dir": DATA_DIR,
        "users": users,
        "user_configs": user_configs,
        "output_index": output_index,
        "user_ids": user_ids,
        "output_counts": output_counts,
    }


def _collect_backup_files(include_outputs):
    selected = []
    for root, _, files in os.walk(DATA_DIR):
        for name in files:
            abs_path = os.path.join(root, name)
            rel = os.path.relpath(abs_path, DATA_DIR).replace("\\", "/")
            if not include_outputs and rel.startswith("outputs/"):
                continue
            selected.append((abs_path, rel))
    return selected


@app.route("/")
def index():
    uid = _ensure_user_id()
    cfg = _load_user_config(uid)
    primary = _normalize_hex_color(cfg.get("theme_color"), "#B22222")
    primary_rgb = f"{int(primary[1:3], 16)}, {int(primary[3:5], 16)}, {int(primary[5:7], 16)}"
    initial_bg_variant = random.choice(["bg-variant-a", "bg-variant-b", "bg-variant-c", "bg-variant-d", "bg-variant-e"])
    return render_template(
        "index.html",
        initial_theme={
            "primary": primary,
            "primary_rgb": primary_rgb,
            "primary_strong": _mix_with_white(primary, 0.05),
            "primary_soft": _mix_with_white(primary, 0.2),
            "primary_surface": _mix_with_white(primary, 0.88),
        },
        initial_bg_variant=initial_bg_variant,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.get("/favicon.ico")
def favicon():
    icon_path = os.path.join(BASE_DIR, "logo.ico")
    if not os.path.isfile(icon_path):
        return "", 404
    return send_file(icon_path, mimetype="image/x-icon")


@app.errorhandler(413)
def too_large(_):
    mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    return jsonify({"error": f"上传文件过大，最大支持 {mb}MB"}), 413


@app.get("/api/me")
def api_me():
    uid = _ensure_user_id()
    return jsonify(
        {
            "logged_in": not _is_guest_user(uid),
            "is_guest": _is_guest_user(uid),
            "user_id": uid,
            "display_user_id": _display_user_id(uid),
        }
    )


@app.post("/api/login")
def api_login():
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    uid = _sanitize_user_id(data.get("user_id", ""))
    password = (data.get("password") or "").strip()
    if not uid:
        return jsonify({"error": "用户ID不能为空，且仅支持字母/数字/_/-"}), 400
    if len(password) < 4:
        return jsonify({"error": "密码不能为空，且至少 4 位"}), 400

    locked, wait_seconds = _is_login_locked(uid)
    if locked:
        _log_event(logging.WARNING, "auth.login_locked", user_id=uid, wait_seconds=wait_seconds)
        return jsonify({"error": f"登录尝试过于频繁，请 {wait_seconds} 秒后重试"}), 429

    users = _load_users()
    has_user_profile = os.path.isfile(_get_user_config_path(uid))
    user_hash = users.get(uid, "")
    if user_hash:
        if not check_password_hash(user_hash, password):
            _register_login_failure(uid)
            _log_event(logging.WARNING, "auth.login_wrong_password", user_id=uid)
            return jsonify({"error": "密码错误"}), 401
    else:
        users[uid] = generate_password_hash(password)
        _save_users(users)
    _clear_login_failures(uid)

    current_uid = _ensure_user_id()
    merge_from_current = bool(data.get("merge_from_current", True))
    current_path = _get_user_config_path(current_uid)
    target_path = _get_user_config_path(uid)
    if merge_from_current and current_uid != uid and os.path.isfile(current_path) and (not has_user_profile):
        save_config(target_path, load_config(current_path))
    _set_session_user_id(uid)
    return jsonify({"ok": True, "user_id": uid, "display_user_id": _display_user_id(uid), "is_guest": _is_guest_user(uid)})


@app.post("/api/logout")
def api_logout():
    session.pop("user_id", None)
    new_uid = _ensure_user_id()
    return jsonify({"ok": True, "user_id": new_uid, "display_user_id": _display_user_id(new_uid), "is_guest": True})


@app.get("/api/init")
def api_init():
    uid = _ensure_user_id()
    cfg = _load_user_config(uid)
    presets = PresetGenerator.get_presets(BASE_DIR)
    default_logos = PresetGenerator.get_default_logos(BASE_DIR)
    preset_payload = [{"name": name, "path": _public_path(path)} for name, path in presets.items()]
    logo_payload = [{"name": name, "path": _public_path(path)} for name, path in default_logos.items()]
    return jsonify(
        {
            "config": cfg,
            "system_templates": SYSTEM_TEMPLATES,
            "system_template_meta": SYSTEM_TEMPLATE_META,
            "presets": preset_payload,
            "default_logos": logo_payload,
        }
    )


@app.get("/api/admin/users")
def api_admin_users():
    blocked = _admin_guard()
    if blocked:
        return blocked
    users = _load_users()
    output_counts = _collect_output_counts()
    rows = []
    for uid in _collect_all_user_ids():
        cfg_path = _get_user_config_path(uid)
        last_active_ts = _user_last_active_timestamp(uid)
        rows.append(
            {
                "user_id": uid,
                "display_user_id": _display_user_id(uid),
                "is_guest": _is_guest_user(uid),
                "has_password": bool(users.get(uid)),
                "has_config": os.path.isfile(cfg_path),
                "output_count": int(output_counts.get(uid, 0)),
                "last_active": datetime.datetime.fromtimestamp(last_active_ts).isoformat(timespec="seconds")
                if last_active_ts
                else "",
            }
        )
    return jsonify({"users": rows, "total": len(rows)})


@app.get("/api/admin/export")
def api_admin_export():
    blocked = _admin_guard()
    if blocked:
        return blocked
    snapshot = _export_all_data_snapshot()
    download = str(request.args.get("download", "0")).strip().lower() in {"1", "true", "yes"}
    if not download:
        return jsonify(snapshot)
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    buf = io.BytesIO(payload)
    buf.seek(0)
    filename = f"poster_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(buf, mimetype="application/json", as_attachment=True, download_name=filename)


@app.get("/api/admin/backup")
def api_admin_backup():
    blocked = _admin_guard()
    if blocked:
        return blocked
    include_outputs = _coerce_request_bool(request.args.get("include_outputs"), True)
    files = _collect_backup_files(include_outputs)
    snapshot = _export_all_data_snapshot()
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(snapshot, ensure_ascii=False, indent=2))
        for abs_path, rel_path in files:
            if not os.path.isfile(abs_path):
                continue
            zf.write(abs_path, arcname=rel_path)
    zip_buf.seek(0)
    filename = f"poster_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(zip_buf, mimetype="application/zip", as_attachment=True, download_name=filename)


@app.post("/api/admin/users/<user_id>/password")
def api_admin_user_password(user_id):
    blocked = _admin_guard()
    if blocked:
        return blocked
    uid = _sanitize_user_id(user_id)
    if not uid:
        return jsonify({"error": "用户ID无效"}), 400
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    password = str(data.get("password", "")).strip()
    if len(password) < 4:
        return jsonify({"error": "密码至少 4 位"}), 400
    users = _load_users()
    users[uid] = generate_password_hash(password)
    _save_users(users)
    return jsonify({"ok": True, "user_id": uid})


@app.patch("/api/admin/users/<user_id>/config")
def api_admin_user_config(user_id):
    blocked = _admin_guard()
    if blocked:
        return blocked
    uid = _sanitize_user_id(user_id)
    if not uid:
        return jsonify({"error": "用户ID无效"}), 400
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cfg_patch = data.get("config")
    if not isinstance(cfg_patch, dict):
        return jsonify({"error": "config 必须是对象"}), 400
    mode = str(data.get("mode", "merge")).strip().lower()
    if mode not in {"merge", "replace"}:
        return jsonify({"error": "mode 仅支持 merge/replace"}), 400
    target_path = _get_user_config_path(uid)
    if mode == "replace":
        cfg = {**DEFAULT_CONFIG, **cfg_patch}
    else:
        base = load_config(target_path) if os.path.isfile(target_path) else load_config(CONFIG_PATH)
        cfg = {**base, **cfg_patch}
    cfg = _sanitize_runtime_cfg(cfg)
    save_config(target_path, cfg)
    return jsonify({"ok": True, "user_id": uid, "config": cfg})


@app.delete("/api/admin/users/<user_id>")
def api_admin_delete_user(user_id):
    blocked = _admin_guard()
    if blocked:
        return blocked
    include_outputs = _coerce_request_bool(request.args.get("include_outputs"), True)
    try:
        deleted = _admin_delete_user_data(user_id, include_outputs=include_outputs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "deleted": deleted})


@app.post("/api/admin/guests/cleanup")
def api_admin_cleanup_guests():
    blocked = _admin_guard()
    if blocked:
        return blocked
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        days = int(data.get("days", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "days 必须是数字"}), 400
    if days < 0 or days > 3650:
        return jsonify({"error": "days 范围应在 0-3650"}), 400
    include_outputs = _coerce_request_bool(data.get("include_outputs"), False)
    now = time.time()
    cutoff = now - days * 86400
    removed = []
    for uid in _collect_all_user_ids():
        if not _is_guest_user(uid):
            continue
        last_ts = _user_last_active_timestamp(uid)
        if last_ts and last_ts > cutoff:
            continue
        deleted = _admin_delete_user_data(uid, include_outputs=include_outputs)
        removed.append(deleted["user_id"])
    return jsonify({"ok": True, "days": days, "include_outputs": include_outputs, "removed_count": len(removed), "removed_user_ids": removed})


@app.post("/api/upload")
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "仅支持 PNG/JPG/JPEG/WEBP"}), 400
    if f.mimetype and not str(f.mimetype).lower().startswith("image/"):
        return jsonify({"error": "仅支持图片文件"}), 400
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)
    ok, msg = _validate_uploaded_image(path)
    if not ok:
        try:
            os.remove(path)
        except Exception:
            _log_exception("upload.cleanup_failed", path=path)
        return jsonify({"error": msg}), 400
    return jsonify({"path": _public_path(path)})


@app.post("/api/preview")
def api_preview():
    uid = _ensure_user_id()
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    content = data.get("content", "")
    title = data.get("title", "")
    try:
        date_str = _normalize_request_date_or_raise(data.get("date", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        cfg = _sanitize_runtime_cfg({**_load_user_config(uid), **data.get("config", {})})
        cfg = _normalize_cfg_paths(cfg)
        cache_id = _build_preview_cache_id(content, date_str, title, cfg)
        png_bytes = PREVIEW_CACHE.get(uid, cache_id)
        cache_hit = png_bytes is not None
        if png_bytes is None:
            img = draw_poster(content, date_str, title, cfg)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "PNG")
            png_bytes = buf.getvalue()
            PREVIEW_CACHE.set(uid, cache_id, png_bytes)
        image_data = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        valid, warnings = validate_content(content)
        image_url = f"/api/preview-image/{cache_id}"
        _log_event(
            logging.INFO,
            "api_preview.ok",
            user_id=uid,
            cache_id=cache_id,
            cache_hit=cache_hit,
            title=(title or "")[:48],
            date=date_str,
        )
        return jsonify(
            {
                "image": image_url,
                "image_url": image_url,
                "image_data": image_data,
                "cache_hit": cache_hit,
                "request_id": getattr(g, "request_id", ""),
                "date": date_str,
                "valid": valid,
                "warnings": warnings,
            }
        )
    except Exception:
        _log_exception("api_preview.failed", user_id=uid, title=title, date=date_str)
        return jsonify({"error": "预览生成失败，请检查图片素材和参数后重试", "request_id": getattr(g, "request_id", "")}), 500


@app.get("/api/preview-image/<cache_id>")
def api_preview_image(cache_id):
    uid = _ensure_user_id()
    if not PREVIEW_ID_RE.match(str(cache_id or "")):
        _log_event(logging.WARNING, "api_preview_image.invalid_id", user_id=uid, cache_id=str(cache_id or "")[:80])
        return jsonify({"error": "预览标识无效"}), 400
    data = PREVIEW_CACHE.get(uid, cache_id)
    if not data:
        _log_event(logging.WARNING, "api_preview_image.cache_miss", user_id=uid, cache_id=cache_id)
        return jsonify({"error": "预览已过期，请重新生成"}), 404
    resp = Response(data, mimetype="image/png")
    resp.headers["Cache-Control"] = f"private, max-age={PREVIEW_CACHE_TTL_SECONDS}"
    resp.headers["ETag"] = cache_id
    return resp


@app.post("/api/generate")
def api_generate():
    uid = _ensure_user_id()
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    content = data.get("content", "")
    title = data.get("title", "") or "公告"
    try:
        date_str = _normalize_request_date_or_raise(data.get("date", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cfg = _sanitize_runtime_cfg({**_load_user_config(uid), **data.get("config", {})})
    cfg = _normalize_cfg_paths(cfg)
    export_format = (data.get("export_format") or cfg.get("export_format") or "PNG").upper()
    try:
        img = draw_poster(content, date_str, title, cfg).convert("RGB")
    except Exception:
        _log_exception("api_generate.failed", user_id=uid, title=title, date=date_str, export_format=export_format)
        return jsonify({"error": "生成失败，请检查图片素材和参数后重试"}), 500

    safe_title = _sanitize_filename(title)
    ext = {"PNG": ".png", "JPEG": ".jpg", "PDF": ".pdf"}.get(export_format, ".png")
    uniq = uuid.uuid4().hex[:8]
    filename = f"{safe_title}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uniq}{ext}"
    user_output_dir = os.path.join(OUTPUT_DIR, uid)
    os.makedirs(user_output_dir, exist_ok=True)
    path = os.path.join(user_output_dir, filename)
    if export_format == "JPEG":
        img.save(path, "JPEG", quality=int(cfg.get("jpeg_quality", 95)))
    elif export_format == "PDF":
        img.save(path, "PDF", resolution=100.0)
    else:
        img.save(path, "PNG")
    relpath = _public_path(path)
    _record_output_owner(relpath, uid)
    _prune_old_outputs_for_user(uid)

    copy_text = f"【{title}】\n{date_str}\n\n{content.strip()}\n\n{cfg.get('shop_name', '')}\n电话：{cfg.get('phone', '')}"
    return jsonify({"file": relpath, "name": filename, "copy_text": copy_text})


@app.get("/download/<path:relpath>")
def api_download(relpath):
    uid = _ensure_user_id()
    relpath = str(relpath or "").replace("\\", "/")
    abs_path = _safe_join_data_path(relpath)
    if not abs_path:
        return jsonify({"error": "非法路径"}), 403
    if not _is_owned_output(relpath, abs_path, uid):
        return jsonify({"error": "无权下载该文件"}), 403
    if not os.path.isfile(abs_path):
        return jsonify({"error": "文件不存在"}), 404
    inline = str(request.args.get("inline", "0")).strip().lower() in {"1", "true", "yes"}
    return send_file(abs_path, as_attachment=not inline)


@app.get("/asset/<path:relpath>")
def api_asset(relpath):
    abs_path = _safe_join_base_path(relpath)
    if not abs_path:
        return jsonify({"error": "非法路径"}), 403

    allowed_roots = [os.path.abspath(UPLOAD_DIR), os.path.abspath(os.path.join(BASE_DIR, "presets"))]
    in_allowed = any(abs_path == root or abs_path.startswith(root + os.sep) for root in allowed_roots)
    if not in_allowed:
        return jsonify({"error": "不允许访问该资源"}), 403

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        return jsonify({"error": "仅支持图片资源"}), 400
    if not os.path.isfile(abs_path):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(abs_path)


@app.post("/api/config")
def api_config():
    uid = _ensure_user_id()
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cfg = _sanitize_runtime_cfg({**DEFAULT_CONFIG, **data})
    save_config(_get_user_config_path(uid), cfg)
    return jsonify({"ok": True, "config": cfg})


@app.post("/api/format")
def api_format():
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"content": auto_format_content(data.get("content", ""))})


@app.post("/api/validate")
def api_validate():
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    valid, warnings = validate_content(data.get("content", ""))
    return jsonify({"valid": valid, "warnings": warnings})


@app.post("/api/batch-adjust")
def api_batch_adjust():
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "调整金额必须是数字"}), 400
    return jsonify({"content": batch_adjust_content(data.get("content", ""), amount)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5173, debug=DEV_AUTO_RELOAD, use_reloader=DEV_AUTO_RELOAD)
