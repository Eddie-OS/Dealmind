<script setup lang="ts">
/**
 * 分析报告（Handbook Analysis Report）· Sprint 2 完整版
 *
 * 业务流：
 *   1. 选源：单会话 或 批次（v-tabs）
 *   2. 启动分析（POST /api/analysis/jobs）
 *   3. 轮询任务进度，完成后显示 9 大板块报告
 *
 * 报告 9 板块：
 *   A. KPI 横条：覆盖率 / 总分类 / 弱项数 / 强项数 / outcome
 *   B. 6 维评分雷达
 *   C. Handbook 覆盖率热图（按 group 分块）
 *   D. 弱项 Top 5（含 LLM 汇总的常见 issues）
 *   E. 强项 Top 5
 *   F. 未覆盖条目列表
 *   G. Persona Insights 表
 *   H. Outcome 分布
 *   I. Handbook 优化建议（基于弱项 + 未覆盖）
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElIcon,
  ElLink,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElProgress,
  ElSelect,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
} from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  BookText,
  Download,
  Microscope,
  RefreshCcw,
  Trash2,
  XCircle,
} from '@lucide/vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  HANDBOOK_STATUS_LABEL,
  HANDBOOK_STATUS_TYPE,
  handbookApi,
  type Handbook,
} from '@/api/handbook'
import { sessionsApi, type SessionInfo } from '@/api/sessions'
import { batchApi, type BatchInfo } from '@/api/batch'
import { personasApi, type Persona } from '@/api/personas'
import {
  analysisApi,
  STATUS_LABEL,
  STATUS_TYPE,
  DIM_LABEL,
  GROUP_LABEL,
  categoryGroup,
  type AnalysisJobDetail,
  type CategoryCoverage,
  type PersonaInsight,
  type TurnHighlight,
  type ExcellentGroup,
  type ExcellentTurn,
  type HandbookRevision,
  type CustomerVoiceGroup,
  type KeyNumber,
  type CoverageGroupStat,
  type Methodology,
} from '@/api/analysis'

use([
  CanvasRenderer,
  BarChart,
  PieChart,
  GridComponent,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
])

// ============================================================
// 状态
// ============================================================

type SourceKind = 'session' | 'batch'
type ViewMode = 'pick' | 'report'

const sourceTab = ref<SourceKind>('session')
const viewMode = ref<ViewMode>('pick')
const loading = ref(false)

const handbooks = ref<Handbook[]>([])
const personas = ref<Persona[]>([])
const sessions = ref<SessionInfo[]>([])
const batches = ref<BatchInfo[]>([])

const selectedSession = ref<SessionInfo | null>(null)
const selectedBatch = ref<BatchInfo | null>(null)

// 当前查看 / 运行中的 job
const currentJob = ref<AnalysisJobDetail | null>(null)
const personaInsights = ref<PersonaInsight[]>([])
const reportLoading = ref(false)
let pollTimer: number | null = null

// 历史 jobs（用于直接打开旧报告）
const historyJobs = ref<AnalysisJobDetail['summary']['session_ids'] extends infer _ ? AnalysisJobDetail[] : never>(
  [] as unknown as AnalysisJobDetail[],
) as unknown as { value: AnalysisJobDetail[] }

// 手动补绑对话框（保留旧逻辑：当源无 handbook 时让用户挑一个一次性 handbook_id）
const bindOpen = ref(false)
const bindTarget = ref<
  | { kind: 'session'; row: SessionInfo }
  | { kind: 'batch'; row: BatchInfo }
  | null
>(null)
const bindChoice = ref<number | null>(null)

// ============================================================
// 加载基础数据
// ============================================================

async function loadAll() {
  loading.value = true
  try {
    const [hbR, persR, sessR, batchR, jobsR] = await Promise.allSettled([
      handbookApi.list(),
      personasApi.list({ limit: 500 }),
      sessionsApi.list({ size: 50, status: 'done' }),
      batchApi.list({ size: 50, status: 'completed' }),
      analysisApi.list({ limit: 20 }),
    ])
    if (hbR.status === 'fulfilled') handbooks.value = hbR.value.items
    if (persR.status === 'fulfilled') personas.value = persR.value.items
    if (sessR.status === 'fulfilled') sessions.value = sessR.value.items
    if (batchR.status === 'fulfilled') batches.value = batchR.value.items
    if (jobsR.status === 'fulfilled') {
      // 列表返回的字段不含 summary，但够列表展示；详情打开时再拉
      historyJobs.value = (jobsR.value.items as unknown) as AnalysisJobDetail[]
    }
  } finally {
    loading.value = false
  }
}

// ============================================================
// Query 自动定位：?session_id=xxx → 找已有 completed job，
// 没有就把该 session 列入选中状态、停在 pick 视图，让用户点 "开始分析"
// ============================================================

const route = useRoute()
const router = useRouter()

async function ensureSessionInList(sid: string): Promise<SessionInfo | null> {
  // 先在本地列表里找
  let s = sessions.value.find((x) => x.id === sid) || null
  if (s) return s
  // 不在的话直接打详情接口拉一份补到列表（最近 50 之外的老会话也支持）
  try {
    const info = await sessionsApi.detail(sid)
    if (info) {
      // 插入列表头部，便于用户后续在表里看到
      sessions.value = [info as any, ...sessions.value]
      s = info as any
    }
  } catch (e: any) {
    console.warn('[analysis] sessionsApi.detail failed:', e)
  }
  return s
}

async function applyRouteQuery() {
  const sid = (route.query.session_id as string | undefined) || ''
  if (!sid) return
  // 1) 先看是否已经有 completed job → 直接打开报告
  try {
    const existing = await analysisApi.findBySession(sid)
    if (existing) {
      await openHistoryJob(existing.id)
      return
    }
  } catch (e: any) {
    console.warn('[analysis] findBySession failed:', e)
  }
  // 2) 没有报告 → 把这个 session 设为选中，留在 pick 视图
  sourceTab.value = 'session'
  const s = await ensureSessionInList(sid)
  if (s) {
    selectedSession.value = s
    ElMessage.info(
      `已定位会话 ${sid.slice(-12)}，点右上角"开始分析"立即生成报告`,
    )
  } else {
    ElMessage.warning(`未找到会话 ${sid}`)
  }
}

onMounted(async () => {
  await loadAll()
  await applyRouteQuery()
})

// 路由变化（同页跳转）也响应
watch(
  () => route.query.session_id,
  async (n, o) => {
    if (n && n !== o && viewMode.value === 'pick') {
      await applyRouteQuery()
    }
  },
)

onBeforeUnmount(() => stopPolling())

async function refresh() {
  await loadAll()
}

// ============================================================
// 选源 + 绑定提示
// ============================================================

const readyHandbooks = computed(() =>
  handbooks.value.filter((h) => h.status === 'ready'),
)
const defaultHandbook = computed(() =>
  readyHandbooks.value.length === 1 ? readyHandbooks.value[0] : null,
)

function handbookOf(id: number | null | undefined): Handbook | null {
  if (id == null) return null
  return handbooks.value.find((h) => h.id === id) || null
}

function personaName(id: number | null | undefined): string {
  if (id == null) return '—'
  return personas.value.find((p) => p.id === id)?.name || `#${id}`
}

function bindingLabel(boundId: number | null | undefined) {
  if (boundId != null) {
    const h = handbookOf(boundId)
    return {
      text: h ? `已绑：${h.name}` : `已绑 #${boundId}（已删除）`,
      type: h ? 'success' : 'danger',
      tip: h
        ? `本场启动时显式绑定 v${h.version_no}`
        : '绑定的 Handbook 已被删除，需手动补绑',
    } as const
  }
  if (defaultHandbook.value) {
    return {
      text: `自动套用：${defaultHandbook.value.name}`,
      type: 'info',
      tip: '本场未显式绑定，库里仅一份 ready Handbook，分析时将自动套用',
    } as const
  }
  return {
    text: '未绑定（需手动选）',
    type: 'warning',
    tip: '本场未绑定，且库里 Handbook 数 ≠ 1，请手动指定后再分析',
  } as const
}

function canAnalyze(boundId: number | null | undefined): boolean {
  if (boundId != null) return handbookOf(boundId) != null
  return !!defaultHandbook.value
}

const selectedSessionHandbook = computed(() => {
  const s = selectedSession.value
  if (!s) return null
  return handbookOf(s.handbook_id) || defaultHandbook.value
})
const selectedBatchHandbook = computed(() => {
  const b = selectedBatch.value
  if (!b) return null
  return handbookOf(b.handbook_id) || defaultHandbook.value
})
const canRunSession = computed(
  () => !!selectedSession.value && canAnalyze(selectedSession.value.handbook_id),
)
const canRunBatch = computed(
  () => !!selectedBatch.value && canAnalyze(selectedBatch.value.handbook_id),
)

function pickSession(row: SessionInfo) {
  selectedSession.value = row
}
function pickBatch(row: BatchInfo) {
  selectedBatch.value = row
}

// ============================================================
// 启动 / 轮询 / 取消
// ============================================================

async function startAnalyze() {
  let payload: { session_id?: string; batch_id?: number; handbook_id?: number | null } = {}
  if (sourceTab.value === 'session' && selectedSession.value) {
    payload.session_id = selectedSession.value.id
    payload.handbook_id =
      selectedSession.value.handbook_id ?? defaultHandbook.value?.id ?? null
  } else if (sourceTab.value === 'batch' && selectedBatch.value) {
    payload.batch_id = selectedBatch.value.id
    payload.handbook_id =
      selectedBatch.value.handbook_id ?? defaultHandbook.value?.id ?? null
  } else {
    return
  }
  try {
    const res = await analysisApi.create(payload)
    currentJob.value = res.job as AnalysisJobDetail
    viewMode.value = 'report'
    ElMessage.success(`分析任务 #${res.job_id} 已启动`)
    startPolling(res.job_id)
  } catch (e: any) {
    ElMessage.error(
      `启动失败：${e?.response?.data?.detail || e?.message || e}`,
    )
  }
}

function stopPolling() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling(jobId: number) {
  stopPolling()
  pollTimer = window.setInterval(() => pullJob(jobId), 1500)
  pullJob(jobId)
}

async function pullJob(jobId: number) {
  try {
    const j = await analysisApi.detail(jobId)
    currentJob.value = j
    if (
      j.status === 'completed' ||
      j.status === 'failed' ||
      j.status === 'cancelled'
    ) {
      stopPolling()
      if (j.status === 'completed') {
        await loadPersonaInsights(jobId)
      }
    }
  } catch (e: any) {
    console.warn('pullJob failed', e)
  }
}

async function loadPersonaInsights(jobId: number) {
  try {
    const r = await analysisApi.personaInsights(jobId)
    personaInsights.value = r.items
  } catch (e: any) {
    personaInsights.value = []
  }
}

async function openHistoryJob(jobId: number) {
  reportLoading.value = true
  viewMode.value = 'report'
  try {
    currentJob.value = await analysisApi.detail(jobId)
    if (currentJob.value.status === 'completed') {
      await loadPersonaInsights(jobId)
    }
    if (currentJob.value.status === 'running' || currentJob.value.status === 'pending') {
      startPolling(jobId)
    }
  } finally {
    reportLoading.value = false
  }
}

async function cancelJob() {
  if (!currentJob.value) return
  try {
    await analysisApi.cancel(currentJob.value.id)
    ElMessage.success('已发送取消请求')
  } catch (e: any) {
    ElMessage.error(`取消失败：${e?.message || e}`)
  }
}

async function deleteJob(jobId: number) {
  try {
    await ElMessageBox.confirm(
      `确认删除分析任务 #${jobId}（关联的分类/评分也会一并清空）？`,
      '删除分析任务',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await analysisApi.remove(jobId)
    ElMessage.success('已删除')
    if (currentJob.value?.id === jobId) {
      backToPick()
    }
    await loadAll()
  } catch (e: any) {
    ElMessage.error(`删除失败：${e?.message || e}`)
  }
}

function backToPick() {
  stopPolling()
  viewMode.value = 'pick'
  currentJob.value = null
  personaInsights.value = []
}

// ============================================================
// 报告渲染：图表 option
// ============================================================

const summary = computed(() => currentJob.value?.summary || null)

/** playbook_v1（按人设 + 4 章流程）报告 —— 文案据此区分旧 1/3/3/5/9/10 */
const isPlaybook = computed(() => (summary.value as any)?.doc_type === 'playbook_v1')
const handbookStructLabel = computed(() =>
  isPlaybook.value ? '开场/卖点/竞品/FAQ' : '1/3/3/5/9/10',
)

