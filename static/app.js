const state = {
  config: {},
  presets: [],
  systemTemplates: {},
  systemTemplateMeta: {},
  currentUser: "",
  isGuest: true,
  guestRegisterTipShown: false,
  holidayBgBackup: null,
  holidayBgApplied: false,
  logoCrop: null,
  priceEditorRows: [],
  previewSeq: 0,
};

const $ = (id) => document.getElementById(id);
const UPLOAD_PREVIEW_FIELDS = [
  { key: "bg_image_path", thumbId: "bgThumb", wrapId: "bgThumbWrap" },
  { key: "logo_image_path", thumbId: "logoThumb", wrapId: "logoThumbWrap" },
  { key: "stamp_image_path", thumbId: "stampThumb", wrapId: "stampThumbWrap" },
  { key: "qrcode_image_path", thumbId: "qrThumb", wrapId: "qrThumbWrap" },
];
const AVAILABLE_CARD_STYLES = new Set(["single", "stack", "block", "flip", "ticket", "double", "aurora", "paper_relief"]);
const BG_VARIANTS = ["bg-variant-a", "bg-variant-b", "bg-variant-c", "bg-variant-d", "bg-variant-e"];
const MAX_UPLOAD_MB = 15;
const GUEST_DRAFT_STORAGE_KEY = "poster_guest_draft_v1";
const GUEST_DRAFT_SCHEMA_VERSION = 1;
const GUEST_DRAFT_EXPIRE_MS = 30 * 24 * 60 * 60 * 1000;
const SETTINGS_TIP_SEEN_KEY = "poster_settings_tip_seen_v1";
const PRICE_LINE_PATTERN = /^\s*【([^】]+)】\s*[：:]\s*(.+?)\s*$/;
const PRICE_UNIT_DEFAULT = "元/吨";
const RANGE_VALUE_FIELDS = [
  { inputId: "bgBlur", valueId: "bgBlurValue", format: (v) => `${Math.round(Number(v) || 0)}` },
  { inputId: "bgBrightness", valueId: "bgBrightnessValue", format: (v) => `${(Number(v) || 0).toFixed(2)}x` },
  { inputId: "cardOpacity", valueId: "cardOpacityValue", format: (v) => `${Math.round((Number(v) || 0) * 100)}%` },
  { inputId: "stampOpacity", valueId: "stampOpacityValue", format: (v) => `${Math.round((Number(v) || 0) * 100)}%` },
  { inputId: "watermarkOpacity", valueId: "watermarkOpacityValue", format: (v) => `${Math.round((Number(v) || 0) * 100)}%` },
  { inputId: "watermarkDensity", valueId: "watermarkDensityValue", format: (v) => `${(Number(v) || 0).toFixed(1)}x` },
];

function getStats(text) {
  const chars = (text || "").replace(/\s/g, "").length;
  const lines = (text || "").split("\n").filter((x) => x.trim()).length;
  return `${chars} 字 · ${lines} 行`;
}

function updateStats() {
  $("statsText").textContent = getStats($("contentInput").value);
}

function syncRangeValue(inputId) {
  const field = RANGE_VALUE_FIELDS.find((x) => x.inputId === inputId);
  if (!field) return;
  const inputEl = $(field.inputId);
  const valueEl = $(field.valueId);
  if (!inputEl || !valueEl) return;
  valueEl.textContent = field.format(inputEl.value);
}

function syncAllRangeValues() {
  RANGE_VALUE_FIELDS.forEach((field) => syncRangeValue(field.inputId));
}

async function api(url, method = "GET", body = null) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const ct = res.headers.get("content-type") || "";
  let payload = null;
  if (ct.includes("application/json")) {
    payload = await res.json();
  } else {
    const text = await res.text();
    payload = text ? { error: text } : {};
  }
  if (!res.ok) {
    throw new Error(payload.error || payload.message || `请求失败(${res.status})`);
  }
  return payload;
}

function setButtonBusy(btn, busy, busyText = "处理中...") {
  if (!btn) return;
  if (!btn.dataset.originText) btn.dataset.originText = btn.textContent || "";
  btn.disabled = !!busy;
  btn.textContent = busy ? busyText : btn.dataset.originText;
}

function showStatusError(msg) {
  $("statusText").textContent = msg || "操作失败，请重试";
}
function syncSettingsMenuUi() {
  const userEl = $("settingsMenuUser");
  const authBtn = $("settingsMenuAuthBtn");
  const clearGuestDraftBtn = $("clearGuestDraftBtn");
  const panelBtn = $("settingsMenuPanelBtn");
  const loggedIn = !!(state.currentUser && !state.isGuest);

  if (userEl) {
    if (!state.currentUser) {
      userEl.textContent = "当前身份：未登录";
    } else if (state.isGuest) {
      userEl.textContent = "当前身份：访客";
    } else {
      userEl.textContent = `当前用户：${state.currentUser}`;
    }
  }

  if (authBtn) {
    authBtn.textContent = loggedIn ? "退出登录" : "登录 / 注册";
  }

  if (clearGuestDraftBtn) {
    const canClear = state.isGuest && hasGuestDraft();
    clearGuestDraftBtn.hidden = !state.isGuest;
    clearGuestDraftBtn.disabled = !canClear;
  }

  // 登录后将“打开设置”置于“退出登录”之前，减少误触退出。
  if (authBtn && panelBtn && authBtn.parentNode === panelBtn.parentNode) {
    if (loggedIn) {
      authBtn.parentNode.insertBefore(panelBtn, authBtn);
    } else {
      authBtn.parentNode.insertBefore(authBtn, panelBtn);
    }
  }
}

function closeSettingsMenu() {
  const menu = $("settingsMenu");
  const btn = $("openSettingsBtn");
  if (!menu || !btn) return;
  menu.hidden = true;
  btn.setAttribute("aria-expanded", "false");
}

function toggleSettingsMenu() {
  const menu = $("settingsMenu");
  const btn = $("openSettingsBtn");
  if (!menu || !btn) return;
  const nextOpen = !!menu.hidden;
  menu.hidden = !nextOpen;
  btn.setAttribute("aria-expanded", nextOpen ? "true" : "false");
}

async function handleSettingsMenuAuthAction() {
  const loggedIn = !!(state.currentUser && !state.isGuest);
  closeSettingsMenu();
  if (!loggedIn) {
    openLoginModal();
    return;
  }
  try {
    // 退出前自动保存当前用户设置，避免下次登录需要重复配置。
    state.config = buildConfigPayloadForSave();
    await api("/api/config", "POST", state.config);
  } catch (_) {}
  try {
    await api("/api/logout", "POST");
    location.reload();
  } catch (e) {
    showStatusError(e.message || "退出登录失败");
  }
}

function withGuestHint(baseText) {
  return state.isGuest ? `${baseText}（访客模式，建议注册：可保存设置和内容）` : baseText;
}

