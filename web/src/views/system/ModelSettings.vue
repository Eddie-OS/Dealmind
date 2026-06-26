<script setup lang="ts">
/**
 * 模型设置中心（蓝图 §Stage 2）
 * 多 LLM provider 管理：list + create + update + delete + set_default + test
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElSlider,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { Plus, CheckCircle2, XCircle, Loader2 } from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import { useProvidersStore } from '@/stores/providers'
import {
  PROVIDER_PRESETS,
  getPreset,
  type Provider,
  type ProviderCreate,
  type ProviderType,
} from '@/api/providers'

const store = useProvidersStore()

onMounted(() => store.fetchAll())

const isLoading = computed(() => store.loading)
const rows = computed(() => store.list)

function maskKey(k: string): string {
  if (!k) return ''
  if (k.length <= 8) return '****'
  return `${k.slice(0, 4)}***${k.slice(-4)}`
}

function truncate(s: string, n = 36): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '...' : s
}

function presetLabel(t: ProviderType): string {
  return getPreset(t)?.label ?? t
}

// ===== 测试状态（按行 id 跟踪） =====

type RowTestState = 'idle' | 'running' | 'ok' | 'fail'
const testState = reactive<Record<number, { state: RowTestState; msg: string }>>({})

async function handleTest(row: Provider) {
  testState[row.id] = { state: 'running', msg: '' }
  try {
    const r = await store.test({ provider_id: row.id })
    if (r.ok) {
      testState[row.id] = {
        state: 'ok',
        msg: `连通成功 · ${r.latency_ms}ms · 回复：${r.reply || '(空)'}`,
      }
      ElMessage.success(`「${row.name}」连通成功，响应 ${r.latency_ms}ms`)
    } else {
      testState[row.id] = {
        state: 'fail',
        msg: r.error ?? '未知错误',
      }
      ElMessage.error(`「${row.name}」连通失败：${r.error ?? ''}`)
    }
  } catch {
    testState[row.id] = { state: 'fail', msg: '请求失败' }
  }
}

// ===== 设为默认 =====

async function handleSetDefault(row: Provider) {
  if (row.is_default) return
  await store.setDefault(row.id)
  ElMessage.success(`已将「${row.name}」设为默认 provider`)
}

// ===== 删除 =====

async function handleDelete(row: Provider) {
  try {
    await ElMessageBox.confirm(
      `确认删除 provider「${row.name}」？此操作不可撤销。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await store.remove(row.id)
  ElMessage.success(`已删除「${row.name}」`)
}

// ===== 新增 / 编辑 Dialog =====

const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingId = ref<number | null>(null)
const dialogTesting = ref(false)
const dialogTestResult = ref<{ ok: boolean; msg: string } | null>(null)
const formRef = ref<FormInstance>()

const blankForm = (): ProviderCreate => ({
  name: '',
  provider_type: 'deepseek',
  base_url: 'https://api.deepseek.com',
  api_key: '',
  model_name: 'deepseek-v4-pro',
  temperature: 1.0,
  max_retries: 2,
  is_active: true,
  is_default: false,
})

const currentModelOptions = computed(() => {
  const preset = PROVIDER_PRESETS.find((p) => p.type === form.provider_type)
  return preset?.model_options ?? []
})

const form = reactive<ProviderCreate>(blankForm())

const rules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  provider_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  base_url: [{ required: true, message: '请输入 base_url', trigger: 'blur' }],
  api_key: [{ required: true, message: '请输入 API Key', trigger: 'blur' }],
  model_name: [{ required: true, message: '请输入模型名', trigger: 'blur' }],
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  Object.assign(form, blankForm())
  dialogTestResult.value = null
  dialogVisible.value = true
}

function openEdit(row: Provider) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    api_key: row.api_key,
    model_name: row.model_name,
    temperature: row.temperature,
    max_retries: row.max_retries,
    is_active: row.is_active,
    is_default: row.is_default,
  })
  dialogTestResult.value = null
  dialogVisible.value = true
}

function onProviderTypeChange(t: ProviderType) {
  const preset = getPreset(t)
  if (!preset) return
  // 切换类型时自动填模板（已填写的不覆盖，避免误改用户输入）
  if (preset.base_url && (form.base_url === '' || isPresetBaseUrl(form.base_url))) {
    form.base_url = preset.base_url
  }
  if (preset.default_model && (form.model_name === '' || isPresetModel(form.model_name))) {
    form.model_name = preset.default_model
  }
}

function isPresetBaseUrl(url: string): boolean {
  return PROVIDER_PRESETS.some((p) => p.base_url === url)
}
function isPresetModel(m: string): boolean {
  return PROVIDER_PRESETS.some((p) => p.default_model === m)
}

async function handleDialogTest() {
  if (!form.base_url || !form.api_key || !form.model_name) {
    ElMessage.warning('请先填写 base_url / api_key / 模型名')
    return
  }
  dialogTesting.value = true
  dialogTestResult.value = null
  try {
    const r = await store.test({
      base_url: form.base_url,
      api_key: form.api_key,
      model_name: form.model_name,
    })
    dialogTestResult.value = {
      ok: r.ok,
      msg: r.ok
        ? `连通成功 · ${r.latency_ms}ms · 回复：${r.reply || '(空)'}`
        : r.error || '未知错误',
    }
  } finally {
    dialogTesting.value = false
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  try {
    if (dialogMode.value === 'create') {
      await store.create({ ...form })
      ElMessage.success(`已创建「${form.name}」`)
    } else if (editingId.value !== null) {
      await store.update(editingId.value, { ...form })
      ElMessage.success(`已更新「${form.name}」`)
    }
    dialogVisible.value = false
  } catch {
    /* 拦截器已弹错误 */
  }
}