const outcomeOption = computed(() => {
  const outc = (summary.value as any)?.outcome_join as Record<string, number> | undefined
  if (!outc || Object.keys(outc).length === 0) return null
  const data = Object.entries(outc).map(([k, v]) => ({ name: k, value: v }))
  return {
    // Notion 风：降饱和中性 + 克制语义点缀
    color: ['#37352f', '#8a8a86', '#c2c1bc', '#2d7a3e', '#9a6c1a', '#9b2c2c'],
    tooltip: { trigger: 'item' },
    legend: { orient: 'horizontal', bottom: 0, textStyle: { color: '#525252' } },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        data,
      },
    ],
  }
})

interface HeatCell {
  category_id: string
  label: string
  hits: number
  avg_quality: number
  covered: boolean
}

interface HeatGroup {
  group_key: string
  group_label: string
  cells: HeatCell[]
}

const heatGroups = computed<HeatGroup[]>(() => {
  if (!summary.value) return []
  const cov = (summary.value as any).category_coverage as Record<string, CategoryCoverage>
  const uncov = ((summary.value as any).uncovered_categories || []) as string[]
  const all: HeatCell[] = []
  // covered
  Object.entries(cov || {}).forEach(([cid, v]) => {
    all.push({
      category_id: cid,
      label: v.label,
      hits: v.hits,
      avg_quality: v.avg_quality,
      covered: true,
    })
  })
  uncov.forEach((cid) => {
    all.push({
      category_id: cid,
      label: cid,
      hits: 0,
      avg_quality: 0,
      covered: false,
    })
  })
  // group by prefix
  const groups: Record<string, HeatGroup> = {}
  const order = ['intro', 'sell', 'comp', 'param', 'faq', 'demo']
  order.forEach((g) => {
    groups[g] = { group_key: g, group_label: GROUP_LABEL[g] || g, cells: [] }
  })
  all.forEach((c) => {
    const g = categoryGroup(c.category_id)
    if (!groups[g]) groups[g] = { group_key: g, group_label: g, cells: [] }
    groups[g].cells.push(c)
  })
  // 排序：按 id 后缀
  Object.values(groups).forEach((g) =>
    g.cells.sort((a, b) =>
      a.category_id.localeCompare(b.category_id, undefined, { numeric: true }),
    ),
  )
  return order.map((k) => groups[k]).filter((g) => g.cells.length > 0)
})

function cellColor(c: HeatCell): string {
  if (!c.covered) return 'var(--dm-bg-muted)'
  // avg_quality 0-10 → 低饱和绿单色梯度（浅灰绿 → 墨绿），克制不刺眼
  const q = Math.max(0, Math.min(10, c.avg_quality))
  const l = 90 - 48 * (q / 10) // 90% → 42%
  return `hsl(140, 24%, ${l.toFixed(0)}%)`
}

function cellTextColor(c: HeatCell): string {
  return c.covered && c.avg_quality >= 7 ? '#fff' : 'var(--dm-text)'
}

// 优化建议聚合：弱项 + 未覆盖 → 一段提纲（V1 兼容，长报告新版用 revisionProposals）
const handbookSuggestions = computed<string[]>(() => {
  if (!summary.value) return []
  const out: string[] = []
  const weaks = ((summary.value as any).weak_categories || []) as Array<{
    category_id: string
    label: string
    avg_quality: number
    hits: number
    reason: string
  }>
  weaks.forEach((w) => {
    out.push(
      `【弱项】「${w.label}」均分 ${w.avg_quality.toFixed(1)} / 10 · 命中 ${w.hits} 次 — ${w.reason}`,
    )
  })
  const uncov = ((summary.value as any).uncovered_categories || []) as string[]
  if (uncov.length > 0) {
    out.push(
      `【未覆盖】共 ${uncov.length} 项 Handbook 条目本批从未被销冠引用：${uncov.slice(0, 6).join(', ')}${uncov.length > 6 ? ' ...' : ''}`,
    )
  }
  return out
})

// ============================================================
// V2 长报告板块数据
// ============================================================

// 改动⑥：按 135910 + 手册外分组的优秀话术（解耦手册一致性 + 行为信号/LLM）
const excellentGroups = computed<ExcellentGroup[]>(
  () => (summary.value as any)?.excellent_by_group?.groups || [],
)
const excellentTotal = computed<number>(
  () => (summary.value as any)?.excellent_by_group?.total || 0,
)
const EXCELLENT_FOLD = 3
const expandedExcellentGroups = ref<Set<string>>(new Set())
function toggleExcellentGroup(key: string) {
  const s = new Set(expandedExcellentGroups.value)
  if (s.has(key)) s.delete(key)
  else s.add(key)
  expandedExcellentGroups.value = s
}
function visibleExcellentItems(g: ExcellentGroup): ExcellentTurn[] {
  return expandedExcellentGroups.value.has(g.key) ? g.items : g.items.slice(0, EXCELLENT_FOLD)
}
const problematicTurns = computed<TurnHighlight[]>(
  () => (summary.value as any)?.problematic_turns || [],
)
// 改动⑤：按 31 条逐条的手册迭代建议（每条含 TOP3 原声）
const handbookRevisions = computed<HandbookRevision[]>(
  () => (summary.value as any)?.handbook_revisions || [],
)
// V2-①：分析方法说明（固定但完全透明）—— 弹窗与导出 HTML 同源
const methodology = computed<Methodology | null>(
  () => (summary.value as any)?.methodology || null,
)
const methodologyVisible = ref(false)
const REVISION_GROUP_LABEL: Record<string, string> = {
  intro: '① 一句话定位',
  sell: '③ 核心卖点',
  comp: '③ 竞品对比',
  param: '⑤ 核心参数',
  faq: '⑨ FAQ',
  demo: '⑩ 现场演示',
  open: '① 开场破冰',
  say: '② 核心卖点（按人设）',
  compete: '③ 竞品应对',
  respond: '④ 常见问答',
}
const REVISION_STATUS_TYPE: Record<string, string> = {
  保持: 'success', 强化: 'primary', 修正: 'danger',
}
function qualityFlagMeta(flag?: string): { type: string; label: string } | null {
  const map: Record<string, { type: string; label: string }> = {
    ok: { type: 'success', label: '可直接采纳' },
    review: { type: 'warning', label: '需人工确认' },
    minor: { type: 'warning', label: '微调·未实质重写' },
    kept_original: { type: 'info', label: '仅保留原文' },
  }
  return (flag && map[flag]) || null
}
const revisionsByGroup = computed(() => {
  const order = [
    'intro', 'sell', 'comp', 'param', 'faq', 'demo',
    'open', 'say', 'compete', 'respond',
  ]
  const map: Record<string, HandbookRevision[]> = {}
  for (const it of handbookRevisions.value) {
    ;(map[it.group] || (map[it.group] = [])).push(it)
  }
  // 已知顺序优先，未知 group 追加在后，避免新结构条目漏渲染
  const keys = [
    ...order.filter((k) => (map[k] || []).length > 0),
    ...Object.keys(map).filter((k) => !order.includes(k)),
  ]
  return keys.map((k) => ({ key: k, label: REVISION_GROUP_LABEL[k] || k, items: map[k] }))
})
const customerVoiceGroups = computed<CustomerVoiceGroup[]>(
  () => (summary.value as any)?.customer_voice || [],
)
const keyNumbers = computed<KeyNumber[]>(
  () => (summary.value as any)?.key_numbers || [],
)
const coverageByGroup = computed<Record<string, CoverageGroupStat>>(
  () => (summary.value as any)?.coverage_by_group || {},
)
// §1 覆盖小计的分组键：playbook 用 4 章流程键，否则旧 6 模块键
const coverageGroupKeys = computed<string[]>(() =>
  isPlaybook.value
    ? ['open', 'say', 'compete', 'respond']
    : ['intro', 'sell', 'comp', 'param', 'faq', 'demo'],
)
function groupStatLabel(key: string): string {
  return REVISION_GROUP_LABEL[key] || GROUP_LABEL[key] || key
}
// 缺口②：运行时对话客户类型分布（仅 playbook）
const conversationPersona = computed(
  () => (summary.value as any)?.conversation_persona_breakdown || null,
)
// 报告生成时间
const reportGeneratedAt = computed(() => {
  const ts = (summary.value as any)?.generated_at as string | undefined
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString('zh-CN')
  } catch {
    return ts
  }
})