function syncFooterNoteVisibility() {
  const note = $("actionBarNote");
  if (!note) return;
  if (document.body.classList.contains("preview-focus")) {
    note.classList.remove("is-visible");
    return;
  }
  const doc = document.documentElement;
  const remain = Math.max(0, doc.scrollHeight - (window.scrollY + window.innerHeight));
  note.classList.toggle("is-visible", remain <= 24);
}

function isMobileLayout() {
  return window.matchMedia("(max-width: 819px)").matches;
}

function getPreviewCard() {
  return document.querySelector(".preview-card");
}

function isDesktopFullscreenWithCard() {
  const card = getPreviewCard();
  if (!card) return false;
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  return fsEl === card;
}

function isDesktopPreviewFocusActive() {
  return isDesktopFullscreenWithCard() || document.body.classList.contains("is-desktop-preview-focus");
}

async function enterDesktopPreviewFocus() {
  const card = getPreviewCard();
  if (!card) return;
  try {
    if (card.requestFullscreen) {
      await card.requestFullscreen();
      return;
    }
    if (card.webkitRequestFullscreen) {
      card.webkitRequestFullscreen();
      return;
    }
  } catch (_) {}
  document.body.classList.add("is-desktop-preview-focus");
}

async function exitDesktopPreviewFocus() {
  document.body.classList.remove("is-desktop-preview-focus");
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  if (fsEl) {
    try {
      if (document.exitFullscreen) {
        await document.exitFullscreen();
        return;
      }
      if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
    } catch (_) {}
  }
}

function syncTopbarCompactOnScroll() {
  const body = document.body;
  if (!body) return;
  if (!isMobileLayout() || body.classList.contains("preview-focus")) {
    body.classList.remove("is-topbar-collapsed");
    return;
  }
  const y = window.scrollY || document.documentElement.scrollTop || 0;
  const collapsed = body.classList.contains("is-topbar-collapsed");
  if (!collapsed && y > 30) {
    body.classList.add("is-topbar-collapsed");
  } else if (collapsed && y < 8) {
    body.classList.remove("is-topbar-collapsed");
  }
}

function syncPreviewFocusUi() {
  const body = document.body;
  const focusBtn = $("togglePreviewFocusBtn");
  const drawerToggleBtn = $("editorDrawerToggleBtn");
  if (!body || !focusBtn || !drawerToggleBtn) return;

  const inFocus = isMobileLayout()
    ? body.classList.contains("preview-focus")
    : isDesktopPreviewFocusActive();
  const drawerOpen = body.classList.contains("editor-drawer-open");

  focusBtn.textContent = inFocus ? "退出全屏" : "全屏预览";
  focusBtn.setAttribute("aria-pressed", inFocus ? "true" : "false");

  drawerToggleBtn.hidden = !isMobileLayout() || !inFocus;
  drawerToggleBtn.textContent = drawerOpen ? "收起编辑区" : "展开编辑区";
  drawerToggleBtn.setAttribute("aria-expanded", drawerOpen ? "true" : "false");
}

async function togglePreviewFocus(force) {
  const body = document.body;
  if (!body) return;

  const shouldEnter = typeof force === "boolean"
    ? force
    : !(
      isMobileLayout()
        ? body.classList.contains("preview-focus")
        : isDesktopPreviewFocusActive()
    );

  if (isMobileLayout()) {
    if (shouldEnter) {
      body.classList.add("preview-focus");
      body.classList.remove("editor-drawer-open");
    } else {
      body.classList.remove("preview-focus");
      body.classList.remove("editor-drawer-open");
    }
  } else if (shouldEnter) {
    await enterDesktopPreviewFocus();
  } else {
    await exitDesktopPreviewFocus();
  }

  syncPreviewFocusUi();
  syncTopbarCompactOnScroll();
  syncFooterNoteVisibility();
}

function hasSeenSettingsTip() {
  try {
    return localStorage.getItem(SETTINGS_TIP_SEEN_KEY) === "1";
  } catch (_) {
    return true;
  }
}

function markSettingsTipSeen() {
  try {
    localStorage.setItem(SETTINGS_TIP_SEEN_KEY, "1");
  } catch (_) {}
}

function showSettingsFirstUseTip() {
  if (hasSeenSettingsTip()) return;
  const btn = $("openSettingsBtn");
  if (!btn) return;

  const old = $("settingsFirstTip");
  if (old) old.remove();

  const tip = document.createElement("aside");
  tip.id = "settingsFirstTip";
  tip.className = "settings-tip";
  tip.setAttribute("role", "status");
  tip.innerHTML = `
    <p>首次使用提示：包站名称、手机号、地址等信息，都在右上角“设置”里。</p>
    <button type="button" class="settings-tip-btn">知道了</button>
  `;
  document.body.appendChild(tip);

  let closed = false;
  let autoCloseTimer = 0;

  const closeTip = () => {
    if (closed) return;
    closed = true;
    if (autoCloseTimer) {
      clearTimeout(autoCloseTimer);
      autoCloseTimer = 0;
    }
    document.removeEventListener("click", onDocClick, true);
    tip.remove();
    markSettingsTipSeen();
  };

  const onDocClick = (e) => {
    if (tip.contains(e.target) || btn.contains(e.target)) return;
    closeTip();
  };

  tip.querySelector(".settings-tip-btn")?.addEventListener("click", (e) => {
    e.preventDefault();
    closeTip();
  });

  btn.addEventListener("click", closeTip, { once: true });
  setTimeout(() => {
    document.addEventListener("click", onDocClick, true);
  }, 0);

  autoCloseTimer = window.setTimeout(closeTip, 12000);
}

function buildConfigPayloadForSave() {
  const payload = { ...formConfig(), custom_templates: state.config.custom_templates || {} };
  payload.last_title = $("titleInput").value.trim();
  payload.last_date = $("dateInput").value.trim();
  payload.last_content = $("contentInput").value;
  return payload;
}

function getGuestDraftEnvelope() {
  try {
    const raw = localStorage.getItem(GUEST_DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY);
      return null;
    }
    if (Number(parsed.version) !== GUEST_DRAFT_SCHEMA_VERSION) {
      localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY);
      return null;
    }
    const updatedAt = Number(parsed.updated_at || 0);
    if (!Number.isFinite(updatedAt) || updatedAt <= 0 || Date.now() - updatedAt > GUEST_DRAFT_EXPIRE_MS) {
      localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY);
      return null;
    }
    if (!parsed.config || typeof parsed.config !== "object") {
      localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch (_) {
    try { localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY); } catch (_) {}
    return null;
  }
}

function hasGuestDraft() {
  return !!getGuestDraftEnvelope();
}

function readGuestDraft() {
  if (!state.isGuest) return null;
  return getGuestDraftEnvelope()?.config || null;
}

function clearGuestDraft(silent = false) {
  try {
    localStorage.removeItem(GUEST_DRAFT_STORAGE_KEY);
  } catch (_) {}
  syncSettingsMenuUi();
  if (!silent) {
    $("statusText").textContent = "已清空访客本地草稿";
  }
}

