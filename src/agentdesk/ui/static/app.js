/* AgentDesk 工作台前端逻辑（原生 JS，无构建） */
"use strict";

const $ = (sel) => document.querySelector(sel);

const api = {
  get: async (url) => {
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  post: async (url, body = {}) => {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  del: async (url) => {
    const res = await fetch(url, { method: "DELETE" });
    return res.json();
  },
};

const state = {
  sessionId: null,
  taskId: null,
  ws: null,
  pendingConfirm: null,
  running: false,
};

/* ---------- 工具函数 ---------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fmtSize(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}
function renderTableHtml(r) {
  if (!r || !r.columns) return "";
  const cols = r.columns, rows = r.preview || [];
  let h = '<div class="table-wrap"><table class="table table-sm table-striped"><thead><tr>';
  h += cols.map((c) => `<th>${esc(c)}</th>`).join("");
  h += "</tr></thead><tbody>";
  for (const row of rows) {
    h += "<tr>" + cols.map((c) => `<td>${esc(row[c] ?? "")}</td>`).join("") + "</tr>";
  }
  h += "</tbody></table></div>";
  return h;
}

/* ---------- 顶部状态 ---------- */
async function loadStatus() {
  const s = await api.get("/api/status");
  $("#meta-model").textContent = "模型 " + s.model;
  $("#meta-search").textContent = "搜索 " + s.search_provider;
  $("#meta-workspace").textContent = s.workspace;
  $("#meta-workspace").title = s.workspace;
}

/* ---------- 会话 ---------- */
async function loadSessions() {
  const list = await api.get("/api/sessions");
  const el = $("#session-list");
  el.innerHTML = "";
  for (const s of list) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === state.sessionId ? " active" : "");
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = s.title;
    item.appendChild(text);
    const del = document.createElement("button");
    del.className = "session-del";
    del.textContent = "×";
    del.title = "删除会话";
    del.onclick = async (e) => {
      e.stopPropagation();
      await api.del("/api/sessions/" + s.id);
      if (state.sessionId === s.id) state.sessionId = null;
      await loadSessions();
    };
    item.appendChild(del);
    item.onclick = () => selectSession(s.id, s.title);
    el.appendChild(item);
  }
  if (!state.sessionId && list.length) selectSession(list[0].id, list[0].title);
}

async function selectSession(id) {
  state.sessionId = id;
  if (state.ws) { state.ws.close(); state.ws = null; }
  state.taskId = null;
  state.running = false;
  $("#chat").innerHTML = "";
  $("#run-log").innerHTML = "";
  $("#plan-list").innerHTML = "";
  $("#accept-panel").innerHTML = "";
  await loadSessions();
  await loadMessages(id);
  await loadFiles();
  await loadBackups();
  await updateCost(id);
}

async function loadMessages(id) {
  const msgs = await api.get(`/api/sessions/${id}/messages`);
  const chat = $("#chat");
  chat.innerHTML = "";
  for (const m of msgs) appendMessage(m.role, m.content);
  chat.scrollTop = chat.scrollHeight;
}

