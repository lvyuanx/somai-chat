<script setup>
import { ElMessage } from "element-plus";
import { computed, onMounted, ref } from "vue";
import { Hide, Refresh, View } from "@element-plus/icons-vue";
import {
  capabilityKeyInputValue,
  createCapabilityDraft,
  createUpdatePayload,
  updateCapabilityKeyInput,
  validateCapabilityDraft,
} from "./capability-state.js";

const props = defineProps({ request: { type: Function, required: true } });
const drafts = ref([]);
const loading = ref(false);
const pageError = ref("");
const metadata = {
  weather: { name: "查询天气", provider: "QWEATHER", description: "查询实时天气与未来逐日预报" },
  time: { name: "查询时间", provider: "CHINA STANDARD TIME", description: "查询当前及未来日期的中国标准时间" },
  web_search: { name: "联网搜索", provider: "TAVILY", description: "访问互联网并返回带来源的结果" },
};
const enabledCount = computed(() => drafts.value.filter((draft) => draft.enabled).length);

function replaceDraft(view) {
  const index = drafts.value.findIndex((item) => item.key === view.key);
  const next = createCapabilityDraft(view);
  if (index < 0) drafts.value.push(next);
  else drafts.value[index] = next;
}

async function loadCapabilities() {
  loading.value = true;
  pageError.value = "";
  try {
    drafts.value = (await props.request("/capabilities")).map(createCapabilityDraft);
  } catch (error) {
    pageError.value = error.message;
  } finally {
    loading.value = false;
  }
}

async function saveCapability(draft) {
  draft.error = validateCapabilityDraft(draft);
  if (draft.error) return;
  draft.saving = true;
  try {
    const saved = await props.request(`/capabilities/${draft.key}`, {
      method: "PUT",
      body: JSON.stringify(createUpdatePayload(draft)),
    });
    replaceDraft(saved);
    ElMessage.success("能力配置已保存，将从下一条消息开始生效");
  } catch (error) {
    draft.error = error.message;
  } finally {
    draft.saving = false;
  }
}

async function revealKey(draft) {
  if (draft.revealed_api_key) {
    draft.revealed_api_key = "";
    return;
  }
  try {
    const result = await props.request(`/capabilities/${draft.key}/api-key/reveal`, { method: "POST" });
    draft.revealed_api_key = result.api_key;
  } catch (error) {
    draft.error = error.message;
  }
}

function clearKey(draft) {
  draft.clear_api_key = true;
  draft.replacement_api_key = "";
  draft.revealed_api_key = "";
}

onMounted(loadCapabilities);
</script>

<template>
  <section class="capabilities-page" v-loading="loading">
    <div class="toolbar">
      <div>
        <p class="eyebrow">CAPABILITY REGISTRY</p>
        <h3>运行时能力</h3>
        <span class="capability-hint">保存后从下一条消息开始生效</span>
      </div>
      <div class="toolbar-actions">
        <el-tag effect="plain">{{ enabledCount }} / {{ drafts.length }} 已启用</el-tag>
        <el-button circle :icon="Refresh" title="刷新能力配置" @click="loadCapabilities" />
      </div>
    </div>
    <el-alert v-if="pageError" :title="pageError" type="error" :closable="false" show-icon />
    <div class="capability-grid">
      <el-card v-for="draft in drafts" :key="draft.key" class="capability-card" shadow="never">
        <div class="capability-header">
          <div>
            <h4>{{ metadata[draft.key].name }}</h4>
            <small>{{ metadata[draft.key].provider }}</small>
          </div>
          <el-switch v-model="draft.enabled" inline-prompt active-text="开" inactive-text="关" />
        </div>
        <p class="capability-description">{{ metadata[draft.key].description }}</p>

        <template v-if="draft.key !== 'time'">
          <el-form label-position="top">
            <el-form-item label="API Host">
              <el-input v-model="draft.configuration.api_host" />
            </el-form-item>
            <el-form-item label="API Key">
              <div class="capability-secret">
                <el-input
                  :model-value="capabilityKeyInputValue(draft)"
                  :type="draft.revealed_api_key ? 'text' : 'password'"
                  :show-password="!draft.revealed_api_key"
                  :placeholder="draft.clear_api_key ? '保存后将清除' : draft.api_key_masked || '输入 API Key'"
                  @input="updateCapabilityKeyInput(draft, $event)"
                />
                <el-button
                  v-if="draft.can_reveal_api_key && !draft.clear_api_key"
                  circle
                  :icon="draft.revealed_api_key ? Hide : View"
                  @click="revealKey(draft)"
                />
              </div>
              <el-button
                v-if="draft.can_reveal_api_key && !draft.clear_api_key"
                class="clear-secret"
                link
                type="danger"
                @click="clearKey(draft)"
              >清除 Key</el-button>
            </el-form-item>
            <div class="capability-number-row">
              <el-form-item label="请求超时（秒）">
                <el-input-number v-model="draft.configuration.timeout_seconds" :min="0.1" :max="60" />
              </el-form-item>
              <el-form-item v-if="draft.key === 'web_search'" label="最大结果数">
                <el-input-number v-model="draft.configuration.max_results" :min="1" :max="20" />
              </el-form-item>
            </div>
          </el-form>
        </template>
        <div v-else class="time-capability-note">
          <strong>无需外部服务参数</strong>
          <span>固定时区：Asia/Shanghai</span>
        </div>
        <el-alert v-if="draft.error" :title="draft.error" type="error" :closable="false" show-icon />
        <div class="capability-actions">
          <small>{{ draft.updated_at ? `更新于 ${new Date(draft.updated_at).toLocaleString('zh-CN')}` : "尚未更新" }}</small>
          <el-button type="primary" :loading="draft.saving" @click="saveCapability(draft)">保存配置</el-button>
        </div>
      </el-card>
    </div>
  </section>
</template>
