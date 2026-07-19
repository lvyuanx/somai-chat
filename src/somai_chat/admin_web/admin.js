const login = document.querySelector("#login");
const consoleView = document.querySelector("#console");
const view = document.querySelector("#view");
const title = document.querySelector("#title");
const loginError = document.querySelector("#login-error");

let csrf = "";
let chatSocket = null;
let chatResponse = null;

async function api(path, options = {}) {
  const response = await fetch(`/api/v1/admin${path}`, {
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf, ...options.headers},
    ...options,
  });
  if (!response.ok) throw new Error((await response.json()).detail || "请求失败");
  return response.status === 204 ? null : response.json();
}

function showOverview() {
  title.textContent = "控制总览";
  view.innerHTML = "<p class=\"overview-copy\">管理机器人客户端凭证，并从 Chat 工作区调试对话服务。</p>";
}

async function showClients() {
  title.textContent = "客户端管理";
  const clients = await api("/clients");
  view.innerHTML = `<div class="toolbar"><button id="new" type="button">创建客户端</button></div>
    <table class="clients"><tr><th>名称</th><th>状态</th><th>操作</th></tr>
    ${clients.map((client) => `<tr><td>${client.name}</td><td>${client.enabled ? "启用" : "停用"}</td>
      <td><button data-id="${client.id}" data-enabled="${client.enabled}" type="button">${client.enabled ? "停用" : "启用"}</button></td></tr>`).join("")}</table>`;
  document.querySelector("#new").onclick = showCreateClient;
  document.querySelectorAll("[data-id]").forEach((button) => {
    button.onclick = async () => {
      await api(`/clients/${button.dataset.id}/enabled?enabled=${button.dataset.enabled !== "true"}`, {method: "POST"});
      await showClients();
    };
  });
}

function showCreateClient() {
  view.insertAdjacentHTML("beforeend", `<form id="create" class="modal"><input name="name" placeholder="客户端名称" required>
    <input name="expires_at" type="datetime-local"><button>创建并显示 Key</button></form>`);
  document.querySelector("#create").onsubmit = createClient;
}

async function createClient(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const result = await api("/clients", {
    method: "POST",
    body: JSON.stringify({name: form.get("name"), expires_at: form.get("expires_at") || null}),
  });
  view.insertAdjacentHTML("beforeend", `<div class="modal"><p>请立即保存 Key，关闭后无法再次查看。</p>
    <code>${result.key}</code><button id="close-key" type="button">已保存</button></div>`);
  document.querySelector("#close-key").onclick = () => showClients();
}

function createConversationId() {
  const token = window.crypto?.randomUUID?.().replaceAll("-", "") || Date.now().toString(36);
  return `conv_admin_${token}`;
}

function appendChatMessage(role, content) {
  const timeline = document.querySelector("#chat-timeline");
  const message = document.createElement("article");
  const label = document.createElement("span");
  const body = document.createElement("p");
  message.className = `chat-message chat-message--${role}`;
  label.textContent = role === "assistant" ? "SOMAI" : role === "user" ? "管理员" : "系统";
  body.textContent = content;
  message.append(label, body);
  timeline.append(message);
  timeline.scrollTop = timeline.scrollHeight;
  return body;
}

function setChatStatus(text, ready = false) {
  const status = document.querySelector("#chat-status");
  status.textContent = text;
  status.dataset.ready = String(ready);
  document.querySelector("#chat-send").disabled = !ready;
}

function chatUrl(conversationId) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/chat/ws/${conversationId}`;
}

function showChatWorkspace() {
  title.textContent = "Chat 工作区";
  if (chatSocket) chatSocket.close();
  view.innerHTML = `<section class="chat-workspace"><header class="chat-workspace__header"><div><p>LIVE DIALOGUE</p>
    <h3>机器人对话调试</h3></div><span id="chat-status">正在连接</span></header><div id="chat-timeline" class="chat-timeline"></div>
    <form id="chat-composer" class="chat-composer"><textarea id="chat-input" rows="3" placeholder="输入消息，Enter 发送"></textarea>
    <div><span>管理员会话已认证</span><button id="chat-send" type="submit" disabled>发送</button></div></form></section>`;
  const socket = new WebSocket(chatUrl(createConversationId()));
  chatSocket = socket;
  socket.onmessage = ({data}) => {
    const event = JSON.parse(data);
    if (event.type === "conversation.ready") setChatStatus("已连接", true);
    if (event.type === "response.started") chatResponse = appendChatMessage("assistant", "");
    if (event.type === "response.delta" && chatResponse) {
      chatResponse.textContent = `${chatResponse.textContent}${typeof event.data.delta === "string" ? event.data.delta : ""}`;
    }
    if (event.type === "response.completed") chatResponse = null;
    if (event.type === "error") appendChatMessage("system", event.data.message || "请求失败");
  };
  socket.onclose = () => setChatStatus("连接已关闭", false);
  document.querySelector("#chat-composer").onsubmit = sendChatMessage;
  document.querySelector("#chat-input").onkeydown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      document.querySelector("#chat-composer").requestSubmit();
    }
  };
}

function sendChatMessage(event) {
  event.preventDefault();
  const input = document.querySelector("#chat-input");
  const content = input.value.trim();
  if (!content || !chatSocket || chatSocket.readyState !== WebSocket.OPEN) return;
  appendChatMessage("user", content);
  chatSocket.send(JSON.stringify({type: "message.create", data: {message_id: crypto.randomUUID(), content}}));
  input.value = "";
}

document.querySelector("#login-form").onsubmit = async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  try {
    const result = await api("/session", {method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    csrf = result.csrf_token;
    document.querySelector("#admin-name").textContent = result.username;
    login.hidden = true;
    consoleView.hidden = false;
    showOverview();
  } catch (error) {
    loginError.textContent = error.message;
  }
};

document.querySelectorAll("[data-view]").forEach((button) => {
  button.onclick = () => {
    if (button.dataset.view === "clients") showClients();
    else if (button.dataset.view === "chat") showChatWorkspace();
    else showOverview();
  };
});

document.querySelector("#logout").onclick = async () => {
  if (chatSocket) chatSocket.close();
  await api("/session", {method: "DELETE"});
  location.reload();
};
