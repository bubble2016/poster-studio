const state = {
  config: {},
  presets: [],
  systemTemplates: {},
  currentUser: "",
  isGuest: true,
  guestRegisterTipShown: false,
};

const $ = (id) => document.getElementById(id);

function getStats(text) {
  const chars = (text || "").replace(/\s/g, "").length;
  const lines = (text || "").split("\n").filter((x) => x.trim()).length;
  return `${chars} 字 · ${lines} 行`;
}

function updateStats() {
  $("statsText").textContent = getStats($("contentInput").value);
}

async function api(url, method = "GET", body = null) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
function updateUserBadge() {
  const el = $("userBadge");
  if (!el) return;
  if (!state.currentUser) {
    el.textContent = "未登录";
    return;
  }
  el.textContent = state.isGuest ? `访客：${state.currentUser}` : `用户：${state.currentUser}`;
}

function withGuestHint(baseText) {
  return state.isGuest ? `${baseText}（访客模式，建议注册：可保存设置和内容）` : baseText;
}

async function ensureLogin() {
  const me = await api("/api/me");
  state.currentUser = me.display_user_id || me.user_id || "";
  state.isGuest = !!me.is_guest;
  updateUserBadge();
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

function openSettingsModal() {
  $("settingsModal").classList.remove("hidden");
  document.body.classList.add("no-scroll");
  switchSettingsTab("base");
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
    copy_mode: $("copyMode").value,
    export_format: $("exportFormat").value,
  };
}

function bindFromConfig(cfg) {
  $("titleInput").value = cfg.last_title || "调价通知";
  $("dateInput").value = cfg.last_date || "今天";
  $("contentInput").value = cfg.last_content || "";

  $("themeColor").value = cfg.theme_color || "#B22222";
  $("cardStyle").value = cfg.card_style || "fold";
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
  $("copyMode").value = cfg.copy_mode || "复制图片";
  $("exportFormat").value = cfg.export_format || "PNG";

  updateStats();
}

function applyTemplateByName(name) {
  if (state.systemTemplates[name]) {
    $("contentInput").value = state.systemTemplates[name][0] || "";
    $("titleInput").value = state.systemTemplates[name][1] || $("titleInput").value;
    return true;
  }
  if (state.config.custom_templates?.[name]) {
    $("contentInput").value = state.config.custom_templates[name] || "";
    return true;
  }
  return false;
}

function getHolidayPresetPath() {
  const byPath = state.presets.find((p) => /preset_luxury_red\.png$/i.test(p.path || ""));
  if (byPath) return byPath.path;
  const byName = state.presets.find((p) => (p.name || "").includes("故宫红"));
  return byName?.path || "";
}

function shouldUseHolidayPreset(templateName, titleText) {
  const text = `${templateName || ""} ${titleText || ""}`;
  return text.includes("放假");
}

function applyHolidayPresetIfNeeded(templateName) {
  if (!shouldUseHolidayPreset(templateName, $("titleInput").value)) return;
  const holidayPath = getHolidayPresetPath();
  if (!holidayPath) return;
  $("presetSelect").value = holidayPath;
  state.config.bg_mode = "preset";
  state.config.bg_image_path = holidayPath;
}

async function uploadFile(inputEl, key) {
  const file = inputEl.files?.[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "上传失败");
  state.config[key] = data.path;
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
  const data = await api("/api/preview", "POST", payload);
  $("previewImage").src = data.image;
  $("dateInput").value = data.date || $("dateInput").value;
  $("statusText").textContent = !data.valid && data.warnings.length ? data.warnings[0] : "预览已更新";
}

function debounce(fn, delay = 500) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

