(function () {
  "use strict";

  const CANVAS_WIDTH = 1080;
  const CANVAS_HEIGHT = 1920;
  const CLIENT_RENDER_DISABLE_KEY = "poster_client_render_disabled_v1";
  const FONT_ASSET_VERSION = "20260513v2";
  const FONT_REGULAR = "PosterCNSans";
  const FONT_BOLD = "PosterCNSansBold";
  const FONT_NUMBER = "PosterNumber";
  const FONT_LXGW_WENKAI = "PosterLXGWWenKai";
  const FONT_LXGW_WENKAI_BOLD = "PosterLXGWWenKaiBold";
  const FONT_PRESETS = Object.freeze({
    source_han_sans: { regular: FONT_REGULAR, bold: FONT_BOLD },
    lxgw_wenkai: { regular: FONT_LXGW_WENKAI, bold: FONT_LXGW_WENKAI_BOLD },
  });
  const PRICE_UNIT_DEFAULT = "元/吨";
  const loadedImageCache = new Map();
  const fontPromises = new Map();

  const DEFAULT_CONFIG = {
    shop_name: "环太平洋废纸回收打包站",
    address: "太平洋基里巴斯群岛101街区",
    phone: "1234567890",
    slogan: "诚信经营 · 现金结算 · 假货勿扰",
    bg_image_path: "",
    bg_mode: "custom",
    logo_image_path: "",
    qrcode_image_path: "",
    stamp_image_path: "",
    stamp_opacity: 0.85,
    bg_blur_radius: 30,
    bg_brightness: 1.0,
    card_opacity: 1.0,
    card_style: "single",
    theme_color: "#B22222",
    price_color_mode: "semantic",
    price_style: "amethyst",
    font_preset: "source_han_sans",
    batch_adjust_note_mode: "none",
    watermark_enabled: false,
    watermark_text: "仅供客户参考",
    watermark_opacity: 0.15,
    watermark_density: 1.0,
    holiday_text_style: "festive",
    last_template: "",
  };

  function isEnabled() {
    try {
      return localStorage.getItem(CLIENT_RENDER_DISABLE_KEY) !== "1";
    } catch (_) {
      return true;
    }
  }

  function toAssetUrl(path) {
    if (!path) return "";
    if (/^(data:|blob:|https?:\/\/)/i.test(path)) return path;
    return `/asset/${String(path).split("/").map((seg) => encodeURIComponent(seg)).join("/")}`;
  }

  function normalizeHexColor(value, fallback = "#B22222") {
    const text = String(value || "").trim();
    return /^#[0-9a-fA-F]{6}$/.test(text) ? text.toUpperCase() : fallback;
  }

  function hexToRgb(hex, fallback = [178, 34, 34]) {
    const value = normalizeHexColor(hex, `#${fallback.map((x) => x.toString(16).padStart(2, "0")).join("")}`);
    return [parseInt(value.slice(1, 3), 16), parseInt(value.slice(3, 5), 16), parseInt(value.slice(5, 7), 16)];
  }

  function mixWithWhite(rgb, ratio) {
    const t = Math.max(0, Math.min(1, Number(ratio) || 0));
    return rgb.map((x) => Math.round(x + (255 - x) * t));
  }

  function rgba(rgb, alpha = 1) {
    return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${Math.max(0, Math.min(1, alpha))})`;
  }

  function font(size, weight = "regular", family = "") {
    const fam = family || (weight === "number" ? FONT_NUMBER : weight === "bold" ? FONT_BOLD : FONT_REGULAR);
    return `${Math.round(size)}px "${fam}", "Microsoft YaHei", "Noto Sans SC", sans-serif`;
  }

  function normalizeFontPreset(value) {
    const key = String(value || "").trim().toLowerCase();
    if (!key || key === "default") return DEFAULT_CONFIG.font_preset;
    return Object.prototype.hasOwnProperty.call(FONT_PRESETS, key) ? key : DEFAULT_CONFIG.font_preset;
  }

  function fontForPreset(value) {
    const preset = FONT_PRESETS[normalizeFontPreset(value)] || FONT_PRESETS.source_han_sans;
    return (size, weight = "regular", family = "") => {
      const fam = family || (weight === "number" ? FONT_NUMBER : weight === "bold" ? preset.bold : preset.regular);
      return font(size, "regular", fam);
    };
  }

  async function loadFontFace(name, url, descriptors) {
    if (!("FontFace" in window)) return false;
    const face = new FontFace(name, `url("${url}")`, descriptors || {});
    const loaded = await face.load();
    document.fonts.add(loaded);
    return true;
  }

  function fontUrl(filename) {
    return `/font/${filename}?v=${FONT_ASSET_VERSION}`;
  }

  function getFontFaceLoads(presetValue) {
    const preset = normalizeFontPreset(presetValue);
    const common = [loadFontFace(FONT_NUMBER, fontUrl("Bahnschrift.ttf"))];
    if (preset === "lxgw_wenkai") {
      return common.concat([
        loadFontFace(FONT_LXGW_WENKAI, fontUrl("LXGWWenKai-Regular.ttf")),
        loadFontFace(FONT_LXGW_WENKAI_BOLD, fontUrl("LXGWWenKai-Medium.ttf")),
      ]);
    }
    return common.concat([
      loadFontFace(FONT_REGULAR, fontUrl("SourceHanSansSC-Regular.otf")),
      loadFontFace(FONT_BOLD, fontUrl("SourceHanSansSC-Bold.otf"), { weight: "700" }),
    ]);
  }

  async function ensureFonts(presetValue) {
    const preset = normalizeFontPreset(presetValue);
    if (fontPromises.has(preset)) return fontPromises.get(preset);
    const promise = Promise.all(getFontFaceLoads(preset)).then(async () => {
      if (document.fonts?.ready) await document.fonts.ready;
      return true;
    });
    fontPromises.set(preset, promise);
    return promise;
  }

  function loadImage(path) {
    const url = toAssetUrl(path);
    if (!url) return Promise.resolve(null);
    if (loadedImageCache.has(url)) return loadedImageCache.get(url);
    const promise = new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error(`图片加载失败：${url}`));
      img.src = url;
    });
    loadedImageCache.set(url, promise);
    return promise;
  }

  function normalizeContentForRender(content) {
    return String(content || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  }

  function normalizeDateForRender(dateStr) {
    const text = String(dateStr || "").trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return text;
    return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`;
  }

  function usesTextNoticeLayout(title, cfg) {
    const template = String(cfg.last_template || "").trim();
    if (template === "放假模板" || template === "文字模版" || template === "调价说明模板") return true;
    return String(title || "").includes("放假");
  }

  function drawRoundedRect(ctx, x, y, w, h, r) {
    const radius = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + w - radius, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
    ctx.lineTo(x + w, y + h - radius);
    ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
    ctx.lineTo(x + radius, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  function fillRoundedRect(ctx, x, y, w, h, r, fillStyle) {
    ctx.save();
    drawRoundedRect(ctx, x, y, w, h, r);
    ctx.fillStyle = fillStyle;
    ctx.fill();
    ctx.restore();
  }

  function strokeRoundedRect(ctx, x, y, w, h, r, strokeStyle, lineWidth = 1) {
    ctx.save();
    drawRoundedRect(ctx, x, y, w, h, r);
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = lineWidth;
    ctx.stroke();
    ctx.restore();
  }

  function drawCoverImage(ctx, image, x, y, w, h) {
    const ratio = Math.max(w / image.naturalWidth, h / image.naturalHeight);
    const nw = image.naturalWidth * ratio;
    const nh = image.naturalHeight * ratio;
    ctx.drawImage(image, x + (w - nw) / 2, y + (h - nh) / 2, nw, nh);
  }

  function drawBackground(ctx, bg, cfg) {
    if (bg) {
      ctx.save();
      const blur = Math.max(0, Number(cfg.bg_blur_radius || 0));
      const brightness = Math.max(0.2, Math.min(3, Number(cfg.bg_brightness || 1)));
      ctx.filter = `blur(${blur}px) brightness(${brightness})`;
      if (cfg.bg_mode === "preset") {
        ctx.drawImage(bg, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      } else {
        drawCoverImage(ctx, bg, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      }
      ctx.restore();
      return;
    }
    ctx.fillStyle = "#E0E0E0";
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
  }

  function measureTextWidth(ctx, text, fontCss) {
    ctx.save();
    ctx.font = fontCss;
    const width = ctx.measureText(String(text || "")).width;
    ctx.restore();
    return width;
  }

  function wrapLine(ctx, text, maxWidth, fontCss) {
    const chars = Array.from(String(text || ""));
    const lines = [];
    let current = "";
    ctx.save();
    ctx.font = fontCss;
    chars.forEach((ch) => {
      const next = current + ch;
      if (current && ctx.measureText(next).width > maxWidth) {
        lines.push(current);
        current = ch;
      } else {
        current = next;
      }
    });
    if (current) lines.push(current);
    ctx.restore();
    return lines.length ? lines : [""];
  }

  function calculateLayout(ctx, lines, cw, isNotice, posterFont) {
    const layout = [];
    let total = 0;
    let rowIdx = 0;
    lines.forEach((raw) => {
      const line = String(raw || "").trim();
      if (!line) {
        const height = isNotice ? 54 : 10;
        layout.push({ type: "space", height });
        total += height;
        return;
      }
      const norm = line.replace(/\s+/g, "");
      const isNote = /^温馨提示[:：]?$/.test(norm);
      if ((line.includes("：") || line.includes(":")) && !isNote && !isNotice) {
        layout.push({ type: "kv", text: line, height: 85, rowIdx });
        total += 85;
        rowIdx += 1;
        return;
      }
      if (rowIdx > 0) {
        layout.push({ type: "space", height: 20 });
        total += 20;
        rowIdx = 0;
      }
      const isSalutation = isNotice && /^(尊敬的|亲爱的|各位|您好)/.test(line);
      const isBlessing = isNotice && line.includes("祝") && (line.includes("快乐") || line.includes("幸福") || line.includes("兴隆"));
      const size = isNote ? 42 : isNotice ? 43 : 38;
      const lineHeight = isNote ? 65 : isNotice ? 74 : 55;
      const fontCss = posterFont(size, isNote || isSalutation || isBlessing ? "bold" : "regular");
      const maxWidth = isNotice ? cw - 180 : cw - 120;
      const wrapped = wrapLine(ctx, line, maxWidth, fontCss);
      const height = wrapped.length * lineHeight;
      layout.push({ type: "text", lines: wrapped, height, lineHeight, isNote, isSalutation, isBlessing, isNotice });
      total += height;
    });
    return { layout, total };
  }

  function drawCard(ctx, cfg, cx, cy, cw, ch, themeRgb) {
    const alpha = Math.max(0.05, Math.min(1, Number(cfg.card_opacity ?? 1)));
    const style = String(cfg.card_style || "single");
    const cardRadius = style === "ticket" ? 28 : 40;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.22)";
    ctx.shadowBlur = style === "aurora" ? 24 : 18;
    ctx.shadowOffsetX = 10;
    ctx.shadowOffsetY = 14;

    if (style === "stack") {
      fillRoundedRect(ctx, cx - 24, cy + 34, cw, ch, 40, `rgba(234,238,244,${Math.min(1, alpha * 0.95)})`);
      strokeRoundedRect(ctx, cx - 24, cy + 34, cw, ch, 40, `rgba(198,208,222,${alpha})`, 2);
    } else if (style === "double") {
      fillRoundedRect(ctx, cx + 30, cy + 34, cw, ch, 40, `rgba(232,236,243,${Math.min(1, alpha * 0.95)})`);
      strokeRoundedRect(ctx, cx + 30, cy + 34, cw, ch, 40, `rgba(201,210,224,${alpha})`, 2);
    } else if (style === "block") {
      for (let i = 12; i > 0; i -= 1) {
        fillRoundedRect(ctx, cx + i, cy + i, cw, ch, 40, `rgba(230,230,230,${alpha})`);
      }
    }

    const fill = style === "aurora" ? `rgba(242,248,255,${Math.min(0.86, alpha)})` : `rgba(255,255,255,${alpha})`;
    fillRoundedRect(ctx, cx, cy, cw, ch, cardRadius, fill);
    ctx.shadowColor = "transparent";

    if (style === "ticket") {
      strokeRoundedRect(ctx, cx, cy, cw, ch, 28, `rgba(214,202,184,${alpha})`, 3);
      ctx.save();
      ctx.strokeStyle = "rgba(186,174,156,0.9)";
      ctx.setLineDash([16, 10]);
      ctx.lineWidth = 2;
      const tearY = Math.max(cy + 240, Math.min(cy + ch - 260, cy + 500 + 18));
      ctx.beginPath();
      ctx.moveTo(cx + 48, tearY);
      ctx.lineTo(cx + cw - 48, tearY);
      ctx.stroke();
      ctx.restore();
    } else if (style === "flip") {
      const fs = 216;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(cx + cw, cy + ch);
      ctx.lineTo(cx + cw, cy + ch - fs);
      ctx.lineTo(cx + cw - fs, cy + ch);
      ctx.closePath();
      ctx.fillStyle = "rgba(222,224,228,0.92)";
      ctx.fill();
      ctx.strokeStyle = "rgba(184,188,196,0.9)";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    } else if (style === "aurora") {
      strokeRoundedRect(ctx, cx + 8, cy + 8, cw - 16, ch - 16, 36, "rgba(184,196,210,0.6)", 2);
      strokeRoundedRect(ctx, cx + 22, cy + 20, cw - 44, Math.max(80, ch * 0.32), 24, "rgba(255,255,255,0.38)", 1);
    } else if (style === "paper_relief") {
      strokeRoundedRect(ctx, cx + 8, cy + 8, cw - 16, ch - 16, 34, rgba(themeRgb, 0.45), 2);
      strokeRoundedRect(ctx, cx + 18, cy + 18, cw - 36, Math.max(80, ch * 0.32), 24, "rgba(255,255,255,0.45)", 1);
    } else {
      strokeRoundedRect(ctx, cx, cy, cw, ch, cardRadius, "rgba(238,241,247,0.95)", 2);
    }
    ctx.restore();
  }

  function drawCircleImage(ctx, image, x, y, size) {
    if (!image) return;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x + size / 2, y + size / 2, size / 2, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    drawCoverImage(ctx, image, x, y, size, size);
    ctx.restore();
  }

  function splitPriceUnit(value) {
    const text = String(value || "").trim();
    const match = text.match(/\s*(元\s*\/\s*吨|\/\s*吨|[^\d\s（）()]+(?:\s*\/\s*[^\d\s（）()]+)*)\s*$/);
    if (!match) return { value: text, unit: "" };
    return { value: text.slice(0, match.index).trim(), unit: match[1].replace(/\s+/g, "") };
  }

  function stripAdjustNote(text) {
    return String(text || "").replace(/\s*[（(](上调|下调|↑|↓)\s*(\d{1,5})\s*(?:元)?[)）]\s*/g, "");
  }

  function drawPriceValueRight(ctx, text, rightX, baseY, color, posterFont) {
    const segments = String(text || "").trim().match(/\d+(?:\.\d+)?|[^\d]+/g) || [];
    let x = rightX;
    for (let i = segments.length - 1; i >= 0; i -= 1) {
      const seg = segments[i];
      const isNumber = /^\d+(?:\.\d+)?$/.test(seg);
      ctx.font = isNumber ? posterFont(65, "number") : posterFont(45, "regular");
      ctx.fillStyle = color;
      ctx.textAlign = "right";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(seg, x, baseY);
      x -= ctx.measureText(seg).width;
    }
  }

  function drawWatermark(ctx, cfg, posterFont) {
    if (!cfg.watermark_enabled || !cfg.watermark_text) return;
    const text = String(cfg.watermark_text || "");
    const opacity = Math.max(0, Math.min(0.8, Number(cfg.watermark_opacity || 0.15)));
    const density = Math.max(0.5, Math.min(2, Number(cfg.watermark_density || 1)));
    ctx.save();
    ctx.translate(CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2);
    ctx.rotate((30 * Math.PI) / 180);
    ctx.font = posterFont(48, "regular");
    ctx.fillStyle = `rgba(128,128,128,${opacity})`;
    const width = ctx.measureText(text).width;
    const sx = Math.max(width + 36, (width + 150) / density);
    const sy = Math.max(76, 170 / density);
    for (let y = -CANVAS_HEIGHT * 1.2; y < CANVAS_HEIGHT * 1.2; y += sy) {
      for (let x = -CANVAS_WIDTH * 1.2; x < CANVAS_WIDTH * 1.2; x += sx) {
        ctx.fillText(text, x, y);
      }
    }
    ctx.restore();
  }

  function canvasToBlob(canvas, mimeType, quality) {
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("浏览器导出图片失败"));
      }, mimeType, quality);
    });
  }

  async function renderToCanvas(payload) {
    if (!isEnabled()) throw new Error("浏览器端渲染已关闭");
    if (!document.createElement("canvas").getContext) throw new Error("当前浏览器不支持 Canvas");

    const cfg = { ...DEFAULT_CONFIG, ...(payload?.config || {}) };
    await ensureFonts(cfg.font_preset);
    const posterFont = fontForPreset(cfg.font_preset);
    const title = String(payload?.title || "调价通知");
    const date = String(payload?.date || "");
    const content = normalizeContentForRender(payload?.content || "");
    const [bg, logo, qr, stamp] = await Promise.all([
      loadImage(cfg.bg_image_path),
      loadImage(cfg.logo_image_path),
      loadImage(cfg.qrcode_image_path),
      loadImage(cfg.stamp_image_path),
    ]);

    const canvas = document.createElement("canvas");
    canvas.width = CANVAS_WIDTH;
    canvas.height = CANVAS_HEIGHT;
    const ctx = canvas.getContext("2d");
    drawBackground(ctx, bg, cfg);

    const themeHex = normalizeHexColor(cfg.theme_color);
    const themeRgb = hexToRgb(themeHex);
    const themeUnitRgb = mixWithWhite(themeRgb, 0.62);
    const cw = 920;
    const cx = (CANVAS_WIDTH - cw) / 2;
    const lines = content.split("\n");
    const isNotice = usesTextNoticeLayout(title, cfg);
    const calculated = calculateLayout(ctx, lines, cw, isNotice, posterFont);
    const ch = Math.min(1800, Math.max(900, 500 + calculated.total - 10 + 460));
    const cy = (CANVAS_HEIGHT - ch) / 2;
    const footerStartY = cy + 500 + calculated.total - 10;

    drawCard(ctx, cfg, cx, cy, cw, ch, themeRgb);

    if (logo) {
      const logoSize = 220;
      const lx = (CANVAS_WIDTH - logoSize) / 2;
      const ly = cy + 60 - logoSize / 2;
      ctx.save();
      ctx.fillStyle = "white";
      ctx.beginPath();
      ctx.arc(CANVAS_WIDTH / 2, cy + 60, logoSize / 2 + 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      drawCircleImage(ctx, logo, lx, ly, logoSize);
    }

    let cur = cy + 190;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = isNotice ? "#8F1D1D" : "#000000";
    ctx.font = posterFont(isNotice ? 81 : 75, "bold");
    ctx.fillText(title || "调价通知", CANVAS_WIDTH / 2, cur);
    cur += 100;
    ctx.fillStyle = isNotice ? "#A16262" : "gray";
    ctx.font = posterFont(35);
    ctx.fillText(normalizeDateForRender(date), CANVAS_WIDTH / 2, cur);
    cur += 60;
    ctx.strokeStyle = isNotice ? "#EFCACA" : "#F0F0F0";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx + 50, cur);
    ctx.lineTo(cx + cw - 50, cur);
    ctx.stroke();
    cur += isNotice ? 50 : 46;

    calculated.layout.forEach((item) => {
      if (item.type === "space") {
        cur += item.height;
        return;
      }

      if (item.type === "kv") {
        if (item.rowIdx % 2 === 0 && cfg.card_style !== "aurora") {
          ctx.fillStyle = "rgba(249,249,249,1)";
          ctx.fillRect(cx + 20, cur - 10, cw - 40, 80);
        }
        const parts = item.text.replace("：", ":").split(":");
        const key = parts.shift().replace(/[【】]/g, "").trim();
        const rawValue = parts.join(":");
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.font = posterFont(45);
        ctx.fillStyle = "rgb(48,52,58)";
        ctx.fillText(key, cx + 60, cur + 30);

        const priceMode = String(cfg.price_color_mode || "semantic").toLowerCase();
        let valueColor = themeHex;
        if (priceMode === "semantic") {
          if (/[上调涨]/.test(rawValue)) valueColor = "#D32F2F";
          else if (/[下调跌降]/.test(rawValue)) valueColor = "#2E7D32";
        }
        const displayValue = String(cfg.batch_adjust_note_mode || "none") === "none" ? stripAdjustNote(rawValue).trim() : rawValue.trim();
        const split = splitPriceUnit(displayValue);
        const baseY = cur + 53;
        const rx = cx + cw - 60;
        if (split.unit) {
          ctx.font = posterFont(30);
          ctx.fillStyle = valueColor === themeHex ? rgba(themeUnitRgb, 1) : valueColor;
          ctx.textAlign = "right";
          ctx.textBaseline = "alphabetic";
          ctx.fillText(split.unit === "/吨" ? PRICE_UNIT_DEFAULT : split.unit, rx, baseY);
          const unitWidth = measureTextWidth(ctx, split.unit === "/吨" ? PRICE_UNIT_DEFAULT : split.unit, posterFont(30));
          drawPriceValueRight(ctx, split.value, rx - unitWidth - 8, baseY, valueColor, posterFont);
        } else {
          drawPriceValueRight(ctx, displayValue, rx, baseY, valueColor, posterFont);
        }
        cur += 85;
        return;
      }

      if (item.type === "text") {
        let color = "#666666";
        let weight = "regular";
        let size = 38;
        if (item.isNote) {
          color = "#FFB347";
          weight = "bold";
          size = 42;
        } else if (isNotice) {
          if (item.isSalutation) {
            color = "#7A1E1E";
            weight = "bold";
          } else if (item.isBlessing) {
            color = "#B45309";
            weight = "bold";
          } else {
            color = "#6B3E3E";
          }
          size = 43;
        }
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.font = posterFont(size, weight);
        ctx.fillStyle = color;
        item.lines.forEach((line) => {
          ctx.fillText(line, cx + 60, cur);
          cur += item.lineHeight;
        });
        if (isNotice && !item.isNote) cur += 6;
      }
    });

    ctx.save();
    ctx.strokeStyle = "#DDDDDD";
    ctx.lineWidth = 2;
    for (let x = cx + 40; x < cx + cw - 40; x += 20) {
      ctx.beginPath();
      ctx.moveTo(x, footerStartY);
      ctx.lineTo(x + 10, footerStartY);
      ctx.stroke();
    }
    ctx.restore();

    if (qr) {
      const qrSize = 260;
      const qx = cx + 50;
      const qy = footerStartY + 70;
      ctx.save();
      drawRoundedRect(ctx, qx, qy, qrSize, qrSize, 15);
      ctx.clip();
      drawCoverImage(ctx, qr, qx, qy, qrSize, qrSize);
      ctx.restore();
      const rx = cx + cw - 60;
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillStyle = "#444444";
      ctx.font = posterFont(44, "bold");
      ctx.fillText(String(cfg.shop_name || ""), rx, qy + 10);
      if (cfg.phone) {
        ctx.font = posterFont(36);
        ctx.fillStyle = "#888888";
        ctx.fillText(`电话：${cfg.phone}`, rx, qy + 95);
      }
      if (cfg.address) {
        ctx.font = posterFont(26);
        ctx.fillStyle = "#888888";
        ctx.fillText(`地址：${cfg.address}`, rx, qy + 180);
      }
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = posterFont(35, "bold");
      ctx.fillStyle = "#5CAF5F";
      ctx.fillText(String(cfg.slogan || ""), CANVAS_WIDTH / 2, footerStartY + 400);
    } else {
      let cy2 = footerStartY + 60;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = posterFont(42, "bold");
      ctx.fillStyle = "#444444";
      ctx.fillText(String(cfg.shop_name || ""), CANVAS_WIDTH / 2, cy2);
      cy2 += 80;
      if (cfg.phone) {
        ctx.font = posterFont(36);
        ctx.fillStyle = "#999999";
        ctx.fillText(`电话：${cfg.phone}`, CANVAS_WIDTH / 2, cy2);
      }
      cy2 += 70;
      if (cfg.address) {
        ctx.font = posterFont(28);
        ctx.fillStyle = "#999999";
        ctx.fillText(`地址：${cfg.address}`, CANVAS_WIDTH / 2, cy2);
      }
      ctx.font = posterFont(35, "bold");
      ctx.fillStyle = "#5CAF5F";
      ctx.fillText(String(cfg.slogan || ""), CANVAS_WIDTH / 2, cy2 + 100);
    }

    if (stamp) {
      const max = 260;
      const ratio = Math.min(max / stamp.naturalWidth, max / stamp.naturalHeight, 1);
      const sw = stamp.naturalWidth * ratio;
      const sh = stamp.naturalHeight * ratio;
      const sx = qr ? cx + cw - sw + 20 : CANVAS_WIDTH / 2 - sw / 2 + 150;
      const sy = qr ? footerStartY + 160 : footerStartY + 30;
      ctx.save();
      ctx.globalAlpha = Math.max(0.05, Math.min(1, Number(cfg.stamp_opacity || 0.85)));
      ctx.drawImage(stamp, sx, sy, sw, sh);
      ctx.restore();
    }

    drawWatermark(ctx, cfg, posterFont);
    return canvas;
  }

  async function renderToBlob(payload, options = {}) {
    const canvas = await renderToCanvas(payload);
    const exportFormat = String(options.exportFormat || payload?.export_format || "PNG").toUpperCase();
    const mimeType = options.mimeType || (exportFormat === "JPEG" ? "image/jpeg" : "image/png");
    const quality = exportFormat === "JPEG" ? Math.max(0.01, Math.min(1, Number(payload?.config?.jpeg_quality || 95) / 100)) : undefined;
    const blob = await canvasToBlob(canvas, mimeType, quality);
    const validation = window.PosterTextTools?.validateContent
      ? window.PosterTextTools.validateContent(payload?.content || "")
      : { valid: true, warnings: [] };
    return { canvas, blob, valid: validation.valid, warnings: validation.warnings || [] };
  }

  async function renderToBlobUrl(payload, options = {}) {
    const result = await renderToBlob(payload, options);
    return { ...result, objectUrl: URL.createObjectURL(result.blob) };
  }

  window.PosterRenderer = {
    CANVAS_SIZE: [CANVAS_WIDTH, CANVAS_HEIGHT],
    CLIENT_RENDER_DISABLE_KEY,
    isEnabled,
    renderToCanvas,
    renderToBlob,
    renderToBlobUrl,
  };
})();
