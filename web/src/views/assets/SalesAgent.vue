<script setup lang="ts">
/**
 * 销冠 Agent 配置中心（Stage 15a Phase A）
 *
 * 5 个 Tab：
 *   1. 人格 Prompt  ← 本轮完整实装（编辑器 + 版本侧栏 + 回滚）
 *   2. 模型采样      ← 本轮占位（Phase B 实装）
 *   3. 技能工具      ← 本轮占位（提示去 /settings/skills 配，下轮内嵌）
 *   4. 记忆与学习    ← 本轮占位（Phase B 实装）
 *   5. 试一试        ← 本轮完整实装（输入客户开场 → 调销冠 → 显示回复 + 工具调用）
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElSkeleton,
  ElTabPane,
  ElTabs,
  ElTag,
} from 'element-plus'
import {
  Brain,
  Save,
  RefreshCcw,
  History,
  RotateCcw,
  Play,
  Wrench,
  Box,
  Building2,
  BookOpen,
  ArrowRight,
  Settings,
  Cpu,
} from '@lucide/vue'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  agentProfileApi,
  type AgentProfile,
  type AgentProfileVersion,
  type EffectiveConfigResp,
  type MemoryResp,
  type TryNextHistoryItem,
  type TryResp,
} from '@/api/agent_profile'
import {
  agentSkillsApi,
  type ToolInfo,
  type SkillsConfig,
} from '@/api/agent_skills'
import { providersApi, type Provider } from '@/api/providers'

const router = useRouter()

// ============================================================
// 状态
// ============================================================

const activeTab = ref<string>('persona')

const loading = ref(true)
const saving = ref(false)
const restoring = ref(false)

const profile = ref<AgentProfile | null>(null)

// Tab 1：人格 Prompt 编辑
const editPrompt = ref('')
const editRoleDesc = ref('')
const editOpenings = ref<string[]>([])  // 维护开场白列表

const versions = ref<AgentProfileVersion[]>([])
const loadingVersions = ref(false)

// 保存对话框（输入备注）
const saveDialogVisible = ref(false)
const saveComment = ref('')

// 版本查看
const previewDialogVisible = ref(false)
const previewVersion = ref<AgentProfileVersion | null>(null)

// Tab 2：模型与采样（销冠专属覆盖 + 默认会话参数）
const modelLoading = ref(true)
const modelSaving = ref(false)
const providersList = ref<Provider[]>([])
const effectiveCfg = ref<EffectiveConfigResp | null>(null)
// 销冠 model_override 编辑态。空值 = 跟随全局默认
const moEdit = ref<{
  provider_id: number | null
  temperature: number | null
  max_tokens: number | null
}>({
  provider_id: null,
  temperature: null,
  max_tokens: null,
})
// 销冠 default_session_params 编辑态
const dspEdit = ref<{
  max_rounds: number | null
  stage: string
  product_kb_id: number | null
  enterprise_kb_id: number | null
}>({
  max_rounds: null,
  stage: '',
  product_kb_id: null,
  enterprise_kb_id: null,
})

// Tab 3：技能与工具（精简内嵌版，深度配置仍跳转 /settings/skills）
const skillsLoading = ref(true)
const skillsSaving = ref(false)
const skillsTools = ref<ToolInfo[]>([])
const skillsCfg = ref<SkillsConfig | null>(null)
const skillsEdit = ref<{
  enabled_tools: string[]
  max_tool_loops: number
  tool_top_k_default: number
}>({
  enabled_tools: [],
  max_tool_loops: 3,
  tool_top_k_default: 3,
})

// Tab 5：试一试
const tryForm = ref({
  topic: '华为 MatePad 12X 学习平板推荐',
  customer_opening: '我刚带娃，预算 5000 左右，想给孩子上网课用的平板，MatePad 12X 和 iPad 比怎么选？',
  product_kb_id: null as number | null,
  enterprise_kb_id: null as number | null,
  persona_name: '试一试·新手宝妈',
  persona_age: 30,
})
const tryRunning = ref(false)
const tryResp = ref<TryResp | null>(null)

// Tab 5：多轮调试模式
interface ChatMsg {
  role: 'persona' | 'sales'
  content: string
  toolCalls?: { loop: number; name: string; arguments: Record<string, any>; result_preview: string; ok: boolean }[]
  strategy?: Record<string, any>
  toolMode?: string | null
}
const chatHistory = ref<ChatMsg[]>([])
const chatNextInput = ref('')

// Tab 4：记忆与学习
const memoryLoading = ref(true)
const memory = ref<MemoryResp | null>(null)

// ============================================================
// 加载
// ============================================================

async function loadProfile() {
  loading.value = true
  try {
    const p = await agentProfileApi.get()
    profile.value = p
    editPrompt.value = p.system_prompt || ''
    editRoleDesc.value = p.role_description || ''
    editOpenings.value = [...(p.opening_lines || [])]
  } catch {
    profile.value = null
  } finally {
    loading.value = false
  }
}

async function loadVersions() {
  loadingVersions.value = true
  try {
    const resp = await agentProfileApi.versions(50)
    versions.value = resp.versions || []
  } finally {
    loadingVersions.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    loadProfile(),
    loadVersions(),
    loadSkills(),
    loadMemory(),
    loadModelTab(),
  ])
})

// ============================================================
// Tab 2：模型与采样
// ============================================================
async function loadModelTab() {
  modelLoading.value = true
  try {
    const [providers, eff] = await Promise.all([
      providersApi.list(),
      agentProfileApi.effectiveConfig(),
    ])
    providersList.value = providers
    effectiveCfg.value = eff
    // 从 profile 同步编辑态（profile 已在 loadProfile 中拿过）
    const mo = (profile.value?.model_override || {}) as Record<string, any>
    moEdit.value = {
      provider_id: mo.provider_id != null ? Number(mo.provider_id) : null,
      temperature: mo.temperature != null && mo.temperature !== ''
        ? Number(mo.temperature)
        : null,
      max_tokens: mo.max_tokens != null && mo.max_tokens !== ''
        ? Number(mo.max_tokens)
        : null,
    }
    const dsp = (profile.value?.default_session_params || {}) as Record<string, any>
    dspEdit.value = {
      max_rounds: dsp.max_rounds != null ? Number(dsp.max_rounds) : null,
      stage: typeof dsp.stage === 'string' ? dsp.stage : '',
      product_kb_id: dsp.product_kb_id != null ? Number(dsp.product_kb_id) : null,
      enterprise_kb_id: dsp.enterprise_kb_id != null
        ? Number(dsp.enterprise_kb_id)
        : null,
    }
  } finally {
    modelLoading.value = false
  }
}

async function saveModelTab() {
  modelSaving.value = true
  try {
    // model_override：去掉所有 null/空字符串，避免存进无意义字段
    const moPayload: Record<string, any> = {}
    if (moEdit.value.provider_id != null) moPayload.provider_id = moEdit.value.provider_id
    if (moEdit.value.temperature != null) moPayload.temperature = moEdit.value.temperature
    if (moEdit.value.max_tokens != null) moPayload.max_tokens = moEdit.value.max_tokens

    const dspPayload: Record<string, any> = {}
    if (dspEdit.value.max_rounds != null) dspPayload.max_rounds = dspEdit.value.max_rounds
    if (dspEdit.value.stage) dspPayload.stage = dspEdit.value.stage
    if (dspEdit.value.product_kb_id != null) dspPayload.product_kb_id = dspEdit.value.product_kb_id
    if (dspEdit.value.enterprise_kb_id != null) dspPayload.enterprise_kb_id = dspEdit.value.enterprise_kb_id

    const updated = await agentProfileApi.update({
      model_override: moPayload,
      default_session_params: dspPayload,
    })
    profile.value = updated
    effectiveCfg.value = await agentProfileApi.effectiveConfig()
    // 同步版本列表（profile.update 会自动新建版本）
    await loadVersions()
    ElMessage.success('销冠模型/会话默认参数已保存，并创建新版本')
  } finally {
    modelSaving.value = false
  }
}

function clearModelOverride() {
  moEdit.value = { provider_id: null, temperature: null, max_tokens: null }
  ElMessage.info('已清空覆盖（保存后将完全跟随全局默认）')
}

const providerOptions = computed(() =>
  providersList.value.map((p) => ({
    value: p.id,
    label: `${p.name} · ${p.model_name}${p.is_default ? ' (默认)' : ''}`,
  }))
)

// ============================================================
// Tab 4：记忆与学习
// ============================================================
async function loadMemory() {
  memoryLoading.value = true
  try {
    memory.value = await agentProfileApi.memory()
  } catch {
    memory.value = null
  } finally {
    memoryLoading.value = false
  }
}

function fmtSourceLabel(s: string): string {
  switch (s) {
    case 'judge_auto': return 'Judge 自动'
    case 'coach_auto': return 'Coach 自动'
    case 'manual': return '人工收藏'
    case 'preset': return '预设训练'
    default: return s
  }
}

// ============================================================
// Tab 3：技能与工具（精简）
// ============================================================
async function loadSkills() {
  skillsLoading.value = true
  try {
    const [toolsResp, cfg] = await Promise.all([
      agentSkillsApi.tools(),
      agentSkillsApi.config(),
    ])
    skillsTools.value = toolsResp.tools || []
    skillsCfg.value = cfg
    skillsEdit.value = {
      enabled_tools: [...(cfg.enabled_tools || [])],
      max_tool_loops: cfg.max_tool_loops,
      tool_top_k_default: cfg.tool_top_k_default,
    }
  } catch {
    skillsTools.value = []
    skillsCfg.value = null
  } finally {
    skillsLoading.value = false
  }
}

const skillsEnabledSet = computed(() => new Set(skillsEdit.value.enabled_tools))

function toggleSkillTool(name: string, on: boolean) {
  const set = new Set(skillsEdit.value.enabled_tools)
  if (on) set.add(name)
  else set.delete(name)
  skillsEdit.value.enabled_tools = Array.from(set)
}

const skillsDirty = computed(() => {
  if (!skillsCfg.value) return false
  const a = JSON.stringify([...(skillsCfg.value.enabled_tools || [])].sort())
  const b = JSON.stringify([...skillsEdit.value.enabled_tools].sort())
  if (a !== b) return true
  if (skillsCfg.value.max_tool_loops !== skillsEdit.value.max_tool_loops) return true
  if (skillsCfg.value.tool_top_k_default !== skillsEdit.value.tool_top_k_default) return true
  return false
})

async function saveSkills() {
  skillsSaving.value = true
  try {
    const cfg = await agentSkillsApi.updateConfig({
      enabled_tools: skillsEdit.value.enabled_tools,
      max_tool_loops: skillsEdit.value.max_tool_loops,
      tool_top_k_default: skillsEdit.value.tool_top_k_default,
    })
    skillsCfg.value = cfg
    ElMessage.success('技能配置已保存')
  } finally {
    skillsSaving.value = false
  }
}

function skillCategoryTag(c: string): 'success' | 'info' | 'warning' | 'primary' | 'danger' {
  switch (c) {
    case 'rag': return 'primary'
    case 'web': return 'success'
    case 'mcp': return 'warning'
    default: return 'info'
  }
}

// ============================================================
// Tab 1：保存 / 回滚
// ============================================================

const dirty = computed(() => {
  if (!profile.value) return false
  if ((profile.value.system_prompt || '') !== editPrompt.value) return true
  if ((profile.value.role_description || '') !== editRoleDesc.value) return true
  const a = JSON.stringify(profile.value.opening_lines || [])
  const b = JSON.stringify(editOpenings.value)
  if (a !== b) return true
  return false
})

const promptCharCount = computed(() => editPrompt.value.length)
const promptLineCount = computed(() => editPrompt.value.split('\n').length)

function discardChanges() {
  if (!profile.value) return
  editPrompt.value = profile.value.system_prompt || ''
  editRoleDesc.value = profile.value.role_description || ''
  editOpenings.value = [...(profile.value.opening_lines || [])]
  ElMessage.info('已恢复到当前已保存的内容')
}

function openSaveDialog() {
  if (!dirty.value) {
    ElMessage.info('没有改动，无需保存')
    return
  }
  saveComment.value = ''
  saveDialogVisible.value = true
}

async function confirmSave() {
  saving.value = true
  try {
    const updated = await agentProfileApi.update({
      system_prompt: editPrompt.value,
      role_description: editRoleDesc.value,
      opening_lines: editOpenings.value.filter((s) => s.trim()),
      version_comment: saveComment.value.trim() || undefined,
    })
    profile.value = updated
    saveDialogVisible.value = false
    ElMessage.success('已保存并建立新版本')
    await loadVersions()
  } finally {
    saving.value = false
  }
}

async function restoreVersion(v: AgentProfileVersion) {
  try {
    await ElMessageBox.confirm(
      `确认回滚到 v${v.version_no}？当前未保存的改动会丢失。`,
      '回滚确认',
      { type: 'warning', confirmButtonText: `回滚 v${v.version_no}`, cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  restoring.value = true
  try {
    const updated = await agentProfileApi.restore(v.version_no)
    profile.value = updated
    editPrompt.value = updated.system_prompt || ''
    editRoleDesc.value = updated.role_description || ''
    editOpenings.value = [...(updated.opening_lines || [])]
    ElMessage.success(`已回滚到 v${v.version_no}，并保留为新版本`)
    await loadVersions()
  } finally {
    restoring.value = false
  }
}

function viewVersion(v: AgentProfileVersion) {
  previewVersion.value = v
  previewDialogVisible.value = true
}

// 开场白管理
function addOpening() {
  editOpenings.value.push('')
}
function removeOpening(i: number) {
  editOpenings.value.splice(i, 1)
}

// ============================================================
// Tab 5：试一试
// ============================================================

async function runTry() {
  if (!tryForm.value.customer_opening.trim()) {
    ElMessage.warning('请填写客户开场白')
    return
  }
  tryRunning.value = true
  tryResp.value = null
  try {
    const resp = await agentProfileApi.tryTurn({
      topic: tryForm.value.topic,
      customer_opening: tryForm.value.customer_opening,
      product_kb_id: tryForm.value.product_kb_id ?? null,
      enterprise_kb_id: tryForm.value.enterprise_kb_id ?? null,
      persona_name: tryForm.value.persona_name,
      persona_age: tryForm.value.persona_age,
      round_idx: 1,
      max_rounds: 8,
    })
    tryResp.value = resp
    if (resp.ok) ElMessage.success('销冠回复已生成')
    else ElMessage.warning(resp.error || '调用失败')
  } finally {
    tryRunning.value = false
  }
}

// ----- 多轮调试模式 -----

function syncTryToChat() {
  /** 把单轮 try 的结果迁移到多轮 chat 列表，方便用户继续追问 */
  if (!tryResp.value || !tryResp.value.ok) {
    ElMessage.info('请先成功跑一轮单次试一试')
    return
  }
  chatHistory.value = [
    { role: 'persona', content: tryForm.value.customer_opening },
    {
      role: 'sales',
      content: tryResp.value.content,
      toolCalls: tryResp.value.tool_calls.map((c) => ({ ...c })),
      strategy: tryResp.value.strategy,
      toolMode: tryResp.value.tool_mode,
    },
  ]
  chatNextInput.value = ''
  ElMessage.success('已迁移到多轮调试模式，请在下方继续输入客户提问')
}