// 切换"看全部 / 只看 Top 5"
const showAllProblematic = ref(false)
const expandedTurnKey = ref<string | null>(null)
// 历史任务列表是否完全展开（默认收起只显 5 条）
const historyExpanded = ref(false)
const HISTORY_DEFAULT_LIMIT = 5
const visibleHistoryJobs = computed(() =>
  historyExpanded.value
    ? historyJobs.value
    : historyJobs.value.slice(0, HISTORY_DEFAULT_LIMIT),
)

// 顶部「开始分析」按钮：根据当前 tab + 已选项决定是否可点
const canStartFromHeader = computed(() => {
  if (viewMode.value !== 'pick') return false
  if (sourceTab.value === 'session') return canRunSession.value
  return canRunBatch.value
})

// 下载当前报告
function downloadCurrentReport(format: 'md' | 'json') {
  if (!currentJob.value) return
  const url = analysisApi.exportUrl(currentJob.value.id, format)
  const a = document.createElement('a')
  a.href = url
  a.download = `analysis-${currentJob.value.id}.${format}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// HTML 精排报告：新标签预览（页内 Ctrl+P 即可「打印 / 另存为 PDF」）
function previewHtmlReport() {
  if (!currentJob.value) return
  const url = analysisApi.exportUrl(currentJob.value.id, 'html')
  window.open(url, '_blank')
}

function turnKey(t: TurnHighlight): string {
  return `${t.session_id}#${t.turn_idx}`
}
function toggleTurn(t: TurnHighlight) {
  const k = turnKey(t)
  expandedTurnKey.value = expandedTurnKey.value === k ? null : k
}

// 6 维分小条颜色（Notion 风：降饱和语义色）
function dimBarColor(score: number): string {
  if (score >= 8) return '#2d7a3e' // 墨绿
  if (score >= 6) return '#9a6c1a' // 暗琥珀
  if (score >= 4) return '#b5701f' // 暗橙
  return '#9b2c2c' // 暗红
}

// 把分类 id 映射 group label
function groupOfCategory(cid: string): string {
  return GROUP_LABEL[categoryGroup(cid)] || cid
}

// 截断长文（用于标题预览）
function trimText(t: string, n = 80): string {
  if (!t) return ''
  return t.length > n ? t.slice(0, n) + '…' : t
}

function gotoSession(sid: string) {
  window.open(`/simulation/detail/${sid}`, '_blank', 'noopener')
}

// 已绑定 Handbook 信息（顶部展示）
const reportHandbook = computed(() => {
  const id = currentJob.value?.handbook_id
  return handbookOf(id ?? null)
})

// ============================================================
// 历史 jobs 描述
// ============================================================

function jobScope(j: AnalysisJobDetail): string {
  if (j.session_id) return `会话 ${j.session_id.slice(-20)}`
  if (j.batch_id) return `批次 #${j.batch_id}`
  return '—'
}

// ============================================================
// 手动补绑（保留 UI；本期改为"分析时按指定 Handbook 跑一次"语义）
// ============================================================

function openBindSession(row: SessionInfo) {
  bindTarget.value = { kind: 'session', row }
  bindChoice.value = row.handbook_id ?? defaultHandbook.value?.id ?? null
  bindOpen.value = true
}

function openBindBatch(row: BatchInfo) {
  bindTarget.value = { kind: 'batch', row }
  bindChoice.value = row.handbook_id ?? defaultHandbook.value?.id ?? null
  bindOpen.value = true
}

async function submitBindAndAnalyze() {
  if (!bindTarget.value || bindChoice.value == null) {
    ElMessage.warning('请选择一份 Handbook')
    return
  }
  const tgt = bindTarget.value
  bindOpen.value = false
  try {
    const payload =
      tgt.kind === 'session'
        ? { session_id: tgt.row.id, handbook_id: bindChoice.value }
        : { batch_id: tgt.row.id, handbook_id: bindChoice.value }
    const res = await analysisApi.create(payload)
    currentJob.value = res.job as AnalysisJobDetail
    viewMode.value = 'report'
    ElMessage.success(`分析任务 #${res.job_id} 已用指定 Handbook 启动`)
    startPolling(res.job_id)
  } catch (e: any) {
    ElMessage.error(`启动失败：${e?.response?.data?.detail || e?.message || e}`)
  }
}
</script>

