const TOKEN_KEY = "poster_admin_token_v1";
const DIALOG_EMPTY = () => {};
const dialogState = {
  resolver: DIALOG_EMPTY,
  mode: "alert",
};

function $(id) {
  return document.getElementById(id);
}

function getToken() {
  return ($("tokenInput").value || "").trim();
}

function setStatus(text, level = "") {
  const el = $("statusText");
  el.textContent = text;
  el.className = `status ${level}`.trim();
}

function saveToken(token) {
  if (!token) return;
  localStorage.setItem(TOKEN_KEY, token);
}

function loadToken() {
  $("tokenInput").value = localStorage.getItem(TOKEN_KEY) || "";
}

function openDialog(options = {}) {
  const modal = $("adminDialogModal");
  const title = $("adminDialogTitle");
  const message = $("adminDialogMessage");
  const input = $("adminDialogInput");
  const confirmBtn = $("adminDialogConfirmBtn");
  const cancelBtn = $("adminDialogCancelBtn");
  if (!modal || !title || !message || !input || !confirmBtn || !cancelBtn) {
    return Promise.resolve(null);
  }

  const mode = options.mode || "alert";
  dialogState.mode = mode;
  title.textContent = options.title || "提示";
  message.textContent = options.message || "";
  confirmBtn.textContent = options.confirmText || "确定";
  cancelBtn.textContent = options.cancelText || "取消";
  cancelBtn.hidden = mode === "alert";
  input.hidden = mode !== "prompt";
  input.value = options.defaultValue || "";
  input.placeholder = options.placeholder || "";

  modal.classList.remove("hidden");
  document.body.classList.add("no-scroll");

  if (mode === "prompt") {
    setTimeout(() => input.focus(), 0);
  } else {
    setTimeout(() => confirmBtn.focus(), 0);
  }

  return new Promise((resolve) => {
    dialogState.resolver = resolve;
  });
}