function clearChat() {
  chatHistory.value = []
  chatNextInput.value = ''
}

async function chatSendNext() {
  const next = chatNextInput.value.trim()
  if (!next) {
    ElMessage.warning('请输入客户的下一句发言')
    return
  }
  // 追加客户发言到历史，UI 立刻看到
  chatHistory.value.push({ role: 'persona', content: next })
  const sentInput = next
  chatNextInput.value = ''

  tryRunning.value = true
  try {
    // 把当前 history 中除最后一条（=刚 push 的 persona next）以外的项作为 history
    const historyPayload: TryNextHistoryItem[] = chatHistory.value
      .slice(0, -1)
      .map((m) => ({ speaker: m.role, content: m.content }))

    const resp = await agentProfileApi.tryNext({
      history: historyPayload,
      customer_next: sentInput,
      topic: tryForm.value.topic,
      product_kb_id: tryForm.value.product_kb_id ?? null,
      enterprise_kb_id: tryForm.value.enterprise_kb_id ?? null,
      persona_name: tryForm.value.persona_name,
      persona_age: tryForm.value.persona_age,
      max_rounds: 12,
    })

    if (!resp.ok) {
      chatHistory.value.push({
        role: 'sales',
        content: `[销冠调用失败] ${resp.error || '未知错误'}`,
      })
      ElMessage.warning(resp.error || '销冠调用失败')
      return
    }
    chatHistory.value.push({
      role: 'sales',
      content: resp.content,
      toolCalls: resp.tool_calls.map((c) => ({ ...c })),
      strategy: resp.strategy,
      toolMode: resp.tool_mode,
    })
  } finally {
    tryRunning.value = false
  }
}