<template>
  <div class="analysis-report">
    <DmPageHeader
      title="分析报告"
      description="选历史会话或批量测试，按其绑定的产品手册结构做归因分析"
    >
      <template #icon>
        <Microscope :size="22" />
      </template>
      <template #actions>
        <!-- pick 视图：永久置顶的"开始分析"按钮，避免下滑找按钮 -->
        <template v-if="viewMode === 'pick'">
          <ElButton
            type="primary"
            :disabled="!canStartFromHeader"
            @click="startAnalyze"
          >
            <Microscope :size="14" />
            <span style="margin-left: 4px">开始分析</span>
          </ElButton>
        </template>
        <!-- report 视图：下载 + 返回 -->
        <template v-else>
          <ElDropdown
            v-if="currentJob?.status === 'completed'"
            trigger="click"
          >
            <ElButton type="primary" plain>
              <Download :size="14" />
              <span style="margin-left: 4px">下载报告</span>
            </ElButton>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem @click="previewHtmlReport">
                  HTML (.html)
                </ElDropdownItem>
                <ElDropdownItem divided @click="downloadCurrentReport('md')">
                  Markdown (.md)
                </ElDropdownItem>
                <ElDropdownItem @click="downloadCurrentReport('json')">
                  JSON (.json)
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
          <ElButton @click="backToPick">
            <ArrowLeft :size="14" />
            <span style="margin-left: 4px">返回选源</span>
          </ElButton>
        </template>
        <ElButton @click="refresh" :loading="loading">
          <RefreshCcw :size="14" />
          <span style="margin-left: 4px">刷新</span>
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- ============================== 选源视图 ============================== -->
    <template v-if="viewMode === 'pick'">
      <!-- 已选源粘性栏：随时可见的"开始分析"快捷栏 -->
      <div
        v-if="selectedSession || selectedBatch"
        class="picked-bar"
      >
        <div class="picked-info">
          <ElTag size="small" type="primary" effect="dark">已选</ElTag>
          <template v-if="sourceTab === 'session' && selectedSession">
            <span class="picked-text">
              会话
              <span class="mono">…{{ selectedSession.id.slice(-15) }}</span>
              · {{ personaName(selectedSession.persona_id) }}
            </span>
            <ElTag
              v-if="selectedSessionHandbook"
              size="small"
              type="success"
            >
              {{ selectedSessionHandbook.name }} v{{ selectedSessionHandbook.version_no }}
            </ElTag>
            <ElTag v-else size="small" type="warning">未绑 Handbook</ElTag>
          </template>
          <template v-else-if="sourceTab === 'batch' && selectedBatch">
            <span class="picked-text">
              批次 #{{ selectedBatch.id }} · {{ selectedBatch.name }}
            </span>
            <ElTag
              v-if="selectedBatchHandbook"
              size="small"
              type="success"
            >
              {{ selectedBatchHandbook.name }} v{{ selectedBatchHandbook.version_no }}
            </ElTag>
            <ElTag v-else size="small" type="warning">未绑 Handbook</ElTag>
          </template>
        </div>
        <ElButton
          type="primary"
          :disabled="!canStartFromHeader"
          @click="startAnalyze"
        >
          <Microscope :size="14" />
          <span style="margin-left: 4px">开始分析</span>
        </ElButton>
      </div>

      <!-- Handbook 库状态（紧凑一行） -->
      <div class="hb-banner compact">
        <span class="hb-banner-icon"><BookText :size="14" /></span>
        <span class="hb-banner-text">
          Handbook：<strong>{{ readyHandbooks.length }}</strong> 份 ready
          <template v-if="defaultHandbook">
            · 默认 <strong>{{ defaultHandbook.name }}</strong>
          </template>
          <template v-else-if="readyHandbooks.length === 0">
            · <span class="hb-warning">无 ready Handbook</span>
          </template>
        </span>
        <router-link to="/kb/handbooks" class="hb-banner-link">
          管理 <ArrowRight :size="12" />
        </router-link>
      </div>

      <!-- 历史分析任务（默认折叠到 5 条） -->
      <ElCard
        v-if="historyJobs.length > 0"
        shadow="never"
        class="history-card"
      >
        <template #header>
          <div class="card-header-row">
            <span class="dm-text-h3">最近的分析任务</span>
            <div class="card-header-right">
              <span class="dm-text-small dm-text-muted">
                共 {{ historyJobs.length }} 条
              </span>
              <ElLink
                v-if="historyJobs.length > HISTORY_DEFAULT_LIMIT"
                type="primary"
                :underline="false"
                @click="historyExpanded = !historyExpanded"
              >
                {{ historyExpanded ? '收起' : `展开全部 (${historyJobs.length})` }}
              </ElLink>
            </div>
          </div>
        </template>
        <ElTable :data="visibleHistoryJobs" size="default" style="width: 100%">
          <ElTableColumn label="ID" prop="id" width="64" align="center" />
          <ElTableColumn label="数据源" min-width="240">
            <template #default="{ row }">
              {{ jobScope(row) }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="Handbook" width="160">
            <template #default="{ row }">
              <span v-if="handbookOf(row.handbook_id)">
                {{ handbookOf(row.handbook_id)!.name }}
              </span>
              <span v-else class="dm-text-muted">—</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="120">
            <template #default="{ row }">
              <ElTag size="small" :type="STATUS_TYPE[row.status as keyof typeof STATUS_TYPE]">
                {{ STATUS_LABEL[row.status as keyof typeof STATUS_LABEL] || row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="进度" width="180">
            <template #default="{ row }">
              <ElProgress
                :percentage="Math.round((row.progress || 0) * 100)"
                :stroke-width="6"
                :show-text="true"
              />
              <div class="dm-text-caption dm-text-muted">
                {{ row.classified_turns }}/{{ row.total_turns }} turn
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="创建" prop="created_at" width="160" />
          <ElTableColumn label="操作" width="160">
            <template #default="{ row }">
              <ElLink type="primary" :underline="false" @click="openHistoryJob(row.id)">
                查看报告
              </ElLink>
              <ElLink
                type="danger"
                :underline="false"
                style="margin-left: 12px"
                @click="deleteJob(row.id)"
              >
                删除
              </ElLink>
            </template>
          </ElTableColumn>
        </ElTable>
      </ElCard>

      <ElTabs v-model="sourceTab" class="source-tabs">
        <!-- 单会话 -->
        <ElTabPane label="按单会话分析" name="session">
          <ElCard shadow="never" class="source-card">
            <template #header>
              <div class="card-header-row">
                <span class="dm-text-h3">选一场已完成的会话</span>
                <span class="dm-text-small dm-text-muted">
                  共 {{ sessions.length }} 场（最近 50）
                </span>
              </div>
            </template>

            <ElEmpty
              v-if="!loading && sessions.length === 0"
              description="还没有已完成的会话"
            />
            <ElTable
              v-else
              :data="sessions"
              highlight-current-row
              @current-change="(row: SessionInfo) => row && pickSession(row)"
              v-loading="loading"
              style="width: 100%"
              size="default"
            >
              <ElTableColumn label="Persona" min-width="120">
                <template #default="{ row }">{{ personaName(row.persona_id) }}</template>
              </ElTableColumn>
              <ElTableColumn label="话题" prop="topic" min-width="180" show-overflow-tooltip />
              <ElTableColumn label="轮数" width="80" align="center">
                <template #default="{ row }">
                  {{ row.summary?.total_rounds ?? row.max_rounds }}
                </template>
              </ElTableColumn>
              <ElTableColumn label="结果" width="100" align="center">
                <template #default="{ row }">
                  <ElTag size="small" effect="plain">
                    {{ row.summary?.outcome || '—' }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="Handbook 绑定" min-width="220">
                <template #default="{ row }">
                  <ElTooltip :content="bindingLabel(row.handbook_id).tip" placement="top">
                    <ElTag size="small" :type="bindingLabel(row.handbook_id).type">
                      {{ bindingLabel(row.handbook_id).text }}
                    </ElTag>
                  </ElTooltip>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="120">
                <template #default="{ row }">
                  <ElLink
                    type="primary"
                    :underline="false"
                    @click.stop="openBindSession(row)"
                  >
                    指定 Handbook
                  </ElLink>
                </template>
              </ElTableColumn>
              <ElTableColumn label="创建时间" prop="created_at" width="160" />
            </ElTable>
          </ElCard>

        </ElTabPane>

        <!-- 按批次 -->
        <ElTabPane label="按批次分析" name="batch">
          <ElCard shadow="never" class="source-card">
            <template #header>
              <div class="card-header-row">
                <span class="dm-text-h3">选一个已完成的批量测试</span>
                <span class="dm-text-small dm-text-muted">
                  共 {{ batches.length }} 个（最近 50）
                </span>
              </div>
            </template>

            <ElEmpty v-if="!loading && batches.length === 0" description="还没有已完成的批次" />
            <ElTable
              v-else
              :data="batches"
              highlight-current-row
              @current-change="(row: BatchInfo) => row && pickBatch(row)"
              v-loading="loading"
              style="width: 100%"
              size="default"
            >
              <ElTableColumn label="ID" prop="id" width="70" align="center" />
              <ElTableColumn label="名称" prop="name" min-width="180" show-overflow-tooltip />
              <ElTableColumn label="完成 / 总" width="100" align="center">
                <template #default="{ row }">
                  {{ row.completed_count }} / {{ row.total_count }}
                </template>
              </ElTableColumn>
              <ElTableColumn label="Handbook 绑定" min-width="220">
                <template #default="{ row }">
                  <ElTooltip :content="bindingLabel(row.handbook_id).tip" placement="top">
                    <ElTag size="small" :type="bindingLabel(row.handbook_id).type">
                      {{ bindingLabel(row.handbook_id).text }}
                    </ElTag>
                  </ElTooltip>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="120">
                <template #default="{ row }">
                  <ElLink type="primary" :underline="false" @click.stop="openBindBatch(row)">
                    指定 Handbook
                  </ElLink>
                </template>
              </ElTableColumn>
              <ElTableColumn label="创建时间" prop="created_at" width="160" />
            </ElTable>
          </ElCard>

        </ElTabPane>
      </ElTabs>

      <!-- 手动指定 Handbook -->
      <ElDialog
        v-model="bindOpen"
        title="为本次分析指定产品手册"
        width="480px"
      >
        <p class="dm-text-body" style="margin-bottom: 12px">
          直接以指定 Handbook 启动一次分析任务（不会回写源会话/批次的绑定）。
        </p>
        <ElSelect v-model="bindChoice" placeholder="选择一份 ready Handbook" style="width: 100%">
          <ElOption
            v-for="hb in handbooks"
            :key="hb.id"
            :value="hb.id"
            :label="`${hb.name}（v${hb.version_no}）`"
            :disabled="hb.status !== 'ready'"
          >
            <span>{{ hb.name }}</span>
            <ElTag
              size="small"
              :type="HANDBOOK_STATUS_TYPE[hb.status]"
              style="margin-left: 8px"
            >
              {{ HANDBOOK_STATUS_LABEL[hb.status] }}
            </ElTag>
          </ElOption>
        </ElSelect>
        <template #footer>
          <ElButton @click="bindOpen = false">取消</ElButton>
          <ElButton type="primary" @click="submitBindAndAnalyze">用该 Handbook 启动分析</ElButton>
        </template>
      </ElDialog>
    </template>

    <!-- ============================== 报告视图 ============================== -->
    <template v-else>
      <ElCard shadow="never" class="report-header-card">
        <div class="report-header">
          <div class="report-header-main">
            <div class="dm-text-h2">分析任务 #{{ currentJob?.id }}</div>
            <div class="dm-text-small dm-text-muted">
              <span v-if="currentJob?.session_id">
                数据源：会话 <span class="mono">{{ currentJob.session_id }}</span>
              </span>
              <span v-else-if="currentJob?.batch_id">
                数据源：批次 #{{ currentJob.batch_id }}
              </span>
              <template v-if="reportHandbook">
                · Handbook：{{ reportHandbook.name }}（v{{ reportHandbook.version_no }}）
              </template>
            </div>
          </div>
          <div class="report-header-actions">
            <ElTag
              :type="STATUS_TYPE[(currentJob?.status as keyof typeof STATUS_TYPE) || 'pending']"
              effect="dark"
            >
              {{ STATUS_LABEL[(currentJob?.status as keyof typeof STATUS_LABEL) || 'pending'] }}
            </ElTag>
            <ElButton
              v-if="currentJob && (currentJob.status === 'pending' || currentJob.status === 'running')"
              type="warning"
              plain
              @click="cancelJob"
            >
              <XCircle :size="14" />
              <span style="margin-left: 4px">取消</span>
            </ElButton>
            <ElButton v-if="currentJob" type="danger" plain @click="deleteJob(currentJob.id)">
              <Trash2 :size="14" />
              <span style="margin-left: 4px">删除</span>
            </ElButton>
          </div>
        </div>

        <div v-if="currentJob" class="progress-block">
          <ElProgress
            :percentage="Math.round(((currentJob.progress as number) || 0) * 100)"
            :stroke-width="10"
            :status="
              currentJob.status === 'completed'
                ? 'success'
                : currentJob.status === 'failed'
                ? 'exception'
                : undefined
            "
          />
          <div class="dm-text-caption dm-text-muted">
            {{ currentJob.classified_turns }}/{{ currentJob.total_turns }} 销冠 turn 已处理
          </div>
        </div>
        <ElAlert
          v-if="currentJob?.status === 'failed'"
          type="error"
          show-icon
          :closable="false"
          :title="`任务失败：${currentJob.error_msg || '未知错误'}`"
          style="margin-top: 8px"
        />
      </ElCard>

      <!-- 完成时才显示报告板块 -->
      <template v-if="currentJob?.status === 'completed' && summary">
        <!-- 0. 摘要封面 -->
        <ElCard shadow="never" class="cover-card">
          <div class="cover-grid">
            <div class="cover-main">
              <div class="cover-label">销冠话术 · 实战分析报告</div>
              <div class="cover-title">
                {{ reportHandbook?.name || 'Handbook' }}
                <span v-if="reportHandbook" class="cover-ver">v{{ reportHandbook.version_no }}</span>
              </div>
              <div class="cover-desc">
                {{ (summary as any).session_count }} 场会话 ·
                {{ (summary as any).total_classifications }} 条销冠分类 ·
                覆盖 {{ (summary as any).coverage_pct }}% Handbook 条目
                <template v-if="reportGeneratedAt"> · 生成于 {{ reportGeneratedAt }}</template>
              </div>
            </div>
            <div class="cover-actions">
              <ElButton
                v-if="methodology"
                plain
                :icon="Microscope"
                @click="methodologyVisible = true"
              >
                分析方法说明
              </ElButton>
            </div>
          </div>
        </ElCard>

        <!-- V2-①：分析方法说明弹窗（固定但完全透明；导出 HTML 同源） -->
        <ElDialog
          v-model="methodologyVisible"
          title="分析方法说明 · 报告可解释性"
          width="760px"
          top="6vh"
          class="methodology-dialog"
        >
          <div v-if="methodology" class="mth-body">
            <p class="mth-intro">{{ methodology.intro }}</p>
            <div
              v-for="sec in methodology.sections"
              :key="sec.key"
              class="mth-section"
            >
              <div class="mth-sec-title">{{ sec.title }}</div>
              <div class="mth-sec-desc">{{ sec.desc }}</div>
              <ul v-if="sec.items.length" class="mth-items">
                <li v-for="(it, i) in sec.items" :key="i">
                  <span class="mth-item-name">{{ it.name }}</span>
                  <span class="mth-item-desc">{{ it.desc }}</span>
                </li>
              </ul>
            </div>
            <div class="mth-foot">方法说明版本 {{ methodology.version }} · 当前为固定透明版，后续将支持维度自定义</div>
          </div>
        </ElDialog>

        <!-- A. KPI 横条（保留，扩展为 6 项） -->
        <div class="kpi-row">
          <div class="kpi">
            <div class="kpi-label">覆盖率</div>
            <div class="kpi-value">{{ (summary as any).coverage_pct }}%</div>
            <div class="kpi-sub">
              {{ (summary as any).categories_covered }} / {{ (summary as any).categories_total }} 项
            </div>
          </div>
          <div class="kpi">
            <div class="kpi-label">分类标签</div>
            <div class="kpi-value">{{ (summary as any).total_classifications }}</div>
            <div class="kpi-sub">销冠话累计命中</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">高分 turn</div>
            <div class="kpi-value">{{ excellentTotal }}</div>
            <div class="kpi-sub">可沉淀为黄金范本</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">问题 turn</div>
            <div class="kpi-value">{{ problematicTurns.length }}</div>
            <div class="kpi-sub">需立即改进</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">短板项</div>
            <div class="kpi-value">{{ ((summary as any).weak_categories || []).length }}</div>
            <div class="kpi-sub">Handbook 弱条目</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">修订建议</div>
            <div class="kpi-value">{{ handbookRevisions.length }}</div>
            <div class="kpi-sub">本批输出</div>
          </div>
        </div>

        <!-- §1. 执行摘要：outcome + 6 大 group 覆盖 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 1</div>
            <div>
              <div class="section-title">执行摘要 · 销冠整体表现</div>
              <div class="section-sub">Outcome 分布 · 6 大模块覆盖小计</div>
            </div>
          </div>
          <ElCard shadow="never" class="chart-card">
            <template #header>
              <span class="dm-text-h3">成交结果分布</span>
            </template>
            <VChart
              v-if="outcomeOption"
              :option="outcomeOption"
              style="height: 280px"
              autoresize
            />
            <ElEmpty v-else description="无 outcome 数据" />
          </ElCard>

          <ElCard
            v-if="Object.keys(coverageByGroup).length > 0"
            shadow="never"
            style="margin-top: 12px"
          >
            <template #header>
              <div class="card-header-row">
                <span class="dm-text-h3">{{ isPlaybook ? 'Handbook 4 大板块覆盖小计' : 'Handbook 6 大模块覆盖小计' }}</span>
                <span class="dm-text-small dm-text-muted">
                  按 {{ handbookStructLabel }} 结构拆分查看
                </span>
              </div>
            </template>
            <div class="group-stat-row">
              <div
                v-for="key in coverageGroupKeys"
                :key="key"
                class="group-stat-cell"
              >
                <div class="group-stat-title">{{ groupStatLabel(key) }}</div>
                <template v-if="coverageByGroup[key]">
                  <div class="group-stat-cov">
                    <strong>{{ coverageByGroup[key].covered }}</strong>
                    <span class="group-stat-sep">/</span>
                    <span>{{ coverageByGroup[key].total }}</span>
                    <span class="group-stat-pct">
                      {{ coverageByGroup[key].coverage_pct }}%
                    </span>
                  </div>
                  <div class="group-stat-q">
                    引用 {{ coverageByGroup[key].hits }} 次 · 加权均分
                    <strong>{{ coverageByGroup[key].weighted_avg_quality.toFixed(1) }}</strong>
                  </div>
                </template>
                <template v-else>
                  <div class="group-stat-empty">—</div>
                </template>
              </div>
            </div>
          </ElCard>

          <!-- 对话客户类型分布（运行时 LLM 判定，仅 playbook） -->
          <ElCard
            v-if="isPlaybook && conversationPersona && conversationPersona.distribution?.length"
            class="dm-card group-stat-card"
            shadow="never"
            style="margin-top: 16px"
          >
            <template #header>
              <div class="card-header-row">
                <span class="dm-text-h3">对话客户类型分布 · 运行时判定</span>
                <span class="dm-text-small dm-text-muted">
                  共 {{ conversationPersona.session_total }} 场 · 已判定
                  {{ conversationPersona.classified }} 场
                </span>
              </div>
            </template>
            <div class="group-stat-row">
              <div
                v-for="r in conversationPersona.distribution"
                :key="r.persona"
                class="group-stat-cell"
              >
                <div class="group-stat-title">
                  {{ r.persona === '?' ? '未判定' : `${r.persona} · ${r.persona_label}` }}
                </div>
                <div class="group-stat-cov">
                  <strong>{{ r.sessions }}</strong>
                  <span class="group-stat-pct">场对话</span>
                </div>
                <div v-if="r.persona !== '?'" class="group-stat-q">
                  本类专属话术 {{ r.own_cats_covered }} / {{ r.own_cats_total }}
                  （{{ r.own_coverage_pct }}%）
                </div>
                <div class="group-stat-q">
                  结局：{{ Object.entries(r.outcomes || {}).map(([k, v]) => `${k} ${v}`).join('、') || '—' }}
                </div>
              </div>
            </div>
          </ElCard>
        </div>

        <!-- §2. 优秀话术原声（按 1/3/3/5/9/10 + 手册外分组） -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 2</div>
            <div>
              <div class="section-title">优秀话术原声 · 按手册结构归类</div>
              <div class="section-sub">
                共 {{ excellentTotal }} 条 · 优秀 = 行为信号（客户购买信号↑/态度转正）⊕ LLM 优秀度，
                <strong>不以"是否照搬手册"评判</strong>；含「手册外精彩话术」可直接喂迭代建议
              </div>
            </div>
          </div>

          <ElEmpty
            v-if="excellentGroups.length === 0"
            description="本批暂无可沉淀的优秀话术原声"
          />
          <template v-else>
            <div
              v-for="g in excellentGroups"
              :key="g.key"
              class="exc-group"
            >
              <div class="exc-group-head">
                <span
                  class="exc-group-badge"
                  :class="g.key === 'off_handbook' ? 'exc-badge-off' : 'exc-badge-hb'"
                >
                  {{ g.label }}
                </span>
                <span class="exc-group-count">{{ g.count }} 条</span>
                <span v-if="g.key === 'off_handbook'" class="exc-group-hint">
                  手册没提到但很有效 → 建议补进 Handbook
                </span>
              </div>

              <div
                v-for="(t, i) in visibleExcellentItems(g)"
                :key="t.session_id + '_' + t.turn_idx"
                class="exc-card"
              >
                <div class="exc-card-top">
                  <ElTag size="small" type="success" effect="dark">
                    {{ t.excellence_score.toFixed(1) }} / 10
                  </ElTag>
                  <span class="exc-signal">
                    购买信号 {{ t.purchase_signal_before.toFixed(1) }}
                    <span class="exc-arrow">→</span>
                    <strong :class="t.purchase_signal_after >= t.purchase_signal_before ? 'exc-up' : 'exc-down'">
                      {{ t.purchase_signal_after.toFixed(1) }}
                    </strong>
                  </span>
                  <ElTag v-if="t.attitude_after" size="small" effect="plain" type="info">
                    客户转「{{ t.attitude_after }}」
                  </ElTag>
                  <ElTag v-if="t.handbook_label" size="small" effect="plain">
                    {{ t.handbook_label }}
                  </ElTag>
                  <span class="exc-where" @click="gotoSession(t.session_id)">
                    {{ t.persona_name }} · 会话 {{ t.session_id.slice(-10) }} #{{ t.turn_idx }}
                  </span>
                </div>
                <div v-if="t.customer_question" class="exc-cust">
                  <span class="exc-cust-label">客户</span>{{ trimText(t.customer_question, 90) }}
                </div>
                <div class="exc-sales">{{ t.sales_content }}</div>
                <ul v-if="(t.why_good || []).length" class="exc-why">
                  <li v-for="(r, ri) in t.why_good" :key="ri">{{ r }}</li>
                </ul>
              </div>

              <div v-if="g.items.length > EXCELLENT_FOLD" class="turn-toggle">
                <ElLink
                  type="primary"
                  :underline="false"
                  @click="toggleExcellentGroup(g.key)"
                >
                  {{ expandedExcellentGroups.has(g.key)
                    ? '收起'
                    : `展开本组全部 ${g.items.length} 条` }}
                </ElLink>
              </div>
            </div>
          </template>
        </div>

        <!-- §3. 销冠话术 · 失误 & 应改成什么 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 3</div>
            <div>
              <div class="section-title">销冠话术 · 失误诊断与应改方向</div>
              <div class="section-sub">
                按 6 维平均分倒序的 Top 低分销冠话，附「为什么差 + 应改成什么」
              </div>
            </div>
          </div>

          <ElEmpty
            v-if="problematicTurns.length === 0"
            description="本批暂无明显问题销冠话（< 6.0）"
          />
          <template v-else>
            <div
              v-for="(t, i) in (showAllProblematic ? problematicTurns : problematicTurns.slice(0, 5))"
              :key="turnKey(t)"
              class="turn-card turn-card-bad"
            >
              <div class="turn-card-head" @click="toggleTurn(t)">
                <div class="turn-card-rank turn-card-rank-bad">#{{ i + 1 }}</div>
                <div class="turn-card-meta">
                  <div class="turn-card-title">
                    <ElTag size="small" type="danger">
                      {{ t.avg_quality.toFixed(1) }} / 10
                    </ElTag>
                    <ElTag v-if="t.primary_label" size="small" effect="plain">
                      {{ t.primary_label.label }}
                    </ElTag>
                    <ElTag size="small" effect="plain" type="info">
                      {{ t.persona_name }}
                      <template v-if="t.persona_cluster"> · {{ t.persona_cluster }}</template>
                    </ElTag>
                    <span class="turn-card-where" @click.stop="gotoSession(t.session_id)">
                      会话 {{ t.session_id.slice(-12) }} · #{{ t.turn_idx }}
                    </span>
                  </div>
                  <div class="turn-card-utter">
                    {{ trimText(t.sales_content, 160) }}
                  </div>
                </div>
                <ElIcon class="turn-card-chev">
                  <ArrowRight
                    :size="16"
                    :style="{
                      transform: expandedTurnKey === turnKey(t) ? 'rotate(90deg)' : 'rotate(0deg)',
                      transition: 'transform .15s ease',
                    }"
                  />
                </ElIcon>
              </div>

              <div v-if="expandedTurnKey === turnKey(t)" class="turn-card-body">
                <div v-if="t.customer_question" class="turn-quote turn-quote-customer">
                  <div class="turn-quote-label">客户问</div>
                  <div class="turn-quote-text">{{ t.customer_question }}</div>
                </div>
                <div class="turn-quote turn-quote-sales">
                  <div class="turn-quote-label">销冠答（完整）</div>
                  <div class="turn-quote-text">{{ t.sales_content }}</div>
                </div>

                <div class="turn-scores">
                  <div
                    v-for="(score, dim) in t.scores"
                    :key="dim"
                    class="turn-score-cell"
                  >
                    <div class="turn-score-label">{{ DIM_LABEL[dim] || dim }}</div>
                    <div class="turn-score-bar">
                      <div
                        class="turn-score-fill"
                        :style="{ width: (score * 10) + '%', background: dimBarColor(score) }"
                      />
                    </div>
                    <div class="turn-score-num" :style="{ color: dimBarColor(score) }">
                      {{ score.toFixed(1) }}
                    </div>
                  </div>
                </div>

                <div class="turn-section">
                  <div class="turn-section-title">为什么差</div>
                  <ul class="turn-list turn-list-bad">
                    <li v-for="(r, ri) in (t.why_bad || [])" :key="ri">{{ r }}</li>
                    <li v-if="(t.why_bad || []).length === 0" class="dm-text-muted">
                      （得分偏低但模型未抓到明显 issue，建议人工抽检）
                    </li>
                  </ul>
                </div>

                <div v-if="t.suggestion" class="turn-section">
                  <div class="turn-section-title">应改成什么（LLM 建议）</div>
                  <div class="turn-fix">{{ t.suggestion }}</div>
                </div>

                <div v-if="t.reference_text" class="turn-section">
                  <div class="turn-section-title">Handbook 标准答（应靠拢）</div>
                  <div class="turn-ref-text">「{{ t.reference_text }}」</div>
                </div>
              </div>
            </div>

            <div v-if="problematicTurns.length > 5" class="turn-toggle">
              <ElLink
                type="primary"
                :underline="false"
                @click="showAllProblematic = !showAllProblematic"
              >
                {{ showAllProblematic ? '收起' : `展开全部 ${problematicTurns.length} 条` }}
              </ElLink>
            </div>
          </template>
        </div>

        <!-- §4. Handbook 覆盖热图 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 4</div>
            <div>
              <div class="section-title">Handbook 覆盖热图</div>
              <div class="section-sub">
                颜色：浅黄 → 浓绿（均分越高色越深）；灰色 = 本批次未引用 = 死条目
              </div>
            </div>
          </div>

          <ElCard shadow="never">
            <div class="heat-wrapper">
              <div v-for="g in heatGroups" :key="g.group_key" class="heat-group">
                <div class="heat-group-title">{{ g.group_label }}</div>
                <div class="heat-cells">
                  <ElTooltip
                    v-for="c in g.cells"
                    :key="c.category_id"
                    placement="top"
                    :content="
                      c.covered
                        ? `${c.label} · 命中 ${c.hits} 次 · 均分 ${c.avg_quality.toFixed(1)}`
                        : `${c.label} · 本批次未被销冠引用`
                    "
                  >
                    <div
                      class="heat-cell"
                      :style="{ background: cellColor(c), color: cellTextColor(c) }"
                    >
                      <div class="heat-cell-id">{{ c.category_id }}</div>
                      <div class="heat-cell-q">
                        {{ c.covered ? c.avg_quality.toFixed(1) : '—' }}
                      </div>
                    </div>
                  </ElTooltip>
                </div>
              </div>
            </div>
          </ElCard>
        </div>

        <!-- §5. 短板诊断 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 5</div>
            <div>
              <div class="section-title">Handbook 条目 · 短板诊断</div>
              <div class="section-sub">
                命中 ≥ 2 次但 6 维均分偏低，常见问题已自动归类
              </div>
            </div>
          </div>

          <ElEmpty
            v-if="((summary as any).weak_categories || []).length === 0"
            description="无明显短板"
          />
          <div
            v-for="w in ((summary as any).weak_categories || [])"
            :key="w.category_id"
            class="weak-card"
          >
            <div class="weak-card-head">
              <div class="weak-card-title">
                <ElTag :type="w.avg_quality < 5 ? 'danger' : 'warning'" effect="plain">
                  {{ w.avg_quality.toFixed(1) }} / 10
                </ElTag>
                <strong>{{ w.label }}</strong>
                <span class="dm-text-caption dm-text-muted mono">{{ w.category_id }}</span>
                <span class="dm-text-caption dm-text-muted">命中 {{ w.hits }} 次</span>
              </div>
            </div>
            <div class="weak-card-body">
              <div v-if="w.issue_top && w.issue_top.length > 0">
                <div class="weak-section-title">高频问题</div>
                <ul class="weak-issues">
                  <li v-for="(iss, ii) in w.issue_top" :key="ii">
                    {{ iss.text }}
                    <ElTag size="small" effect="plain" type="warning" style="margin-left: 6px">
                      ×{{ iss.count }}
                    </ElTag>
                  </li>
                </ul>
              </div>
              <div v-if="w.suggestion_samples && w.suggestion_samples.length > 0">
                <div class="weak-section-title">LLM 修改建议样本</div>
                <ul class="weak-issues">
                  <li v-for="(sug, si) in w.suggestion_samples" :key="si">{{ sug }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <!-- §6. 强项亮点（Handbook 条目级） -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 6</div>
            <div>
              <div class="section-title">Handbook 条目 · 强项亮点</div>
              <div class="section-sub">销冠多次复述官方口径，可沉淀为标准模板</div>
            </div>
          </div>
          <ElCard shadow="never">
            <ElEmpty
              v-if="((summary as any).strong_categories || []).length === 0"
              description="样本不足"
            />
            <ElTable v-else :data="(summary as any).strong_categories" size="default">
              <ElTableColumn label="Handbook 项" min-width="240">
                <template #default="{ row }">
                  <strong>{{ row.label }}</strong>
                  <div class="dm-text-caption dm-text-muted mono">{{ row.category_id }}</div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="均分" width="120" align="center">
                <template #default="{ row }">
                  <ElTag type="success" effect="plain">{{ row.avg_quality.toFixed(1) }} / 10</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="命中" width="100" align="center" prop="hits" />
              <ElTableColumn label="亮点说明">
                <template #default="{ row }">
                  <span class="dm-text-small">{{ row.highlight_reason || '—' }}</span>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </div>

        <!-- §7. Persona 分群 · 销冠表现 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 7</div>
            <div>
              <div class="section-title">按 Persona 分群 · 销冠表现</div>
              <div class="section-sub">
                销冠均质量 · 成交率 · 该群客户最关心的 Handbook 条目
              </div>
            </div>
          </div>
          <ElCard shadow="never">
            <ElEmpty v-if="personaInsights.length === 0" description="尚无 Persona 洞察" />
            <ElTable v-else :data="personaInsights" size="default">
              <ElTableColumn label="Persona" min-width="180">
                <template #default="{ row }">
                  {{ personaName(row.persona_id) }}
                  <ElTag v-if="row.persona_cluster" size="small" effect="plain" style="margin-left: 6px">
                    {{ row.persona_cluster }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="销冠均质量" width="120" align="center">
                <template #default="{ row }">
                  <span v-if="row.avg_quality != null">{{ row.avg_quality.toFixed(2) }}</span>
                  <span v-else class="dm-text-muted">—</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="成交率" width="100" align="center">
                <template #default="{ row }">
                  <span v-if="row.deal_rate != null">
                    {{ (row.deal_rate * 100).toFixed(0) }}%
                  </span>
                  <span v-else class="dm-text-muted">—</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="客户最关心的 Top Handbook 项">
                <template #default="{ row }">
                  <ElTag
                    v-for="c in (row.top_concerns || [])"
                    :key="c.category_id"
                    size="small"
                    effect="plain"
                    style="margin: 2px 4px 2px 0"
                  >
                    {{ c.label }} ×{{ c.count }}
                  </ElTag>
                </template>
              </ElTableColumn>
            </ElTable>
          </ElCard>
        </div>

        <!-- §8. 客户原声调研 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 8</div>
            <div>
              <div class="section-title">客户原声调研 · 按 Persona 聚类</div>
              <div class="section-sub">
                各类型客户最有信息量的真实提问，可直接用于下版 Handbook 场景演绎
              </div>
            </div>
          </div>

          <ElEmpty v-if="customerVoiceGroups.length === 0" description="无可用客户原话" />
          <div v-else class="voice-grid">
            <ElCard
              v-for="g in customerVoiceGroups"
              :key="g.persona_id ?? 'na'"
              shadow="never"
              class="voice-card"
            >
              <template #header>
                <div class="voice-card-head">
                  <strong>{{ g.persona_name }}</strong>
                  <ElTag size="small" effect="plain" style="margin-left: 8px">
                    {{ g.persona_cluster }}
                  </ElTag>
                  <span class="dm-text-caption dm-text-muted" style="margin-left: auto">
                    {{ g.sample_count }} 条样本
                  </span>
                </div>
              </template>
              <ul class="voice-list">
                <li v-for="(s, i) in g.samples" :key="i" class="voice-item">
                  <span class="voice-quote">「{{ s.content }}」</span>
                  <span
                    class="voice-where"
                    @click="gotoSession(s.session_id)"
                  >
                    {{ s.session_id.slice(-10) }} · #{{ s.turn_idx }}
                  </span>
                </li>
              </ul>
            </ElCard>
          </div>
        </div>

        <!-- §9. Handbook 迭代建议 · 按 1/3/3/5/9/10 逐条（改动⑤） -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 9</div>
            <div>
              <div class="section-title">Handbook 迭代建议 · 逐条（31 条）</div>
              <div class="section-sub">
                按手册结构对全部 31 个条目逐条给建议——<strong>即使表现好也给增强点</strong>，
                每条附 TOP3 命中原声
              </div>
            </div>
          </div>

          <ElEmpty v-if="handbookRevisions.length === 0" description="无迭代建议" />
          <div v-for="grp in revisionsByGroup" :key="grp.key" class="rev-group">
            <div class="rev-group-title">{{ grp.label }}</div>
            <div
              v-for="it in grp.items"
              :key="it.category_id"
              class="rev-card"
              :class="it.coverage.covered ? 'rev-card-medium' : 'rev-card-high'"
            >
              <div class="rev-card-head">
                <ElTag size="small" :type="REVISION_STATUS_TYPE[it.status] || 'info'" effect="dark">
                  {{ it.status }}
                </ElTag>
                <span class="rev-card-title">
                  {{ it.label }}
                  <span class="dm-text-caption dm-text-muted mono">({{ it.category_id }})</span>
                </span>
                <ElTag
                  v-if="qualityFlagMeta(it.quality_flag)"
                  size="small"
                  effect="light"
                  :type="qualityFlagMeta(it.quality_flag)!.type"
                >
                  {{ qualityFlagMeta(it.quality_flag)!.label }}
                </ElTag>
                <span class="rev-cov" :class="it.coverage.covered ? '' : 'rev-cov-dead'">
                  <template v-if="it.coverage.covered">
                    命中 {{ it.coverage.hits }} 次 · {{ it.coverage.sessions }} 场 ·
                    均分 {{ it.coverage.avg_quality.toFixed(1) }}
                  </template>
                  <template v-else>本批 0 次引用（死条目）</template>
                </span>
              </div>
              <div class="rev-card-body">
                <div v-if="it.handbook_text" class="rev-row">
                  <div class="rev-row-label">原文</div>
                  <div class="rev-row-text">{{ it.handbook_text }}</div>
                </div>
                <div v-if="it.assessment" class="rev-row">
                  <div class="rev-row-label">评估</div>
                  <div class="rev-row-text">{{ it.assessment }}</div>
                </div>
                <div class="rev-row">
                  <div class="rev-row-label rev-row-label-strong">建议</div>
                  <div class="rev-row-text rev-row-suggestion">{{ it.suggestion }}</div>
                </div>
                <div v-if="it.revised_text" class="rev-row">
                  <div class="rev-row-label rev-row-label-strong">修改后</div>
                  <div class="rev-row-text rev-row-suggestion">{{ it.revised_text }}</div>
                </div>
                <div v-if="it.fact_warnings && it.fact_warnings.length" class="rev-row">
                  <div class="rev-row-label rev-row-label-warn">⚠ 事实核查</div>
                  <div class="rev-row-text rev-row-warn">
                    {{ it.fact_warnings.join('；') }}（手册外信息，请人工确认后再决定是否采纳）
                  </div>
                </div>
                <div v-if="it.top_quotes.length" class="rev-row">
                  <div class="rev-row-label">TOP3 命中原声</div>
                  <div class="rev-row-text">
                    <div
                      v-for="(q, qi) in it.top_quotes"
                      :key="qi"
                      class="rev-quote"
                    >
                      <div class="rev-quote-meta">
                        <span v-if="q.score != null" class="rev-quote-score">{{ q.score.toFixed(1) }}</span>
                        <span class="rev-quote-by">{{ q.persona_name }}</span>
                      </div>
                      <div v-if="q.customer_question" class="rev-quote-line">
                        <b>客户原文</b>{{ trimText(q.customer_question, 120) }}
                      </div>
                      <div class="rev-quote-line">
                        <b>销售原文</b>{{ trimText(q.content, 120) }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- §10. 关键数字便签 -->
        <div class="section">
          <div class="section-head">
            <div class="section-num">§ 10</div>
            <div>
              <div class="section-title">关键数字便签（销冠应随时背得出）</div>
              <div class="section-sub">从 Handbook 核心参数 / 卖点 / FAQ 中抽出的可量化数字</div>
            </div>
          </div>

          <ElEmpty v-if="keyNumbers.length === 0" description="未抽到数字 token" />
          <div v-else class="kn-grid">
            <div v-for="(n, i) in keyNumbers" :key="i" class="kn-cell">
              <div class="kn-value">{{ n.value }}</div>
              <div class="kn-ctx">{{ n.context }}</div>
              <div class="kn-src" :title="n.source_text">
                <ElTag size="small" effect="plain">{{ n.source_group }}</ElTag>
                <span class="kn-src-text">{{ trimText(n.source_text, 48) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 报告底部 · 旧版简易建议保留作快速摘要 -->
        <ElCard shadow="never" class="footer-card">
          <template #header>
            <span class="dm-text-h3">报告摘要（快速摘抄）</span>
          </template>
          <ul class="suggestion-list">
            <li v-for="(s, i) in handbookSuggestions" :key="i">{{ s }}</li>
            <li v-if="handbookSuggestions.length === 0" class="dm-text-muted">
              本次分析未发现明显问题，建议增加样本数或更换更具挑战的 persona 再跑一遍。
            </li>
          </ul>
        </ElCard>
      </template>

      <ElCard
        v-else-if="currentJob && currentJob.status !== 'completed'"
        shadow="never"
      >
        <div class="dm-text-body dm-text-muted" style="text-align: center; padding: 60px 0">
          <template v-if="currentJob.status === 'pending' || currentJob.status === 'running'">
            分析进行中，请稍候…当前 {{ currentJob.classified_turns }} / {{ currentJob.total_turns }} turn
          </template>
          <template v-else>
            任务 {{ STATUS_LABEL[currentJob.status as keyof typeof STATUS_LABEL] }}，无可显示的报告
          </template>
        </div>
      </ElCard>
    </template>
  </div>
</template>

<style scoped>
.analysis-report {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.mono { font-family: var(--dm-font-mono, ui-monospace, SFMono-Regular, monospace); }

.hb-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--dm-bg-soft);
  border: 1px solid var(--dm-border);
}
.hb-banner.compact {
  padding: 8px 12px;
  font-size: 12px;
}
.hb-banner.compact .hb-banner-icon {
  width: 22px;
  height: 22px;
}
.hb-banner-icon {
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  background: var(--dm-bg);
  border: 1px solid var(--dm-border);
  border-radius: 6px;
}
.hb-banner-text { flex: 1; }
.hb-warning { color: var(--dm-color-warning, #d97706); }
.hb-banner-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--dm-color-primary);
  text-decoration: none;
  font-weight: 500;
}

/* 已选源粘性栏 — 顶部置顶，永远可见，"开始分析"近在咫尺 */
.picked-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border-strong);
  box-shadow: var(--dm-shadow-xs);
}
.picked-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.picked-text { font-size: 14px; }
.picked-text .mono {
  font-family: var(--dm-font-mono);
}

.card-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.source-tabs { background: transparent; }
.source-card, .action-card, .history-card { margin-top: 12px; }

.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.action-info { display: flex; flex-direction: column; gap: 6px; }

.report-header-card {
  border: 1px solid var(--dm-border);
}
.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.report-header-actions { display: flex; gap: 8px; align-items: center; }
.progress-block { margin-top: 16px; }

.kpi-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.kpi {
  background: var(--dm-bg, #fff);
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  padding: 16px 18px;
}
.kpi-label { color: var(--dm-text-muted); font-size: 12px; }
.kpi-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--dm-text-primary, #111827);
  margin: 6px 0 2px;
}
.kpi-sub { color: var(--dm-text-muted); font-size: 12px; }

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.chart-card { min-height: 360px; }

.heat-wrapper { display: flex; flex-direction: column; gap: 18px; }
.heat-group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--dm-text-muted);
  margin-bottom: 8px;
}
.heat-cells {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.heat-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 84px;
  height: 56px;
  border-radius: 8px;
  padding: 4px 6px;
  font-size: 12px;
  cursor: default;
  transition: transform 0.12s ease;
}
.heat-cell:hover { transform: scale(1.04); }
.heat-cell-id { font-family: var(--dm-font-mono); font-size: 11px; opacity: 0.85; }
.heat-cell-q { font-size: 16px; font-weight: 700; }

.suggestion-list { padding-left: 18px; line-height: 1.8; margin: 0; }
.suggestion-list li { margin-bottom: 6px; }

/* ============== 长报告布局 ============== */
.cover-card {
  border: 1px solid var(--dm-border);
  background: var(--dm-bg-elevated);
}
.cover-grid {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
}
.cover-main { flex: 1; min-width: 280px; }
.cover-actions { flex-shrink: 0; }
/* V2-① 分析方法说明弹窗 */
.mth-body { max-height: 70vh; overflow-y: auto; padding-right: 4px; }
.mth-intro {
  font-size: 13px;
  line-height: 1.7;
  color: var(--dm-text-secondary, #475569);
  background: var(--dm-bg-muted);
  border-left: 3px solid var(--dm-border-strong);
  padding: 10px 14px;
  border-radius: 6px;
  margin: 0 0 16px;
}
.mth-section { margin-bottom: 18px; }
.mth-sec-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--dm-text-primary);
  margin-bottom: 4px;
}
.mth-sec-desc {
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--dm-text-muted, #64748b);
  margin-bottom: 8px;
}
.mth-items { margin: 0; padding-left: 0; list-style: none; }
.mth-items li {
  font-size: 13px;
  line-height: 1.6;
  padding: 6px 0 6px 14px;
  border-bottom: 1px dashed var(--dm-border, #e2e8f0);
  position: relative;
}
.mth-items li::before {
  content: '';
  position: absolute;
  left: 0; top: 13px;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--dm-color-primary, #3b82f6);
}
.mth-item-name { font-weight: 600; color: var(--dm-text-primary); margin-right: 6px; }
.mth-item-desc { color: var(--dm-text-secondary, #475569); }
.mth-foot {
  margin-top: 12px;
  font-size: 12px;
  color: var(--dm-text-muted, #94a3b8);
  text-align: right;
}
.cover-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--dm-text-muted);
  text-transform: uppercase;
  margin-bottom: 4px;
}
.cover-title {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--dm-text-primary);
}
.cover-ver {
  display: inline-block;
  margin-left: 12px;
  font-size: 14px;
  font-weight: 500;
  color: var(--dm-text-secondary);
  background: var(--dm-bg-muted);
  padding: 2px 10px;
  border-radius: 12px;
}
.cover-desc {
  margin-top: 8px;
  color: var(--dm-text-muted);
  font-size: 13px;
  line-height: 1.6;
}
.cover-overall {
  text-align: center;
  padding: 16px 28px;
  background: #fff;
  border: 1px solid var(--dm-border);
  border-radius: 12px;
  min-width: 200px;
}
.cover-overall-label {
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-bottom: 4px;
}
.cover-overall-value {
  font-size: 36px;
  font-weight: 800;
  color: var(--dm-text-primary);
  line-height: 1.1;
}
.cover-overall-unit {
  font-size: 16px;
  color: var(--dm-text-muted);
  font-weight: 500;
}

/* KPI 行扩展到 6 列 */
.kpi-row { grid-template-columns: repeat(6, 1fr); }

.section { display: flex; flex-direction: column; gap: 12px; }
.section-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 4px 0;
  border-top: 2px solid var(--dm-border);
  margin-top: 8px;
}
.section-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--dm-bg-inverse);
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.04em;
  font-size: 13px;
}
.section-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--dm-text-primary);
  line-height: 1.3;
}
.section-sub {
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-top: 2px;
}

