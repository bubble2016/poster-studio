import datetime
import json
import os
import random
import re
import threading
from copy import deepcopy

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


CANVAS_SIZE = (1080, 1920)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _existing_path(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _candidate_cjk_fonts():
    local_regular = [
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Regular.otf"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-Regular.otf"),
    ]
    local_bold = [
        os.path.join(BASE_DIR, "fonts", "SourceHanSansSC-Bold.otf"),
        os.path.join(BASE_DIR, "fonts", "NotoSansSC-Bold.otf"),
    ]

    if os.name == "nt":
        win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        return {
            "regular": local_regular + [
                os.path.join(win, "msyh.ttc"),
                os.path.join(win, "msyh.ttf"),
                os.path.join(win, "simsun.ttc"),
                os.path.join(win, "simhei.ttf"),
                os.path.join(win, "simfang.ttf"),
            ],
            "bold": local_bold + [
                os.path.join(win, "msyhbd.ttc"),
                os.path.join(win, "msyhbd.ttf"),
                os.path.join(win, "simhei.ttf"),
                os.path.join(win, "msyh.ttc"),
            ],
        }
    if os.name == "posix":
        return {
            "regular": local_regular + [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/arphic/uming.ttc",
                "/System/Library/Fonts/PingFang.ttc",
            ],
            "bold": local_bold + [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/System/Library/Fonts/PingFang.ttc",
            ],
        }
    return {"regular": local_regular, "bold": local_bold}


