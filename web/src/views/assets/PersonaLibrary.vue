<script setup lang="ts">
/**
 * Persona 人设库主页（蓝图 §Stage 3）
 * 卡片网格 + 顶部筛选 + 详情抽屉（三 tabs）+ 手动创建 dialog + 文件上传
 *
 * 简化决定（对齐 simplicity first）：
 * - 「✨ LLM 生成」按钮暂禁用（蓝图 generate 接口未实装）
 * - 雷达图用 9 个迷你 progress bar 代替（蓝图允许）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElCol,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElProgress,
  ElRadio,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSlider,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload,
  type FormInstance,
  type UploadInstance,
  type UploadRawFile,
} from 'element-plus'
import {
  Plus,
  Upload as UploadIcon,
  Sparkles,
  Search,
  Trash2,
  RefreshCcw,
  Save,
  X as XIcon,
} from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import PersonaAvatar from '@/components/PersonaAvatar.vue'
import { usePersonasStore } from '@/stores/personas'
import {
  DEFAULT_PRESSURE,
  PRESSURE_DIMENSIONS,
  personasApi,
  type CountryOption,
  type Persona,
  type PersonaCreatePayload,
  type PersonaFormat,
  type PressureProfile,
  type ClarifyQuestion,
  type PersonaDraft,
} from '@/api/personas'

const store = usePersonasStore()

// ===== 顶部筛选 =====
const filterFormat = ref<PersonaFormat | ''>('')
const filterTag = ref('')
const searchKw = ref('')

async function applyFilter() {
  await store.fetchAll({
    format_type: filterFormat.value || undefined,
    tag: filterTag.value || undefined,
    search: searchKw.value.trim() || undefined,
  })
}

onMounted(() => applyFilter())

// 搜索关键字加 debounce，避免每输入一字符就请求
let searchTimer: number | null = null
watch(searchKw, () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(applyFilter, 350)
})
watch([filterFormat, filterTag], () => applyFilter())

function resetFilters() {
  filterFormat.value = ''
  filterTag.value = ''
  searchKw.value = ''
  applyFilter()
}

// ===== 卡片辅助 =====
function fmtLabel(f: PersonaFormat): string {
  return f === 'prompt_based' ? 'Prompt' : 'Structured'
}
function fmtType(f: PersonaFormat): 'primary' | 'success' {
  return f === 'prompt_based' ? 'primary' : 'success'
}
function truncate(s: string | null | undefined, n = 80): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '...' : s
}

// 卡片上的压力摘要：只显示 3 个高显著维度
function topPressure(p: PressureProfile): { key: string; label: string; val: number }[] {
  const items = PRESSURE_DIMENSIONS.map((d) => ({
    key: d.key as string,
    label: d.label,
    val: p[d.key] ?? 0.5,
  }))
  items.sort((a, b) => Math.abs(b.val - 0.5) - Math.abs(a.val - 0.5))
  return items.slice(0, 3)
}

function pressureColor(v: number): string {
  if (v >= 0.7) return '#ef4444'
  if (v <= 0.3) return '#3b82f6'
  return '#94a3b8'
}

// ===== 详情抽屉 =====
const drawerVisible = ref(false)
const editTab = ref<'desc' | 'pressure' | 'profile'>('desc')

// 编辑态副本（避免直接改 store.current）
const editDraft = reactive<{
  id: number | null
  name: string
  format_type: PersonaFormat
  prompt_text: string
  pressure: PressureProfile
  tags: string[]
  source: string
  profile: Record<string, any>
  avatar_key: string | null
  // v0.2.1
  country_code: string | null
  currency: string | null
  market_domains: string[]
}>({
  id: null,
  name: '',
  format_type: 'prompt_based',
  prompt_text: '',
  pressure: { ...DEFAULT_PRESSURE },
  tags: [],
  source: '',
  profile: {},
  avatar_key: null,
  country_code: null,
  currency: null,
  market_domains: [],
})

// v0.2.1：国家清单（编辑弹窗下拉用，挂载时加载一次）
const countryOptions = ref<CountryOption[]>([])
onMounted(async () => {
  try {
    countryOptions.value = await personasApi.listCountries()
  } catch {
    /* 加载失败不阻塞主流程；下拉就空 */
  }
})

// 当用户改国家时，自动同步货币 + 默认域名（如果用户没自定义过域名）
function onCountryChange(code: string | null) {
  if (!code) {
    editDraft.currency = null
    editDraft.market_domains = []
    return
  }
  const opt = countryOptions.value.find((c) => c.code === code)
  if (!opt) return
  // 货币：直接同步
  editDraft.currency = opt.currency
  // 域名：只在为空时才覆盖（保留用户自定义）
  if (!editDraft.market_domains?.length) {
    editDraft.market_domains = [...opt.default_market_domains]
  }
}