function canDelete(row: Provider): boolean {
  return !row.is_default && rows.value.length > 1
}
</script>

<template>
  <div class="model-settings">
    <DmPageHeader
      title="模型设置"
      subtitle="管理 LLM Provider 配置。支持 DeepSeek / OpenAI / 通义千问 / Moonshot / 智谱 GLM / 自定义 OpenAI 兼容服务。"
    >
      <template #actions>
        <el-button type="primary" @click="openCreate">
          <Plus :size="16" :stroke-width="1.8" style="margin-right: 6px" />
          新增 Provider
        </el-button>
      </template>
    </DmPageHeader>

    <div class="card">
      <el-table
        v-if="rows.length > 0 || isLoading"
        v-loading="isLoading"
        :data="rows"
        stripe
        style="width: 100%"
      >
        <el-table-column prop="name" label="名称" min-width="110">
          <template #default="{ row }">
            <span class="dm-text-body-strong">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="类型" width="92">
          <template #default="{ row }">
            <el-tag size="small" class="type-tag">{{ presetLabel(row.provider_type) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="model_name" label="模型" min-width="120" />

        <el-table-column label="Base URL" min-width="160">
          <template #default="{ row }">
            <el-tooltip :content="row.base_url" placement="top">
              <span class="muted-cell">{{ truncate(row.base_url, 24) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <el-table-column label="API Key" width="140">
          <template #default="{ row }">
            <span class="muted-cell dm-numeric">{{ maskKey(row.api_key) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="温度" width="56" align="center">
          <template #default="{ row }">
            <span class="dm-numeric">{{ row.temperature }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="92">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag v-if="row.is_default" size="small" type="primary" effect="dark">默认</el-tag>
              <el-tag v-if="!row.is_active" size="small" type="info">已停用</el-tag>
              <el-tag v-else-if="!row.is_default" size="small" type="success">启用</el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="310" fixed="right">
          <template #default="{ row }">
            <div class="actions">
              <el-button
                size="small"
                :loading="testState[row.id]?.state === 'running'"
                @click="handleTest(row)"
              >
                <CheckCircle2
                  v-if="testState[row.id]?.state === 'ok'"
                  :size="14"
                  :stroke-width="1.8"
                  class="icon-ok"
                />
                <XCircle
                  v-else-if="testState[row.id]?.state === 'fail'"
                  :size="14"
                  :stroke-width="1.8"
                  class="icon-fail"
                />
                <Loader2
                  v-else-if="testState[row.id]?.state === 'running'"
                  :size="14"
                  :stroke-width="1.8"
                  class="icon-spin"
                />
                测试
              </el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                size="small"
                :disabled="row.is_default"
                @click="handleSetDefault(row)"
              >
                {{ row.is_default ? '已默认' : '设为默认' }}
              </el-button>
              <el-button
                size="small"
                :disabled="!canDelete(row)"
                @click="handleDelete(row)"
              >
                删除
              </el-button>
            </div>
            <div
              v-if="testState[row.id] && testState[row.id].state !== 'idle' && testState[row.id].state !== 'running'"
              class="test-msg"
              :class="testState[row.id].state"
            >
              {{ testState[row.id].msg }}
            </div>
          </template>
        </el-table-column>
      </el-table>

      <DmEmpty
        v-else
        title="暂无 Provider 配置"
        description="点击右上角「新增 Provider」开始配置你的第一个 LLM 服务。"
      />
    </div>

    <!-- ===== 新增/编辑 Dialog ===== -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新增 Provider' : '编辑 Provider'"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="类型" prop="provider_type">
          <el-select
            v-model="form.provider_type"
            placeholder="选择 Provider 类型"
            style="width: 100%"
            @change="onProviderTypeChange"
          >
            <el-option
              v-for="p in PROVIDER_PRESETS"
              :key="p.type"
              :label="p.label"
              :value="p.type"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="名称" prop="name">
          <el-input
            v-model="form.name"
            placeholder="自定义名称，如 deepseek-prod"
            :disabled="dialogMode === 'edit'"
          />
        </el-form-item>

        <el-form-item label="Base URL" prop="base_url">
          <el-input v-model="form.base_url" placeholder="https://api.xxx.com/v1" />
        </el-form-item>

        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="getPreset(form.provider_type)?.api_key_hint ?? 'sk-xxxxxxxx'"
          />
        </el-form-item>

        <el-form-item label="模型名" prop="model_name">
          <el-select
            v-model="form.model_name"
            placeholder="如 deepseek-v4-pro（可手动输入）"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
          >
            <el-option
              v-for="opt in currentModelOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <div
            v-if="form.provider_type === 'deepseek'"
            style="margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5;"
          >
            DeepSeek V4-Pro 默认开启思考模式（Thinking Mode），系统已为分析/复盘任务自动启用 high/max 推理强度。
          </div>
        </el-form-item>

        <el-form-item label="温度（temperature）">
          <div class="slider-row">
            <el-slider
              v-model="form.temperature"
              :min="0"
              :max="1"
              :step="0.1"
              style="flex: 1 1 auto"
            />
            <span class="dm-numeric slider-value">{{ form.temperature.toFixed(1) }}</span>
          </div>
        </el-form-item>

        <el-form-item label="最大重试次数">
          <el-input-number v-model="form.max_retries" :min="0" :max="10" :step="1" />
        </el-form-item>

        <div class="dialog-switches">
          <el-form-item label="启用">
            <el-switch v-model="form.is_active" />
          </el-form-item>
          <el-form-item label="设为默认">
            <el-switch v-model="form.is_default" />
          </el-form-item>
        </div>

        <el-form-item>
          <div class="dialog-test-row">
            <el-button :loading="dialogTesting" @click="handleDialogTest">
              测试连通
            </el-button>
            <span
              v-if="dialogTestResult"
              class="test-msg inline"
              :class="dialogTestResult.ok ? 'ok' : 'fail'"
            >
              {{ dialogTestResult.msg }}
            </span>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.model-settings {
  width: 100%;
}

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-lg);
  padding: 4px;
}

.type-tag {
  background: var(--dm-bg-muted) !important;
  color: var(--dm-text-secondary) !important;
}

.muted-cell {
  color: var(--dm-text-secondary);
  font-size: var(--dm-fs-caption);
}

.status-cell {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.icon-ok   { color: var(--dm-success); margin-right: 4px; }
.icon-fail { color: var(--dm-danger);  margin-right: 4px; }
.icon-spin {
  margin-right: 4px;
  animation: dm-spin 1s linear infinite;
}
@keyframes dm-spin {
  to { transform: rotate(360deg); }
}

.test-msg {
  margin-top: 6px;
  font-size: var(--dm-fs-small);
  line-height: 1.5;
  color: var(--dm-text-muted);
  word-break: break-all;
}
.test-msg.ok   { color: var(--dm-success); }
.test-msg.fail { color: var(--dm-danger); }
.test-msg.inline { margin-top: 0; margin-left: 12px; }

.slider-row {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
}
.slider-value {
  width: 36px;
  text-align: right;
  color: var(--dm-text);
  font-weight: var(--dm-fw-medium);
}

.dialog-switches {
  display: flex;
  gap: 32px;
}

.dialog-test-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}
</style>