_font_candidates = _candidate_cjk_fonts()
FONT_CN_REG = _existing_path([os.getenv("POSTER_FONT_CN_REG", "")] + _font_candidates["regular"])
FONT_CN_BOLD = _existing_path([os.getenv("POSTER_FONT_CN_BOLD", "")] + _font_candidates["bold"] + _font_candidates["regular"])
FONT_NUM = _existing_path([os.getenv("POSTER_FONT_NUM", ""), FONT_CN_BOLD, FONT_CN_REG])
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
DEFAULT_CONFIG = {
    "shop_name": "云泽西关打包站",
    "shop_name_hist": ["云泽西关打包站"],
    "address": "古城区中山大道六和辅路东侧100米院内",
    "address_hist": ["古城区中山大道六和辅路东侧100米院内"],
    "phone": "13826495317",
    "phone_hist": ["13826495317"],
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
    "card_style": "fold",
    "theme_color": "#B22222",
    "copy_mode": "复制图片",
    "last_content": "",
    "last_date": "",
    "last_title": "调价通知",
    "custom_templates": {},
    "export_format": "PNG",
    "jpeg_quality": 95,
    "watermark_enabled": False,
    "watermark_text": "仅供客户参考",
    "watermark_opacity": 0.15,
}


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
    def gen_mountain_morning():
        w, h = CANVAS_SIZE
        sky_top = (218, 238, 255)
        sky_bottom = (240, 249, 255)
        img = Image.new("RGB", (w, h), sky_top)
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(sky_top[0] + (sky_bottom[0] - sky_top[0]) * t)
            g = int(sky_top[1] + (sky_bottom[1] - sky_top[1]) * t)
            b = int(sky_top[2] + (sky_bottom[2] - sky_top[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        mist = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        md = ImageDraw.Draw(mist)
        layers = [
            (h * 0.56, (162, 188, 214, 120), 220),
            (h * 0.67, (141, 172, 199, 140), 260),
            (h * 0.78, (122, 155, 184, 155), 320),
        ]
        for y_base, color, amp in layers:
            points = [(0, int(y_base))]
            for x in range(0, w + 120, 120):
                y = int(y_base + random.randint(-amp // 12, amp // 12))
                points.append((x, y))
            points += [(w, h), (0, h)]
            md.polygon(points, fill=color)

        for _ in range(12):
            x = random.randint(-60, w + 60)
            y = random.randint(int(h * 0.18), int(h * 0.68))
            r = random.randint(120, 240)
            md.ellipse((x - r, y - r // 2, x + r, y + r // 2), fill=(255, 255, 255, random.randint(22, 45)))

        mist = mist.filter(ImageFilter.GaussianBlur(18))
        img = Image.alpha_composite(img.convert("RGBA"), mist).convert("RGB")
        return PresetGenerator._add_noise(img, 0.03)

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
    def gen_obsidian_grid():
        w, h = CANVAS_SIZE
        img = Image.new("RGB", (w, h), "#12161F")
        noise = Image.effect_noise((w, h), 28).convert("RGB")
        img = ImageChops.blend(img, noise, 0.12)

        grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grid)
        line_color = (155, 174, 204, 30)
        for x in range(0, w, 72):
            gd.line([(x, 0), (x, h)], fill=line_color, width=1)
        for y in range(0, h, 72):
            gd.line([(0, y), (w, y)], fill=line_color, width=1)
        for _ in range(6):
            x = random.randint(100, w - 100)
            y = random.randint(120, h - 120)
            r = random.randint(110, 220)
            gd.ellipse((x - r, y - r, x + r, y + r), outline=(110, 132, 170, 34), width=2)
        grid = grid.filter(ImageFilter.GaussianBlur(1))
        img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")
        return PresetGenerator._add_noise(img, 0.025)

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
            ("preset_obsidian_grid.png", "曜石网格黑", PresetGenerator.gen_obsidian_grid),
            ("preset_mountain_morning.png", "山岚晨光", PresetGenerator.gen_mountain_morning),
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
        elif price < 100:
            warnings.append(f"价格 {price} 元可能过低")
        elif price > 9999:
            warnings.append(f"价格 {price} 元可能过高")
    return len(warnings) == 0, warnings


def batch_adjust_content(content, amount):
    txt = content or ""

    def repl_range(m):
        p1, p2 = int(m.group(1)), int(m.group(2))
        return f"{max(0, p1 + amount)}-{max(0, p2 + amount)}"

    txt = re.sub(r"(\d{3,5})-(\d{3,5})(?=\s*鍏?", repl_range, txt)
    txt = re.sub(r"(涓婅皟|涓嬭皟)(\d{1,5})(?=\s*鍏?", lambda _: f"{'涓婅皟' if amount >= 0 else '涓嬭皟'}{abs(amount)}", txt)
    txt = re.sub(r"(\d{3,5})(?=\s*鍏?", lambda m: str(max(0, int(m.group(1)) + amount)), txt)
    return txt.strip()


def _load_image(path):
    if path and os.path.exists(path):
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None
    return None


def _apply_watermark(img, text, opacity=0.15):
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = FontManager.get(FONT_CN_REG, 48)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    sx, sy = tw + 150, th + 120
    color = (128, 128, 128, int(255 * opacity))
    offset = 0
    for y in range(-h, h * 2, sy):
        offset += sx // 2
        for x in range(-w + (offset % sx), w * 2, sx):
            draw.text((x, y), text, font=font, fill=color)
    layer = layer.rotate(30, center=(w // 2, h // 2), resample=Image.BICUBIC)
    return Image.alpha_composite(img, layer)


def draw_poster(content, date_str, title, cfg):
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    content = normalize_content_for_render(content or "")
    w, h = CANVAS_SIZE

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
    get_num_font = lambda size: FontManager.get(FONT_NUM, size)
    cw = 920
    cx = (w - cw) // 2
    lines = (content or "").split("\n")
    is_holiday_mode = "放假" in (title or "")
    sim_y, row_idx = 0, 0
    td = ImageDraw.Draw(Image.new("L", (1, 1)))
    for line in lines:
        line = line.strip()
        if not line:
            sim_y += 40 if is_holiday_mode else 10
            continue
        is_note = any(k in line for k in ["注", "要求", "提示"])
        if (("：" in line or ":" in line) and not is_note and not is_holiday_mode):
            sim_y += 85
            row_idx += 1
        else:
            if row_idx > 0:
                sim_y += 20
                row_idx = 0
            f = get_font(42, True) if is_note else get_font(38)
            lh = 65 if (is_note or is_holiday_mode) else 55
            chars, start = list(line), 0
            while start < len(chars):
                est_len = int((cw - 120) / (42 if is_note else 38))
                end = min(len(chars), start + est_len + 5)
                while end > start and td.textlength("".join(chars[start:end]), font=f) > (cw - 120):
                    end -= 1
                if end == start:
                    end += 1
                sim_y += lh
                start = end

    ch = min(1800, max(900, 500 + sim_y - 10 + 460))
    cy = (h - ch) // 2
    footer_start_y = cy + 500 + sim_y - 10

    style = cfg.get("card_style", "fold")
    alpha = int(float(cfg.get("card_opacity", 1.0)) * 255)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dc = ImageDraw.Draw(card)
    if style == "ticket":
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=20, fill=(255, 255, 255, alpha))
        dc.ellipse((cx - 10, cy + ch // 2 - 10, cx + 10, cy + ch // 2 + 10), fill=(0, 0, 0, 0))
        dc.ellipse((cx + cw - 10, cy + ch // 2 - 10, cx + cw + 10, cy + ch // 2 + 10), fill=(0, 0, 0, 0))
    elif style == "double":
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([(cx + 18, cy + 24), (cx + cw + 18, cy + ch + 24)], radius=42, fill=(0, 0, 0, 60))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(20)))
        dc.rounded_rectangle([(cx + 20, cy + 20), (cx + cw + 20, cy + ch + 20)], radius=40, fill=(235, 235, 235, alpha))
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
    elif style == "sidebar":
        dc.rectangle([(cx, cy), (cx + cw, cy + ch)], fill=(255, 255, 255, alpha))
        dc.rectangle([(cx, cy), (cx + 25, cy + ch)], fill=cfg.get("theme_color", "#B22222"))
    elif style == "block":
        for i in range(12, 0, -1):
            ImageDraw.Draw(card).rounded_rectangle([(cx + i, cy + i), (cx + cw + i, cy + ch + i)], radius=40, fill=(230, 230, 230, alpha))
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
    elif style == "stack":
        dc.rounded_rectangle([(cx + 12, cy + 22), (cx + cw - 12, cy + ch + 22)], radius=35, fill=(245, 245, 245, alpha))
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
    elif style == "flip":
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=40, fill=(255, 255, 255, alpha))
        fs = 200
        dc.polygon([(cx + cw, cy + ch), (cx + cw, cy + ch - fs), (cx + cw - fs, cy + ch)], fill=(240, 240, 240, 255))
    else:
        dc.rounded_rectangle([(cx, cy), (cx + cw, cy + ch)], radius=15, fill=(255, 255, 255, alpha))
    img = Image.alpha_composite(img, card)
    draw = ImageDraw.Draw(img)

    logo = _load_image(cfg.get("logo_image_path"))
    if logo:
        logo = ImageOps.fit(logo, (180, 180), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (180, 180), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 180, 180), fill=255)
        ly, lx = cy + 60, (w - 180) // 2
        draw.ellipse((lx - 5, int(ly - 90) - 5, lx + 185, int(ly + 90) + 5), fill="white")
        img.paste(logo, (lx, int(ly - 90)), mask)

    cur = cy + 190
    draw.text((w // 2, cur), title or "调价通知", font=get_font(75, True), fill="black", anchor="mt")
    cur += 100
    draw.text((w // 2, cur), date_str or datetime.datetime.now().strftime("%Y年%m月%d日"), font=get_font(35), fill="gray", anchor="mt")
    cur += 60
    draw.line([(cx + 50, cur), (cx + cw - 50, cur)], fill="#F0F0F0", width=3)
    cur += 40

    row_idx = 0
    theme_c = cfg.get("theme_color", "#B22222")
    for line in lines:
        line = line.strip()
        if not line:
            cur += 40 if is_holiday_mode else 10
            continue
        is_note = any(k in line for k in ["注", "要求", "提示"])
        if (("：" in line or ":" in line) and not is_note and not is_holiday_mode):
            if row_idx % 2 == 0:
                draw.rectangle([(cx + 20, cur - 10), (cx + cw - 20, cur + 70)], fill="#F9F9F9")
            k, v = line.replace("：", ":").split(":", 1)
            draw.text((cx + 60, cur + 30), k.replace("【", "").replace("】", "").strip(), font=get_font(45, True), fill="#333", anchor="lm")
            c_val = "#D32F2F" if any(x in v for x in ["上调", "涨"]) else "#2E7D32" if any(x in v for x in ["下调", "跌", "降"]) else theme_c
            base_y, rx = cur + 53, cx + cw - 60
            if "元" in v:
                val_pt, unit_pt = v.split("元", 1)
                fu = get_font(30)
                draw.text((rx, base_y), "元" + unit_pt.strip(), font=fu, fill=c_val, anchor="rs")
                uw = draw.textlength("元" + unit_pt.strip(), font=fu)
                fv = get_num_font(65)
                if any("\u4e00" <= c <= "\u9fff" for c in val_pt):
                    fv = get_font(60)
                draw.text((rx - uw - 8, base_y), val_pt.strip(), font=fv, fill=c_val, anchor="rs")
            else:
                fv = get_num_font(65)
                draw.text((rx, base_y), v.strip(), font=fv, fill=c_val, anchor="rs")
            cur += 85
            row_idx += 1
        else:
            if row_idx > 0:
                cur += 20
                row_idx = 0
            c = "#E65100" if is_note else "#666"
            f = get_font(42, True) if is_note else get_font(38)
            lh = 65 if (is_note or is_holiday_mode) else 55
            chars, start = list(line), 0
            while start < len(chars):
                est_len = int((cw - 120) / (42 if is_note else 38))
                end = min(len(chars), start + est_len + 5)
                while end > start and draw.textlength("".join(chars[start:end]), font=f) > (cw - 120):
                    end -= 1
                if end == start:
                    end += 1
                draw.text((cx + 60, cur), "".join(chars[start:end]), font=f, fill=c, anchor="lt")
                cur += lh
                start = end

    fy = footer_start_y
    for x in range(cx + 40, cx + cw - 40, 20):
        draw.line([(x, fy), (x + 10, fy)], fill="#DDDDDD", width=2)

    qr = _load_image(cfg.get("qrcode_image_path"))
    if qr:
        qr.thumbnail((260, 260))
        qx, qy = cx + 50, fy + 70
        mask = Image.new("L", qr.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([(0, 0), qr.size], radius=15, fill=255)
        img.paste(qr, (qx, qy), mask)
        rx = cx + cw - 60
        draw.text((rx, qy + 10), cfg.get("shop_name", ""), font=get_font(42, True), fill="#444", anchor="rt")
        if cfg.get("phone"):
            draw.text((rx, qy + 95), f"电话：{cfg['phone']}", font=get_font(36), fill="#888", anchor="rt")
        if cfg.get("address"):
            draw.text((rx, qy + 180), f"地址：{cfg['address']}", font=get_font(26), fill="#888", anchor="rt")
        draw.text((w // 2, fy + 400), cfg.get("slogan", ""), font=get_font(35, True), fill="#5CAF5F", anchor="mm")
    else:
        cy2 = fy + 60
        draw.text((w // 2, cy2), cfg.get("shop_name", ""), font=get_font(40, True), fill="#444", anchor="mm")
        cy2 += 80
        if cfg.get("phone"):
            draw.text((w // 2, cy2), f"电话：{cfg['phone']}", font=get_font(36), fill="#999", anchor="mm")
        cy2 += 70
        if cfg.get("address"):
            draw.text((w // 2, cy2), f"地址：{cfg['address']}", font=get_font(28), fill="#999", anchor="mm")
        draw.text((w // 2, cy2 + 100), cfg.get("slogan", ""), font=get_font(35, True), fill="#5CAF5F", anchor="mm")

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
        img = _apply_watermark(img, cfg["watermark_text"], float(cfg.get("watermark_opacity", 0.15)))
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
        return deepcopy(DEFAULT_CONFIG)


def save_config(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