function loadIntoDraft(p: Persona) {
  editDraft.id = p.id
  editDraft.name = p.name
  editDraft.format_type = p.format_type
  editDraft.prompt_text = p.prompt_text ?? ''
  editDraft.pressure = { ...DEFAULT_PRESSURE, ...(p.pressure || {}) }
  editDraft.tags = [...(p.tags || [])]
  editDraft.source = p.source ?? ''
  editDraft.profile = { ...(p.profile || {}) }
  editDraft.avatar_key = p.avatar_key ?? null
  editDraft.country_code = p.country_code ?? null
  editDraft.currency = p.currency ?? null
  editDraft.market_domains = [...(p.market_domains || [])]
}

async function openDetail(p: Persona) {
  loadIntoDraft(p)
  editTab.value = 'desc'
  drawerVisible.value = true
  // 取最新详情（pressure 可能在别处被更新）
  try {
    const fresh = await store.fetchDetail(p.id)
    loadIntoDraft(fresh)
  } catch {
    /* 抽屉里继续用列表数据即可 */
  }
}

async function saveDraft() {
  if (!editDraft.id) return
  // v0.2.1：保存时把 country_name 也带上（用 registry 反查保证一致）
  const cn = editDraft.country_code
    ? countryOptions.value.find((c) => c.code === editDraft.country_code)?.name_cn ?? null
    : null
  try {
    await store.update(editDraft.id, {
      name: editDraft.name,
      format_type: editDraft.format_type,
      prompt_text: editDraft.prompt_text,
      pressure: editDraft.pressure,
      tags: editDraft.tags,
      source: editDraft.source,
      profile: editDraft.profile,
      avatar_key: editDraft.avatar_key,
      country_code: editDraft.country_code,
      country_name: cn,
      currency: editDraft.currency,
      market_domains: editDraft.market_domains,
    })
    ElMessage.success('已保存')
    drawerVisible.value = false
  } catch (e: any) {
    ElMessage.error(`保存失败：${e?.message || e}`)
  }
}

const extracting = ref(false)
async function reExtractPressure() {
  if (!editDraft.id) return
  if (editDraft.format_type !== 'prompt_based') {
    ElMessage.warning('仅 prompt_based 支持自动抽参')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将调用 LLM 重新抽取 9 维量化参数，会覆盖当前参数。继续？',
      '重新抽取',
      { type: 'warning' },
    )
  } catch {
    return
  }
  extracting.value = true
  try {
    const updated = await store.extractPressure(editDraft.id)
    loadIntoDraft(updated)
    ElMessage.success('LLM 抽取完成')
  } catch (e: any) {
    ElMessage.error(`抽取失败：${e?.message || e}`)
  } finally {
    extracting.value = false
  }
}

