import datetime
import json
import logging
import os
import random
import re
import tempfile
import threading
from copy import deepcopy

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


CANVAS_SIZE = (1080, 1920)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGGER = logging.getLogger("poster_engine")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)


def _existing_path(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _candidate_cjk_fonts():
    local_regular = [
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Regular.otf"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-Regular.otf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simhei.ttf"),
    ]
    local_bold = [
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Bold.otf"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-Bold.otf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyhbd.ttc"),
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),
    ]
    return {"regular": local_regular, "bold": local_bold}


_font_candidates = _candidate_cjk_fonts()
FONT_CN_REG = _existing_path(_font_candidates["regular"])
FONT_CN_BOLD = _existing_path(_font_candidates["bold"] + _font_candidates["regular"])
FONT_CN_MED = _existing_path(
    [
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Medium.otf"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-Medium.otf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        FONT_CN_REG,
        FONT_CN_BOLD,
    ]
)
FONT_CN_LABEL = _existing_path(
    [
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-VF.ttf"),
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Medium.otf"),
        FONT_CN_MED,
        FONT_CN_REG,
    ]
)
FONT_NUM_AMETHYST = _existing_path(
    [
        os.path.join(BASE_DIR, "fonts", "Bahnschrift.ttf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        FONT_CN_BOLD,
        FONT_CN_MED,
        FONT_CN_REG,
    ]
)
FONT_NUM_PLUM = _existing_path(
    [
        os.path.join(BASE_DIR, "fonts", "Bahnschrift.ttf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        FONT_CN_BOLD,
        FONT_CN_MED,
        FONT_CN_REG,
    ]
)
FONT_NUM_INDIGO = _existing_path(
    [
        os.path.join(BASE_DIR, "fonts", "Bahnschrift.ttf"),
        os.path.join(BASE_DIR, "fonts", "MicrosoftYaHei.ttc"),
        FONT_CN_BOLD,
        FONT_CN_MED,
        FONT_CN_REG,
    ]
)
FONT_NUM = _existing_path(
    [
        FONT_NUM_AMETHYST,
        FONT_NUM_PLUM,
        FONT_NUM_INDIGO,
        FONT_CN_BOLD,
        FONT_CN_MED,
        FONT_CN_REG,
    ]
)
DEFAULT_FOOTER = "温馨提示：\n1. 严禁掺杂兑假，发现永久拒收\n2. 过磅数据记录最长保留 24 天"
SYSTEM_TEMPLATES = {
    "报价模板": (
        f"【工厂黄板】：1350 元/吨\n【手选黄板】：1300 元/吨\n【统货花纸】：800-900 元/吨\n【统货书本】：1300 元/吨\n【优质书本】：1330 元/吨\n【精选报纸】：1800-1900 元/吨\n\n{DEFAULT_FOOTER}",
        "调价通知",
    ),
    "调价模板": (
        f"【工厂黄板】：上调5 元/吨\n【手选黄板】：上调5 元/吨\n【统货花纸】：上调5 元/吨\n【统货书本】：上调5 元/吨\n【优质书本】：上调5 元/吨\n【精选报纸】：上调5 元/吨\n\n{DEFAULT_FOOTER}",
        "调价通知",
    ),
    "放假模板": (
        "尊敬的客户：\n春节将至，本店定于2026年1月26日（腊月二十七）起放假，2月4日（正月初八）正常开门收货。\n\n请各位老板合理安排送货时间。\n祝大家新春快乐，生意兴隆，阖家幸福！",
        "放假通知",
    ),
}
SYSTEM_TEMPLATE_META = {
    "报价模板": {"is_holiday": False},
    "调价模板": {"is_holiday": False},
    "放假模板": {"is_holiday": True},
}
DEFAULT_CONFIG = {
    "shop_name": "环太平洋废纸回收打包站",
    "shop_name_hist": ["环太平洋废纸回收打包站"],
    "address": "太平洋基里巴斯群岛101街区",
    "address_hist": ["太平洋基里巴斯群岛101街区"],
    "phone": "1234567890",
    "phone_hist": ["1234567890"],
    "slogan": "诚信经营 · 现金结算 · 假货勿扰",
    "slogan_hist": ["诚信经营 · 现金结算 · 假货勿扰"],
    "bg_image_path": "",
    "bg_mode": "custom",
    "logo_image_path": "",
    "qrcode_image_path": "",
    "stamp_image_path": "",
    "stamp_opacity": 0.85,
    "bg_blur_radius": 30,
    "bg_brightness": 1.0,
    "card_opacity": 1.0,
    "card_style": "single",
    "theme_color": "#B22222",
    "price_color_mode": "semantic",
    "price_style": "amethyst",
    "last_content": "",
    "last_date": "",
    "last_title": "调价通知",
    "custom_templates": {},
    "export_format": "PNG",
    "jpeg_quality": 95,
    "watermark_enabled": False,
    "watermark_text": "仅供客户参考",
    "watermark_opacity": 0.15,
    "watermark_density": 1.0,
}

PRICE_STYLES = {
    "amethyst": {"font": FONT_NUM_AMETHYST, "color": "#5B3FA8", "unit_color": "#6D57B5"},
    "plum": {"font": FONT_NUM_PLUM, "color": "#6A2C91", "unit_color": "#7A48A2"},
    "indigo": {"font": FONT_NUM_INDIGO, "color": "#3F4DB8", "unit_color": "#5F6AD1"},
}


def _normalize_hex_color(value, fallback="#B22222"):
    text = str(value or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", text):
        return text.upper()
    return fallback


def _hex_to_rgb(value, fallback=(178, 34, 34)):
    hex_color = _normalize_hex_color(value, "#{:02X}{:02X}{:02X}".format(*fallback))
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def _mix_with_white(rgb, ratio):
    t = max(0.0, min(1.0, float(ratio)))
    r, g, b = rgb
    return (
        int(r + (255 - r) * t),
        int(g + (255 - g) * t),
        int(b + (255 - b) * t),
    )


class FontManager:
    _cache = {}

    @staticmethod
    def get(font_name, size):
        key = (font_name, size)
        if key in FontManager._cache:
            return FontManager._cache[key]
        candidates = [font_name, FONT_CN_BOLD, FONT_CN_REG]
        font = None
        for name in candidates:
            if not name:
                continue
            try:
                font = ImageFont.truetype(name, size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        FontManager._cache[key] = font
        return font


class PresetGenerator:
    _cache = {}
    _lock = threading.Lock()

    @staticmethod
    def _add_noise(img, intensity=0.08):
        noise = Image.effect_noise(img.size, 20).convert("RGB")
        return ImageChops.blend(img, noise, intensity)

    @staticmethod
    def _gen_fluid_base(width, height, bg_color, blobs):
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        for x, y, r, color in blobs:
            rx = x + random.randint(-50, 50)
            ry = y + random.randint(-50, 50)
            draw.ellipse((rx - r, ry - r, rx + r, ry + r), fill=color)
        return img.filter(ImageFilter.GaussianBlur(radius=120))

    @staticmethod
    def gen_luxury_red():
        w, h = CANVAS_SIZE
        blobs = [(w * 0.2, h * 0.2, 400, (200, 20, 20)), (w * 0.8, h * 0.8, 500, (100, 0, 0)), (w * 0.5, h * 0.4, 300, (220, 50, 50))]
        img = PresetGenerator._gen_fluid_base(w, h, "#8B0000", blobs)
        draw = ImageDraw.Draw(img)
        for _ in range(1200):
            x, y = random.randint(0, w), random.randint(0, h)
            s = random.randint(1, 3)
            draw.ellipse((x, y, x + s, y + s), fill=(255, 215, 0, 180))
        return PresetGenerator._add_noise(img, 0.05)

    @staticmethod
    def gen_fluid_blue():
        w, h = CANVAS_SIZE
        blobs = [(0, 0, 600, (10, 40, 90)), (w, h, 700, (0, 100, 160)), (w * 0.8, h * 0.2, 400, (0, 200, 200))]
        img = PresetGenerator._gen_fluid_base(w, h, "#051020", blobs)
        return PresetGenerator._add_noise(img, 0.04)

    @staticmethod
    def gen_misty_green():
        w, h = CANVAS_SIZE
        blobs = [(w * 0.5, h, 800, (20, 60, 40)), (w * 0.2, h * 0.3, 400, (180, 200, 180)), (w * 0.9, h * 0.1, 300, (200, 220, 200))]
        img = PresetGenerator._gen_fluid_base(w, h, "#F0F5F0", blobs)
        return PresetGenerator._add_noise(img, 0.06)

    @staticmethod
    def gen_frosted_grey():
        w, h = CANVAS_SIZE
        img = Image.new("RGB", (w, h), "#F2F2F2")
        return PresetGenerator._add_noise(img.filter(ImageFilter.GaussianBlur(40)), 0.08)

    @staticmethod
    def gen_kraft_pro():
        w, h = CANVAS_SIZE
        img = Image.new("RGB", (w, h), "#D8C09D")
        noise = Image.effect_noise((w // 2, h // 2), 40).resize((w, h), Image.Resampling.BICUBIC).convert("RGB")
        return ImageChops.blend(img, noise, 0.15)

    @staticmethod
    def gen_aurora_cyan():
        w, h = CANVAS_SIZE
        blobs = [
            (w * 0.1, h * 0.22, 520, (10, 46, 92)),
            (w * 0.78, h * 0.18, 460, (25, 102, 168)),
            (w * 0.28, h * 0.72, 500, (8, 132, 145)),
            (w * 0.88, h * 0.82, 540, (24, 72, 124)),
        ]
        base = PresetGenerator._gen_fluid_base(w, h, "#07162A", blobs)

        aurora = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ad = ImageDraw.Draw(aurora)
        for _ in range(8):
            x0 = random.randint(-200, w // 3)
            x1 = random.randint(w * 2 // 3, w + 200)
            y0 = random.randint(40, h // 2)
            y1 = y0 + random.randint(240, 520)
            col = random.choice([(96, 255, 226, 54), (35, 203, 255, 52), (132, 255, 186, 42)])
            ad.ellipse((x0, y0, x1, y1), outline=col, width=random.randint(6, 12))
        aurora = aurora.filter(ImageFilter.GaussianBlur(22))
        img = Image.alpha_composite(base.convert("RGBA"), aurora).convert("RGB")
        return PresetGenerator._add_noise(img, 0.04)

    @staticmethod
    def gen_neon_city():
        w, h = CANVAS_SIZE
        blobs = [
            (w * 0.12, h * 0.18, 430, (15, 32, 92)),
            (w * 0.92, h * 0.14, 360, (0, 170, 220)),
            (w * 0.28, h * 0.82, 420, (160, 40, 190)),
            (w * 0.82, h * 0.82, 480, (30, 120, 255)),
        ]
        base = PresetGenerator._gen_fluid_base(w, h, "#0A0F2A", blobs)
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for _ in range(14):
            x1 = random.randint(-120, w)
            x2 = x1 + random.randint(280, 620)
            y = random.randint(40, h - 40)
            color = random.choice(
                [(20, 255, 255, 90), (255, 80, 180, 86), (70, 130, 255, 86), (255, 190, 70, 68)]
            )
            gd.line([(x1, y), (x2, y + random.randint(-50, 50))], fill=color, width=random.randint(3, 7))
        glow = glow.filter(ImageFilter.GaussianBlur(14))
        img = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
        return PresetGenerator._add_noise(img, 0.045)

    @staticmethod
    def gen_sunset_amber():
        w, h = CANVAS_SIZE
        top = (255, 236, 198)
        mid = (255, 173, 116)
        bottom = (127, 79, 198)
        img = Image.new("RGB", (w, h), top)
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            if t < 0.55:
                s = t / 0.55
                r = int(top[0] + (mid[0] - top[0]) * s)
                g = int(top[1] + (mid[1] - top[1]) * s)
                b = int(top[2] + (mid[2] - top[2]) * s)
            else:
                s = (t - 0.55) / 0.45
                r = int(mid[0] + (bottom[0] - mid[0]) * s)
                g = int(mid[1] + (bottom[1] - mid[1]) * s)
                b = int(mid[2] + (bottom[2] - mid[2]) * s)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        haze = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        hd = ImageDraw.Draw(haze)
        for _ in range(10):
            rx = random.randint(-120, w + 120)
            ry = random.randint(-80, h + 80)
            rr = random.randint(180, 360)
            col = random.choice([(255, 255, 255, 30), (255, 224, 186, 40), (244, 170, 255, 28)])
            hd.ellipse((rx - rr, ry - rr, rx + rr, ry + rr), fill=col)
        haze = haze.filter(ImageFilter.GaussianBlur(30))
        img = Image.alpha_composite(img.convert("RGBA"), haze).convert("RGB")
        return PresetGenerator._add_noise(img, 0.035)

    @staticmethod
    def gen_noir_depth():
        w, h = CANVAS_SIZE
        base_top = (14, 18, 24)
        base_bottom = (5, 7, 10)
        img = Image.new("RGB", (w, h), base_top)
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(base_top[0] + (base_bottom[0] - base_top[0]) * t)
            g = int(base_top[1] + (base_bottom[1] - base_top[1]) * t)
            b = int(base_top[2] + (base_bottom[2] - base_top[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((int(-w * 0.2), int(h * 0.05), int(w * 0.62), int(h * 0.9)), fill=(64, 96, 132, 66))
        gd.ellipse((int(w * 0.42), int(-h * 0.18), int(w * 1.2), int(h * 0.62)), fill=(52, 72, 102, 54))
        for _ in range(18):
            x = random.randint(-200, w + 120)
            y = random.randint(0, h)
            ln = random.randint(280, 640)
            gd.line([(x, y), (x + ln, y + random.randint(-38, 38))], fill=(190, 210, 235, random.randint(8, 18)), width=1)
        glow = glow.filter(ImageFilter.GaussianBlur(18))

        vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        vd.rectangle((0, 0, w, h), fill=(0, 0, 0, 46))
        for i in range(56):
            a = int(3 + i * 1.25)
            vd.rounded_rectangle([(i * 8, i * 8), (w - i * 8, h - i * 8)], radius=120, outline=(0, 0, 0, min(150, a)), width=2)
        vignette = vignette.filter(ImageFilter.GaussianBlur(14))

        img = Image.alpha_composite(img.convert("RGBA"), glow)
        img = Image.alpha_composite(img, vignette).convert("RGB")
        return PresetGenerator._add_noise(img, 0.05)

    @staticmethod
    def get_presets(base_dir):
        presets_dir = os.path.join(base_dir, "presets")
        os.makedirs(presets_dir, exist_ok=True)
        presets = [
            ("preset_luxury_red.png", "鎏金故宫红", PresetGenerator.gen_luxury_red),
            ("preset_fluid_blue.png", "深海流体蓝", PresetGenerator.gen_fluid_blue),
            ("preset_misty_green.png", "晨雾森林绿", PresetGenerator.gen_misty_green),
            ("preset_neon_city.png", "霓虹赛博夜", PresetGenerator.gen_neon_city),
            ("preset_sunset_amber.png", "落日琥珀橙", PresetGenerator.gen_sunset_amber),
            ("preset_noir_depth.png", "深空曜黑", PresetGenerator.gen_noir_depth),
            ("preset_aurora_cyan.png", "极光青域", PresetGenerator.gen_aurora_cyan),
        ]
        out = {}
        for filename, name, fn in presets:
            path = os.path.join(presets_dir, filename)
            if not os.path.exists(path) or os.path.getsize(path) < 1024:
                fn().save(path)
            out[name] = path
        with PresetGenerator._lock:
            PresetGenerator._cache = out
        return deepcopy(out)


def format_date_input(value):
    val = (value or "").strip().lower()
    if not val:
        return ""
    now = datetime.datetime.now()
    if val in {"今天", "0", "today"}:
        return now.strftime("%Y年%m月%d日")
    if val in {"明天", "+1", "tmr"}:
        return (now + datetime.timedelta(days=1)).strftime("%Y年%m月%d日")
    if val in {"后天", "+2"}:
        return (now + datetime.timedelta(days=2)).strftime("%Y年%m月%d日")
    if val in {"昨天", "-1", "yest"}:
        return (now - datetime.timedelta(days=1)).strftime("%Y年%m月%d日")
    val = re.sub(r"[./-]", " ", val)
    parts = val.split()
    if len(parts) == 3:
        y, m, d = parts
        if len(y) == 2:
            y = f"20{y}"
        return f"{y}年{m}月{d}日"
    return value.strip()


def normalize_date_for_render(value):
    text = (value or "").strip()
    if not text:
        return datetime.datetime.now().strftime("%Y年%m月%d日")
    fixed = format_date_input(text)
    out = fixed if fixed else text
    if "?" not in out and "？" not in out:
        return out

    nums = re.findall(r"\d+", out)
    if len(nums) >= 3:
        y, m, d = nums[0], nums[1], nums[2]
    else:
        compact = "".join(re.findall(r"\d", out))
        if len(compact) >= 8:
            y, m, d = compact[:4], compact[4:6], compact[6:8]
        else:
            return out.replace("?", "").replace("？", "")
    try:
        return f"{int(y):04d}年{int(m):02d}月{int(d):02d}日"
    except Exception:
        return out.replace("?", "").replace("？", "")


def normalize_content_for_render(content):
    text = (content or "").replace(":", "：").replace(",", "，").replace("(", "（").replace(")", "）")
    text = re.sub(r"([\u4e00-\u9fa5])(\d)", r"\1 \2", text)
    text = re.sub(r"(\d)([\u4e00-\u9fa5])", r"\1 \2", text)
    return text


def auto_format_content(content):
    lines = (content or "").strip().split("\n")
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            out.append("")
            continue
        if line.startswith("【") or "：" in line or ":" in line:
            out.append(line)
            continue
        m = re.match(r"^([^\d\s]+)\s*(\d{3,5})(?:\s*元)?$", line)
        if m:
            name, price = m.groups()
            out.append(f"【{name}】：{price} 元/吨")
        else:
            out.append(line)
    return "\n".join(out).strip()


def validate_content(content):
    warnings = []
    prices = re.findall(r"(\d{1,5})(?:\s*元)?", content or "")
    for price_str in prices:
        price = int(price_str)
        if price == 0:
            warnings.append("发现价格为 0 元")
        elif price > 9999:
            warnings.append(f"价格 {price} 元可能过高")
    return len(warnings) == 0, warnings


def batch_adjust_content(content, amount):
    txt = content or ""

    def repl_range(m):
        p1, p2 = int(m.group(1)), int(m.group(2))
        return f"{max(0, p1 + amount)}-{max(0, p2 + amount)}"

    def protect_ranges(text):
        holders = []

        def _store(m):
            token = f"__RANGE_TOKEN_{len(holders)}__"
            holders.append(repl_range(m))
            return token

        protected = re.sub(r"(\d{3,5})\s*[-~～至到]\s*(\d{3,5})", _store, text)
        return protected, holders

    def restore_ranges(text, holders):
        out = text
        for i, val in enumerate(holders):
            out = out.replace(f"__RANGE_TOKEN_{i}__", val)
        return out

    def adjust_line(line):
        raw = line or ""
        if not raw.strip():
            return raw

        is_price_line = bool(
            re.search(r"(元|吨|上调|下调)", raw)
            or re.search(r"【[^】]{1,30}】\s*[：:]\s*(?:上调|下调|\d{3,5})", raw)
        )
        if not is_price_line:
            return raw

        out, range_holders = protect_ranges(raw)
        out = re.sub(
            r"(上调|下调)\s*(\d{1,5})",
            lambda _: f"{'上调' if amount >= 0 else '下调'}{abs(amount)}",
            out,
        )
        out = re.sub(r"(?<!\d)(\d{3,5})(?!\d)", lambda m: str(max(0, int(m.group(1)) + amount)), out)
        out = restore_ranges(out, range_holders)
        return out

    lines = txt.split("\n")
    return "\n".join(adjust_line(line) for line in lines).strip()


def _load_image(path):
    if path and os.path.exists(path):
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            LOGGER.exception("load_image.failed | %s", json.dumps({"path": path}, ensure_ascii=False, default=str))
            return None
    return None


def _apply_watermark(img, text, opacity=0.15, density=1.0):
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = FontManager.get(FONT_CN_REG, 48)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    try:
        density = float(density)
    except Exception:
        density = 1.0
    density = max(0.5, min(2.0, density))
    sx = max(tw + 36, int((tw + 150) / density))
    sy = max(th + 28, int((th + 120) / density))
    color = (128, 128, 128, int(255 * opacity))
    offset = 0
    for y in range(-h, h * 2, sy):
        offset += sx // 2
        for x in range(-w + (offset % sx), w * 2, sx):
            draw.text((x, y), text, font=font, fill=color)
    layer = layer.rotate(30, center=(w // 2, h // 2), resample=Image.BICUBIC)
    return Image.alpha_composite(img, layer)


def _calculate_layout_lines(lines, cw, is_holiday_mode, get_font):
    layout = []
    total_height = 0
    row_idx = 0
    td = ImageDraw.Draw(Image.new("L", (1, 1)))

    for line in lines:
        line = line.strip()
        if not line:
            h = 40 if is_holiday_mode else 10
            layout.append({"type": "space", "height": h})
            total_height += h
            continue
        
        norm_line = re.sub(r"\s+", "", line)
        is_note = bool(re.fullmatch(r"温馨提示[:：]?", norm_line))
        if (("：" in line or ":" in line) and not is_note and not is_holiday_mode):
             h = 85
             layout.append({"type": "kv", "text": line, "height": h, "row_idx": row_idx})
             total_height += h
             row_idx += 1
        else:
             if row_idx > 0:
                 total_height += 20
                 layout.append({"type": "space", "height": 20})
                 row_idx = 0
             
             f = get_font(42, True) if is_note else get_font(38)
             lh = 65 if (is_note or is_holiday_mode) else 55
             
             chars, start = list(line), 0
             wrapped_lines = []
             while start < len(chars):
                 est_len = int((cw - 120) / (42 if is_note else 38))
                 end = min(len(chars), start + est_len + 5)
                 while end > start and td.textlength("".join(chars[start:end]), font=f) > (cw - 120):
                     end -= 1
                 if end == start: end += 1
                 wrapped_lines.append("".join(chars[start:end]))
                 start = end
             
             block_height = len(wrapped_lines) * lh
             layout.append({"type": "text", "lines": wrapped_lines, "height": block_height, "lh": lh, "is_note": is_note})
             total_height += block_height

    return layout, total_height


def draw_poster(content, date_str, title, cfg):
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    content = normalize_content_for_render(content or "")
    w, h = CANVAS_SIZE
    theme_hex = _normalize_hex_color(cfg.get("theme_color", "#B22222"))
    theme_rgb = _hex_to_rgb(theme_hex)
    theme_unit = _mix_with_white(theme_rgb, 0.62)
    row_bg_fixed = (249, 249, 249)

    if cfg.get("bg_mode") == "preset" and cfg.get("bg_image_path"):
        base = _load_image(cfg.get("bg_image_path")) or Image.new("RGB", (w, h), "#E0E0E0")
        base = base.resize((w, h), Image.Resampling.LANCZOS)
    elif cfg.get("bg_image_path"):
        base = _load_image(cfg.get("bg_image_path"))
        if base:
            ratio = max(w / base.width, h / base.height)
            nw, nh = int(base.width * ratio), int(base.height * ratio)
            base = base.resize((nw, nh), Image.Resampling.LANCZOS).crop(
                ((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h)
            )
            if cfg.get("bg_blur_radius"):
                base = base.filter(ImageFilter.GaussianBlur(cfg["bg_blur_radius"]))
            base = ImageEnhance.Brightness(base).enhance(float(cfg.get("bg_brightness", 1.0)))
        else:
            base = Image.new("RGB", (w, h), "#E0E0E0")
    else:
        base = Image.new("RGB", (w, h), "#E0E0E0")
    img = base.convert("RGBA")

    get_font = lambda size, bold=False: FontManager.get(FONT_CN_BOLD if bold else FONT_CN_REG, size)
    get_med_font = lambda size: FontManager.get(FONT_CN_MED, size)
    get_label_font = lambda size: FontManager.get(FONT_CN_LABEL, size)
    price_style = PRICE_STYLES.get(cfg.get("price_style", "amethyst"), PRICE_STYLES["amethyst"])
    get_num_font = lambda size: FontManager.get(price_style.get("font") or FONT_NUM, size)
    cw = 920
    cx = (w - cw) // 2
    
    lines = (content or "").split("\n")
    is_holiday_mode = "放假" in (title or "")
    layout_items, sim_y = _calculate_layout_lines(lines, cw, is_holiday_mode, get_font)


    ch = min(1800, max(900, 500 + sim_y - 10 + 460))
    cy = (h - ch) // 2
    footer_start_y = cy + 500 + sim_y - 10

    style = cfg.get("card_style", "single")
    if style in {"fold", "sidebar", "soft", "outline_pro", "outline", "ink", "neon"}:
        style = "single"
    alpha = int(float(cfg.get("card_opacity", 1.0)) * 255)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    flip_overlay = None
    dc = ImageDraw.Draw(card)
    is_dark_style = False
    if style == "ticket":
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([(cx + 10, cy + 14), (cx + cw + 10, cy + ch + 14)], radius=30, fill=(0, 0, 0, 66))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(14)))

        dc.rounded_rectangle(
            [(cx, cy), (cx + cw, cy + ch)],
            radius=28,
            fill=(255, 252, 246, alpha),
            outline=(214, 202, 184, min(255, alpha)),
            width=3,
        )
        dc.rounded_rectangle(
            [(cx + 14, cy + 14), (cx + cw - 14, cy + ch - 14)],
            radius=22,
            outline=(242, 232, 216, min(255, alpha)),
            width=2,
        )

        # 左右齿孔，强化票据辨识度
        notch_r = 9
        notch_step = 38
        notch_top = cy + 56
        notch_bottom = cy + ch - 56
        for y_notch in range(notch_top, notch_bottom, notch_step):
            dc.ellipse((cx - notch_r, y_notch - notch_r, cx + notch_r, y_notch + notch_r), fill=(0, 0, 0, 0))
            dc.ellipse((cx + cw - notch_r, y_notch - notch_r, cx + cw + notch_r, y_notch + notch_r), fill=(0, 0, 0, 0))

        tear_y = max(cy + 240, min(cy + ch - 260, footer_start_y - 38))
        dash_start = cx + 48
        dash_end = cx + cw - 48
        dash_w = 16
        dash_gap = 10
        x_dash = dash_start
        while x_dash < dash_end:
            dc.line([(x_dash, tear_y), (min(x_dash + dash_w, dash_end), tear_y)], fill=(186, 174, 156, 230), width=2)
            x_dash += dash_w + dash_gap
        dc.ellipse((cx - 12, tear_y - 12, cx + 12, tear_y + 12), fill=(0, 0, 0, 0))
        dc.ellipse((cx + cw - 12, tear_y - 12, cx + cw + 12, tear_y + 12), fill=(0, 0, 0, 0))
    elif style == "double":
        back_dx, back_dy = 30, 34
        back_alpha = min(255, int(alpha * 0.9) + 28)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            [(cx + back_dx + 8, cy + back_dy + 10), (cx + cw + back_dx + 8, cy + ch + back_dy + 10)],
            radius=42,
            fill=(0, 0, 0, 76),
        )
        sd.rounded_rectangle(
            [(cx + 10, cy + 12), (cx + cw + 10, cy + ch + 12)],
            radius=40,
            fill=(0, 0, 0, 58),
        )
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(24)))

        dc.rounded_rectangle(
            [(cx + back_dx, cy + back_dy), (cx + cw + back_dx, cy + ch + back_dy)],
            radius=40,
            fill=(232, 236, 243, back_alpha),
            outline=(201, 210, 224, min(255, alpha)),
            width=2,
        )
        dc.rounded_rectangle(
            [(cx, cy), (cx + cw, cy + ch)],
            radius=40,
            fill=(255, 255, 255, alpha),
            outline=(238, 241, 247, min(255, alpha + 10)),
            width=2,
        )

        double_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dod = ImageDraw.Draw(double_overlay)
        for i in range(16):
            a = int(42 * (1 - i / 16))
            dod.line(
                [(cx + back_dx + 40, cy + back_dy + 10 + i), (cx + cw + back_dx - 40, cy + back_dy + 10 + i)],
                fill=(255, 255, 255, a),
                width=1,
            )
        for i in range(24):
            a = int(54 * (1 - i / 24))
            dod.line(
                [(cx + cw + 2 + i, cy + 28 + i), (cx + cw + 2 + i, cy + ch - 36)],
                fill=(132, 140, 154, a),
                width=2,
            )
            dod.line(
                [(cx + 32 + i, cy + ch + 2 + i), (cx + cw - 38, cy + ch + 2 + i)],
                fill=(132, 140, 154, a),
                width=2,
            )
        flip_overlay = double_overlay.filter(ImageFilter.GaussianBlur(0.8))
    elif style == "block":
        for i in range(12, 0, -1):
            ImageDraw.Draw(card).rounded_rectangle([(cx + i, cy + i), (cx + cw + i, cy + ch + i)], radius=40, fill=(230, 230, 230, alpha))
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
    elif style == "stack":
        back_dx, back_dy = -24, 34
        back_angle = -2.8
        back_alpha = min(255, int(alpha * 0.9) + 24)

        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            [(cx + back_dx + 18, cy + back_dy + 16), (cx + cw + back_dx + 18, cy + ch + back_dy + 16)],
            radius=40,
            fill=(0, 0, 0, 78),
        )
        sd.rounded_rectangle(
            [(cx + 12, cy + 14), (cx + cw + 12, cy + ch + 14)],
            radius=40,
            fill=(0, 0, 0, 56),
        )
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(20)))

        pad = 88
        back_sheet = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
        bsd = ImageDraw.Draw(back_sheet)
        bsd.rounded_rectangle(
            [(pad, pad), (pad + cw, pad + ch)],
            radius=38,
            fill=(234, 238, 244, back_alpha),
            outline=(198, 208, 222, min(255, alpha)),
            width=2,
        )
        for i in range(12):
            a = int(42 * (1 - i / 12))
            bsd.line(
                [(pad + 34, pad + 8 + i), (pad + cw - 34, pad + 8 + i)],
                fill=(255, 255, 255, a),
                width=1,
            )
        back_rotated = back_sheet.rotate(back_angle, resample=Image.Resampling.BICUBIC, expand=True)
        off_x = cx + back_dx - (back_rotated.width - back_sheet.width) // 2 - pad
        off_y = cy + back_dy - (back_rotated.height - back_sheet.height) // 2 - pad
        card.alpha_composite(back_rotated, (int(off_x), int(off_y)))

        dc.rounded_rectangle(
            [(cx, cy), (cx + cw, cy + ch)],
            radius=40,
            fill=(255, 255, 255, alpha),
            outline=(238, 241, 247, min(255, alpha + 10)),
            width=2,
        )

        stack_overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sod = ImageDraw.Draw(stack_overlay)
        for i in range(22):
            a = int(56 * (1 - i / 22))
            sod.line(
                [(cx + cw + 2 + i, cy + 34 + i), (cx + cw + 2 + i, cy + ch - 42)],
                fill=(126, 136, 152, a),
                width=2,
            )
            sod.line(
                [(cx + 42 + i, cy + ch + 2 + i), (cx + cw - 44, cy + ch + 2 + i)],
                fill=(126, 136, 152, a),
                width=2,
            )
        flip_overlay = stack_overlay.filter(ImageFilter.GaussianBlur(0.8))
    elif style == "flip":
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([(cx + 14, cy + 18), (cx + cw + 14, cy + ch + 18)], radius=42, fill=(0, 0, 0, 55))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(16)))
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
        fs = 216
        dc.polygon([(cx + cw, cy + ch), (cx + cw, cy + ch - fs), (cx + cw - fs, cy + ch)], fill=(0, 0, 0, 0))

        fold = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fold)

        for i in range(34):
            a = int(46 * (1 - i / 34))
            fd.line(
                [(cx + cw - fs - 8 + i, cy + ch + 2 + i // 3), (cx + cw + 2, cy + ch - fs - 8 + i)],
                fill=(88, 95, 108, a),
                width=2,
            )

        fold_pad = 26
        fold_inset = 12
        tile_left = cx + cw - fs - fold_pad
        tile_top = cy + ch - fs - fold_pad
        tile_right = cx + cw + fold_pad
        tile_bottom = cy + ch + fold_pad
        tile_w = max(1, tile_right - tile_left)
        tile_h = max(1, tile_bottom - tile_top)
        scale = 4
        hi = Image.new("RGBA", (tile_w * scale, tile_h * scale), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hi)

        def hp(px, py):
            return ((px - tile_left) * scale, (py - tile_top) * scale)

        p_corner = (cx + cw - 2, cy + ch - 2)
        p_top = (cx + cw - 2, cy + ch - fs + fold_inset)
        p_left = (cx + cw - fs + fold_inset, cy + ch - 2)
        p_inner = (cx + cw - int(fs * 0.54), cy + ch - int(fs * 0.54))

        hd.polygon([hp(*p_corner), hp(*p_top), hp(*p_left)], fill=(248, 248, 248, min(255, alpha + 16)))
        hd.polygon([hp(*p_corner), hp(*p_top), hp(*p_inner)], fill=(222, 224, 228, 236))

        hd.line([hp(*p_left), hp(*p_top)], fill=(184, 188, 196, 220), width=max(3, scale * 2))

        grad_steps = fs - fold_inset - 4
        for i in range(max(1, grad_steps)):
            t = i / max(1, grad_steps - 1)
            shade = int(255 - 42 * t)
            a = int(92 * (1 - t))
            x1 = cx + cw - 2 - i
            y1 = cy + ch - 2
            x2 = cx + cw - 2
            y2 = cy + ch - 2 - i
            hd.line([hp(x1, y1), hp(x2, y2)], fill=(shade, shade, shade, a), width=scale)

        for i in range(8):
            a = int(68 * (1 - i / 8))
            hd.line(
                [hp(cx + cw - fs + fold_inset + i, cy + ch - 2), hp(cx + cw - 2, cy + ch - fs + fold_inset + i)],
                fill=(255, 255, 255, a),
                width=scale,
            )

        aa_tile = hi.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        fold.alpha_composite(aa_tile, (tile_left, tile_top))
        flip_overlay = fold.filter(ImageFilter.GaussianBlur(0.6))
    elif style == "aurora":
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([(cx + 14, cy + 20), (cx + cw + 14, cy + ch + 20)], radius=44, fill=(10, 16, 28, 62))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(14)))

        # 先对卡片区域做背景模糊，强化玻璃磨砂感
        frost_mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(frost_mask).rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=42, fill=255)
        blurred_bg = img.filter(ImageFilter.GaussianBlur(24))
        frost_layer = Image.composite(blurred_bg, Image.new("RGBA", (w, h), (0, 0, 0, 0)), frost_mask)
        img = Image.alpha_composite(img, frost_layer)

        # 玻璃基底：半透明，避免看起来像实体白卡
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=42, fill=(242, 248, 255, min(200, alpha + 6)))

        # 冷色折射层：制造玻璃内部色散
        tint = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        td = ImageDraw.Draw(tint)
        for i in range(34):
            t = i / 33
            col = (
                int(170 + 40 * (1 - t)),
                int(194 + 34 * (1 - t)),
                int(225 + 24 * t),
                int(40 * (1 - t)),
            )
            td.rounded_rectangle(
                [(cx + 8 + i, cy + 8 + i), (cx + cw - 8 - i, cy + ch - 8 - i)],
                radius=max(16, 36 - i),
                outline=col,
                width=1,
            )
        img = Image.alpha_composite(img, tint.filter(ImageFilter.GaussianBlur(0.8)))

        glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glass)
        edge_rgb = (184, 196, 210)
        for i in range(20):
            t = i / 19
            gd.rounded_rectangle(
                [(cx + i, cy + i), (cx + cw - i, cy + ch - i)],
                radius=max(16, 42 - i),
                outline=(
                    int(edge_rgb[0] + (245 - edge_rgb[0]) * t),
                    int(edge_rgb[1] + (247 - edge_rgb[1]) * t),
                    int(edge_rgb[2] + (250 - edge_rgb[2]) * t),
                    112 - int(84 * t),
                ),
                width=1,
            )
        # 顶部柔和线性高光（单段实现，避免调试叠加造成冗余）
        for i in range(18):
            t = i / 17
            a = int(58 * (1 - t))
            inset = 26 + int(8 * t)
            gd.line([(cx + inset, cy + 18 + i), (cx + cw - inset, cy + 18 + i)], fill=(249, 252, 255, a), width=1)
        # 外缘再叠一层柔光，提升“边缘模糊”观感
        edge_glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        eg = ImageDraw.Draw(edge_glow)
        for i in range(12):
            a = int(18 * (1 - i / 12))
            eg.rounded_rectangle(
                [(cx - 6 - i, cy - 6 - i), (cx + cw + 6 + i, cy + ch + 6 + i)],
                radius=46 + i,
                outline=(edge_rgb[0], edge_rgb[1], edge_rgb[2], a),
                width=1,
            )
        flip_overlay = Image.alpha_composite(
            glass.filter(ImageFilter.GaussianBlur(1.6)),
            edge_glow.filter(ImageFilter.GaussianBlur(1.8)),
        )
    elif style == "paper_relief":
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([(cx + 14, cy + 22), (cx + cw + 14, cy + ch + 22)], radius=38, fill=(52, 70, 92, 68))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(18)))

        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=38, fill=(255, 255, 255, min(255, alpha + 10)))

        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fd = ImageDraw.Draw(frame)
        for i in range(10):
            t = i / 9
            fd.rounded_rectangle(
                [(cx + 6 + i, cy + 6 + i), (cx + cw - 6 - i, cy + ch - 6 - i)],
                radius=max(14, 34 - i),
                outline=(
                    int(255 - (255 - theme_rgb[0]) * (0.25 + 0.6 * t)),
                    int(255 - (255 - theme_rgb[1]) * (0.25 + 0.6 * t)),
                    int(255 - (255 - theme_rgb[2]) * (0.25 + 0.6 * t)),
                    155 - i * 12,
                ),
                width=2 if i < 3 else 1,
            )
        for i in range(14):
            a = int(70 * (1 - i / 14))
            fd.rounded_rectangle(
                [(cx + 22 + i, cy + 20 + i), (cx + cw - 22 - i, int(cy + ch * 0.35) - i)],
                radius=max(8, 24 - i),
                outline=(255, 255, 255, a),
                width=1,
            )
        for i in range(18):
            a = int(52 * (1 - i / 18))
            fd.line([(cx + 48, cy + ch - 18 + i), (cx + cw - 48, cy + ch - 18 + i)], fill=(68, 84, 106, a), width=1)
        flip_overlay = frame.filter(ImageFilter.GaussianBlur(0.7))
    else:
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=15, fill=(255, 255, 255, alpha))
    img = Image.alpha_composite(img, card)
    if flip_overlay is not None:
        img = Image.alpha_composite(img, flip_overlay)
    draw = ImageDraw.Draw(img)

    logo = _load_image(cfg.get("logo_image_path"))
    if logo:
        logo_size = 198
        logo_half = logo_size // 2
        ring_pad = 6
        logo = ImageOps.fit(logo, (logo_size, logo_size), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (logo_size, logo_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo_size, logo_size), fill=255)
        ly, lx = cy + 60, (w - logo_size) // 2
        draw.ellipse((lx - ring_pad, int(ly - logo_half) - ring_pad, lx + logo_size + ring_pad, int(ly + logo_half) + ring_pad), fill="white")
        img.paste(logo, (lx, int(ly - logo_half)), mask)

    cur = cy + 190
    draw.text((w // 2, cur), title or "调价通知", font=get_font(75, True), fill=("#F5F7FB" if is_dark_style else "black"), anchor="mt")
    cur += 100
    draw.text((w // 2, cur), normalize_date_for_render(date_str), font=get_font(35), fill=("#B3BDC9" if is_dark_style else "gray"), anchor="mt")
    cur += 60
    draw.line([(cx + 50, cur), (cx + cw - 50, cur)], fill=(theme_unit if is_dark_style else "#F0F0F0"), width=3)
    cur += 40

    row_idx = 0

    def _draw_price_value_right(text, right_x, base_y, color):
        value = (text or "").strip()
        if not value:
            return
        has_cn = any("\u4e00" <= c <= "\u9fff" for c in value)
        m = re.search(r"\d+(?:\.\d+)?", value)
        if has_cn and m:
            cn_font = get_label_font(45)
            num_font = get_num_font(65)
            left_txt = value[:m.start()]
            num_txt = value[m.start():m.end()]
            right_txt = value[m.end():]
            x = right_x
            if right_txt:
                draw.text((x, base_y), right_txt, font=cn_font, fill=color, anchor="rs")
                x -= draw.textlength(right_txt, font=cn_font)
            draw.text((x, base_y), num_txt, font=num_font, fill=color, anchor="rs")
            x -= draw.textlength(num_txt, font=num_font)
            if left_txt:
                draw.text((x, base_y), left_txt, font=cn_font, fill=color, anchor="rs")
            return
        font = get_label_font(45) if has_cn else get_num_font(65)
        draw.text((right_x, base_y), value, font=font, fill=color, anchor="rs")
    
    for item in layout_items:
        if item["type"] == "space":
            cur += item["height"]
            continue
        
        if item["type"] == "kv":
            line = item["text"]
            row_idx = item["row_idx"]
            if row_idx % 2 == 0 and style != "aurora":
                draw.rectangle(
                    [(cx + 20, cur - 10), (cx + cw - 20, cur + 70)],
                    fill=((34, 40, 52, 215) if is_dark_style else (*row_bg_fixed, 255)),
                )
             
            k, v = line.replace("：", ":").split(":", 1)
            draw.text(
                (cx + 60, cur + 30),
                k.replace("【", "").replace("】", "").strip(),
                font=get_label_font(45),
                fill=("#DCE4EE" if is_dark_style else (48, 52, 58)),
                anchor="lm",
            )
             
            price_mode = str(cfg.get("price_color_mode", "semantic") or "semantic").lower()
            if price_mode == "semantic":
                if any(x in v for x in ["上调", "涨"]):
                    c_val = "#D32F2F"
                elif any(x in v for x in ["下调", "跌", "降"]):
                    c_val = "#2E7D32"
                else:
                    c_val = theme_hex
            else:
                c_val = theme_hex
             
            base_y, rx = cur + 53, cx + cw - 60
            if "元" in v:
                val_pt, unit_pt = v.split("元", 1)
                fu = get_font(30)
                if is_dark_style:
                    unit_color = "#AAB6C5" if c_val not in {"#D32F2F", "#2E7D32"} else c_val
                else:
                    unit_color = c_val if c_val in {"#D32F2F", "#2E7D32"} else theme_unit
                draw.text((rx, base_y), "元" + unit_pt.strip(), font=fu, fill=unit_color, anchor="rs")
                uw = draw.textlength("元" + unit_pt.strip(), font=fu)
                _draw_price_value_right(val_pt, rx - uw - 8, base_y, c_val)
            else:
                _draw_price_value_right(v, rx, base_y, c_val)
            cur += 85
            
        elif item["type"] == "text":
            is_note = item["is_note"]
            c = "#FFB347" if is_note else ("#AAB6C5" if is_dark_style else "#666")
            f = get_font(42, True) if is_note else get_font(38)
            lh = item["lh"]
            
            for subline in item["lines"]:
                draw.text((cx + 60, cur), subline, font=f, fill=c, anchor="lt")
                cur += lh

    fy = footer_start_y
    for x in range(cx + 40, cx + cw - 40, 20):
        draw.line([(x, fy), (x + 10, fy)], fill=("#7F8EA3" if is_dark_style else "#DDDDDD"), width=2)

    qr = _load_image(cfg.get("qrcode_image_path"))
    if qr:
        qr.thumbnail((260, 260))
        qx, qy = cx + 50, fy + 70
        mask = Image.new("L", qr.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), qr.size], radius=15, fill=255)
        img.paste(qr, (qx, qy), mask)
        rx = cx + cw - 60
        draw.text((rx, qy + 10), cfg.get("shop_name", ""), font=get_font(44, True), fill=("#F4F7FD" if is_dark_style else "#444"), anchor="rt")
        if cfg.get("phone"):
            draw.text((rx, qy + 95), f"电话：{cfg['phone']}", font=get_font(36), fill=("#AAB6C5" if is_dark_style else "#888"), anchor="rt")
        if cfg.get("address"):
            draw.text((rx, qy + 180), f"地址：{cfg['address']}", font=get_font(26), fill=("#AAB6C5" if is_dark_style else "#888"), anchor="rt")
        draw.text((w // 2, fy + 400), cfg.get("slogan", ""), font=get_font(35, True), fill=(theme_unit if is_dark_style else "#5CAF5F"), anchor="mm")
    else:
        cy2 = fy + 60
        draw.text((w // 2, cy2), cfg.get("shop_name", ""), font=get_font(42, True), fill=("#F4F7FD" if is_dark_style else "#444"), anchor="mm")
        cy2 += 80
        if cfg.get("phone"):
            draw.text((w // 2, cy2), f"电话：{cfg['phone']}", font=get_font(36), fill=("#AAB6C5" if is_dark_style else "#999"), anchor="mm")
        cy2 += 70
        if cfg.get("address"):
            draw.text((w // 2, cy2), f"地址：{cfg['address']}", font=get_font(28), fill=("#AAB6C5" if is_dark_style else "#999"), anchor="mm")
        draw.text((w // 2, cy2 + 100), cfg.get("slogan", ""), font=get_font(35, True), fill=(theme_unit if is_dark_style else "#5CAF5F"), anchor="mm")

    st = _load_image(cfg.get("stamp_image_path"))
    if st:
        st.thumbnail((260, 260))
        st.putalpha(ImageEnhance.Brightness(st.split()[3]).enhance(float(cfg.get("stamp_opacity", 0.85))))
        sx = cx + cw - st.width + 20 if qr else w // 2 - st.width // 2 + 150
        sy = fy + 160 if qr else fy + 30
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste(st, (sx, sy))
        img = Image.alpha_composite(img, layer)

    if cfg.get("watermark_enabled") and cfg.get("watermark_text"):
        img = _apply_watermark(
            img,
            cfg["watermark_text"],
            float(cfg.get("watermark_opacity", 0.15)),
            float(cfg.get("watermark_density", 1.0)),
        )
    return img


def load_config(path):
    if not os.path.exists(path):
        return deepcopy(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        out = deepcopy(DEFAULT_CONFIG)
        out.update(cfg)
        return out
    except Exception:
        LOGGER.exception("load_config.failed | %s", json.dumps({"path": path}, ensure_ascii=False, default=str))
        return deepcopy(DEFAULT_CONFIG)


def save_config(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write_json(path, cfg)


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