/* 6 大 group 覆盖小计 */
.group-stat-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}
.group-stat-cell {
  background: var(--dm-bg);
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  padding: 12px 14px;
}
.group-stat-title {
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-bottom: 6px;
  font-weight: 600;
}
.group-stat-cov {
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.group-stat-sep { color: var(--dm-text-muted); font-weight: 500; }
.group-stat-pct {
  margin-left: auto;
  font-size: 12px;
  font-weight: 600;
  color: var(--dm-color-primary, #3b82f6);
}
.group-stat-q {
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-top: 4px;
}
.group-stat-empty { color: var(--dm-text-muted); }

/* ============== turn 卡片（亮点 / 失误） ============== */
.turn-card {
  background: #fff;
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  margin-bottom: 10px;
  overflow: hidden;
  transition: box-shadow 0.15s ease;
}
.turn-card:hover { box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06); }
.turn-card-good { border-left: 4px solid var(--dm-success); }
.turn-card-bad { border-left: 4px solid var(--dm-danger); }
.turn-card-head {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
}
.turn-card-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}
.turn-card-rank-good { background: var(--dm-success-bg); color: var(--dm-success); }
.turn-card-rank-bad { background: var(--dm-danger-bg); color: var(--dm-danger); }
.turn-card-meta { flex: 1; min-width: 0; }
.turn-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.turn-card-where {
  margin-left: auto;
  font-family: var(--dm-font-mono);
  font-size: 11px;
  color: var(--dm-color-primary);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dashed;
  text-decoration-color: var(--dm-border);
  text-underline-offset: 3px;
}
.turn-card-where:hover { text-decoration-style: solid; }
.turn-card-utter {
  color: var(--dm-text-primary);
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
.turn-card-chev { color: var(--dm-text-muted); margin-top: 6px; flex-shrink: 0; }
.turn-card-body {
  padding: 4px 16px 16px;
  border-top: 1px dashed var(--dm-border);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.turn-quote {
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
}
.turn-quote-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--dm-text-muted);
  margin-bottom: 4px;
  letter-spacing: 0.04em;
}
.turn-quote-customer {
  background: var(--dm-bg-muted);
  border-left: 3px solid var(--dm-border-strong);
}
.turn-quote-sales {
  background: var(--dm-bg-elevated);
  border-left: 3px solid var(--dm-text);
}
.turn-quote-text { color: var(--dm-text-primary); }