function closeDialog(result = null) {
  const modal = $("adminDialogModal");
  if (!modal || modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  document.body.classList.remove("no-scroll");
  const resolve = dialogState.resolver || DIALOG_EMPTY;
  dialogState.resolver = DIALOG_EMPTY;
  resolve(result);
}

async function appConfirm(message, title = "请确认") {
  const ret = await openDialog({
    mode: "confirm",
    title,
    message,
    confirmText: "确认",
    cancelText: "取消",
  });
  return ret === true;
}

async function appPrompt(message, defaultValue = "", title = "请输入", placeholder = "") {
  const ret = await openDialog({
    mode: "prompt",
    title,
    message,
    defaultValue,
    placeholder,
    confirmText: "确定",
    cancelText: "取消",
  });
  if (!ret || ret.action !== "confirm") return null;
  return ret.value;
}

async function adminFetch(path, opts = {}) {
  const token = getToken();
  if (!token) throw new Error("请先输入管理员令牌");
  const headers = { ...(opts.headers || {}), "X-Admin-Token": token };
  const resp = await fetch(path, { ...opts, headers });
  const type = String(resp.headers.get("content-type") || "").toLowerCase();
  if (!resp.ok) {
    if (type.includes("application/json")) {
      const err = await resp.json();
      throw new Error(err.error || `请求失败 (${resp.status})`);
    }
    throw new Error(`请求失败 (${resp.status})`);
  }
  return resp;
}

async function adminJson(path, opts = {}) {
  const resp = await adminFetch(path, opts);
  return resp.json();
}

function renderUsers(rows) {
  const body = $("usersBody");
  if (!Array.isArray(rows) || !rows.length) {
    body.innerHTML = '<tr><td colspan="8" style="color:#6b7280;">暂无数据</td></tr>';
    return;
  }
  body.innerHTML = rows
    .map(
      (x) => `
      <tr>
        <td class="mono">${x.user_id || ""}</td>
        <td>${x.display_user_id || ""}</td>
        <td>${x.is_guest ? "是" : "否"}</td>
        <td>${x.has_password ? "是" : "否"}</td>
        <td>${x.has_config ? "是" : "否"}</td>
        <td>${Number(x.output_count || 0)}</td>
        <td class="mono">${x.last_active || "-"}</td>
        <td>
          <button type="button" class="row-op" data-op="password" data-user="${x.user_id}">重置密码</button>
          <button type="button" class="row-op" data-op="config" data-user="${x.user_id}">编辑配置</button>
          <button type="button" class="row-op row-op-danger" data-op="delete" data-user="${x.user_id}">删除</button>
        </td>
      </tr>`
    )
    .join("");
}

async function refreshUsers() {
  saveToken(getToken());
  setStatus("加载用户中...");
  const data = await adminJson("/api/admin/users");
  renderUsers(data.users || []);
  $("totalText").textContent = `总数 ${Number(data.total || 0)}`;
  setStatus(`已加载 ${Number(data.total || 0)} 个用户`, "ok");
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function downloadFile(path, fallbackName) {
  const resp = await adminFetch(path);
  const blob = await resp.blob();
  const dispo = String(resp.headers.get("content-disposition") || "");
  const m = dispo.match(/filename\*?=(?:UTF-8''|\"?)([^\";]+)/i);
  const name = m ? decodeURIComponent(m[1].replace(/"/g, "")) : fallbackName;
  triggerDownload(blob, name);
}

async function handleResetPassword(userId) {
  const password = await appPrompt(`给用户 ${userId} 设置新密码（至少4位）：`, "", "重置密码", "至少 4 位");
  if (password === null) return;
  await adminJson(`/api/admin/users/${encodeURIComponent(userId)}/password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  setStatus(`用户 ${userId} 密码已更新`, "ok");
}

async function handleEditConfig(userId) {
  const raw = await appPrompt(
    `输入用户 ${userId} 的配置 JSON 补丁（merge 模式），例如：{"shop_name":"新店名"}`,
    "{}",
    "编辑配置",
    '{"shop_name":"新店名"}'
  );
  if (raw === null) return;
  let cfg;
  try {
    cfg = JSON.parse(raw);
  } catch (_) {
    throw new Error("JSON 格式不正确");
  }
  if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) {
    throw new Error("配置必须是 JSON 对象");
  }
  await adminJson(`/api/admin/users/${encodeURIComponent(userId)}/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "merge", config: cfg }),
  });
  setStatus(`用户 ${userId} 配置已更新`, "ok");
}

async function handleDeleteUser(userId) {
  const sure = await appConfirm(`确定删除用户 ${userId} 吗？会删除账号和配置。`, "删除用户");
  if (!sure) return;
  const includeOutputs = await appConfirm(
    "是否同时删除该用户导出文件？确认=删除，取消=保留。",
    "删除导出文件"
  );
  await adminJson(`/api/admin/users/${encodeURIComponent(userId)}?include_outputs=${includeOutputs ? 1 : 0}`, {
    method: "DELETE",
  });
  setStatus(`用户 ${userId} 已删除`, "ok");
  await refreshUsers();
}

async function handleCleanupGuests(includeOutputs) {
  const days = Number(($("cleanupDaysInput").value || "30").trim());
  if (!Number.isFinite(days) || days < 0 || days > 3650) {
    throw new Error("天数范围应在 0-3650");
  }
  const data = await adminJson("/api/admin/guests/cleanup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days, include_outputs: includeOutputs }),
  });
  setStatus(`已清理 ${data.removed_count || 0} 个访客账号`, "ok");
  await refreshUsers();
}

function wireActions() {
  $("adminDialogConfirmBtn")?.addEventListener("click", () => {
    if (dialogState.mode === "prompt") {
      closeDialog({ action: "confirm", value: ($("adminDialogInput").value || "").trim() });
      return;
    }
    closeDialog(true);
  });
  $("adminDialogCancelBtn")?.addEventListener("click", () => closeDialog(false));
  $("adminDialogMask")?.addEventListener("click", () => closeDialog(false));
  $("adminDialogInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      closeDialog({ action: "confirm", value: ($("adminDialogInput").value || "").trim() });
    }
  });

  $("loadUsersBtn").addEventListener("click", async () => {
    try {
      await refreshUsers();
    } catch (e) {
      setStatus(e.message || "加载失败", "err");
    }
  });

  $("exportJsonBtn").addEventListener("click", async () => {
    try {
      setStatus("请求导出数据中...");
      const data = await adminJson("/api/admin/export");
      void data;
      setStatus("导出接口请求成功", "ok");
    } catch (e) {
      setStatus(e.message || "导出失败", "err");
    }
  });

  $("downloadExportBtn").addEventListener("click", async () => {
    try {
      setStatus("准备下载 JSON...");
      await downloadFile("/api/admin/export?download=1", "poster_export.json");
      setStatus("JSON 下载完成", "ok");
    } catch (e) {
      setStatus(e.message || "下载失败", "err");
    }
  });

  $("downloadBackupBtn").addEventListener("click", async () => {
    try {
      setStatus("准备下载完整备份...");
      await downloadFile("/api/admin/backup", "poster_backup.zip");
      setStatus("完整备份下载完成", "ok");
    } catch (e) {
      setStatus(e.message || "下载失败", "err");
    }
  });

  $("downloadLiteBackupBtn").addEventListener("click", async () => {
    try {
      setStatus("准备下载轻量备份...");
      await downloadFile("/api/admin/backup?include_outputs=0", "poster_backup_lite.zip");
      setStatus("轻量备份下载完成", "ok");
    } catch (e) {
      setStatus(e.message || "下载失败", "err");
    }
  });

  $("cleanupGuestsBtn").addEventListener("click", async () => {
    try {
      await handleCleanupGuests(false);
    } catch (e) {
      setStatus(e.message || "清理失败", "err");
    }
  });

  $("cleanupGuestsWithOutputsBtn").addEventListener("click", async () => {
    try {
      const ok = await appConfirm("此操作会删除访客导出文件，是否继续？", "清理确认");
      if (!ok) return;
      await handleCleanupGuests(true);
    } catch (e) {
      setStatus(e.message || "清理失败", "err");
    }
  });

  $("usersBody").addEventListener("click", async (e) => {
    const btn = e.target.closest(".row-op");
    if (!btn) return;
    const userId = String(btn.getAttribute("data-user") || "");
    const op = String(btn.getAttribute("data-op") || "");
    if (!userId || !op) return;
    try {
      if (op === "password") await handleResetPassword(userId);
      if (op === "config") await handleEditConfig(userId);
      if (op === "delete") await handleDeleteUser(userId);
    } catch (err) {
      setStatus(err.message || "操作失败", "err");
    }
  });
}

function init() {
  loadToken();
  wireActions();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDialog(false);
  });
}

init();