async function handleDelete(p: Persona) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${p.name}」？该操作不可恢复。`,
      '删除人设',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await store.remove(p.id)
    ElMessage.success('已删除')
    if (drawerVisible.value && editDraft.id === p.id) drawerVisible.value = false
  } catch (e: any) {
    ElMessage.error(`删除失败：${e?.message || e}`)
  }
}

// ===== 创建 dialog（AI 生成 + 手动兜底）=====
const createDialogVisible = ref(false)
const createFormRef = ref<FormInstance | null>(null)
// 'ai' 默认；'manual' 兜底
const createMode = ref<'ai' | 'manual'>('ai')
// AI 子步骤：填想法 → 补全题 → 预览编辑
const aiStep = ref<'idea' | 'clarify' | 'review'>('idea')
const aiLoading = ref(false)
const ideaText = ref('')
const clarifyQuestions = ref<ClarifyQuestion[]>([])
// 单选答案：{ qid: optionId }；多选答案：{ qid: optionId[] }
const answersSingle = reactive<Record<string, string>>({})
const answersMulti = reactive<Record<string, string[]>>({})

// 复用 createForm 承载「手动表单」与「AI 草稿预览编辑」
const createForm = reactive<PersonaCreatePayload>({
  name: '',
  format_type: 'prompt_based',
  prompt_text: '',
  tags: [],
  source: 'manual',
  locale: 'zh-CN',
  profile: {},
  pressure: { ...DEFAULT_PRESSURE },
  avatar_key: null,
})
// 草稿里 PersonaCreatePayload 不含的地区字段，单独存，创建后补 update
const draftRegion = reactive<{
  country_code: string | null
  country_name: string | null
  currency: string | null
  market_domains: string[]
}>({ country_code: null, country_name: null, currency: null, market_domains: [] })

function resetCreateForm() {
  Object.assign(createForm, {
    name: '',
    format_type: 'prompt_based',
    prompt_text: '',
    tags: [],
    source: 'manual',
    locale: 'zh-CN',
    profile: {},
    pressure: { ...DEFAULT_PRESSURE },
    avatar_key: null,
  })
  Object.assign(draftRegion, {
    country_code: null,
    country_name: null,
    currency: null,
    market_domains: [],
  })
}

function openCreate() {
  resetCreateForm()
  createMode.value = 'ai'
  aiStep.value = 'idea'
  ideaText.value = ''
  clarifyQuestions.value = []
  Object.keys(answersSingle).forEach((k) => delete answersSingle[k])
  Object.keys(answersMulti).forEach((k) => delete answersMulti[k])
  createDialogVisible.value = true
}

const createTitle = computed(() => {
  if (createMode.value === 'manual') return '手动创建 Persona'
  if (aiStep.value === 'idea') return 'AI 生成人设 · 描述想法'
  if (aiStep.value === 'clarify') return 'AI 生成人设 · 补全关键信息'
  return 'AI 生成人设 · 预览并微调'
})

// 把已收集的答案整理成后端要的 [{question, answer}]
function collectAnswers() {
  const out: { question: string; answer: string | string[] }[] = []
  for (const q of clarifyQuestions.value) {
    if (q.type === 'single') {
      const optId = answersSingle[q.id]
      if (!optId) continue
      const label = q.options.find((o) => o.id === optId)?.label ?? optId
      out.push({ question: q.prompt, answer: label })
    } else {
      const ids = answersMulti[q.id] || []
      if (!ids.length) continue
      const labels = ids.map(
        (id) => q.options.find((o) => o.id === id)?.label ?? id,
      )
      out.push({ question: q.prompt, answer: labels })
    }
  }
  return out
}

function applyDraft(draft: PersonaDraft) {
  createForm.name = draft.name
  createForm.format_type = 'prompt_based'
  createForm.prompt_text = draft.prompt_text
  createForm.tags = [...(draft.tags || [])]
  createForm.profile = { ...(draft.profile || {}) }
  createForm.pressure = { ...DEFAULT_PRESSURE, ...(draft.pressure || {}) }
  createForm.avatar_key = draft.avatar_key ?? null
  draftRegion.country_code = draft.country_code
  draftRegion.country_name = draft.country_name
  draftRegion.currency = draft.currency
  draftRegion.market_domains = [...(draft.market_domains || [])]
}

// 第一步：根据想法 → 智能判断（够完整直接进预览；否则进补全题）
async function startGenerate() {
  if (!ideaText.value.trim()) {
    ElMessage.warning('先简单描述一下你想要的客户')
    return
  }
  aiLoading.value = true
  try {
    const res = await personasApi.generate({ idea: ideaText.value.trim() })
    if (res.status === 'need_clarification') {
      clarifyQuestions.value = res.questions
      // 多选题预置空数组，避免 v-model 报错
      for (const q of res.questions) {
        if (q.type === 'multi' && !answersMulti[q.id]) answersMulti[q.id] = []
      }
      aiStep.value = 'clarify'
    } else {
      applyDraft(res.draft)
      aiStep.value = 'review'
    }
  } catch (e: any) {
    ElMessage.error(`生成失败：${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    aiLoading.value = false
  }
}