function jumpTo(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="page-wrap">
    <DmPageHeader
      title="销冠 Agent"
      subtitle="销冠 Agent 的人格 / 模型 / 技能 / 记忆 集中配置中心。Prompt 改完即时生效，每次保存建一版可回滚。"
    >
      <template #actions>
        <ElButton :icon="RefreshCcw" @click="loadProfile">刷新</ElButton>
      </template>
    </DmPageHeader>

    <ElSkeleton v-if="loading" :rows="6" animated />

    <template v-else-if="profile">
      <ElTabs v-model="activeTab" class="agent-tabs" type="border-card">

        <!-- ============ Tab 1: 人格 Prompt ============ -->
        <ElTabPane label="人格 Prompt" name="persona">
          <div class="tab1-layout">
            <!-- 左：编辑区 -->
            <div class="edit-col">
              <ElForm label-position="top">
                <ElFormItem label="销冠角色一句话定位">
                  <ElInput
                    v-model="editRoleDesc"
                    type="textarea"
                    :rows="2"
                    placeholder="例如：华为终端销冠，擅长在不同客户面前快速建立信任..."
                  />
                </ElFormItem>

                <ElFormItem>
                  <template #label>
                    <div class="prompt-label">
                      <span>System Prompt（Sales Agent 的核心人格说明）</span>
                      <span class="dm-text-muted dm-text-small">
                        {{ promptLineCount }} 行 · {{ promptCharCount }} 字
                      </span>
                    </div>
                  </template>
                  <ElInput
                    v-model="editPrompt"
                    type="textarea"
                    :rows="22"
                    spellcheck="false"
                    class="prompt-editor"
                    placeholder="销冠 Agent 的完整 system prompt..."
                  />
                </ElFormItem>

                <ElFormItem>
                  <template #label>
                    <div class="prompt-label">
                      <span>默认开场白模板（新建对话时下拉选）</span>
                      <ElButton size="small" text type="primary" @click="addOpening">
                        + 新增
                      </ElButton>
                    </div>
                  </template>
                  <div v-if="!editOpenings.length" class="dm-text-muted dm-text-small">
                    暂无开场白，点上方「新增」添加
                  </div>
                  <div
                    v-for="(_, i) in editOpenings"
                    :key="i"
                    class="opening-row"
                  >
                    <span class="opening-idx">#{{ i + 1 }}</span>
                    <ElInput v-model="editOpenings[i]" placeholder="开场白内容" />
                    <ElButton size="small" text type="danger" @click="removeOpening(i)">
                      删除
                    </ElButton>
                  </div>
                </ElFormItem>
              </ElForm>

              <div class="save-bar">
                <ElTag v-if="dirty" type="warning" size="small">有未保存改动</ElTag>
                <ElTag v-else type="success" size="small" effect="plain">已保存</ElTag>
                <span style="flex: 1" />
                <ElButton :disabled="!dirty" @click="discardChanges">放弃改动</ElButton>
                <ElButton
                  type="primary"
                  :icon="Save"
                  :loading="saving"
                  :disabled="!dirty"
                  @click="openSaveDialog"
                >
                  保存并建新版本
                </ElButton>
              </div>
            </div>

            <!-- 右：版本侧栏 -->
            <div class="versions-col">
              <div class="versions-head">
                <ElIcon><History :size="14" /></ElIcon>
                <span>版本历史</span>
                <span class="dm-text-muted dm-text-small">{{ versions.length }} 个</span>
                <span style="flex: 1" />
                <ElButton size="small" text :icon="RefreshCcw" @click="loadVersions" />
              </div>
              <ElSkeleton v-if="loadingVersions" :rows="3" animated />
              <ElEmpty v-else-if="!versions.length" description="暂无历史版本" :image-size="48" />
              <div v-else class="versions-list">
                <div v-for="v in versions" :key="v.id" class="version-item">
                  <div class="version-head">
                    <ElTag size="small" type="primary" effect="plain">v{{ v.version_no }}</ElTag>
                    <span class="dm-text-muted dm-text-small">{{ v.created_at }}</span>
                  </div>
                  <div class="version-comment">{{ v.comment || '（无备注）' }}</div>
                  <div class="version-actions">
                    <ElButton size="small" text @click="viewVersion(v)">查看</ElButton>
                    <ElButton
                      size="small"
                      text
                      type="primary"
                      :icon="RotateCcw"
                      :loading="restoring"
                      @click="restoreVersion(v)"
                    >
                      回滚此版
                    </ElButton>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </ElTabPane>

        <!-- ============ Tab 2: 模型与采样 ============ -->
        <ElTabPane label="模型与采样" name="model">
          <ElSkeleton v-if="modelLoading" :rows="4" animated />

          <template v-else>
            <!-- 当前生效卡片 -->
            <div
              v-if="effectiveCfg"
              class="effective-card"
              :class="{ 'has-override': effectiveCfg.has_any_override }"
            >
              <div class="eff-head">
                <ElIcon><Cpu :size="14" /></ElIcon>
                <span class="eff-title">当前生效配置</span>
                <ElTag
                  v-if="effectiveCfg.has_any_override"
                  type="warning"
                  size="small"
                  effect="plain"
                >
                  销冠覆盖生效
                </ElTag>
                <ElTag v-else type="info" size="small" effect="plain">
                  完全跟随全局默认
                </ElTag>
                <span style="flex: 1" />
                <ElButton size="small" text :icon="RefreshCcw" @click="loadModelTab">
                  刷新
                </ElButton>
              </div>
              <div class="eff-grid">
                <div class="eff-cell">
                  <div class="eff-label">Model</div>
                  <div class="eff-value mono">{{ effectiveCfg.effective_model }}</div>
                </div>
                <div class="eff-cell">
                  <div class="eff-label">Temperature</div>
                  <div class="eff-value mono">
                    {{ effectiveCfg.effective_temperature.toFixed(2) }}
                  </div>
                </div>
                <div class="eff-cell">
                  <div class="eff-label">Max tokens</div>
                  <div class="eff-value mono">
                    {{ effectiveCfg.effective_max_tokens ?? '—' }}
                  </div>
                </div>
                <div class="eff-cell">
                  <div class="eff-label">Provider</div>
                  <div class="eff-value">
                    {{ effectiveCfg.override_provider?.name
                       || effectiveCfg.global_default.name
                       || '(env)' }}
                    <span class="dm-text-small dm-text-muted">
                      ({{ effectiveCfg.override_provider ? '销冠覆盖' : '全局默认' }})
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div class="model-section-row">
              <!-- 左：销冠 model_override -->
              <div class="model-col">
                <div class="sub-title-tiny">销冠专属覆盖（留空 = 跟随全局）</div>
                <ElForm label-position="top" class="model-form">
                  <ElFormItem label="Provider 覆盖">
                    <ElSelect
                      v-model="moEdit.provider_id"
                      placeholder="跟随全局默认"
                      clearable
                      style="width: 100%"
                    >
                      <ElOption
                        v-for="opt in providerOptions"
                        :key="opt.value"
                        :label="opt.label"
                        :value="opt.value"
                      />
                    </ElSelect>
                  </ElFormItem>
                  <ElFormItem label="Temperature 覆盖">
                    <div class="slider-row">
                      <ElSlider
                        v-model="moEdit.temperature"
                        :min="0"
                        :max="2"
                        :step="0.05"
                        :marks="{ 0.1: '严谨', 0.7: '默认', 1.2: '发散' }"
                        style="flex: 1"
                      />
                      <ElButton
                        v-if="moEdit.temperature != null"
                        size="small"
                        text
                        @click="moEdit.temperature = null"
                      >
                        清空
                      </ElButton>
                    </div>
                    <div class="form-hint">
                      留空 = 跟随 provider 默认。建议销冠走 0.5–0.8。
                    </div>
                  </ElFormItem>
                  <ElFormItem label="Max tokens 覆盖">
                    <ElInputNumber
                      v-model="moEdit.max_tokens"
                      :min="64"
                      :max="8192"
                      :step="64"
                      controls-position="right"
                      placeholder="留空 = 不限"
                      style="width: 180px"
                    />
                    <span class="form-hint">单轮回复最大长度</span>
                  </ElFormItem>
                  <div>
                    <ElButton size="small" plain @click="clearModelOverride">
                      一键清空所有覆盖
                    </ElButton>
                  </div>
                </ElForm>
              </div>

              <!-- 右：default_session_params -->
              <div class="model-col">
                <div class="sub-title-tiny">默认会话参数（"新建对话"页将自动带入）</div>
                <ElForm label-position="top" class="model-form">
                  <ElFormItem label="默认最大轮数">
                    <ElInputNumber
                      v-model="dspEdit.max_rounds"
                      :min="6"
                      :max="50"
                      controls-position="right"
                      placeholder="未设置"
                      style="width: 180px"
                    />
                  </ElFormItem>
                  <ElFormItem label="默认起始阶段">
                    <ElSelect
                      v-model="dspEdit.stage"
                      clearable
                      style="width: 100%"
                      placeholder="未设置"
                    >
                      <ElOption label="开场与需求暴露" value="开场与需求暴露" />
                      <ElOption label="中段·需求挖掘" value="中段·需求挖掘" />
                      <ElOption label="中段·方案匹配" value="中段·方案匹配" />
                      <ElOption label="收尾·促成成交" value="收尾·促成成交" />
                    </ElSelect>
                  </ElFormItem>
                  <ElFormItem label="默认产品知识库 ID">
                    <ElInputNumber
                      v-model="dspEdit.product_kb_id"
                      :min="1"
                      controls-position="right"
                      placeholder="未绑定"
                      style="width: 180px"
                    />
                    <ElButton
                      size="small"
                      text
                      :icon="ArrowRight"
                      @click="jumpTo('/kb/product')"
                    >
                      查看
                    </ElButton>
                  </ElFormItem>
                  <ElFormItem label="默认企业知识库 ID">
                    <ElInputNumber
                      v-model="dspEdit.enterprise_kb_id"
                      :min="1"
                      controls-position="right"
                      placeholder="未绑定"
                      style="width: 180px"
                    />
                    <ElButton
                      size="small"
                      text
                      :icon="ArrowRight"
                      @click="jumpTo('/kb/enterprise')"
                    >
                      查看
                    </ElButton>
                  </ElFormItem>
                </ElForm>
              </div>
            </div>

            <div class="save-bar">
              <ElButton
                size="small"
                text
                :icon="Settings"
                @click="jumpTo('/settings/model')"
              >
                管理全局 Provider
              </ElButton>
              <span style="flex: 1" />
              <ElButton
                type="primary"
                :icon="Save"
                :loading="modelSaving"
                @click="saveModelTab"
              >
                保存并创建新版本
              </ElButton>
            </div>
          </template>
        </ElTabPane>

        <!-- ============ Tab 3: 技能与工具 ============ -->
        <ElTabPane label="技能与工具" name="skills">
          <ElSkeleton v-if="skillsLoading" :rows="4" animated />
          <template v-else>
            <div class="skills-head-row">
              <div class="skills-head-info">
                启用 {{ skillsEdit.enabled_tools.length }} / {{ skillsTools.length }} 个工具
                · max_tool_loops {{ skillsEdit.max_tool_loops }}
                · top_k 默认 {{ skillsEdit.tool_top_k_default }}
              </div>
              <ElButton
                size="small"
                :icon="Settings"
                @click="jumpTo('/settings/skills')"
              >
                高级配置（WebSearch / MCP）
              </ElButton>
            </div>

            <ElForm label-position="top" class="skills-form">
              <ElFormItem label="单轮最大工具调用次数（max_tool_loops）">
                <ElInputNumber
                  v-model="skillsEdit.max_tool_loops"
                  :min="0"
                  :max="8"
                  controls-position="right"
                  style="width: 140px"
                />
                <span class="form-hint">
                  0 = 关闭工具自助检索（销冠走老 RAG 注入路径）
                </span>
              </ElFormItem>
              <ElFormItem label="工具默认 top_k">
                <ElInputNumber
                  v-model="skillsEdit.tool_top_k_default"
                  :min="1"
                  :max="10"
                  controls-position="right"
                  style="width: 140px"
                />
              </ElFormItem>
            </ElForm>

            <div class="skills-list">
              <div
                v-for="t in skillsTools"
                :key="t.name"
                class="skill-row"
                :class="{ disabled: !skillsEnabledSet.has(t.name) }"
              >
                <ElSwitch
                  :model-value="skillsEnabledSet.has(t.name)"
                  @update:model-value="(v: any) => toggleSkillTool(t.name, Boolean(v))"
                />
                <div class="skill-info">
                  <div class="skill-title">
                    <span class="mono">{{ t.name }}</span>
                    <ElTag :type="skillCategoryTag(t.category)" size="small" effect="light">
                      {{ t.category }}
                    </ElTag>
                  </div>
                  <div class="skill-desc">{{ t.description }}</div>
                </div>
              </div>
            </div>

            <div class="save-bar">
              <ElTag v-if="skillsDirty" type="warning" size="small">有未保存改动</ElTag>
              <ElTag v-else type="success" size="small" effect="plain">已同步</ElTag>
              <span style="flex: 1" />
              <ElButton
                type="primary"
                :icon="Save"
                :loading="skillsSaving"
                :disabled="!skillsDirty"
                @click="saveSkills"
              >
                保存技能配置
              </ElButton>
            </div>
          </template>
        </ElTabPane>

        <!-- ============ Tab 4: 记忆与学习 ============ -->
        <ElTabPane label="记忆与学习" name="memory">
          <ElSkeleton v-if="memoryLoading" :rows="4" animated />

          <template v-else-if="memory">
            <div class="memory-head-row">
              <span class="dm-text-small dm-text-muted">
                销冠已学到的全部资料一览
              </span>
              <ElButton size="small" :icon="RefreshCcw" @click="loadMemory">刷新</ElButton>
            </div>

            <div class="memory-cards">
              <!-- 产品库 -->
              <div class="memory-card" @click="jumpTo('/kb/product')">
                <div class="memory-card-head">
                  <ElIcon :size="20"><Box /></ElIcon>
                  <span class="memory-title">产品知识库</span>
                  <ElTag
                    v-if="memory.product_kb.is_default_bound"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    默认绑定
                  </ElTag>
                </div>
                <div class="memory-name">
                  {{ memory.product_kb.name || '（未配置）' }}
                </div>
                <div class="memory-stats">
                  <div class="stat">
                    <span class="stat-num">{{ memory.product_kb.file_count }}</span>
                    <span class="stat-label">文件</span>
                  </div>
                  <div class="stat">
                    <span class="stat-num">{{ memory.product_kb.chunk_count }}</span>
                    <span class="stat-label">chunks</span>
                  </div>
                </div>
                <div class="memory-last">
                  最近上传：{{ memory.product_kb.last_uploaded_at || '—' }}
                </div>
                <ElButton size="small" type="primary" plain :icon="ArrowRight">
                  上传新资料
                </ElButton>
              </div>

              <!-- 企业库 -->
              <div class="memory-card" @click="jumpTo('/kb/enterprise')">
                <div class="memory-card-head">
                  <ElIcon :size="20"><Building2 /></ElIcon>
                  <span class="memory-title">企业知识库</span>
                  <ElTag
                    v-if="memory.enterprise_kb.is_default_bound"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    默认绑定
                  </ElTag>
                </div>
                <div class="memory-name">
                  {{ memory.enterprise_kb.name || '（未配置）' }}
                </div>
                <div class="memory-stats">
                  <div class="stat">
                    <span class="stat-num">{{ memory.enterprise_kb.file_count }}</span>
                    <span class="stat-label">文件</span>
                  </div>
                  <div class="stat">
                    <span class="stat-num">{{ memory.enterprise_kb.chunk_count }}</span>
                    <span class="stat-label">chunks</span>
                  </div>
                </div>
                <div class="memory-last">
                  最近上传：{{ memory.enterprise_kb.last_uploaded_at || '—' }}
                </div>
                <ElButton size="small" type="primary" plain :icon="ArrowRight">
                  上传新资料
                </ElButton>
              </div>

              <!-- 案例集 -->
              <div class="memory-card" @click="jumpTo('/kb/cases')">
                <div class="memory-card-head">
                  <ElIcon :size="20"><BookOpen /></ElIcon>
                  <span class="memory-title">销售案例集</span>
                </div>
                <div class="memory-name">沉淀的精彩对话</div>
                <div class="memory-stats">
                  <div class="stat">
                    <span class="stat-num">{{ memory.sales_cases.total }}</span>
                    <span class="stat-label">案例</span>
                  </div>
                </div>
                <div class="memory-source-list">
                  <span
                    v-for="(n, k) in memory.sales_cases.by_source"
                    :key="k"
                    class="source-pill"
                  >{{ fmtSourceLabel(String(k)) }}: {{ n }}</span>
                </div>
                <ElButton size="small" type="primary" plain :icon="ArrowRight">
                  查看案例
                </ElButton>
              </div>
            </div>

            <!-- 最近上传 -->
            <div class="recent-uploads">
              <div class="sub-title-tiny">最近上传</div>
              <div v-if="!memory.recent_uploads.length" class="dm-text-muted dm-text-small">
                还没有任何上传记录
              </div>
              <ul v-else class="recent-list">
                <li v-for="u in memory.recent_uploads" :key="u.kb_id + '_' + u.filename">
                  <ElTag size="small" type="info" effect="plain">{{ u.kb_type }}</ElTag>
                  <span class="recent-kb-name">{{ u.kb_name || '?' }}</span>
                  <span class="recent-filename">{{ u.filename }}</span>
                  <ElTag
                    v-if="u.status === 'ready'"
                    size="small"
                    type="success"
                    effect="plain"
                  >
                    {{ u.chunk_count }} chunks
                  </ElTag>
                  <ElTag
                    v-else
                    size="small"
                    :type="u.status === 'failed' ? 'danger' : 'warning'"
                    effect="plain"
                  >
                    {{ u.status }}
                  </ElTag>
                  <span class="dm-text-muted dm-text-small">{{ u.created_at }}</span>
                </li>
              </ul>
            </div>
          </template>

          <ElEmpty v-else description="无法加载记忆数据" />
        </ElTabPane>

        <!-- ============ Tab 5: 试一试 ============ -->
        <ElTabPane label="试一试" name="try">
          <div class="try-layout">
            <!-- 左：输入 -->
            <div class="try-input-col">
              <ElForm label-position="top">
                <ElFormItem label="话题（topic）">
                  <ElInput v-model="tryForm.topic" />
                </ElFormItem>
                <ElFormItem label="客户开场白 / 当前发言">
                  <ElInput
                    v-model="tryForm.customer_opening"
                    type="textarea"
                    :rows="5"
                    placeholder="客户对销冠说的话，将作为本轮 persona turn 传入"
                  />
                </ElFormItem>
                <ElFormItem label="客户人设（仅用于测试）">
                  <div class="row-2col">
                    <ElInput v-model="tryForm.persona_name" placeholder="人设名" />
                    <ElInputNumber
                      v-model="tryForm.persona_age"
                      :min="16"
                      :max="80"
                      controls-position="right"
                    />
                  </div>
                </ElFormItem>
                <ElFormItem label="（可选）绑定 KB ID">
                  <div class="row-2col">
                    <ElInputNumber
                      v-model="tryForm.product_kb_id"
                      :min="1"
                      placeholder="product_kb_id"
                      controls-position="right"
                    />
                    <ElInputNumber
                      v-model="tryForm.enterprise_kb_id"
                      :min="1"
                      placeholder="enterprise_kb_id"
                      controls-position="right"
                    />
                  </div>
                  <div class="form-hint">
                    留空 = 不挂 KB（fallback 走 product_text）；填了销冠会 RAG 检索
                  </div>
                </ElFormItem>
              </ElForm>
              <div class="try-actions">
                <ElButton
                  type="primary"
                  :icon="Play"
                  :loading="tryRunning"
                  @click="runTry"
                >
                  调用销冠 Agent
                </ElButton>
              </div>
            </div>

            <!-- 右：单轮输出 + 多轮调试 -->
            <div class="try-output-col">
              <div class="try-output-head">
                <ElIcon><Brain :size="14" /></ElIcon>
                <span>销冠回复（单轮试一试）</span>
                <ElTag v-if="tryResp?.tool_mode" size="small" type="success" effect="plain">
                  {{ tryResp.tool_mode }}
                </ElTag>
                <span style="flex: 1" />
                <ElButton
                  v-if="tryResp?.ok"
                  size="small"
                  type="primary"
                  plain
                  @click="syncTryToChat"
                >
                  → 进入多轮调试
                </ElButton>
              </div>

              <div v-if="!tryResp" class="dm-text-muted">点击左侧「调用销冠 Agent」试一下</div>

              <template v-else-if="!tryResp.ok">
                <div class="try-err">{{ tryResp.error || '调用失败' }}</div>
              </template>

              <template v-else>
                <div class="try-content">{{ tryResp.content || '（销冠没说话）' }}</div>

                <div v-if="Object.keys(tryResp.strategy || {}).length" class="try-block">
                  <div class="sub-title-tiny">strategy</div>
                  <pre class="try-pre">{{ JSON.stringify(tryResp.strategy, null, 2) }}</pre>
                </div>

                <div v-if="tryResp.tool_calls?.length" class="try-block">
                  <div class="sub-title-tiny">
                    工具调用 {{ tryResp.tool_calls.length }} 次
                  </div>
                  <div
                    v-for="(c, i) in tryResp.tool_calls"
                    :key="i"
                    class="tool-call-item"
                  >
                    <div class="tool-call-head">
                      <ElTag size="small" type="info" effect="plain">loop {{ c.loop }}</ElTag>
                      <span class="mono">{{ c.name }}</span>
                      <ElTag v-if="!c.ok" size="small" type="danger">失败</ElTag>
                    </div>
                    <div class="tool-call-args mono">
                      args = {{ JSON.stringify(c.arguments) }}
                    </div>
                    <pre class="try-pre try-pre-small">{{ c.result_preview }}</pre>
                  </div>
                </div>

                <div
                  v-if="tryResp.used_product_kb?.length || tryResp.used_enterprise_kb?.length"
                  class="try-block"
                >
                  <div class="sub-title-tiny">命中 KB chunks</div>
                  <div class="dm-text-small">
                    product: {{ tryResp.used_product_kb.length }} ·
                    enterprise: {{ tryResp.used_enterprise_kb.length }}
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- 多轮调试区（始终展示，无历史时显示引导） -->
          <div class="chat-section">
            <div class="chat-head">
              <ElIcon><Brain :size="14" /></ElIcon>
              <span>多轮调试</span>
              <span class="dm-text-small dm-text-muted">
                {{ chatHistory.length }} 条记录
              </span>
              <span style="flex: 1" />
              <ElButton
                v-if="chatHistory.length"
                size="small"
                type="danger"
                plain
                @click="clearChat"
              >
                清空对话
              </ElButton>
            </div>

            <div v-if="!chatHistory.length" class="chat-empty dm-text-small dm-text-muted">
              先在上方跑一轮单次试一试 → 点「→ 进入多轮调试」开始，<br>
              或者直接在下方输入框开始客户提问。
            </div>

            <div v-else class="chat-list">
              <div
                v-for="(m, i) in chatHistory"
                :key="i"
                class="chat-msg"
                :class="m.role"
              >
                <div class="chat-msg-head">
                  <span class="chat-role">{{ m.role === 'sales' ? '销冠' : '客户' }}</span>
                  <ElTag
                    v-if="m.toolCalls?.length"
                    size="small"
                    type="info"
                    effect="plain"
                  >
                    工具调用 {{ m.toolCalls.length }} 次
                  </ElTag>
                </div>
                <div class="chat-msg-content">{{ m.content }}</div>
                <details v-if="m.toolCalls?.length" class="chat-tool-details">
                  <summary class="dm-text-small dm-text-muted">查看工具调用详情</summary>
                  <div
                    v-for="(c, ci) in m.toolCalls"
                    :key="ci"
                    class="tool-call-item"
                  >
                    <div class="tool-call-head">
                      <ElTag size="small" type="info" effect="plain">loop {{ c.loop }}</ElTag>
                      <span class="mono">{{ c.name }}</span>
                    </div>
                    <div class="tool-call-args mono">
                      args = {{ JSON.stringify(c.arguments) }}
                    </div>
                    <pre class="try-pre try-pre-small">{{ c.result_preview }}</pre>
                  </div>
                </details>
              </div>
            </div>

            <div class="chat-input-row">
              <ElInput
                v-model="chatNextInput"
                type="textarea"
                :rows="2"
                placeholder="输入客户的下一句发言，回车键 Ctrl+Enter 发送"
                @keydown.ctrl.enter="chatSendNext"
              />
              <ElButton
                type="primary"
                :icon="Play"
                :loading="tryRunning"
                @click="chatSendNext"
              >
                让销冠回复
              </ElButton>
            </div>
          </div>
        </ElTabPane>

      </ElTabs>
    </template>

    <ElEmpty v-else description="无法加载销冠 Agent 配置" />

    <!-- 保存对话框（输入备注） -->
    <ElDialog v-model="saveDialogVisible" title="保存并建新版本" width="480">
      <p class="dm-text-small">每次保存都会建立一个新版本快照，可在右侧版本侧栏回滚。</p>
      <ElInput
        v-model="saveComment"
        type="textarea"
        :rows="3"
        placeholder="（可选）本次改动备注，例如：调整开场白；增加竞品对比话术"
      />
      <template #footer>
        <ElButton @click="saveDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="saving" @click="confirmSave">保存</ElButton>
      </template>
    </ElDialog>

    <!-- 版本预览对话框 -->
    <ElDialog
      v-model="previewDialogVisible"
      :title="previewVersion ? 'v' + previewVersion.version_no + ' 快照' : '版本快照'"
      width="720"
    >
      <template v-if="previewVersion">
        <div class="preview-block">
          <div class="sub-title-tiny">role_description</div>
          <div class="preview-text">
            {{ previewVersion.snapshot.role_description || '（空）' }}
          </div>
        </div>
        <div class="preview-block">
          <div class="sub-title-tiny">
            system_prompt（{{ (previewVersion.snapshot.system_prompt || '').length }} 字）
          </div>
          <pre class="preview-pre">{{ previewVersion.snapshot.system_prompt || '（空）' }}</pre>
        </div>
        <div class="preview-block">
          <div class="sub-title-tiny">开场白</div>
          <ul class="preview-list">
            <li
              v-for="(s, i) in (previewVersion.snapshot.opening_lines || [])"
              :key="i"
            >{{ s }}</li>
          </ul>
        </div>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped lang="scss">
.page-wrap {
  padding: 24px 28px 60px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.agent-tabs {
  border-radius: 12px;
  border: 1px solid var(--dm-border, #ebebea);
}

.sub-title-tiny {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--dm-text-muted, #8b8a87);
  margin-bottom: 4px;
  letter-spacing: 0.4px;
}
.mono {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
}
.dm-text-muted { color: var(--dm-text-muted, #8b8a87); }
.dm-text-small { font-size: 12px; }
.form-hint { font-size: 12px; color: var(--dm-text-muted, #8b8a87); }

// ========== Tab 1 ==========
.tab1-layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 18px;
}
.edit-col { min-width: 0; }
.versions-col {
  border-left: 1px dashed var(--dm-border, #ebebea);
  padding-left: 16px;
}

.prompt-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.prompt-editor :deep(textarea) {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.opening-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.opening-idx {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  color: var(--dm-text-muted, #8b8a87);
  font-size: 12px;
  width: 32px;
}

.save-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--dm-border, #ebebea);
}

.versions-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 10px;
}
.versions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 600px;
  overflow-y: auto;
}
.version-item {
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--dm-bg-surface, #fff);

  &:hover { border-color: #4f46e5; }
}
.version-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.version-comment {
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--dm-text, #2c2b29);
  margin-bottom: 6px;
  word-break: break-word;
}
.version-actions {
  display: flex;
  gap: 4px;
}

// ========== Tab 2 模型与采样 ==========
.effective-card {
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 10px;
  background: linear-gradient(180deg, #fafaf9 0%, #ffffff 100%);

  &.has-override {
    background: linear-gradient(180deg, #fffbeb 0%, #ffffff 100%);
    border-color: #fde68a;
  }
}
.eff-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--dm-border, #ebebea);
}
.eff-title { font-weight: 600; font-size: 13.5px; }
.eff-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
}
.eff-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.eff-label {
  font-size: 11.5px;
  color: var(--dm-text-muted, #8b8a87);
  letter-spacing: 0.4px;
  text-transform: uppercase;
}
.eff-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--dm-text, #2c2b29);
}

.model-section-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  padding-top: 4px;

  @media (max-width: 1100px) {
    grid-template-columns: 1fr;
  }
}
.model-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.model-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
  /* ElFormItem 内容区是 flex，子项默认 flex:0 1 auto，
     而内部 ElSlider 用 flex:1（basis 0、无固有宽度）会把本行收缩到 0 宽，
     导致轨道塌缩、刻度全挤在左侧。撑满整行宽度即可。 */
  width: 100%;
  /* ElSlider 的刻度标签(严谨/默认/发散)绝对定位在轨道下方约 30px 处，
     此处预留竖向空间，否则刻度文字会压住下面的提示与「Max tokens 覆盖」项 */
  padding-bottom: 30px;
}
/* 刻度文字两端(严谨/发散)不换行、不溢出轨道两侧 */
.model-form :deep(.el-slider__marks-text) {
  white-space: nowrap;
  font-size: 11.5px;
}

// ========== Tab 3 技能（精简内嵌） ==========
.skills-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--dm-border, #ebebea);
}
.skills-head-info {
  font-size: 13px;
  color: var(--dm-text-muted, #8b8a87);
}
.skills-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 24px;
  margin-bottom: 14px;
}
.skills-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.skill-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 8px;
  background: var(--dm-bg-surface, #fff);

  &.disabled {
    background: #fafafa;
    opacity: 0.85;
  }
}
.skill-info { flex: 1; min-width: 0; }
.skill-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 4px;
}
.skill-desc {
  font-size: 12.5px;
  color: var(--dm-text-muted, #8b8a87);
  line-height: 1.55;
}

// ========== Tab 4 占位 ==========
.placeholder-card {
  text-align: center;
  padding: 40px 20px;
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 12px;
}
.placeholder-icon { color: #4f46e5; margin-bottom: 12px; }
.placeholder-title { font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.placeholder-desc {
  color: var(--dm-text-muted, #8b8a87);
  font-size: 13px;
  margin-bottom: 18px;
  max-width: 520px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.6;
}

// ========== Tab 4 记忆 ==========
.memory-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.memory-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.memory-card {
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 10px;
  padding: 16px;
  background: var(--dm-bg-surface, #fff);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;

  &:hover {
    border-color: #4f46e5;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  }
}
.memory-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.memory-title { font-weight: 600; font-size: 14px; }
.memory-name {
  font-size: 13px;
  color: var(--dm-text, #2c2b29);
  font-weight: 500;
}
.memory-stats {
  display: flex;
  gap: 18px;
  padding: 8px 12px;
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 6px;
}
.stat {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.stat-num {
  font-size: 20px;
  font-weight: 700;
  color: #4f46e5;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.stat-label {
  font-size: 11px;
  color: var(--dm-text-muted, #8b8a87);
  letter-spacing: 0.4px;
}
.memory-last {
  font-size: 12px;
  color: var(--dm-text-muted, #8b8a87);
}
.memory-source-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.source-pill {
  background: #ecfdf5;
  color: #065f46;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11.5px;
  border: 1px solid #a7f3d0;
}

.recent-uploads {
  margin-top: 18px;
  padding: 12px 14px;
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 8px;
}
.recent-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;

  li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    font-size: 12.5px;
    border-bottom: 1px dashed var(--dm-border, #ebebea);

    &:last-child { border-bottom: none; }
  }
}
.recent-kb-name { font-weight: 500; min-width: 80px; }
.recent-filename {
  flex: 1;
  min-width: 0;
  color: var(--dm-text-muted, #8b8a87);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

// ========== Tab 5 试一试 ==========
.try-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.try-input-col { min-width: 0; }
.try-output-col {
  min-width: 0;
  border-left: 1px dashed var(--dm-border, #ebebea);
  padding-left: 16px;
}
.row-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.try-actions { margin-top: 10px; }
.try-output-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
}
.try-content {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e3a8a;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.try-err {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12.5px;
}
.try-block { margin-top: 14px; }
.try-pre {
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11.5px;
  line-height: 1.55;
  padding: 10px 12px;
  border-radius: 6px;
  max-height: 240px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.try-pre-small {
  max-height: 140px;
  font-size: 11px;
}
.tool-call-item {
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.tool-call-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.tool-call-args {
  font-size: 11.5px;
  color: var(--dm-text-muted, #8b8a87);
  margin-bottom: 6px;
}

// ========== Tab 5 多轮调试 ==========
.chat-section {
  margin-top: 20px;
  padding: 16px;
  background: var(--dm-bg-surface, #fff);
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 10px;
}
.chat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--dm-border, #ebebea);
  font-weight: 600;
  font-size: 14px;
}
.chat-empty {
  padding: 16px 12px;
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 6px;
  text-align: center;
  line-height: 1.7;
}
.chat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
  max-height: 520px;
  overflow-y: auto;
}
.chat-msg {
  border-radius: 8px;
  padding: 10px 12px;
  border: 1px solid var(--dm-border, #ebebea);
  background: var(--dm-bg-surface, #fff);

  &.persona {
    background: #fafaf9;
  }
  &.sales {
    background: #eef2ff;
    border-color: #c7d2fe;
  }
}
.chat-msg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.chat-role {
  font-weight: 600;
  font-size: 12.5px;
}
.chat-msg-content {
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-tool-details {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #cbd5e1;

  summary { cursor: pointer; user-select: none; }
}
.chat-input-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;

  :deep(.el-textarea) { flex: 1; }
}

// ========== 预览对话框 ==========
.preview-block { margin-bottom: 14px; }
.preview-text {
  background: var(--dm-bg-subtle, #f7f6f3);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.preview-pre {
  background: var(--dm-bg-subtle, #f7f6f3);
  padding: 10px 12px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.6;
  max-height: 380px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}
.preview-list {
  margin: 0;
  padding-left: 20px;

  li { margin-bottom: 4px; font-size: 13px; }
}
</style>