function saveGuestDraft() {
  if (!state.isGuest) return;
  try {
    const payload = {
      version: GUEST_DRAFT_SCHEMA_VERSION,
      updated_at: Date.now(),
      config: buildConfigPayloadForSave(),
    };
    localStorage.setItem(GUEST_DRAFT_STORAGE_KEY, JSON.stringify(payload));
    syncSettingsMenuUi();
  } catch (_) {}
}

async function ensureLogin() {
  const me = await api("/api/me");
  state.currentUser = me.display_user_id || me.user_id || "";
  state.isGuest = !!me.is_guest;
  syncSettingsMenuUi();
}

function switchSettingsTab(tab) {
  document.querySelectorAll("[data-settings-tab]").forEach((btn) => {
    const active = btn.dataset.settingsTab === tab;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });

  document.querySelectorAll("[data-settings-pane]").forEach((pane) => {
    const active = pane.dataset.settingsPane === tab;
    pane.classList.toggle("is-active", active);
    pane.hidden = !active;
  });
}

function syncSettingsPaneHeight() {
  const basePane = $("settingsPaneBase");
  if (!basePane || basePane.hidden) return;

  // 以“基础信息”面板为基准，统一其他面板最小高度，避免切换时跳动。
  basePane.style.minHeight = "0px";
  const baseHeight = Math.ceil(basePane.scrollHeight);
  if (!baseHeight) return;

  document.querySelectorAll("[data-settings-pane]").forEach((pane) => {
    pane.style.minHeight = `${baseHeight}px`;
  });
}

function openSettingsModal() {
  closeSettingsMenu();
  $("settingsModal").classList.remove("hidden");
  document.body.classList.add("no-scroll");
  switchSettingsTab("base");
  syncSettingsPaneHeight();
}

function closeSettingsModal() {
  $("settingsModal").classList.add("hidden");
  if ($("loginModal").classList.contains("hidden")) {
    document.body.classList.remove("no-scroll");
  }
}

function setLoginError(msg = "") {
  const el = $("loginErrorText");
  if (!el) return;
  el.textContent = msg;
}

function openLoginModal() {
  $("loginModal").classList.remove("hidden");
  document.body.classList.add("no-scroll");
  $("loginUserIdInput").value = state.isGuest ? "" : (state.currentUser || "");
  $("loginPasswordInput").value = "";
  $("loginPasswordInput").type = "password";
  $("toggleLoginPwdBtn").textContent = "显示";
  setLoginError("");
  $("loginUserIdInput").focus();
}

function closeLoginModal() {
  $("loginModal").classList.add("hidden");
  if ($("settingsModal").classList.contains("hidden")) {
    document.body.classList.remove("no-scroll");
  }
  setLoginError("");
}

function formConfig() {
  return {
    ...state.config,
    theme_color: $("themeColor").value,
    card_style: $("cardStyle").value,
    price_color_mode: $("priceColorMode").value,
    shop_name: $("shopName").value.trim(),
    phone: $("phone").value.trim(),
    address: $("address").value.trim(),
    slogan: $("slogan").value.trim(),
    bg_blur_radius: Number($("bgBlur").value),
    bg_brightness: Number($("bgBrightness").value),
    card_opacity: Number($("cardOpacity").value),
    stamp_opacity: Number($("stampOpacity").value),
    watermark_enabled: $("watermarkEnabled").checked,
    watermark_text: $("watermarkText").value,
    watermark_opacity: Number($("watermarkOpacity").value),
    watermark_density: Number($("watermarkDensity").value),
    copy_mode: $("copyMode").value,
    export_format: $("exportFormat").value,
  };
}

function bindFromConfig(cfg) {
  $("titleInput").value = cfg.last_title || "调价通知";
  $("dateInput").value = cfg.last_date || "今天";
  $("contentInput").value = cfg.last_content || "";
  syncMainPriceEditorFromContent();

  $("themeColor").value = cfg.theme_color || "#B22222";
  syncThemeColorUi($("themeColor").value);
  const legacyStyleMap = { soft: "single", outline_pro: "single", outline: "single", fold: "single", sidebar: "single", ink: "single", neon: "single" };
  const savedCardStyle = legacyStyleMap[cfg.card_style] || cfg.card_style || "single";
  $("cardStyle").value = AVAILABLE_CARD_STYLES.has(savedCardStyle) ? savedCardStyle : "single";
  $("priceColorMode").value = cfg.price_color_mode || "semantic";
  $("shopName").value = cfg.shop_name || "";
  $("phone").value = cfg.phone || "";
  $("address").value = cfg.address || "";
  $("slogan").value = cfg.slogan || "";
  $("bgBlur").value = cfg.bg_blur_radius ?? 30;
  $("bgBrightness").value = cfg.bg_brightness ?? 1.0;
  $("cardOpacity").value = cfg.card_opacity ?? 1.0;
  $("stampOpacity").value = cfg.stamp_opacity ?? 0.85;
  $("watermarkEnabled").checked = !!cfg.watermark_enabled;
  $("watermarkText").value = cfg.watermark_text || "仅供客户参考";
  $("watermarkOpacity").value = cfg.watermark_opacity ?? 0.15;
  $("watermarkDensity").value = cfg.watermark_density ?? 1.0;
  $("copyMode").value = cfg.copy_mode || "复制图片";
  $("exportFormat").value = cfg.export_format || "PNG";
  syncUploadThumbsFromConfig(cfg);
  syncAllRangeValues();

  updateStats();
}

