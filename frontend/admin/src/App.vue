<script setup>
import { ElMessage } from "element-plus";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  ChatDotRound,
  CircleCheckFilled,
  CircleCloseFilled,
  Connection,
  DataAnalysis,
  DocumentCopy,
  Hide,
  Key,
  Plus,
  Refresh,
  SwitchButton,
  View,
} from "@element-plus/icons-vue";

const apiBase = "/api/v1/admin";
const active = ref("overview");
const authenticated = ref(false);
const username = ref("admin");
const password = ref("");
const csrf = ref("");
const loginError = ref("");
const clients = ref([]);
const createOpen = ref(false);
const keyOpen = ref(false);
const generatedKey = ref("");
const revealedKeys = ref({});
const clientFormError = ref("");
let clientRefreshTimer;
const clientForm = ref({
  name: "",
  description: "",
  expires_at: null,
  long_lived: true,
});

const onlineCount = computed(
  () => clients.value.filter((client) => client.online).length,
);
const enabledCount = computed(
  () => clients.value.filter((client) => client.enabled).length,
);

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf.value,
      ...options.headers,
    },
    ...options,
  });
  const body =
    response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || "请求失败，请稍后重试");
  return body;
}

async function loadClients() {
  clients.value = await request("/clients");
}

function startClientRefresh() {
  window.clearInterval(clientRefreshTimer);
  clientRefreshTimer = window.setInterval(() => {
    if (authenticated.value) loadClients().catch(() => undefined);
  }, 5000);
}

