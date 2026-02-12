import base64
import datetime
import io
import json
import os
import random
import re
import string
import uuid

from flask import Flask, jsonify, render_template, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from poster_engine import (
    DEFAULT_CONFIG,
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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("POSTER_DATA_DIR", os.path.join(BASE_DIR, "web_data"))
if not os.path.isabs(DATA_DIR):
    DATA_DIR = os.path.join(BASE_DIR, DATA_DIR)
DATA_DIR = os.path.abspath(DATA_DIR)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUT_DIR = os.path.join(DATA_DIR, "outputs")
USER_CONFIG_DIR = os.path.join(DATA_DIR, "user_configs")
USERS_PATH = os.path.join(DATA_DIR, "users.json")
CONFIG_PATH = os.path.join(DATA_DIR, "web_config.json")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(USER_CONFIG_DIR, exist_ok=True)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.secret_key = os.environ.get("POSTER_APP_SECRET", "replace-this-in-production")


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


def _sanitize_user_id(user_id):
    user_id = (user_id or "").strip()
    if not user_id:
        return ""
    # 仅允许字母、数字、下划线、短横线，避免路径注入。
    user_id = re.sub(r"[^0-9A-Za-z_-]", "", user_id)
    return user_id[:64]


def _is_guest_user(user_id):
    return bool(user_id) and user_id.startswith("guest_")


def _display_user_id(user_id):
    if _is_guest_user(user_id):
        short = user_id[len("guest_"):]
        return short[:5] if short else user_id
    return user_id


def _get_user_id():
    uid = _sanitize_user_id(session.get("user_id", ""))
    if uid and uid != session.get("user_id"):
        session["user_id"] = uid
    return uid


def _ensure_user_id():
    uid = _get_user_id()
    if uid:
        return uid
    short = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    uid = f"guest_{short}"
    session["user_id"] = uid
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
        return {}


def _save_users(users):
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _load_user_config(user_id):
    user_path = _get_user_config_path(user_id)
    if os.path.isfile(user_path):
        return load_config(user_path)
    # 新用户首次进入：继承站点默认配置，并给一个随机预设背景。
    cfg = load_config(CONFIG_PATH)
    if not cfg.get("bg_image_path"):
        presets = list(PresetGenerator.get_presets(BASE_DIR).values())
        if presets:
            picked = random.choice(presets)
            cfg["bg_mode"] = "preset"
            cfg["bg_image_path"] = _public_path(picked)
    if _is_guest_user(user_id):
        # 访客模式默认不展示站点素材，避免误用他人品牌元素。
        cfg["logo_image_path"] = ""
        cfg["stamp_image_path"] = ""
        cfg["qrcode_image_path"] = ""
    save_config(user_path, cfg)
    return cfg


def _safe_join_data_path(relpath):
    abs_path = os.path.abspath(os.path.join(BASE_DIR, relpath))
    data_root = os.path.abspath(DATA_DIR)
    if abs_path == data_root or abs_path.startswith(data_root + os.sep):
        return abs_path
    return ""


def _safe_join_base_path(relpath):
    abs_path = os.path.abspath(os.path.join(BASE_DIR, relpath))
    base_root = os.path.abspath(BASE_DIR)
    if abs_path == base_root or abs_path.startswith(base_root + os.sep):
        return abs_path
    return ""


def _json_body():
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("请求体必须是 JSON")
    if not isinstance(data, dict):
        raise ValueError("JSON 格式错误")
    return data


@app.route("/")
def index():
    return render_template("index.html")


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

    users = _load_users()
    has_user_profile = os.path.isfile(_get_user_config_path(uid))
    user_hash = users.get(uid, "")
    if user_hash:
        if not check_password_hash(user_hash, password):
            return jsonify({"error": "密码错误"}), 401
    else:
        # 首次注册新用户，或为历史用户首次补充密码。
        users[uid] = generate_password_hash(password)
        _save_users(users)

    current_uid = _ensure_user_id()
    merge_from_current = bool(data.get("merge_from_current", True))
    current_path = _get_user_config_path(current_uid)
    target_path = _get_user_config_path(uid)
    if merge_from_current and current_uid != uid and os.path.isfile(current_path) and (not has_user_profile):
        save_config(target_path, load_config(current_path))
    session["user_id"] = uid
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
    preset_payload = [{"name": name, "path": _public_path(path)} for name, path in presets.items()]
    return jsonify({"config": cfg, "system_templates": SYSTEM_TEMPLATES, "presets": preset_payload})


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
    date_str = format_date_input(data.get("date", ""))
    try:
        cfg = _normalize_cfg_paths({**_load_user_config(uid), **data.get("config", {})})
        img = draw_poster(content, date_str, title, cfg)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        valid, warnings = validate_content(content)
        return jsonify({"image": f"data:image/png;base64,{b64}", "date": date_str, "valid": valid, "warnings": warnings})
    except Exception:
        return jsonify({"error": "预览生成失败，请检查图片素材和参数后重试"}), 500


@app.post("/api/generate")
def api_generate():
    uid = _ensure_user_id()
    try:
        data = _json_body()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    content = data.get("content", "")
    title = data.get("title", "") or "公告"
    date_str = format_date_input(data.get("date", ""))
    cfg = _normalize_cfg_paths({**_load_user_config(uid), **data.get("config", {})})
    export_format = (data.get("export_format") or cfg.get("export_format") or "PNG").upper()
    try:
        img = draw_poster(content, date_str, title, cfg).convert("RGB")
    except Exception:
        return jsonify({"error": "生成失败，请检查图片素材和参数后重试"}), 500

    safe_title = _sanitize_filename(title)
    ext = {"PNG": ".png", "JPEG": ".jpg", "PDF": ".pdf"}.get(export_format, ".png")
    uniq = uuid.uuid4().hex[:8]
    filename = f"{safe_title}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uniq}{ext}"
    path = os.path.join(OUTPUT_DIR, filename)
    if export_format == "JPEG":
        img.save(path, "JPEG", quality=int(cfg.get("jpeg_quality", 95)))
    elif export_format == "PDF":
        img.save(path, "PDF", resolution=100.0)
    else:
        img.save(path, "PNG")

    copy_text = f"【{title}】\n{date_str}\n\n{content.strip()}\n\n{cfg.get('shop_name', '')}\n电话：{cfg.get('phone', '')}"
    return jsonify({"file": _public_path(path), "name": filename, "copy_text": copy_text})


@app.get("/download/<path:relpath>")
def api_download(relpath):
    abs_path = _safe_join_data_path(relpath)
    if not abs_path:
        return jsonify({"error": "非法路径"}), 403
    if not os.path.isfile(abs_path):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(abs_path, as_attachment=True)


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
    cfg = {**DEFAULT_CONFIG, **data}
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
    app.run(host="0.0.0.0", port=5173, debug=False)