function normalizeHexColor(v) {
  const m = String(v || "").trim().match(/^#([0-9a-fA-F]{6})$/);
  return m ? `#${m[1].toUpperCase()}` : "";
}

function hexToRgb(hex) {
  const h = normalizeHexColor(hex);
  if (!h) return null;
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  return { r, g, b };
}

function mixWithWhite(hex, ratio) {
  const rgb = hexToRgb(hex);
  if (!rgb) return "#B22222";
  const t = Math.max(0, Math.min(1, ratio));
  const r = Math.round(rgb.r + (255 - rgb.r) * t);
  const g = Math.round(rgb.g + (255 - rgb.g) * t);
  const b = Math.round(rgb.b + (255 - rgb.b) * t);
  return `#${[r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

function applyThemeToPage(color) {
  const hex = normalizeHexColor(color) || "#B22222";
  const rgb = hexToRgb(hex) || { r: 178, g: 34, b: 34 };
  const root = document.documentElement;
  root.style.setProperty("--primary", hex);
  root.style.setProperty("--primary-rgb", `${rgb.r}, ${rgb.g}, ${rgb.b}`);
  root.style.setProperty("--primary-strong", mixWithWhite(hex, 0.05));
  root.style.setProperty("--primary-soft", mixWithWhite(hex, 0.2));
  root.style.setProperty("--primary-surface", mixWithWhite(hex, 0.88));
}

function syncThemeColorUi(color) {
  const hex = normalizeHexColor(color) || "#B22222";
  const hexEl = $("themeColorHex");
  if (hexEl) hexEl.textContent = hex;
  applyThemeToPage(hex);
  document.querySelectorAll(".theme-swatch").forEach((btn) => {
    btn.classList.toggle("is-active", normalizeHexColor(btn.dataset.color) === hex);
  });
}

function toAssetUrl(path) {
  if (!path) return "";
  if (/^(data:|blob:|https?:\/\/)/i.test(path)) return path;
  const safePath = String(path)
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
  return `/asset/${safePath}`;
}

function toDownloadUrl(path) {
  if (!path) return "";
  const safePath = String(path)
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
  return `/download/${safePath}`;
}

function renderUploadThumb(key, path) {
  const item = UPLOAD_PREVIEW_FIELDS.find((x) => x.key === key);
  if (!item) return;
  const img = $(item.thumbId);
  const wrap = $(item.wrapId);
  if (!img || !wrap) return;

  if (!path) {
    img.removeAttribute("src");
    wrap.hidden = true;
    return;
  }

  img.src = toAssetUrl(path);
  wrap.hidden = false;
}

function syncUploadThumbsFromConfig(cfg) {
  UPLOAD_PREVIEW_FIELDS.forEach((item) => {
    renderUploadThumb(item.key, cfg[item.key]);
  });
}

function applyTemplateByName(name) {
  if (state.systemTemplates[name]) {
    $("contentInput").value = state.systemTemplates[name][0] || "";
    $("titleInput").value = state.systemTemplates[name][1] || $("titleInput").value;
    syncMainPriceEditorFromContent();
    return true;
  }
  if (state.config.custom_templates?.[name]) {
    $("contentInput").value = state.config.custom_templates[name] || "";
    syncMainPriceEditorFromContent();
    return true;
  }
  return false;
}

function createPriceRow() {
  return { name: "", mode: "number", value: "", min: "", max: "", text: "", unit: PRICE_UNIT_DEFAULT };
}

function parsePriceLineValue(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) return { mode: "text", text: "", unit: PRICE_UNIT_DEFAULT };

  let body = raw;
  let unit = "";
  const unitMatch = body.match(/\s*(元\s*\/\s*吨)\s*$/);
  if (unitMatch) {
    unit = PRICE_UNIT_DEFAULT;
    body = body.slice(0, unitMatch.index).trim();
  }

  const rangeMatch = body.match(/^(-?\d+(?:\.\d+)?)\s*[-~～至到]+\s*(-?\d+(?:\.\d+)?)$/);
  if (rangeMatch) {
    return { mode: "range", min: rangeMatch[1], max: rangeMatch[2], unit: unit || PRICE_UNIT_DEFAULT };
  }

  const numberMatch = body.match(/^(-?\d+(?:\.\d+)?)$/);
  if (numberMatch) {
    return { mode: "number", value: numberMatch[1], unit: unit || PRICE_UNIT_DEFAULT };
  }

  return { mode: "text", text: body, unit };
}

function parseContentToPriceEditor(content) {
  const lines = String(content || "").replace(/\r\n/g, "\n").split("\n");
  const rows = [];
  const extraLines = [];

  lines.forEach((line) => {
    const match = line.match(PRICE_LINE_PATTERN);
    if (!match) {
      extraLines.push(line);
      return;
    }

    const name = String(match[1] || "").trim();
    const parsed = parsePriceLineValue(match[2] || "");
    rows.push({
      name,
      mode: parsed.mode || "text",
      value: parsed.value || "",
      min: parsed.min || "",
      max: parsed.max || "",
      text: parsed.text || "",
      unit: parsed.unit || PRICE_UNIT_DEFAULT,
    });
  });

  return {
    rows,
    extra: extraLines.join("\n").replace(/^\n+|\n+$/g, ""),
  };
}

function getPriceEditorRowsFromDom() {
  const tbody = $("priceTableBody");
  if (!tbody) return [];
  const rows = [];

  tbody.querySelectorAll("tr").forEach((tr) => {
    rows.push({
      name: tr.querySelector('[data-field="name"]')?.value?.trim() || "",
      mode: tr.querySelector('[data-field="mode"]')?.value || "number",
      value: tr.querySelector('[data-field="value"]')?.value?.trim() || "",
      min: tr.querySelector('[data-field="min"]')?.value?.trim() || "",
      max: tr.querySelector('[data-field="max"]')?.value?.trim() || "",
      text: tr.querySelector('[data-field="text"]')?.value?.trim() || "",
      unit: tr.querySelector('[data-field="unit"]')?.value?.trim() || "",
    });
  });

  return rows;
}

function buildContentFromPriceEditor(rows, extra) {
  const out = [];
  rows.forEach((row) => {
    const name = String(row.name || "").trim();
    if (!name) return;

    const mode = String(row.mode || "number");
    const unit = String(row.unit || "").trim();
    const suffix = unit ? ` ${unit}` : "";

    if (mode === "range") {
      const v1 = String(row.min || "").trim();
      const v2 = String(row.max || "").trim();
      if (!v1 || !v2) return;
      out.push(`【${name}】：${v1}-${v2}${suffix}`);
      return;
    }

    if (mode === "text") {
      const text = String(row.text || "").trim();
      if (!text) return;
      out.push(`【${name}】：${text}${suffix}`);
      return;
    }

    const value = String(row.value || "").trim();
    if (!value) return;
    out.push(`【${name}】：${value}${suffix}`);
  });

  const note = String(extra || "").replace(/\r\n/g, "\n").trim();
  if (note) {
    if (out.length) out.push("");
    out.push(note);
  }
  return out.join("\n").trim();
}

function escapeAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderPriceEditorTable() {
  const tbody = $("priceTableBody");
  if (!tbody) return;
  if (!state.priceEditorRows.length) state.priceEditorRows = [createPriceRow()];

  tbody.innerHTML = state.priceEditorRows.map((row, idx) => {
    const mode = row.mode || "number";
    let valueCellHtml = `<input data-field="value" value="${escapeAttr(row.value || "")}" placeholder="1350" />`;
    if (mode === "range") {
      valueCellHtml = `
        <div class="price-range-wrap">
          <input data-field="min" value="${escapeAttr(row.min || "")}" placeholder="800" />
          <input data-field="max" value="${escapeAttr(row.max || "")}" placeholder="900" />
        </div>
      `;
    } else if (mode === "text") {
      valueCellHtml = `<input data-field="text" value="${escapeAttr(row.text || "")}" placeholder="上调5" />`;
    }
    return `
      <tr data-row-index="${idx}">
        <td><input data-field="name" value="${escapeAttr(row.name || "")}" placeholder="例如：工厂黄板" /></td>
        <td>
          <select data-field="mode">
            <option value="number"${mode === "number" ? " selected" : ""}>单价</option>
            <option value="range"${mode === "range" ? " selected" : ""}>区间</option>
            <option value="text"${mode === "text" ? " selected" : ""}>文字</option>
          </select>
        </td>
        <td>${valueCellHtml}</td>
        <td><input data-field="unit" value="${escapeAttr(row.unit || "")}" placeholder="元/吨" /></td>
        <td>
          <button class="price-row-remove" data-action="remove-row" type="button" aria-label="删除此行" title="删除此行">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 3.75A2.25 2.25 0 0 0 6.75 6H4.5a1 1 0 1 0 0 2h.38l1.03 10.34A2.25 2.25 0 0 0 8.15 20.5h7.7a2.25 2.25 0 0 0 2.24-2.16L19.12 8h.38a1 1 0 1 0 0-2h-2.25A2.25 2.25 0 0 0 15 3.75H9Zm0 2h6a.25.25 0 0 1 .25.25V6h-6.5v-.25A.25.25 0 0 1 9 5.75Zm.25 5a1 1 0 0 1 1 1v4.5a1 1 0 1 1-2 0v-4.5a1 1 0 0 1 1-1Zm5.5 0a1 1 0 0 1 1 1v4.5a1 1 0 1 1-2 0v-4.5a1 1 0 0 1 1-1Z"/>
            </svg>
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

function syncMainPriceEditorFromContent() {
  const parsed = parseContentToPriceEditor($("contentInput").value);
  state.priceEditorRows = parsed.rows.length ? parsed.rows : [createPriceRow()];
  $("priceEditorExtra").value = parsed.extra || "";
  renderPriceEditorTable();
}

function syncHiddenContentFromMainPriceEditor() {
  state.priceEditorRows = getPriceEditorRowsFromDom();
  $("contentInput").value = buildContentFromPriceEditor(state.priceEditorRows, $("priceEditorExtra").value);
  updateStats();
}

function isHolidayTemplateName(name) {
  const key = String(name || "");
  const metaMap = state.systemTemplateMeta;
  if (!metaMap || typeof metaMap !== "object") return false;
  const meta = metaMap[key];
  if (!meta || typeof meta !== "object") return false;
  return meta.is_holiday === true;
}

function syncHolidayActionButtonsVisibility(isHolidayMode) {
  const formatBtn = $("formatBtn");
  const batchBtn = $("batchBtn");
  if (formatBtn) formatBtn.hidden = !!isHolidayMode;
  if (batchBtn) batchBtn.hidden = !!isHolidayMode;
}

function syncEditorModeByTemplate() {
  const contentInput = $("contentInput");
  const priceEditorPanel = $("priceEditorPanel");
  const tplSel = $("templateSelect");
  if (!contentInput || !priceEditorPanel || !tplSel) return;

  const holidayMode = isHolidayTemplateName(tplSel.value);
  if (!holidayMode) {
    syncMainPriceEditorFromContent();
  }

  syncHolidayActionButtonsVisibility(holidayMode);
  contentInput.hidden = !holidayMode;
  priceEditorPanel.hidden = holidayMode;
}

function getHolidayPresetPath() {
  const byPath = state.presets.find((p) => /preset_luxury_red\.png$/i.test(p.path || ""));
  if (byPath) return byPath.path;
  const byName = state.presets.find((p) => (p.name || "").includes("故宫红"));
  return byName?.path || "";
}

function shouldUseHolidayPreset(templateName) {
  return isHolidayTemplateName(templateName);
}

function applyHolidayPresetIfNeeded(templateName) {
  if (!shouldUseHolidayPreset(templateName)) {
    if (state.holidayBgApplied && state.holidayBgBackup) {
      state.config.bg_mode = state.holidayBgBackup.bg_mode || "custom";
      state.config.bg_image_path = state.holidayBgBackup.bg_image_path || "";
      $("presetSelect").value = state.config.bg_mode === "preset" ? (state.config.bg_image_path || "") : "";
    }
    state.holidayBgApplied = false;
    state.holidayBgBackup = null;
    return;
  }
  const holidayPath = getHolidayPresetPath();
  if (!holidayPath) return;
  if (!state.holidayBgApplied) {
    state.holidayBgBackup = {
      bg_mode: state.config.bg_mode,
      bg_image_path: state.config.bg_image_path,
    };
  }
  $("presetSelect").value = holidayPath;
  state.config.bg_mode = "preset";
  state.config.bg_image_path = holidayPath;
  state.holidayBgApplied = true;
}

async function uploadFile(inputEl, key) {
  const file = inputEl.files?.[0];
  if (!file) return;
  if (!String(file.type || "").startsWith("image/")) {
    throw new Error("仅支持图片文件");
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    throw new Error(`图片不能超过 ${MAX_UPLOAD_MB}MB`);
  }
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "上传失败");
  state.config[key] = data.path;
  renderUploadThumb(key, data.path);
  saveGuestDraft();
}

async function uploadBlob(blob, filename, key) {
  if (blob.size > MAX_UPLOAD_MB * 1024 * 1024) {
    throw new Error(`图片不能超过 ${MAX_UPLOAD_MB}MB`);
  }
  const fd = new FormData();
  fd.append("file", blob, filename);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "上传失败");
  state.config[key] = data.path;
  renderUploadThumb(key, data.path);
  saveGuestDraft();
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function closeLogoCropModal() {
  $("logoCropModal").classList.add("hidden");
  if ($("settingsModal").classList.contains("hidden")) {
    document.body.classList.remove("no-scroll");
  }
  state.logoCrop = null;
  $("logoUpload").value = "";
}

function renderLogoCropPreview() {
  const crop = state.logoCrop;
  if (!crop?.img) return;
  const canvas = $("logoCropCanvas");
  const ctx = canvas.getContext("2d");
  const { img } = crop;
  const iw = img.naturalWidth || img.width;
  const ih = img.naturalHeight || img.height;
  const side = Math.min(iw, ih) / crop.scale;
  const maxDx = Math.max(0, (iw - side) / 2);
  const maxDy = Math.max(0, (ih - side) / 2);
  const sx = clamp((iw - side) / 2 + maxDx * (crop.offsetX / 100), 0, iw - side);
  const sy = clamp((ih - side) / 2 + maxDy * (crop.offsetY / 100), 0, ih - side);
  crop.sx = sx;
  crop.sy = sy;
  crop.side = side;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, sx, sy, side, side, 0, 0, canvas.width, canvas.height);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(15, 23, 42, 0.35)";
  ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
}