function formatLastAuthentication(value) {
  if (!value) return "尚未连接";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function login() {
  loginError.value = "";
  try {
    const session = await request("/session", {
      method: "POST",
      body: JSON.stringify({
        username: username.value,
        password: password.value,
      }),
    });
    csrf.value = session.csrf_token;
    username.value = session.username;
    authenticated.value = true;
    await loadClients();
    startClientRefresh();
  } catch (error) {
    loginError.value = error.message;
  }
}

async function createClient() {
  clientFormError.value = "";
  try {
    const payload = {
      name: clientForm.value.name,
      description: clientForm.value.description || null,
      expires_at: clientForm.value.long_lived
        ? null
        : clientForm.value.expires_at,
    };
    const created = await request("/clients", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    generatedKey.value = created.key;
    createOpen.value = false;
    keyOpen.value = true;
    clientForm.value = {
      name: "",
      description: "",
      expires_at: null,
      long_lived: true,
    };
    await loadClients();
  } catch (error) {
    clientFormError.value = error.message;
  }
}

async function toggleClient(client) {
  await request(`/clients/${client.id}/enabled?enabled=${!client.enabled}`, {
    method: "POST",
  });
  await loadClients();
}

async function rotateClient(client) {
  const created = await request(`/clients/${client.id}/keys/rotate`, {
    method: "POST",
    body: JSON.stringify({ expires_at: null }),
  });
  generatedKey.value = created.key;
  revealedKeys.value = { ...revealedKeys.value, [client.id]: created.key };
  keyOpen.value = true;
  await loadClients();
}

async function revealKey(client) {
  if (revealedKeys.value[client.id]) {
    const { [client.id]: _, ...remainingKeys } = revealedKeys.value;
    revealedKeys.value = remainingKeys;
    return;
  }
  const result = await request(`/clients/${client.id}/key/reveal`, {
    method: "POST",
  });
  revealedKeys.value = { ...revealedKeys.value, [client.id]: result.key };
}

async function copyKey(client) {
  try {
    const key =
      revealedKeys.value[client.id] ||
      (await request(`/clients/${client.id}/key/reveal`, { method: "POST" }))
        .key;
    await navigator.clipboard.writeText(key);
    ElMessage.success("Key 已复制");
  } catch (_) {
    ElMessage.error("复制失败，请检查浏览器权限");
  }
}

async function logout() {
  await request("/session", { method: "DELETE" });
  authenticated.value = false;
  password.value = "";
  revealedKeys.value = {};
  window.clearInterval(clientRefreshTimer);
}

onMounted(async () => {
  try {
    const session = await request("/session");
    csrf.value = session.csrf_token;
    username.value = session.username;
    authenticated.value = true;
    await loadClients();
    startClientRefresh();
  } catch (_) {
    authenticated.value = false;
  }
});

onBeforeUnmount(() => window.clearInterval(clientRefreshTimer));
</script>

<template>
  <main class="admin-root">
    <section v-if="!authenticated" class="login-stage">
      <el-card class="login-card" shadow="never">
        <div class="brand-mark">S</div>
        <p class="eyebrow">SOMAI / CONTROL PLANE</p>
        <h1>机器人控制中心</h1>
        <el-form label-position="top" @submit.prevent="login">
          <el-form-item label="管理员账号"
            ><el-input v-model="username" autocomplete="username"
          /></el-form-item>
          <el-form-item label="密码"
            ><el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="current-password"
              @keyup.enter="login"
          /></el-form-item>
          <el-alert
            v-if="loginError"
            :title="loginError"
            type="error"
            :closable="false"
            show-icon
          />
          <el-button
            class="login-action"
            type="primary"
            native-type="submit"
            @click="login"
            >进入控制台</el-button
          >
        </el-form>
      </el-card>
    </section>

    <el-container v-else class="admin-shell">
      <el-aside width="248px" class="side-panel">
        <div class="side-brand">
          <span class="brand-mark">S</span><strong>SOMAI</strong>
        </div>
        <p class="side-caption">ADMINISTRATION</p>
        <el-menu
          :default-active="active"
          class="side-menu"
          @select="active = $event"
        >
          <el-menu-item index="overview"
            ><el-icon><DataAnalysis /></el-icon
            ><span>控制总览</span></el-menu-item
          >
          <el-menu-item index="clients"
            ><el-icon><Connection /></el-icon
            ><span>客户端管理</span></el-menu-item
          >
          <el-menu-item index="chat"
            ><el-icon><ChatDotRound /></el-icon
            ><span>Chat 工作区</span></el-menu-item
          >
        </el-menu>
        <div class="side-footer">
          <el-button text @click="logout"
            ><el-icon><SwitchButton /></el-icon>退出登录</el-button
          >
        </div>
      </el-aside>
      <el-container>
        <el-header class="topbar"
          ><div>
            <p class="eyebrow">SOMAI / ADMIN</p>
            <h2>
              {{
                active === "overview"
                  ? "控制总览"
                  : active === "clients"
                    ? "客户端管理"
                    : "Chat 工作区"
              }}
            </h2>
          </div>
          <el-tag effect="plain"
            ><el-icon><Key /></el-icon>{{ username }}</el-tag
          ></el-header
        >
        <el-main class="content-panel">
          <section v-if="active === 'overview'" class="overview-grid">
            <el-card shadow="never"
              ><p>在线客户端</p>
              <strong>{{ onlineCount }}</strong
              ><span>当前持有活跃 WebSocket 连接</span></el-card
            >
            <el-card shadow="never"
              ><p>已创建客户端</p>
              <strong>{{ clients.length }}</strong
              ><span>当前受管理客户端</span></el-card
            >
            <el-card shadow="never"
              ><p>已启用客户端</p>
              <strong>{{ enabledCount }}</strong
              ><span>可接受机器人 Key 认证</span></el-card
            >
            <el-card class="overview-note" shadow="never"
              ><h3>系统状态</h3>
              <el-tag type="success">管理 API 已连接</el-tag>
              <p>
                从客户端管理创建机器人 Key，完整 Chat 控制台在工作区中可用。
              </p></el-card
            >
          </section>

          <section v-else-if="active === 'clients'" class="clients-page">
            <div class="toolbar">
              <div>
                <p class="eyebrow">CLIENT REGISTRY</p>
                <h3>机器人客户端</h3>
              </div>
              <div class="toolbar-actions">
                <el-button
                  circle
                  :icon="Refresh"
                  title="刷新客户端状态"
                  @click="loadClients"
                />
                <el-button
                  type="primary"
                  :icon="Plus"
                  @click="createOpen = true"
                  >创建客户端</el-button
                >
              </div>
            </div>
            <div v-if="clients.length" class="client-grid">
              <el-card
                v-for="client in clients"
                :key="client.id"
                class="client-card"
                shadow="never"
              >
                <div class="client-card-header">
                  <div>
                    <h4>{{ client.name }}</h4>
                    <p>{{ client.description || "未添加客户端说明" }}</p>
                  </div>
                  <el-tag
                    :class="client.online ? 'is-online' : 'is-offline'"
                    effect="plain"
                  >
                    <el-icon
                      ><CircleCheckFilled
                        v-if="client.online" /><CircleCloseFilled v-else
                    /></el-icon>
                    {{
                      client.online
                        ? "在线"
                        : client.enabled
                          ? "离线"
                          : "已停用"
                    }}
                  </el-tag>
                </div>
                <div class="client-meta">
                  <div>
                    <span>认证状态</span
                    ><strong>{{ client.enabled ? "已启用" : "已停用" }}</strong>
                  </div>
                  <div>
                    <span>最近连接</span
                    ><strong>{{
                      formatLastAuthentication(client.last_authenticated_at)
                    }}</strong>
                  </div>
                </div>
                <div class="client-key-row">
                  <div>
                    <span>连接 Key</span>
                    <code>{{
                      revealedKeys[client.id] ||
                      client.key_masked ||
                      "历史 Key 不可恢复，请轮换"
                    }}</code>
                    <small
                      v-if="!client.can_reveal_key"
                      class="client-key-legacy"
                    >
                      轮换后可查看与复制
                    </small>
                  </div>
                  <div v-if="client.can_reveal_key" class="client-key-actions">
                    <el-button
                      circle
                      :icon="revealedKeys[client.id] ? View : Hide"
                      :title="
                        revealedKeys[client.id]
                          ? 'Key 已显示，点击隐藏'
                          : 'Key 已隐藏，点击查看'
                      "
                      @click="revealKey(client)"
                    />
                    <el-button
                      circle
                      :icon="DocumentCopy"
                      title="复制 Key"
                      @click="copyKey(client)"
                    />
                  </div>
                </div>
                <div class="client-card-actions">
                  <el-switch
                    :model-value="client.enabled"
                    active-text="已启用"
                    inactive-text="已停用"
                    inline-prompt
                    @change="toggleClient(client)"
                  />
                  <el-button link @click="rotateClient(client)"
                    >轮换 Key</el-button
                  >
                </div>
              </el-card>
            </div>
            <el-empty
              v-else
              description="还没有客户端，创建后会在这里显示连接状态。"
            />
          </section>

          <section v-else class="chat-page">
            <iframe
              title="SOMAI Chat 工作区"
              src="/assets/index.html?embed=1"
            />
          </section>
        </el-main>
      </el-container>
    </el-container>

    <el-dialog
      v-model="createOpen"
      title="创建机器人客户端"
      width="460px"
      @closed="
        clientForm = {
          name: '',
          description: '',
          expires_at: null,
          long_lived: true,
        };
        clientFormError = '';
      "
    >
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="clientForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="clientForm.description" type="textarea" />
        </el-form-item>
        <el-alert
          v-if="clientFormError"
          :title="clientFormError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form-item>
          <el-checkbox v-model="clientForm.long_lived">长期有效</el-checkbox>
        </el-form-item>
        <el-form-item v-if="!clientForm.long_lived" label="到期时间">
          <el-date-picker
            v-model="clientForm.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!clientForm.name"
          @click="createClient"
          >创建</el-button
        >
      </template>
    </el-dialog>

    <el-dialog
      v-model="keyOpen"
      title="客户端 Key"
      width="560px"
      :close-on-click-modal="false"
      ><el-alert
        title="请立即保存此 Key，关闭后无法再次查看。"
        type="warning"
        :closable="false"
        show-icon
      /><el-input class="key-field" :model-value="generatedKey" readonly
        ><template #append
          ><el-button @click="navigator.clipboard.writeText(generatedKey)"
            >复制</el-button
          ></template
        ></el-input
      ><template #footer
        ><el-button type="primary" @click="keyOpen = false"
          >已保存</el-button
        ></template
      ></el-dialog
    >
  </main>
</template>