// 第二步：带补全答案 → 生成草稿（也用于「跳过直接生成」）
async function generateWithAnswers(skipClarify = false) {
  aiLoading.value = true
  try {
    const res = await personasApi.generate({
      idea: ideaText.value.trim(),
      answers: skipClarify ? undefined : collectAnswers(),
      skip_clarify: true,
    })
    if (res.status === 'ok') {
      applyDraft(res.draft)
      aiStep.value = 'review'
    }
  } catch (e: any) {
    ElMessage.error(`生成失败：${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    aiLoading.value = false
  }
}

// 预览页「重新生成」：回到想法步骤
function regenerate() {
  aiStep.value = clarifyQuestions.value.length ? 'clarify' : 'idea'
}

// 最终落库：先 create，再补地区字段 update
async function submitCreate() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写 persona 名称')
    return
  }
  if (createForm.format_type === 'prompt_based' && !createForm.prompt_text?.trim()) {
    ElMessage.warning('Prompt-based 必须填写 prompt 文本')
    return
  }
  try {
    const created = await store.create(createForm)
    // AI 草稿带地区信息 → 补一次 update（create 接口不收地区字段）
    if (draftRegion.country_code) {
      try {
        await store.update(created.id, {
          country_code: draftRegion.country_code,
          country_name: draftRegion.country_name,
          currency: draftRegion.currency,
          market_domains: draftRegion.market_domains,
        })
      } catch {
        /* 地区补写失败不阻塞创建 */
      }
    }
    ElMessage.success('已创建')
    createDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(`创建失败：${e?.message || e}`)
  }
}

// ===== 文件上传 =====
const uploadRef = ref<UploadInstance | null>(null)

async function handleUpload(file: UploadRawFile): Promise<boolean> {
  try {
    const res = await store.upload(file as unknown as File)
    ElMessage.success(`已导入 ${res.imported} 个 persona`)
  } catch (e: any) {
    ElMessage.error(`上传失败：${e?.message || e}`)
  }
  return false // 阻止 element-plus 自带的 http
}
</script>

<template>
  <div class="persona-library">
    <DmPageHeader
      title="Persona 人设库"
      subtitle="双格式（Structured / Prompt-based）· 44 预填 · 支持上传与 LLM 抽参"
    >
      <template #actions>
        <ElButton type="primary" @click="openCreate">
          <ElIcon><Sparkles /></ElIcon>
          <span style="margin-left: 6px">AI 创建人设</span>
        </ElButton>

        <ElUpload
          ref="uploadRef"
          :show-file-list="false"
          accept=".json,.yaml,.yml,.md,.txt"
          :before-upload="handleUpload"
          style="display: inline-block; margin-left: 8px"
        >
          <ElButton>
            <ElIcon><UploadIcon /></ElIcon>
            <span style="margin-left: 6px">上传文件</span>
          </ElButton>
        </ElUpload>

        <ElTooltip content="LLM 生成功能预留，下一阶段开放">
          <ElButton disabled style="margin-left: 8px">
            <ElIcon><Sparkles /></ElIcon>
            <span style="margin-left: 6px">LLM 生成</span>
          </ElButton>
        </ElTooltip>
      </template>
    </DmPageHeader>

    <!-- 筛选条 -->
    <ElCard shadow="never" class="filter-bar">
      <div class="filter-row">
        <ElSelect
          v-model="filterFormat"
          placeholder="格式类型"
          clearable
          style="width: 160px"
        >
          <ElOption label="Prompt-based" value="prompt_based" />
          <ElOption label="Structured" value="structured" />
        </ElSelect>

        <ElSelect
          v-model="filterTag"
          placeholder="按标签筛选"
          clearable
          filterable
          style="width: 220px"
        >
          <ElOption
            v-for="t in store.allTags"
            :key="t"
            :label="t"
            :value="t"
          />
        </ElSelect>

        <ElInput
          v-model="searchKw"
          placeholder="搜索 name / source / prompt 关键字"
          clearable
          style="width: 320px"
        >
          <template #prefix>
            <ElIcon><Search /></ElIcon>
          </template>
        </ElInput>

        <ElButton text @click="resetFilters">
          <ElIcon><XIcon /></ElIcon>
          <span style="margin-left: 4px">重置</span>
        </ElButton>

        <div class="filter-stat">
          共 <strong>{{ store.list.length }}</strong> 条
        </div>
      </div>
    </ElCard>

    <!-- 卡片网格 -->
    <div v-if="store.loading" class="loading-hint">加载中...</div>
    <DmEmpty
      v-else-if="store.list.length === 0"
      title="暂无人设"
      description="点右上「AI 创建人设」或「上传文件」开始构建你的人设库"
    />

    <ElRow v-else :gutter="20" class="card-grid">
      <ElCol
        v-for="p in store.list"
        :key="p.id"
        :xs="24"
        :sm="12"
        :md="12"
        :lg="8"
        :xl="8"
      >
        <ElCard
          shadow="hover"
          class="persona-card"
          @click="openDetail(p)"
        >
          <div class="card-head">
            <PersonaAvatar
              :avatar-key="p.avatar_key"
              :name="p.name"
              :size="44"
            />
            <div class="card-head-text">
              <div class="card-name" :title="p.name">{{ p.name }}</div>
              <div class="card-head-tags">
                <ElTag size="small" :type="fmtType(p.format_type)" effect="plain">
                  {{ fmtLabel(p.format_type) }}
                </ElTag>
                <ElTag
                  v-if="p.country_code"
                  size="small"
                  type="info"
                  effect="plain"
                  class="country-badge"
                  :title="`市场：${p.country_name || p.country_code} · 货币 ${p.currency || '-'}`"
                >
                  📍 {{ p.country_code }}{{ p.currency ? ' · ' + p.currency : '' }}
                </ElTag>
              </div>
            </div>
          </div>

          <div class="card-source" v-if="p.source">{{ p.source }}</div>

          <div class="card-tags" v-if="p.tags?.length">
            <ElTag
              v-for="t in p.tags.slice(0, 4)"
              :key="t"
              size="small"
              effect="plain"
              type="info"
            >{{ t }}</ElTag>
            <span v-if="p.tags.length > 4" class="more-tags">
              +{{ p.tags.length - 4 }}
            </span>
          </div>

          <div class="card-prompt" v-if="p.prompt_text">
            {{ truncate(p.prompt_text, 90) }}
          </div>

          <div class="card-pressure">
            <div
              v-for="(it, i) in topPressure(p.pressure)"
              :key="i"
              class="pressure-pill"
              :title="`${it.label}: ${(it.val * 100).toFixed(0)}%`"
            >
              <span class="pill-dot" :style="{ background: pressureColor(it.val) }"></span>
              {{ it.label }} {{ (it.val * 100).toFixed(0) }}
            </div>
          </div>

          <div class="card-footer">
            <ElTag
              v-if="!p.pressure_extracted"
              size="small"
              type="warning"
              effect="plain"
            >未抽参</ElTag>
            <span class="spacer"></span>
            <ElButton
              link
              type="danger"
              size="small"
              @click.stop="handleDelete(p)"
            >
              <ElIcon><Trash2 /></ElIcon>
            </ElButton>
          </div>
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- 详情抽屉 -->
    <ElDrawer
      v-model="drawerVisible"
      size="50%"
      direction="rtl"
    >
      <template #header>
        <div class="drawer-head">
          <PersonaAvatar
            :avatar-key="editDraft.avatar_key"
            :name="editDraft.name"
            :size="48"
          />
          <div class="drawer-head-text">
            <div class="drawer-head-name">{{ editDraft.name || '人设详情' }}</div>
            <div class="drawer-head-sub dm-text-small dm-text-muted">
              {{ editDraft.source || '—' }}
            </div>
          </div>
        </div>
      </template>
      <template #default>
        <ElTabs v-model="editTab">
          <ElTabPane label="人设描述" name="desc">
            <ElForm label-position="top">
              <ElFormItem label="名称">
                <ElInput v-model="editDraft.name" />
              </ElFormItem>
              <ElFormItem label="头像（44 个预设可选）">
                <div class="avatar-picker">
                  <PersonaAvatar
                    v-for="i in 44"
                    :key="i"
                    :avatar-key="`p${String(i).padStart(2, '0')}`"
                    :name="editDraft.name"
                    :size="36"
                    :selected="editDraft.avatar_key === `p${String(i).padStart(2, '0')}`"
                    class="avatar-picker-item"
                    @click="editDraft.avatar_key = `p${String(i).padStart(2, '0')}`"
                  />
                </div>
              </ElFormItem>
              <ElFormItem label="来源 / Source">
                <ElInput v-model="editDraft.source" placeholder="例如：panel_import / manual" />
              </ElFormItem>
              <ElFormItem label="格式类型">
                <ElSelect v-model="editDraft.format_type" style="width: 200px">
                  <ElOption label="Prompt-based" value="prompt_based" />
                  <ElOption label="Structured" value="structured" />
                </ElSelect>
              </ElFormItem>
              <ElFormItem label="标签（回车添加）">
                <ElSelect
                  v-model="editDraft.tags"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入标签后回车"
                  style="width: 100%"
                />
              </ElFormItem>

              <div class="market-section">
                <div class="market-section-title">
                  📍 客户所在市场（v0.2.1 — 决定 web_search 信源 & 货币）
                </div>
                <ElFormItem label="国家 / 地区">
                  <ElSelect
                    :model-value="editDraft.country_code"
                    placeholder="选择国家（自动同步货币和默认域名）"
                    clearable
                    filterable
                    style="width: 320px"
                    @update:model-value="(v: string | null) => { editDraft.country_code = v; onCountryChange(v) }"
                  >
                    <ElOption
                      v-for="c in countryOptions"
                      :key="c.code"
                      :label="`${c.label} · ${c.currency} ${c.currency_symbol}`"
                      :value="c.code"
                    />
                  </ElSelect>
                </ElFormItem>
                <ElFormItem label="货币（ISO 4217，可手动覆盖）">
                  <ElInput
                    v-model="editDraft.currency"
                    placeholder="如 MYR / PHP / CNY"
                    style="width: 200px"
                  />
                </ElFormItem>
                <ElFormItem label="可信信源域名（web_search 工具被强制锁定到这些域名）">
                  <ElSelect
                    v-model="editDraft.market_domains"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入域名后回车，例如 consumer.huawei.com/my"
                    style="width: 100%"
                  />
                  <div class="dm-text-small dm-text-muted" style="margin-top: 4px">
                    建议：1 个华为官方该国分站 + 1-2 个该国主流电商。切换国家时会自动填充默认值。
                  </div>
                </ElFormItem>
              </div>

              <ElFormItem label="Prompt 文本（核心人设）">
                <ElInput
                  v-model="editDraft.prompt_text"
                  type="textarea"
                  :autosize="{ minRows: 10, maxRows: 24 }"
                  placeholder="Prompt-based 模式必填；structured 模式可留空"
                />
              </ElFormItem>
            </ElForm>
          </ElTabPane>

          <ElTabPane label="量化参数（9 维）" name="pressure">
            <div class="pressure-tab-head">
              <span class="pressure-extract-state">
                <ElTag
                  size="small"
                  :type="editDraft.id && store.current?.pressure_extracted ? 'success' : 'warning'"
                >
                  {{ store.current?.pressure_extracted ? '已抽取' : '未抽取（当前为默认 0.5）' }}
                </ElTag>
              </span>
              <ElButton
                size="small"
                :loading="extracting"
                @click="reExtractPressure"
                :disabled="editDraft.format_type !== 'prompt_based'"
              >
                <ElIcon><RefreshCcw /></ElIcon>
                <span style="margin-left: 4px">LLM 重新抽取</span>
              </ElButton>
            </div>

            <div class="pressure-grid">
              <div
                v-for="d in PRESSURE_DIMENSIONS"
                :key="d.key"
                class="pressure-row"
              >
                <div class="p-label">
                  {{ d.label }}
                  <ElTooltip :content="d.desc" placement="top">
                    <span class="p-hint">?</span>
                  </ElTooltip>
                </div>
                <div class="p-slider">
                  <ElSlider
                    v-model="editDraft.pressure[d.key]"
                    :min="0"
                    :max="1"
                    :step="0.05"
                    :format-tooltip="(v: number) => v.toFixed(2)"
                  />
                </div>
                <div class="p-value">
                  {{ (editDraft.pressure[d.key] ?? 0.5).toFixed(2) }}
                </div>
              </div>
            </div>
          </ElTabPane>

          <ElTabPane label="行为偏好" name="profile">
            <ElForm label-position="top">
              <ElFormItem label="年龄">
                <ElInputNumber
                  v-model="editDraft.profile.age"
                  :min="0"
                  :max="120"
                  style="width: 160px"
                />
              </ElFormItem>
              <ElFormItem label="职业">
                <ElInput v-model="editDraft.profile.occupation" />
              </ElFormItem>
              <ElFormItem label="预算">
                <ElInput v-model="editDraft.profile.budget" placeholder="如 RM2500-RM4000" />
              </ElFormItem>
              <ElFormItem label="性格">
                <ElInput
                  v-model="editDraft.profile.personality"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 5 }"
                />
              </ElFormItem>
              <ElFormItem label="异议风格">
                <ElInput
                  v-model="editDraft.profile.objection_style"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                />
              </ElFormItem>
              <ElFormItem label="购买目标">
                <ElInput
                  v-model="editDraft.profile.purchase_goal"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 4 }"
                />
              </ElFormItem>
            </ElForm>
          </ElTabPane>
        </ElTabs>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <ElButton @click="drawerVisible = false">取消</ElButton>
          <ElButton type="primary" @click="saveDraft">
            <ElIcon><Save /></ElIcon>
            <span style="margin-left: 6px">保存</span>
          </ElButton>
        </div>
      </template>
    </ElDrawer>

    <!-- 创建 dialog：AI 生成（默认）+ 手动兜底 -->
    <ElDialog
      v-model="createDialogVisible"
      :title="createTitle"
      width="680px"
    >
      <!-- ===== AI 模式 ===== -->
      <template v-if="createMode === 'ai'">
        <!-- 步骤 1：描述想法 -->
        <div v-if="aiStep === 'idea'" v-loading="aiLoading">
          <p class="ai-hint">
            用一句话或一段话描述你想要的客户，AI 会补全成像「阿明、法汉」那样的完整人设。
            信息够具体就直接生成；不够时会先问你几道小题。
          </p>
          <ElInput
            v-model="ideaText"
            type="textarea"
            :autosize="{ minRows: 5, maxRows: 12 }"
            placeholder="例如：马来西亚的大学生，预算紧，想买 iPad 上课记笔记，但一直在和安卓平板比价，怕买了不值"
          />
        </div>

        <!-- 步骤 2：补全题 -->
        <div v-else-if="aiStep === 'clarify'" v-loading="aiLoading">
          <p class="ai-hint">
            补充几个关键信息，AI 生成的人设会更贴合你的目标（也可直接跳过生成）。
          </p>
          <div
            v-for="q in clarifyQuestions"
            :key="q.id"
            class="clarify-q"
          >
            <div class="clarify-q-prompt">{{ q.prompt }}</div>
            <ElRadioGroup
              v-if="q.type === 'single'"
              v-model="answersSingle[q.id]"
            >
              <ElRadio
                v-for="o in q.options"
                :key="o.id"
                :value="o.id"
                border
                class="clarify-opt"
              >
                {{ o.label }}
              </ElRadio>
            </ElRadioGroup>
            <ElCheckboxGroup v-else v-model="answersMulti[q.id]">
              <ElCheckbox
                v-for="o in q.options"
                :key="o.id"
                :value="o.id"
                border
                class="clarify-opt"
              >
                {{ o.label }}
              </ElCheckbox>
            </ElCheckboxGroup>
          </div>
        </div>

        <!-- 步骤 3：预览并微调 -->
        <div v-else v-loading="aiLoading">
          <ElForm :model="createForm" label-position="top">
            <ElFormItem label="名称" required>
              <ElInput v-model="createForm.name" />
            </ElFormItem>
            <ElFormItem label="头像（留空按 id 自动分配）">
              <div class="avatar-picker">
                <PersonaAvatar
                  v-for="i in 44"
                  :key="i"
                  :avatar-key="`p${String(i).padStart(2, '0')}`"
                  :name="createForm.name || '?'"
                  :size="32"
                  :selected="createForm.avatar_key === `p${String(i).padStart(2, '0')}`"
                  class="avatar-picker-item"
                  @click="createForm.avatar_key = `p${String(i).padStart(2, '0')}`"
                />
              </div>
            </ElFormItem>
            <ElFormItem v-if="draftRegion.country_code" label="市场 / 货币 / 信源（AI 推断，可在创建后编辑）">
              <div class="region-chips">
                <ElTag size="small" type="success" effect="plain">
                  {{ draftRegion.country_name || draftRegion.country_code }}
                </ElTag>
                <ElTag v-if="draftRegion.currency" size="small" effect="plain">
                  {{ draftRegion.currency }}
                </ElTag>
                <ElTag
                  v-for="d in draftRegion.market_domains"
                  :key="d"
                  size="small"
                  type="info"
                  effect="plain"
                >
                  {{ d }}
                </ElTag>
              </div>
            </ElFormItem>
            <ElFormItem label="标签">
              <ElSelect
                v-model="createForm.tags"
                multiple
                filterable
                allow-create
                placeholder="输入回车添加"
                style="width: 100%"
              />
            </ElFormItem>
            <ElFormItem label="人设正文（Prompt 文本）">
              <ElInput
                v-model="createForm.prompt_text"
                type="textarea"
                :autosize="{ minRows: 8, maxRows: 18 }"
              />
            </ElFormItem>
            <ElFormItem label="9 维量化压力（AI 预估，创建后可在详情里微调）">
              <div class="pressure-preview">
                <div
                  v-for="dim in PRESSURE_DIMENSIONS"
                  :key="dim.key"
                  class="pressure-preview-row"
                >
                  <span class="pp-label">{{ dim.label }}</span>
                  <ElProgress
                    :percentage="Math.round((createForm.pressure?.[dim.key] ?? 0.5) * 100)"
                    :stroke-width="6"
                    :show-text="false"
                    style="flex: 1"
                  />
                  <span class="pp-val">{{ (createForm.pressure?.[dim.key] ?? 0.5).toFixed(2) }}</span>
                </div>
              </div>
            </ElFormItem>
          </ElForm>
        </div>
      </template>

      <!-- ===== 手动模式（兜底）===== -->
      <template v-else>
        <ElForm ref="createFormRef" :model="createForm" label-position="top">
          <ElFormItem label="名称" required>
            <ElInput v-model="createForm.name" placeholder="例如：精打细算的大学生" />
          </ElFormItem>
          <ElFormItem label="头像（44 个预设可选 · 留空则按 id 取模自动分配）">
            <div class="avatar-picker">
              <PersonaAvatar
                v-for="i in 44"
                :key="i"
                :avatar-key="`p${String(i).padStart(2, '0')}`"
                :name="createForm.name || '?'"
                :size="32"
                :selected="createForm.avatar_key === `p${String(i).padStart(2, '0')}`"
                class="avatar-picker-item"
                @click="createForm.avatar_key = `p${String(i).padStart(2, '0')}`"
              />
            </div>
            <div
              v-if="createForm.avatar_key"
              class="dm-text-small dm-text-muted"
              style="margin-top: 6px"
            >
              已选 {{ createForm.avatar_key }}
              <ElButton size="small" text @click="createForm.avatar_key = null">
                清除
              </ElButton>
            </div>
          </ElFormItem>
          <ElFormItem label="格式类型">
            <ElSelect v-model="createForm.format_type" style="width: 220px">
              <ElOption label="Prompt-based（推荐）" value="prompt_based" />
              <ElOption label="Structured（YAML 字段）" value="structured" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="标签">
            <ElSelect
              v-model="createForm.tags"
              multiple
              filterable
              allow-create
              placeholder="输入回车添加"
              style="width: 100%"
            />
          </ElFormItem>
          <ElFormItem v-if="createForm.format_type === 'prompt_based'" label="Prompt 文本">
            <ElInput
              v-model="createForm.prompt_text"
              type="textarea"
              :autosize="{ minRows: 8, maxRows: 16 }"
              placeholder="完整描述角色设定、心理特征、消费习惯、语言风格..."
            />
          </ElFormItem>
          <ElFormItem v-else label="结构化字段（最少填 personality 或 pain_points）">
            <ElInput
              v-model.lazy="createForm.profile!.personality"
              placeholder="性格描述"
              style="margin-bottom: 8px"
            />
            <ElInput
              v-model="createForm.profile!.purchase_goal"
              placeholder="购买目标"
              style="margin-bottom: 8px"
            />
            <ElInput
              v-model="createForm.profile!.objection_style"
              placeholder="异议风格"
            />
          </ElFormItem>
        </ElForm>
      </template>

      <!-- ===== 动态 footer ===== -->
      <template #footer>
        <div class="create-footer">
        <!-- AI · 想法步骤 -->
        <template v-if="createMode === 'ai' && aiStep === 'idea'">
          <ElButton text @click="createMode = 'manual'">切换到手动填写</ElButton>
          <span style="flex: 1" />
          <ElButton @click="createDialogVisible = false">取消</ElButton>
          <ElButton type="primary" :loading="aiLoading" @click="startGenerate">
            生成人设
          </ElButton>
        </template>
        <!-- AI · 补全步骤 -->
        <template v-else-if="createMode === 'ai' && aiStep === 'clarify'">
          <ElButton text @click="aiStep = 'idea'">上一步</ElButton>
          <span style="flex: 1" />
          <ElButton :disabled="aiLoading" @click="generateWithAnswers(true)">
            跳过直接生成
          </ElButton>
          <ElButton type="primary" :loading="aiLoading" @click="generateWithAnswers(false)">
            生成人设
          </ElButton>
        </template>
        <!-- AI · 预览步骤 -->
        <template v-else-if="createMode === 'ai' && aiStep === 'review'">
          <ElButton text :disabled="aiLoading" @click="regenerate">重新生成</ElButton>
          <span style="flex: 1" />
          <ElButton @click="createDialogVisible = false">取消</ElButton>
          <ElButton type="primary" @click="submitCreate">创建</ElButton>
        </template>
        <!-- 手动模式 -->
        <template v-else>
          <ElButton text @click="createMode = 'ai'">切换到 AI 生成</ElButton>
          <span style="flex: 1" />
          <ElButton @click="createDialogVisible = false">取消</ElButton>
          <ElButton type="primary" @click="submitCreate">创建</ElButton>
        </template>
        </div>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.persona-library {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar :deep(.el-card__body) {
  padding: 14px 18px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.filter-stat {
  margin-left: auto;
  color: var(--dm-text-tertiary, #94a3b8);
  font-size: 13px;
}
.filter-stat strong {
  color: var(--dm-text-primary, #1a202c);
  font-weight: 600;
}

.loading-hint {
  padding: 40px;
  color: var(--dm-text-tertiary, #94a3b8);
  text-align: center;
}

.card-grid {
  row-gap: 20px;
}

.persona-card {
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  height: 100%;
}
.persona-card:hover {
  transform: translateY(-2px);
}

.persona-card :deep(.el-card__body) {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 220px;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.card-head-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  flex: 1;
  min-width: 0;
}
.card-head-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.country-badge {
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

/* v0.2.1 市场设置 section */
.market-section {
  background: #f9fafb;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 22px;
}
.market-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--dm-text-primary, #1a202c);
  margin-bottom: 12px;
}
.market-section :deep(.el-form-item) {
  margin-bottom: 12px;
}
.market-section :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.card-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--dm-text-primary, #1a202c);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.card-source {
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.more-tags {
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
  align-self: center;
}
.card-prompt {
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}
.card-pressure {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pressure-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  font-size: 11.5px;
  color: #475569;
}
.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.spacer { flex: 1; }

.pressure-tab-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.pressure-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.pressure-row {
  display: grid;
  grid-template-columns: 160px 1fr 56px;
  align-items: center;
  gap: 12px;
}
.p-label {
  font-size: 13px;
  color: var(--dm-text-secondary, #475569);
  display: flex;
  align-items: center;
  gap: 6px;
}
.p-hint {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #64748b;
  font-size: 11px;
  cursor: help;
}
.p-value {
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--dm-text-primary, #1a202c);
  font-size: 13px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* ============ Drawer header with avatar ============ */
.drawer-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.drawer-head-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.drawer-head-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--dm-text-primary, #1a202c);
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  max-width: 320px;
}
.drawer-head-sub {
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
  max-width: 320px;
}

/* ============ Avatar picker grid ============ */
.avatar-picker {
  display: grid;
  grid-template-columns: repeat(11, 1fr);
  gap: 6px;
  max-height: 168px;
  overflow-y: auto;
  padding: 8px;
  background: #fafaf9;
  border: 1px solid #ebebea;
  border-radius: 8px;

  @media (max-width: 900px) {
    grid-template-columns: repeat(8, 1fr);
  }
}
.avatar-picker-item {
  cursor: pointer;
  transition: transform 0.12s ease;

  &:hover {
    transform: scale(1.08);
  }
}

/* ============ AI 生成弹窗 ============ */
.ai-hint {
  font-size: 13px;
  color: var(--dm-text-secondary, #475569);
  line-height: 1.6;
  margin: 0 0 12px;
}
.clarify-q {
  margin-bottom: 18px;
}
.clarify-q-prompt {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--dm-text-primary, #1a202c);
  margin-bottom: 8px;
}
.clarify-opt {
  margin: 0 8px 8px 0 !important;
}
.region-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pressure-preview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 18px;
  width: 100%;
}
.pressure-preview-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pp-label {
  font-size: 12px;
  color: var(--dm-text-secondary, #475569);
  width: 72px;
  flex-shrink: 0;
}
.pp-val {
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
  width: 32px;
  text-align: right;
  flex-shrink: 0;
}
.create-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