function bindLogoCropDrag() {
  const canvas = $("logoCropCanvas");
  if (!canvas) return;

  const stopDragging = () => {
    if (!state.logoCrop) return;
    state.logoCrop.dragging = false;
    canvas.classList.remove("is-dragging");
  };

  canvas.addEventListener("pointerdown", (e) => {
    const crop = state.logoCrop;
    if (!crop?.img) return;
    crop.dragging = true;
    crop.dragPointerId = e.pointerId;
    crop.lastClientX = e.clientX;
    crop.lastClientY = e.clientY;
    canvas.classList.add("is-dragging");
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  canvas.addEventListener("pointermove", (e) => {
    const crop = state.logoCrop;
    if (!crop?.img || !crop.dragging) return;
    const dx = e.clientX - crop.lastClientX;
    const dy = e.clientY - crop.lastClientY;
    crop.lastClientX = e.clientX;
    crop.lastClientY = e.clientY;

    const iw = crop.img.naturalWidth || crop.img.width;
    const ih = crop.img.naturalHeight || crop.img.height;
    const side = Math.min(iw, ih) / crop.scale;
    const maxDx = Math.max(0, (iw - side) / 2);
    const maxDy = Math.max(0, (ih - side) / 2);
    const cw = canvas.clientWidth || canvas.width;
    const ch = canvas.clientHeight || canvas.height;

    if (maxDx > 0 && cw > 0) {
      const sourceDx = (dx / cw) * side;
      const offsetDx = (sourceDx / maxDx) * 100;
      crop.offsetX = clamp(crop.offsetX + offsetDx, -100, 100);
    }
    if (maxDy > 0 && ch > 0) {
      const sourceDy = (dy / ch) * side;
      const offsetDy = (sourceDy / maxDy) * 100;
      crop.offsetY = clamp(crop.offsetY + offsetDy, -100, 100);
    }
    renderLogoCropPreview();
    e.preventDefault();
  });

  canvas.addEventListener("pointerup", (e) => {
    if (state.logoCrop?.dragPointerId === e.pointerId) {
      stopDragging();
    }
  });
  canvas.addEventListener("pointercancel", stopDragging);
  canvas.addEventListener("pointerleave", () => {
    if (state.logoCrop?.dragging) stopDragging();
  });
}

function openLogoCropModal(file) {
  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => {
      state.logoCrop = { file, img, scale: 1, offsetX: 0, offsetY: 0, sx: 0, sy: 0, side: 0 };
      $("logoCropScale").value = "1";
      $("logoCropModal").classList.remove("hidden");
      document.body.classList.add("no-scroll");
      renderLogoCropPreview();
    };
    img.src = String(reader.result || "");
  };
  reader.readAsDataURL(file);
}

function setPreviewLoading(text = "正在生成预览...") {
  $("previewStage").classList.remove("is-loaded");
  $("previewStage").classList.add("is-loading");
  $("previewPlaceholder").textContent = text;
}

function setPreviewLoaded() {
  $("previewStage").classList.remove("is-loading");
  $("previewStage").classList.add("is-loaded");
}

async function refreshPreview() {
  const seq = ++state.previewSeq;
  $("statusText").textContent = "生成预览中...";
  if (!$("previewImage").src) {
    setPreviewLoading("正在生成预览...");
  }
  const payload = {
    title: $("titleInput").value.trim(),
    date: $("dateInput").value.trim(),
    content: $("contentInput").value,
    config: formConfig(),
  };
  try {
    const data = await api("/api/preview", "POST", payload);
    if (seq !== state.previewSeq) return;
    const previewSrc = data.image_url || data.image;
    if (!previewSrc) throw new Error("预览地址无效");
    $("previewImage").src = previewSrc;
    $("dateInput").value = data.date || $("dateInput").value;
    $("statusText").textContent = !data.valid && data.warnings.length ? data.warnings[0] : "预览已更新";
  } catch (e) {
    if (seq !== state.previewSeq) return;
    setPreviewLoading("预览生成失败");
    showStatusError(e.message || "预览生成失败");
  }
}

function debounce(fn, delay = 500) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

function applyRandomBackgroundVariant() {
  const body = document.body;
  if (!body) return;
  BG_VARIANTS.forEach((cls) => body.classList.remove(cls));
  const picked = BG_VARIANTS[Math.floor(Math.random() * BG_VARIANTS.length)];
  body.classList.add(picked);
}

async function init() {
  applyRandomBackgroundVariant();
  syncSettingsMenuUi();
  syncPreviewFocusUi();
  await ensureLogin();
  bindLogoCropDrag();
  setPreviewLoading("正在生成预览...");
  $("previewImage").addEventListener("load", setPreviewLoaded);
  $("previewImage").addEventListener("error", () => {
    setPreviewLoading("预览加载失败，请重试");
  });

  const data = await api("/api/init");
  const remoteConfig = data.config || {};
  const guestDraft = readGuestDraft();
  state.config = state.isGuest && guestDraft ? { ...remoteConfig, ...guestDraft } : remoteConfig;
  state.systemTemplates = data.system_templates || {};
  state.systemTemplateMeta = data.system_template_meta || {};
  state.presets = data.presets || [];

  bindFromConfig(state.config);

  document.querySelectorAll(".theme-swatch").forEach((btn) => {
    if (btn.dataset.color) btn.style.background = btn.dataset.color;
    btn.addEventListener("click", () => {
      const color = normalizeHexColor(btn.dataset.color);
      if (!color) return;
      $("themeColor").value = color;
      syncThemeColorUi(color);
      $("themeColor").dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  const tplSel = $("templateSelect");
  tplSel.innerHTML = "";
  Object.keys(state.systemTemplates).forEach((name) => tplSel.add(new Option(name, name)));
  Object.keys(state.config.custom_templates || {}).forEach((name) => tplSel.add(new Option(name, name)));

  if (tplSel.options.length > 0) {
    tplSel.value = tplSel.options[0].value;
  }

  const hasSavedContent = !!(state.config.last_content || "").trim();
  if (!hasSavedContent && tplSel.value) {
    applyTemplateByName(tplSel.value);
    updateStats();
  }

  const presetSel = $("presetSelect");
  state.presets.forEach((p) => presetSel.add(new Option(p.name, p.path)));

  const onType = debounce(async () => {
    updateStats();
    saveGuestDraft();
    await refreshPreview();
  }, 650);

  const watchIds = [
    "titleInput", "dateInput", "contentInput",
    "shopName", "phone", "address", "slogan",
    "themeColor", "cardStyle", "bgBlur", "bgBrightness",
    "priceColorMode", "cardOpacity", "stampOpacity", "watermarkEnabled",
    "watermarkText", "watermarkOpacity", "watermarkDensity", "copyMode", "exportFormat",
  ];

  watchIds.forEach((id) => {
    $(id).addEventListener("input", onType);
    $(id).addEventListener("change", onType);
  });
  RANGE_VALUE_FIELDS.forEach((field) => {
    const el = $(field.inputId);
    if (!el) return;
    el.addEventListener("input", () => syncRangeValue(field.inputId));
    el.addEventListener("change", () => syncRangeValue(field.inputId));
  });
  $("themeColor").addEventListener("input", () => syncThemeColorUi($("themeColor").value));
  $("themeColor").addEventListener("change", () => syncThemeColorUi($("themeColor").value));

  $("openSettingsBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleSettingsMenu();
  });
  $("settingsMenuPanelBtn").addEventListener("click", openSettingsModal);
  $("settingsMenuAuthBtn").addEventListener("click", handleSettingsMenuAuthAction);
  $("clearGuestDraftBtn").addEventListener("click", () => {
    closeSettingsMenu();
    if (!state.isGuest) return;
    if (!hasGuestDraft()) {
      $("statusText").textContent = "当前没有可清空的访客草稿";
      syncSettingsMenuUi();
      return;
    }
    const ok = confirm("确认清空当前浏览器中的访客草稿吗？此操作不可撤销。");
    if (!ok) return;
    clearGuestDraft();
  });
  document.addEventListener("click", (e) => {
    const menu = $("settingsMenu");
    const btn = $("openSettingsBtn");
    if (!menu || menu.hidden) return;
    if (menu.contains(e.target) || btn?.contains(e.target)) return;
    closeSettingsMenu();
  });
  $("closeSettingsBtn").addEventListener("click", closeSettingsModal);
  $("closeSettingsBtn2").addEventListener("click", closeSettingsModal);
  $("settingsMask").addEventListener("click", closeSettingsModal);
  $("closeLoginBtn").addEventListener("click", closeLoginModal);
  $("cancelLoginBtn").addEventListener("click", closeLoginModal);
  $("loginMask").addEventListener("click", closeLoginModal);
  $("closeLogoCropBtn").addEventListener("click", closeLogoCropModal);
  $("cancelLogoCropBtn").addEventListener("click", closeLogoCropModal);
  $("logoCropMask").addEventListener("click", closeLogoCropModal);
  $("addPriceRowBtn").addEventListener("click", () => {
    state.priceEditorRows = getPriceEditorRowsFromDom();
    state.priceEditorRows.push(createPriceRow());
    renderPriceEditorTable();
    syncHiddenContentFromMainPriceEditor();
    onType();
  });
  $("priceTableBody").addEventListener("click", (e) => {
    const btn = e.target.closest('[data-action="remove-row"]');
    if (!btn) return;
    const tr = btn.closest("tr");
    if (!tr) return;
    const idx = Number(tr.dataset.rowIndex);
    if (!Number.isInteger(idx)) return;
    state.priceEditorRows = getPriceEditorRowsFromDom();
    state.priceEditorRows.splice(idx, 1);
    if (!state.priceEditorRows.length) state.priceEditorRows = [createPriceRow()];
    renderPriceEditorTable();
    syncHiddenContentFromMainPriceEditor();
    onType();
  });
  $("priceTableBody").addEventListener("input", () => {
    syncHiddenContentFromMainPriceEditor();
    onType();
  });
  $("priceTableBody").addEventListener("change", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.getAttribute("data-field") === "mode") {
      state.priceEditorRows = getPriceEditorRowsFromDom();
      renderPriceEditorTable();
      syncHiddenContentFromMainPriceEditor();
      onType();
    }
  });
  $("priceEditorExtra").addEventListener("input", () => {
    syncHiddenContentFromMainPriceEditor();
    onType();
  });
  $("priceEditorExtra").addEventListener("change", () => {
    syncHiddenContentFromMainPriceEditor();
    saveGuestDraft();
  });
  $("logoCropScale").addEventListener("input", () => {
    if (!state.logoCrop) return;
    state.logoCrop.scale = Number($("logoCropScale").value) || 1;
    renderLogoCropPreview();
  });
  $("confirmLogoCropBtn").addEventListener("click", async () => {
    const crop = state.logoCrop;
    if (!crop?.img) return;
    const btn = $("confirmLogoCropBtn");
    setButtonBusy(btn, true, "上传中...");
    try {
      const outSize = 640;
      const out = document.createElement("canvas");
      out.width = outSize;
      out.height = outSize;
      const ox = out.getContext("2d");
      ox.drawImage(crop.img, crop.sx, crop.sy, crop.side, crop.side, 0, 0, outSize, outSize);
      const blob = await new Promise((resolve) => out.toBlob(resolve, "image/png", 0.95));
      if (!blob) throw new Error("裁剪失败，请重试");
      await uploadBlob(blob, "logo-crop.png", "logo_image_path");
      closeLogoCropModal();
      await refreshPreview();
    } catch (e) {
      showStatusError(e.message || "Logo 上传失败");
    } finally {
      setButtonBusy(btn, false);
    }
  });
  $("toggleLoginPwdBtn").addEventListener("click", () => {
    const input = $("loginPasswordInput");
    const isPwd = input.type === "password";
    input.type = isPwd ? "text" : "password";
    $("toggleLoginPwdBtn").textContent = isPwd ? "隐藏" : "显示";
  });
  $("confirmLoginBtn").addEventListener("click", async () => {
    const userId = $("loginUserIdInput").value.trim();
    const password = $("loginPasswordInput").value;
    if (!userId) {
      setLoginError("请输入用户ID");
      return;
    }
    if (!password || password.trim().length < 4) {
      setLoginError("请输入至少 4 位密码");
      return;
    }
    const guestDraft = state.isGuest ? readGuestDraft() : null;
    const migrateGuestDraft = !!(guestDraft && confirm("检测到访客草稿。登录后是否迁移到当前账号？"));
    try {
      const d = await api("/api/login", "POST", { user_id: userId, password, merge_from_current: true });
      state.currentUser = d.display_user_id || d.user_id || userId;
      state.isGuest = !!d.is_guest;
      if (migrateGuestDraft && guestDraft) {
        try {
          await api("/api/config", "POST", guestDraft);
          clearGuestDraft(true);
        } catch (e2) {
          showStatusError(e2.message || "登录成功，但访客草稿迁移失败");
        }
      }
      syncSettingsMenuUi();
      location.reload();
    } catch (e) {
      setLoginError(e.message || "登录失败");
    }
  });
  $("loginPasswordInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      $("confirmLoginBtn").click();
    }
  });
  $("loginUserIdInput").addEventListener("input", () => setLoginError(""));
  $("loginPasswordInput").addEventListener("input", () => setLoginError(""));

  document.querySelectorAll("[data-settings-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchSettingsTab(btn.dataset.settingsTab));
  });

  window.addEventListener("resize", debounce(syncSettingsPaneHeight, 120));
  window.addEventListener("resize", syncFooterNoteVisibility);
  window.addEventListener("resize", async () => {
    if (!isMobileLayout() && document.body.classList.contains("preview-focus")) {
      await togglePreviewFocus(false);
    }
    syncTopbarCompactOnScroll();
    syncPreviewFocusUi();
  });
  window.addEventListener("scroll", syncFooterNoteVisibility, { passive: true });
  window.addEventListener("scroll", syncTopbarCompactOnScroll, { passive: true });
  document.addEventListener("fullscreenchange", syncPreviewFocusUi);
  document.addEventListener("webkitfullscreenchange", syncPreviewFocusUi);

  $("togglePreviewFocusBtn").addEventListener("click", async () => {
    await togglePreviewFocus();
  });
  $("previewStage").addEventListener("dblclick", async (e) => {
    if (isMobileLayout()) return;
    e.preventDefault();
    await togglePreviewFocus();
  });
  $("editorDrawerToggleBtn").addEventListener("click", () => {
    const body = document.body;
    if (!body.classList.contains("preview-focus")) return;
    body.classList.toggle("editor-drawer-open");
    syncPreviewFocusUi();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.body.classList.contains("is-desktop-preview-focus")) {
      togglePreviewFocus(false);
      return;
    }
    if (document.body.classList.contains("preview-focus")) {
      const body = document.body;
      if (body.classList.contains("editor-drawer-open")) {
        body.classList.remove("editor-drawer-open");
        syncPreviewFocusUi();
        return;
      }
      togglePreviewFocus(false);
      return;
    }
    const menu = $("settingsMenu");
    if (menu && !menu.hidden) {
      closeSettingsMenu();
      return;
    }
    if (!$("logoCropModal").classList.contains("hidden")) {
      closeLogoCropModal();
      return;
    }
    if (!$("loginModal").classList.contains("hidden")) {
      closeLoginModal();
      return;
    }
    if (!$("settingsModal").classList.contains("hidden")) {
      closeSettingsModal();
    }
  });

  $("presetSelect").addEventListener("change", async (e) => {
    try {
      const path = e.target.value;
      if (path) {
        state.config.bg_mode = "preset";
        state.config.bg_image_path = path;
      }
      renderUploadThumb("bg_image_path", state.config.bg_image_path || "");
      saveGuestDraft();
      await refreshPreview();
    } catch (e2) {
      showStatusError(e2.message || "背景切换失败");
    }
  });

  $("todayBtn").addEventListener("click", async () => {
    $("dateInput").value = "今天";
    saveGuestDraft();
    await refreshPreview();
  });

  $("tomorrowBtn").addEventListener("click", async () => {
    $("dateInput").value = "明天";
    saveGuestDraft();
    await refreshPreview();
  });

  $("formatBtn").addEventListener("click", async () => {
    try {
      const d = await api("/api/format", "POST", { content: $("contentInput").value });
      $("contentInput").value = d.content;
      syncMainPriceEditorFromContent();
      updateStats();
      saveGuestDraft();
      await refreshPreview();
    } catch (e) {
      showStatusError(e.message || "自动格式化失败");
    }
  });

  $("batchBtn").addEventListener("click", async () => {
    const raw = prompt("输入调整金额（如 +50 或 -30）", "+10");
    if (!raw) return;
    const cleaned = String(raw).trim().replace(/\s+/g, "").replace("＋", "+").replace("－", "-");
    const m = cleaned.match(/^([+-]?)(\d{1,5})$/);
    if (!m) {
      showStatusError("请输入有效金额，例如 +50 或 -30");
      return;
    }
    const sign = m[1] === "-" ? -1 : 1;
    const amount = sign * Number(m[2]);
    try {
      const d = await api("/api/batch-adjust", "POST", { content: $("contentInput").value, amount });
      $("contentInput").value = d.content;
      syncMainPriceEditorFromContent();
      updateStats();
      saveGuestDraft();
      await refreshPreview();
    } catch (e) {
      showStatusError(e.message || "批量调价失败");
    }
  });
  $("templateSelect").addEventListener("change", async (e) => {
    const selectedName = e.target.value;
    applyTemplateByName(selectedName);
    applyHolidayPresetIfNeeded(selectedName);
    syncEditorModeByTemplate();
    updateStats();
    saveGuestDraft();
    await refreshPreview();
  });

  $("saveTemplateBtn").addEventListener("click", () => {
    const name = prompt("请输入模板名称");
    if (!name) return;
    const trimmed = name.trim();
    if (!trimmed) return;

    state.config.custom_templates ||= {};
    state.config.custom_templates[trimmed] = $("contentInput").value;

    if (![...$("templateSelect").options].find((o) => o.value === trimmed)) {
      $("templateSelect").add(new Option(trimmed, trimmed));
    }
    $("templateSelect").value = trimmed;
    syncEditorModeByTemplate();
    saveGuestDraft();
  });

  $("deleteTemplateBtn").addEventListener("click", () => {
    const name = $("templateSelect").value;
    if (state.systemTemplates[name]) {
      alert("系统模板不可删除");
      return;
    }
    delete state.config.custom_templates[name];
    $("templateSelect").querySelector(`option[value="${name}"]`)?.remove();
    if ($("templateSelect").options.length > 0) {
      $("templateSelect").value = $("templateSelect").options[0].value;
      applyTemplateByName($("templateSelect").value);
      syncEditorModeByTemplate();
      updateStats();
    }
    saveGuestDraft();
  });

  $("saveConfigBtn").addEventListener("click", async () => {
    const btn = $("saveConfigBtn");
    setButtonBusy(btn, true, "保存中...");
    try {
      state.config = buildConfigPayloadForSave();
      saveGuestDraft();
      const d = await api("/api/config", "POST", state.config);
      state.config = d.config;
      $("statusText").textContent = withGuestHint("设置已保存");
      closeSettingsModal();
      await refreshPreview();
    } catch (e) {
      showStatusError(e.message || "保存设置失败");
    } finally {
      setButtonBusy(btn, false);
    }
  });

  $("logoUpload").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      if (!String(file.type || "").startsWith("image/")) {
        throw new Error("仅支持图片文件");
      }
      if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
        throw new Error(`图片不能超过 ${MAX_UPLOAD_MB}MB`);
      }
      openLogoCropModal(file);
    } catch (e2) {
      showStatusError(e2.message || "Logo 选择失败");
      e.target.value = "";
    }
  });

  [["bgUpload", "bg_image_path", "custom"], ["stampUpload", "stamp_image_path"], ["qrUpload", "qrcode_image_path"]].forEach(([id, key, mode]) => {
    $(id).addEventListener("change", async (e) => {
      try {
        await uploadFile(e.target, key);
        if (mode === "custom") state.config.bg_mode = "custom";
        await refreshPreview();
      } catch (e2) {
        showStatusError(e2.message || "上传失败");
      } finally {
        e.target.value = "";
      }
    });
  });

  $("generateBtn").addEventListener("click", async () => {
    const btn = $("generateBtn");
    setButtonBusy(btn, true, "生成中...");
    const payload = {
      title: $("titleInput").value.trim(),
      date: $("dateInput").value.trim(),
      content: $("contentInput").value,
      config: formConfig(),
      export_format: $("exportFormat").value,
    };

    try {
      const d = await api("/api/generate", "POST", payload);
      const mode = $("copyMode").value;
      const downloadUrl = toDownloadUrl(d.file);

      if (mode.includes("文案")) {
        await navigator.clipboard.writeText(d.copy_text);
      }

      if (mode.includes("图片")) {
        const resp = await fetch(downloadUrl);
        if (resp.ok) {
          const blob = await resp.blob();
          try {
            await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
          } catch (_) {}
        }
      }

      window.open(downloadUrl, "_blank");
      $("statusText").textContent = withGuestHint(`已生成 ${d.name}`);
      if (state.isGuest && !state.guestRegisterTipShown) {
        state.guestRegisterTipShown = true;
        alert("已生成成功。建议注册一个用户：可以保存设置和内容，下次可直接继续使用。");
      }
    } catch (e) {
      showStatusError(e.message || "生成失败");
    } finally {
      setButtonBusy(btn, false);
    }
  });

  syncEditorModeByTemplate();
  await refreshPreview();
  syncSettingsPaneHeight();
  syncFooterNoteVisibility();
  syncTopbarCompactOnScroll();
  showSettingsFirstUseTip();
}

init().catch((e) => {
  $("statusText").textContent = `初始化失败: ${e.message}`;
});