.turn-scores {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px 18px;
}
.turn-score-cell {
  display: grid;
  grid-template-columns: 90px 1fr 36px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.turn-score-label { color: var(--dm-text-muted); }
.turn-score-bar {
  height: 8px;
  background: var(--dm-bg-soft);
  border-radius: 4px;
  overflow: hidden;
}
.turn-score-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
.turn-score-num { font-weight: 700; text-align: right; }

.turn-section { margin-top: 4px; }
.turn-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dm-text-muted);
  margin-bottom: 4px;
  letter-spacing: 0.03em;
}
.turn-list { padding-left: 18px; line-height: 1.7; margin: 0; font-size: 13px; }
.turn-list-good li { color: var(--dm-success); }
.turn-list-bad li { color: var(--dm-danger); }
.turn-ref-text {
  background: var(--dm-bg-soft);
  padding: 8px 12px;
  border-radius: 6px;
  font-style: italic;
  font-size: 13px;
  color: var(--dm-text-primary);
}
.turn-fix {
  background: var(--dm-warning-bg);
  border-left: 3px solid var(--dm-warning);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--dm-text-primary);
}
.turn-toggle {
  text-align: center;
  padding: 4px 0 12px;
}

/* ============== §2 优秀话术分组（改动⑥） ============== */
.exc-group {
  margin-bottom: 18px;
}
.exc-group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 10px;
}
.exc-group-badge {
  font-weight: 700;
  font-size: 14px;
  padding: 3px 12px;
  border-radius: 6px;
  color: #fff;
}
.exc-badge-hb { background: #37352f; }
.exc-badge-off { background: var(--dm-warning); }
.exc-group-count {
  font-size: 12px;
  color: var(--dm-text-muted, #6b7280);
}
.exc-group-hint {
  font-size: 12px;
  color: var(--dm-warning);
  font-style: italic;
}
.exc-card {
  background: #fff;
  border: 1px solid var(--dm-border, #e5e7eb);
  border-left: 4px solid var(--dm-success);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 8px;
}
.exc-card-top {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.exc-signal {
  font-size: 12px;
  color: var(--dm-text-muted, #6b7280);
}
.exc-arrow { margin: 0 2px; opacity: .6; }
.exc-up { color: var(--dm-success); }
.exc-down { color: var(--dm-danger); }
.exc-where {
  margin-left: auto;
  font-size: 12px;
  color: var(--dm-text-secondary);
  cursor: pointer;
}
.exc-where:hover { text-decoration: underline; }
.exc-cust {
  font-size: 13px;
  color: var(--dm-text-muted, #6b7280);
  margin-bottom: 4px;
}
.exc-cust-label {
  display: inline-block;
  font-size: 11px;
  background: var(--dm-bg-muted);
  color: var(--dm-text-muted);
  border-radius: 4px;
  padding: 1px 6px;
  margin-right: 6px;
}
.exc-sales {
  font-size: 14px;
  line-height: 1.6;
  color: var(--dm-text, #1f2937);
  white-space: pre-wrap;
}
.exc-why {
  margin: 8px 0 0;
  padding-left: 18px;
}
.exc-why li {
  font-size: 12.5px;
  color: var(--dm-success);
  margin: 2px 0;
}

/* ============== 短板诊断卡片 ============== */
.weak-card {
  background: #fff;
  border: 1px solid var(--dm-border);
  border-left: 4px solid var(--dm-warning);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.weak-card-head { margin-bottom: 10px; }
.weak-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 14px;
}
.weak-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  font-size: 13px;
}
.weak-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dm-text-muted);
  margin-bottom: 4px;
}
.weak-issues { padding-left: 18px; margin: 0; line-height: 1.7; }

/* ============== 客户原声 ============== */
.voice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
}
.voice-card {
  border: 1px solid var(--dm-border);
}
.voice-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.voice-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.voice-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  padding: 8px 10px;
  background: var(--dm-bg-soft);
  border-radius: 6px;
}
.voice-quote { color: var(--dm-text-primary); line-height: 1.6; }
.voice-where {
  font-family: var(--dm-font-mono);
  font-size: 11px;
  color: var(--dm-color-primary);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dashed;
  text-decoration-color: var(--dm-border);
}

/* ============== 修订建议卡片（v3.1 风格） ============== */
.rev-group { margin-bottom: 16px; }
.rev-group-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--dm-text-primary);
  padding: 6px 0 8px;
  border-bottom: 2px solid var(--dm-border);
  margin-bottom: 10px;
}
.rev-cov {
  margin-left: auto;
  font-size: 12px;
  color: var(--dm-text-muted, #6b7280);
}
.rev-cov-dead { color: var(--dm-danger); font-weight: 600; }
.rev-quote {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--dm-border);
}
.rev-quote:last-child { border-bottom: none; }
.rev-quote-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.rev-quote-score {
  font-weight: 700;
  font-size: 12px;
  color: var(--dm-success);
  min-width: 30px;
}
.rev-quote-by {
  font-size: 11px;
  color: var(--dm-text-muted, #6b7280);
  min-width: 76px;
}
.rev-quote-line {
  font-size: 12.5px;
  color: var(--dm-text-primary);
  line-height: 1.55;
}
.rev-quote-line b {
  display: inline-block;
  min-width: 56px;
  margin-right: 6px;
  color: var(--dm-text-muted, #6b7280);
  font-weight: 600;
}
.rev-quote-text { font-size: 12.5px; color: var(--dm-text-primary); line-height: 1.55; }
.rev-card {
  background: #fff;
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  margin-bottom: 12px;
  overflow: hidden;
}
.rev-card-high { border-left: 4px solid var(--dm-danger); }
.rev-card-medium { border-left: 4px solid var(--dm-warning); }
.rev-card-low { border-left: 4px solid var(--dm-border-strong); }
.rev-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--dm-bg-soft);
  border-bottom: 1px solid var(--dm-border);
  flex-wrap: wrap;
}
.rev-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--dm-text-primary);
  margin-left: 4px;
}
.rev-card-body {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rev-row {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 12px;
  font-size: 13px;
  line-height: 1.65;
}
.rev-row-label {
  color: var(--dm-text-muted);
  font-weight: 600;
  font-size: 12px;
}
.rev-row-label-strong {
  color: var(--dm-danger);
}
.rev-row-text { color: var(--dm-text-primary); }
.rev-row-evidence {
  color: var(--dm-text-secondary, #4b5563);
}
.rev-row-suggestion {
  background: #f4eded;
  border-left: 3px solid var(--dm-danger);
  padding: 8px 12px;
  border-radius: 6px;
  font-weight: 500;
}
.rev-row-label-warn { color: #b45309; }
.rev-row-warn {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #b45309;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12.5px;
}
.rev-issue-pill {
  display: inline-block;
  background: var(--dm-warning-bg);
  color: var(--dm-warning);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  margin: 2px 4px 2px 0;
}
.rev-issue-pill em { font-style: normal; opacity: 0.75; }

/* ============== 关键数字 ============== */
.kn-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.kn-cell {
  background: #fff;
  border: 1px solid var(--dm-border);
  border-left: 3px solid var(--dm-color-primary, #3b82f6);
  border-radius: 8px;
  padding: 12px 14px;
}
.kn-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--dm-text-primary);
  font-family: var(--dm-font-mono);
  line-height: 1.2;
}
.kn-ctx {
  font-size: 13px;
  color: var(--dm-text-primary);
  font-weight: 500;
  margin-top: 4px;
}
.kn-src {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--dm-text-muted);
}
.kn-src-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.footer-card { margin-top: 12px; }

/* ============== 销售健康度仪表 ============== */
.section-num-warning {
  background: var(--dm-danger);
  font-size: 18px;
}
.health-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.health-card {
  background: #fff;
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 130px;
}
.health-label {
  font-size: 12px;
  color: var(--dm-text-muted);
  font-weight: 600;
}
.health-value {
  font-size: 32px;
  font-weight: 800;
  color: var(--dm-text-primary);
  line-height: 1.1;
}
.health-sub {
  font-size: 12px;
  color: var(--dm-text-muted);
}
.health-hint {
  margin-top: auto;
  font-size: 11px;
  color: var(--dm-text-secondary, #4b5563);
  line-height: 1.5;
  font-style: italic;
}

.token-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.token-pill {
  display: inline-block;
  background: var(--dm-success-bg);
  color: var(--dm-success);
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}
.token-pill em {
  font-style: normal;
  opacity: 0.7;
  margin-left: 4px;
}

.punt-card {
  border-left: 4px solid var(--dm-danger);
}
.punt-card-title { color: var(--dm-danger); }
.punt-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
  font-size: 13px;
  color: var(--dm-text-primary);
}
.punt-list li {
  margin-bottom: 4px;
}

.dup-card {
  border-left: 4px solid var(--dm-warning);
}
.dup-card-title { color: var(--dm-warning); }
.dup-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
  font-size: 13px;
  font-family: var(--dm-font-mono);
  color: var(--dm-text-primary);
}

@media (max-width: 1280px) {
  .health-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 1024px) {
  .health-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 1280px) {
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
  .group-stat-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 1024px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .two-col { grid-template-columns: 1fr; }
  .turn-scores { grid-template-columns: 1fr; }
  .weak-card-body { grid-template-columns: 1fr; }
  .rev-row { grid-template-columns: 1fr; }
  .rev-row-label { font-size: 11px; }
  .group-stat-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