function appendMessage(role, content) {
  const chat = $("#chat");
  const wrap = document.createElement("div");
  wrap.className = "msg " + (role === "user" ? "msg-user" : "msg-agent");
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = content;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

/* ---------- 任务 ---------- */
async function sendTask() {
  const text = $("#input").value.trim();
  if (!text) return;
  if (!state.sessionId) {
    await api.post("/api/sessions", { title: "新会话" });
    await loadSessions();
  }
  if (!state.sessionId) return;
  $("#input").value = "";
  appendMessage("user", text);
  setRunning(true);
  $("#run-log").innerHTML = "";
  $("#plan-list").innerHTML = "";
  $("#accept-panel").innerHTML = "";
  try {
    const res = await api.post(`/api/sessions/${state.sessionId}/tasks`, { request: text });
    state.taskId = res.task_id;
    connectWS(state.taskId);
  } catch (e) {
    appendMessage("agent", "⚠ 任务启动失败：" + e.message);
    setRunning(false);
  }
}

function setRunning(running) {
  state.running = running;
  $("#btn-send").disabled = running;
  $("#btn-stop").disabled = !running;
  $("#task-status").textContent = running ? "⏳ 任务执行中…" : "";
}

/* ---------- WebSocket 实时事件 ---------- */
function connectWS(taskId) {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${taskId}`);
  state.ws = ws;
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    handleEvent(msg);
  };
  ws.onclose = () => {
    if (state.taskId === taskId) setRunning(false);
  };
  ws.onerror = () => ws.close();
}

function handleEvent(msg) {
  const { type, data } = msg;
  switch (type) {
    case "plan": renderPlan(data.plan); break;
    case "tool_start": logTool("start", data); break;
    case "tool_end":
      logTool(data.status, data);
      break;
    case "needs_confirm": handleNeedsConfirm(data); break;
    case "message": appendMessage("agent", data.content); break;
    case "done":
    case "stopped": finishTask(type, data); break;
    case "error":
      appendMessage("agent", "⚠ " + data.error);
      setRunning(false);
      break;
  }
}

/* ---------- 执行面板 ---------- */
function logTool(status, data) {
  const log = $("#run-log");
  const card = document.createElement("div");
  card.className = "tool-card " + (status === "start" ? "start" : status);
  const badge = {
    start: '<span class="badge text-bg-primary">执行中</span>',
    success: '<span class="badge text-bg-success">成功</span>',
    failed: '<span class="badge text-bg-danger">失败</span>',
    waiting_confirm: '<span class="badge text-bg-warning">待确认</span>',
  }[status] || `<span class="badge text-bg-secondary">${esc(status)}</span>`;

  const head = document.createElement("div");
  head.className = "tool-head";
  head.innerHTML = `<code>${esc(data.name)}</code>${badge}`;
  if (data.duration != null) {
    const t = document.createElement("span");
    t.className = "ms-auto text-secondary small";
    t.textContent = data.duration + "s";
    head.appendChild(t);
  }
  card.appendChild(head);
  if (data.args && Object.keys(data.args).length) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(data.args, null, 2);
    card.appendChild(pre);
  }
  if (data.summary) {
    const p = document.createElement("p");
    p.textContent = data.summary;
    card.appendChild(p);
  }
  if (data.files && data.files.length) {
    const p = document.createElement("p");
    p.className = "text-secondary small";
    p.textContent = "产出: " + data.files.join(", ");
    card.appendChild(p);
  }
  log.prepend(card);
  log.scrollTop = 0;
}

function renderPlan(plan) {
  const el = $("#plan-list");
  el.innerHTML = "";
  if (!plan || !plan.length) {
    el.innerHTML = '<p class="text-secondary small">暂无计划</p>';
    return;
  }
  plan.forEach((s, i) => {
    const item = document.createElement("div");
    item.className = "plan-step";
    item.innerHTML = `<span class="plan-num">${i + 1}</span><span>${esc(s.goal)}</span>`;
    if (s.tool) item.innerHTML += `<code class="ms-auto">${esc(s.tool)}</code>`;
    el.appendChild(item);
  });
}

/* ---------- 确认弹窗 ---------- */
function showConfirm(reason) {
  $("#confirm-reason").textContent = reason || "操作需要确认";
  $("#confirm-args").textContent = "";
  const modal = new bootstrap.Modal($("#confirm-modal"));
  modal.show();
}

$("#btn-confirm-yes").onclick = async () => {
  hideModal();
  if (state.taskId) {
    try { await api.post(`/api/tasks/${state.taskId}/confirm`, { call_id: state.pendingConfirm }); }
    catch (e) { appendMessage("agent", "⚠ 确认失败：" + e.message); setRunning(false); }
  }
  state.pendingConfirm = null;
};
$("#btn-confirm-no").onclick = async () => {
  hideModal();
  if (state.taskId) {
    try { await api.post(`/api/tasks/${state.taskId}/reject`, { call_id: state.pendingConfirm }); }
    catch (e) { appendMessage("agent", "⚠ 操作失败：" + e.message); setRunning(false); }
  }
  state.pendingConfirm = null;
};
function hideModal() {
  const modal = bootstrap.Modal.getInstance($("#confirm-modal"));
  if (modal) modal.hide();
}

/* needs_confirm 事件里带上 call_id（事件 data 有 call_id） */
function handleNeedsConfirm(data) {
  state.pendingConfirm = data.call_id;
  showConfirm(data.reason);
}

/* ---------- 任务结束 / 验收 ---------- */
async function finishTask(type, data) {
  setRunning(false);
  appendMessage("agent", data.summary || (type === "done" ? "任务完成 ✅" : "任务已停止"));
  if (state.taskId) {
    await renderAccept(state.taskId);
    await loadFiles();
    await loadBackups();
    await updateCost(state.sessionId);
  }
}

async function renderAccept(taskId) {
  const r = await api.get("/api/tasks/" + taskId);
  const el = $("#accept-panel");
  const badge = {
    done: "text-bg-success", stopped: "text-bg-warning",
    failed: "text-bg-danger", waiting_confirm: "text-bg-warning",
  }[r.status] || "text-bg-secondary";
  let html = `<div class="accept-head">
    <span class="badge ${badge}">${esc(r.status)}</span>
    <span class="ms-auto text-secondary small">${r.steps} 步 · ¥${Number(r.cost_yuan).toFixed(4)}</span>
  </div>`;
  html += `<p class="mt-2">${esc(r.summary)}</p>`;
  if (r.files && r.files.length) {
    html += "<div class='fw-bold mt-2'>产出文件</div><ul>";
    html += r.files.map((f) => `<li><code>${esc(f)}</code></li>`).join("");
    html += "</ul>";
  }
  html += "<div class='fw-bold mt-2'>工具调用</div>";
  for (const c of r.tool_calls || []) {
    const cb = { success: "text-bg-success", failed: "text-bg-danger" }[c.status] || "text-bg-secondary";
    html += `<details class="tool-detail"><summary><code>${esc(c.name)}</code>` +
      `<span class="badge ${cb}">${esc(c.status)}</span>` +
      `<span class="text-secondary small">${Number(c.duration_s).toFixed(2)}s</span></summary>`;
    if (c.result && c.result.preview) html += renderTableHtml(c.result);
    if (c.result) html += `<pre>${esc(JSON.stringify(c.result, null, 2).slice(0, 2000))}</pre>`;
    html += "</details>";
  }
  el.innerHTML = html;
}

/* ---------- 文件面板 ---------- */
async function loadFiles() {
  try {
    const data = await api.get("/api/workspace/files?path=.");
    const el = $("#file-tree");
    el.innerHTML = "";
    for (const e of data.entries || []) {
      const row = document.createElement("div");
      row.className = "file-row";
      const size = e.type === "file" ? fmtSize(e.size) : "";
      row.innerHTML = `<span class="file-icon">${e.type === "dir" ? "📁" : "📄"}</span>` +
        `<span>${esc(e.name)}</span><span class="ms-auto text-secondary small">${size}</span>`;
      el.appendChild(row);
    }
  } catch (e) {
    $("#file-tree").innerHTML = `<p class="text-danger small">${esc(e.message)}</p>`;
  }
}

const dz = $("#file-upload");
const fileInput = $("#file-input");
dz.onclick = () => fileInput.click();
dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("dragover"); };
dz.ondragleave = () => dz.classList.remove("dragover");
dz.ondrop = (e) => {
  e.preventDefault();
  dz.classList.remove("dragover");
  uploadFiles(e.dataTransfer.files);
};
fileInput.onchange = () => { uploadFiles(fileInput.files); fileInput.value = ""; };

async function uploadFiles(files) {
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    if (!res.ok) alert("上传失败：" + (await res.text()));
  }
  await loadFiles();
}

/* ---------- 撤销面板 ---------- */
async function loadBackups() {
  const list = await api.get("/api/backups");
  const el = $("#undo-list");
  el.innerHTML = "";
  if (!list.length) {
    el.innerHTML = '<p class="text-secondary small">暂无备份。Agent 覆盖/删除文件时会自动备份，可一键恢复。</p>';
    return;
  }
  for (const b of list) {
    const row = document.createElement("div");
    row.className = "backup-row";
    row.innerHTML = `<code>${esc(b.src_rel)}</code>` +
      `<span class="text-secondary small">${esc(b.op)} · ${esc(b.created_at)}</span>` +
      (b.restored ? '<span class="badge text-bg-success ms-auto">已恢复</span>' : "");
    if (!b.restored) {
      const btn = document.createElement("button");
      btn.className = "btn btn-sm btn-outline-danger ms-auto";
      btn.textContent = "恢复";
      btn.onclick = async () => {
        try {
          await api.post(`/api/backups/${b.id}/restore`);
          await loadBackups();
          await loadFiles();
        } catch (e) { alert("恢复失败：" + e.message); }
      };
      row.appendChild(btn);
    }
    el.appendChild(row);
  }
}

/* ---------- 成本 ---------- */
async function updateCost(sid) {
  if (!sid) return;
  const tasks = await api.get(`/api/sessions/${sid}/tasks`);
  const total = tasks.reduce((s, t) => s + (t.cost_yuan || 0), 0);
  $("#total-cost").textContent = "¥" + total.toFixed(4);
}

/* ---------- 顶栏与输入 ---------- */
$("#btn-new-session").onclick = async () => {
  await api.post("/api/sessions", { title: "新会话" });
  await loadSessions();
};

$("#btn-export").onclick = async () => {
  if (!state.sessionId) return;
  const res = await fetch(`/api/sessions/${state.sessionId}/export?fmt=md`);
  const text = await res.text();
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "agentdesk-report-" + state.sessionId + ".md";
  a.click();
  URL.revokeObjectURL(a.href);
};

$("#btn-stop").onclick = async () => {
  if (state.taskId) {
    try { await api.post(`/api/tasks/${state.taskId}/cancel`); } catch (e) { /* 忽略 */ }
  }
};

$("#task-template").onchange = (e) => {
  const v = e.target.value;
  if (v) { $("#input").value = v; e.target.value = ""; $("#input").focus(); }
};

$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#btn-send").click();
  }
});
$("#btn-send").onclick = sendTask;

/* ---------- 启动 ---------- */
(async function init() {
  try {
    await loadStatus();
    await loadSessions();
  } catch (e) {
    $("#chat").innerHTML = `<div class="msg"><div class="msg-bubble text-danger">后端初始化失败：${esc(e.message)}</div></div>`;
  }
})();