async function init() {
  updateUserBadge();
  await ensureLogin();
  setPreviewLoading("正在生成预览...");
  $("previewImage").addEventListener("load", setPreviewLoaded);
  $("previewImage").addEventListener("error", () => {
    setPreviewLoading("预览加载失败，请重试");
  });

  const data = await api("/api/init");
  state.config = data.config;
  state.systemTemplates = data.system_templates || {};
  state.presets = data.presets || [];

  bindFromConfig(state.config);

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
    await refreshPreview();
  }, 650);

  const watchIds = [
    "titleInput", "dateInput", "contentInput",
    "shopName", "phone", "address", "slogan",
    "themeColor", "cardStyle", "bgBlur", "bgBrightness",
    "cardOpacity", "stampOpacity", "watermarkEnabled",
    "watermarkText", "watermarkOpacity", "copyMode", "exportFormat",
  ];

  watchIds.forEach((id) => {
    $(id).addEventListener("input", onType);
    $(id).addEventListener("change", onType);
  });

  $("openSettingsBtn").addEventListener("click", openSettingsModal);
  $("switchUserBtn")?.addEventListener("click", openLoginModal);
  $("closeSettingsBtn").addEventListener("click", closeSettingsModal);
  $("closeSettingsBtn2").addEventListener("click", closeSettingsModal);
  $("settingsMask").addEventListener("click", closeSettingsModal);
  $("closeLoginBtn").addEventListener("click", closeLoginModal);
  $("cancelLoginBtn").addEventListener("click", closeLoginModal);
  $("loginMask").addEventListener("click", closeLoginModal);
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
    try {
      const d = await api("/api/login", "POST", { user_id: userId, password, merge_from_current: true });
      state.currentUser = d.display_user_id || d.user_id || userId;
      state.isGuest = !!d.is_guest;
      updateUserBadge();
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

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("loginModal").classList.contains("hidden")) {
      closeLoginModal();
      return;
    }
    if (!$("settingsModal").classList.contains("hidden")) {
      closeSettingsModal();
    }
  });

  $("presetSelect").addEventListener("change", async (e) => {
    const path = e.target.value;
    if (path) {
      state.config.bg_mode = "preset";
      state.config.bg_image_path = path;
    }
    await refreshPreview();
  });

  $("todayBtn").addEventListener("click", async () => {
    $("dateInput").value = "今天";
    await refreshPreview();
  });

  $("tomorrowBtn").addEventListener("click", async () => {
    $("dateInput").value = "明天";
    await refreshPreview();
  });

  $("previewBtn").addEventListener("click", refreshPreview);

  $("formatBtn").addEventListener("click", async () => {
    const d = await api("/api/format", "POST", { content: $("contentInput").value });
    $("contentInput").value = d.content;
    updateStats();
    await refreshPreview();
  });

  $("batchBtn").addEventListener("click", async () => {
    const raw = prompt("输入调整金额（如 +50 或 -30）", "+10");
    if (!raw) return;
    const amount = Number(raw.replace("+", "").trim()) * (raw.trim().startsWith("-") ? -1 : 1);
    if (Number.isNaN(amount)) return;
    const d = await api("/api/batch-adjust", "POST", { content: $("contentInput").value, amount });
    $("contentInput").value = d.content;
    updateStats();
    await refreshPreview();
  });

  $("templateSelect").addEventListener("change", async (e) => {
    const selectedName = e.target.value;
    applyTemplateByName(selectedName);
    applyHolidayPresetIfNeeded(selectedName);
    updateStats();
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
      updateStats();
    }
  });

  $("saveConfigBtn").addEventListener("click", async () => {
    state.config = { ...formConfig(), custom_templates: state.config.custom_templates || {} };
    state.config.last_title = $("titleInput").value.trim();
    state.config.last_date = $("dateInput").value.trim();
    state.config.last_content = $("contentInput").value;

    const d = await api("/api/config", "POST", state.config);
    state.config = d.config;
    $("statusText").textContent = withGuestHint("设置已保存");
    closeSettingsModal();
    await refreshPreview();
  });

  [["bgUpload", "bg_image_path", "custom"], ["logoUpload", "logo_image_path"], ["stampUpload", "stamp_image_path"], ["qrUpload", "qrcode_image_path"]].forEach(([id, key, mode]) => {
    $(id).addEventListener("change", async (e) => {
      await uploadFile(e.target, key);
      if (mode === "custom") state.config.bg_mode = "custom";
      await refreshPreview();
    });
  });

  $("generateBtn").addEventListener("click", async () => {
    const payload = {
      title: $("titleInput").value.trim(),
      date: $("dateInput").value.trim(),
      content: $("contentInput").value,
      config: formConfig(),
      export_format: $("exportFormat").value,
    };

    const d = await api("/api/generate", "POST", payload);
    const mode = $("copyMode").value;

    if (mode.includes("文案")) {
      await navigator.clipboard.writeText(d.copy_text);
    }

    if (mode.includes("图片")) {
      const resp = await fetch(`/download/${d.file}`);
      const blob = await resp.blob();
      try {
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
      } catch (_) {}
    }

    window.open(`/download/${d.file}`, "_blank");
    $("statusText").textContent = withGuestHint(`已生成 ${d.name}`);
    if (state.isGuest && !state.guestRegisterTipShown) {
      state.guestRegisterTipShown = true;
      alert("已生成成功。建议注册一个用户：可以保存设置和内容，下次可直接继续使用。");
    }
  });

  await refreshPreview();
}

init().catch((e) => {
  $("statusText").textContent = `初始化失败: ${e.message}`;
});





