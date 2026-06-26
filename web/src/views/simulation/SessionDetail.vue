<script setup lang="ts">
/**
 * 会话复盘详情（Stage 7）
 *
 * URL: /simulation/detail/:id
 * 顶部：标题 + 元信息（persona / outcome / 轮数 / 时间）+ 导出 ▼ + 删除
 * Tabs：
 *   1. 对话   — 复用 DialogueStream 渲染历史 turns（无 stage marker，从 DB 还原）
 *   2. Coach  — el-collapse 6 panel
 *   3. Judge  — 最新 sales_score 雷达 + 历次综合质量 line + 文字 reason
 *   4. 画像   — 终态 session_memory 字段卡片
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElCollapse,
  ElCollapseItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElSelect,
  ElTabPane,
  ElTabs,
  ElTag,
} from 'element-plus'
import {
  ArrowLeft,
  BookText,
  Bookmark,
  Download,
  Trash2,
  Wrench,
} from '@lucide/vue'
import { casesApi } from '@/api/cases'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import DialogueStream from '@/components/DialogueStream.vue'
import PersonaAvatar from '@/components/PersonaAvatar.vue'
import {
  sessionsApi,
  type ExportFormat,
  type SessionDetail,
} from '@/api/sessions'
import type { StreamItem } from '@/stores/liveSession'

use([
  CanvasRenderer,
  RadarChart,
  LineChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
])

const route = useRoute()
const router = useRouter()

const sessionId = computed(() => (route.params.id as string) || '')

const loading = ref(true)
const detail = ref<SessionDetail | null>(null)
const activeTab = ref<'dialogue' | 'coach' | 'judge' | 'memory'>('dialogue')

// ============================================================
// 销冠 prompt 透视抽屉（C1 · 验证 Handbook 注入是否生效）
// ============================================================
const inspectOpen = ref(false)
const inspectLoading = ref(false)
const inspectData = ref<{
  handbook_block: string
  handbook_meta: {
    handbook_id: number | null
    handbook_resolved_from: 'explicit' | 'default' | 'none'
    handbook_block_len: number
    handbook_block_hash: string
    handbook_version_no: number | null
    handbook_status: string | null
  }
  session_handbook_id_raw: number | null
} | null>(null)

async function openPromptInspect() {
  if (!sessionId.value) return
  inspectOpen.value = true
  if (inspectData.value) return  // 缓存：同一 session 不重复请求
  inspectLoading.value = true
  try {
    inspectData.value = await sessionsApi.promptInspect(sessionId.value)
  } catch (e: any) {
    ElMessage.error(
      '加载销冠 prompt 失败：' +
        (e?.response?.data?.detail || e?.message || e),
    )
  } finally {
    inspectLoading.value = false
  }
}

const inspectMetaItems = computed(() => {
  const m = inspectData.value?.handbook_meta
  if (!m) return [] as Array<{ k: string; v: string }>
  const fromText: Record<string, string> = {
    explicit: '会话显式绑定',
    default: '全库唯一 ready 自动套用',
    none: '未绑定（销冠按通用经验答）',
  }
  return [
    { k: 'Handbook ID', v: m.handbook_id != null ? `#${m.handbook_id}` : '—' },
    { k: '绑定来源', v: fromText[m.handbook_resolved_from] || m.handbook_resolved_from },
    { k: 'Version', v: m.handbook_version_no != null ? `v${m.handbook_version_no}` : '—' },
    { k: 'Status', v: m.handbook_status || '—' },
    { k: '注入字符数', v: `${m.handbook_block_len.toLocaleString()} 字` },
    { k: '内容签名', v: m.handbook_block_hash || '—' },
  ]
})

// ============================================================
// 加载
// ============================================================

async function load(): Promise<void> {
  loading.value = true
  try {
    detail.value = await sessionsApi.fullDetail(sessionId.value)
  } catch (e: any) {
    ElMessage.error('加载失败：' + (e?.response?.data?.detail || e?.message || e))
    detail.value = null
  } finally {
    loading.value = false
  }
}

// ============================================================
// 对话 tab：收藏 turn 为案例（Stage 11 manual 轨）
// ============================================================
const collectVisible = ref(false)
const collectSubmitting = ref(false)
const collectForm = ref<{
  turn_idx: number
  title: string
  why_excellent: string
  tags: string[]
  context_radius: number
}>({
  turn_idx: 0,
  title: '',
  why_excellent: '',
  tags: ['manual'],
  context_radius: 2,
})

const salesTurnOptions = computed(() => {
  const turns = detail.value?.turns || []
  return turns.map((t) => ({
    value: t.idx,
    label: `#${t.idx} · ${t.role === 'sales' ? '销冠' : '客户'} · ${
      (t.content || '').slice(0, 32)
    }`,
  }))
})

function openCollectDialog() {
  const turns = detail.value?.turns || []
  const firstSales = turns.find((t) => t.role === 'sales') || turns[0]
  collectForm.value = {
    turn_idx: firstSales?.idx ?? 0,
    title: '',
    why_excellent: '',
    tags: ['manual'],
    context_radius: 2,
  }
  collectVisible.value = true
}

async function submitCollect() {
  if (!sessionId.value) return
  collectSubmitting.value = true
  try {
    const resp = await casesApi.collectFromSession(sessionId.value, {
      turn_idx: collectForm.value.turn_idx,
      title: collectForm.value.title.trim() || undefined,
      why_excellent: collectForm.value.why_excellent.trim() || undefined,
      tags: collectForm.value.tags,
      context_radius: collectForm.value.context_radius,
    })
    ElMessage.success(`已收藏为案例 #${resp.case.id}`)
    collectVisible.value = false
  } catch (e: any) {
    ElMessage.error('收藏失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    collectSubmitting.value = false
  }
}

// ============================================================
// 对话 tab：TurnRecord[] → StreamItem[]
// ============================================================
const streamItems = computed<StreamItem[]>(() => {
  if (!detail.value) return []
  return detail.value.turns.map((t) => ({
    idx: t.idx,
    speaker: t.role,
    content: t.content,
    metadata: t.metadata || {},
    stage: t.stage || '',
    created_at: t.created_at,
  }))
})

// ============================================================
// 对话 tab：工具调用（Stage 14）
//   detail.turns[*].metadata.tool_calls = [{loop, name, arguments, result_preview, ok}, ...]
// ============================================================
interface ToolCallEntry {
  turnIdx: number
  loop: number
  name: string
  arguments: Record<string, unknown>
  resultPreview: string
  ok: boolean
}
const toolCallEntries = computed<ToolCallEntry[]>(() => {
  const out: ToolCallEntry[] = []
  if (!detail.value) return out
  for (const t of detail.value.turns) {
    const tcs = ((t.metadata || {}) as any).tool_calls as any[] | undefined
    if (!Array.isArray(tcs)) continue
    for (const tc of tcs) {
      out.push({
        turnIdx: t.idx,
        loop: Number(tc?.loop ?? 0),
        name: String(tc?.name ?? '?'),
        arguments: (tc?.arguments && typeof tc.arguments === 'object') ? tc.arguments : {},
        resultPreview: String(tc?.result_preview ?? ''),
        ok: tc?.ok !== false,
      })
    }
  }
  return out
})
const openToolCalls = ref<string[]>([])
function toolCallKey(e: ToolCallEntry, i: number): string {
  return `${e.turnIdx}-${e.loop}-${e.name}-${i}`
}

// ============================================================
// Coach tab：6 panel
// ============================================================
interface CoachPanel {
  key: string
  title: string
  kind: 'text' | 'list' | 'list_of_objects' | 'rebuttals'
}
const COACH_PANELS: CoachPanel[] = [
  { key: 'outcome_analysis',    title: '总体分析',     kind: 'text' },
  { key: 'what_worked',         title: '有效策略',     kind: 'list_of_objects' },
  { key: 'what_failed',         title: '失效操作',     kind: 'list_of_objects' },
  { key: 'persona_insight',     title: '对客户的新认识', kind: 'text' },
  { key: 'key_lessons',         title: '核心经验',     kind: 'list' },
  { key: 'suggested_rebuttals', title: '推荐话术',     kind: 'rebuttals' },
]
const openCoachPanels = ref<string[]>([
  'outcome_analysis', 'what_worked', 'what_failed',
])

function coachField(key: string): unknown {
  return detail.value?.coach_review?.[key]
}
function isEmptyVal(v: unknown): boolean {
  if (v === null || v === undefined) return true
  if (typeof v === 'string') return v.trim() === ''
  if (Array.isArray(v)) return v.length === 0
  return false
}

// ============================================================
// Judge tab：雷达 + 时序
// ============================================================
const SCORE_AXES: { key: string; label: string }[] = [
  { key: 'responsiveness',     label: '响应度' },
  { key: 'specificity',        label: '具体度' },
  { key: 'evidence_usage',     label: '证据使用' },
  { key: 'objection_handling', label: '异议处理' },
  { key: 'closing_progress',   label: '推进度' },
]

const lastJudge = computed(() => {
  const arr = detail.value?.judge_evaluations || []
  return arr.length ? arr[arr.length - 1] : null
})

const radarOption = computed(() => {
  const score = (lastJudge.value?.score || {}) as Record<string, any>
  const values = SCORE_AXES.map((a) => {
    const v = Number(score[a.key] ?? 0)
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0
  })
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: SCORE_AXES.map((a) => ({ name: a.label, max: 1 })),
      radius: '62%',
      axisName: { color: '#525252', fontSize: 12 },
      splitLine: { lineStyle: { color: '#ececec' } },
      splitArea: { areaStyle: { color: ['#fafaf8', '#ffffff'] } },
      axisLine: { lineStyle: { color: '#ececec' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: values,
        name: '末轮评分',
        lineStyle: { color: '#1a1a1a', width: 2 },
        itemStyle: { color: '#1a1a1a' },
        areaStyle: { color: 'rgba(26, 26, 26, 0.08)' },
      }],
    }],
  }
})

const trendOption = computed(() => {
  const evals = detail.value?.judge_evaluations || []
  const rounds = evals.map((e) => e.turn_idx ?? 0)
  const qualities = evals.map((e) => {
    const v = (e.feedback as any)?.dialogue_quality_score
    return typeof v === 'number' ? v : 0
  })
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 16, top: 24, bottom: 30 },
    xAxis: {
      type: 'category',
      data: rounds,
      name: 'round',
      nameTextStyle: { color: '#888888', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 10,
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    series: [{
      name: '综合质量',
      type: 'line',
      smooth: true,
      data: qualities,
      itemStyle: { color: '#1a1a1a' },
      lineStyle: { color: '#1a1a1a', width: 2 },
      areaStyle: { color: 'rgba(26, 26, 26, 0.06)' },
      symbolSize: 5,
    }],
  }
})

function fmtScore(v: any): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : '-'
}

// ============================================================
// 画像 tab
// ============================================================
interface MemoField { key: string; label: string; kind: 'text' | 'list' }
const MEM_FIELDS: MemoField[] = [
  { key: 'current_need',          label: '当前需求',   kind: 'text' },
  { key: 'main_objections',       label: '核心异议',   kind: 'list' },
  { key: 'budget_boundary',       label: '预算边界',   kind: 'text' },
  { key: 'emotional_state',       label: '情绪状态',   kind: 'text' },
  { key: 'mentioned_competitors', label: '提及竞品',   kind: 'list' },
  { key: 'decision_constraints', label: '决策约束',   kind: 'list' },
  { key: 'do_not_repeat',         label: '避免重复',   kind: 'list' },
  { key: 'next_best_action',      label: '下一步建议', kind: 'text' },
]

// ============================================================
// 顶部操作
// ============================================================

function doExport(format: ExportFormat): void {
  const url = sessionsApi.exportUrl(sessionId.value, format)
  const a = document.createElement('a')
  a.href = url
  a.download = `${sessionId.value}.${format}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

async function doDelete(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除会话 ${sessionId.value}？\n关联 turns / evaluations / outputs 文件都会清除。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await sessionsApi.del(sessionId.value)
    ElMessage.success('已删除')
    router.push('/simulation/history')
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

const OUTCOME_TAG_TYPE: Record<string, 'info' | 'warning' | 'success' | 'danger' | 'primary'> = {
  DEAL_DONE: 'success', WALK_AWAY: 'warning', COMPLAINT: 'danger',
  TIMEOUT: 'info', CANCELLED: 'info', CONTINUE: 'primary',
}

onMounted(load)
</script>

<template>
  <div class="page">
    <!-- 顶部 -->
    <header class="topbar">
      <ElButton text @click="router.push('/simulation/history')">
        <template #icon><ArrowLeft :size="14" :stroke-width="1.6" /></template>
        返回历史
      </ElButton>
      <div class="title-wrap">
        <h1 class="title dm-text-h2">会话复盘</h1>
        <span class="sid mono dm-text-caption">{{ sessionId }}</span>
      </div>
      <div class="actions">
        <ElButton @click="openPromptInspect">
          <template #icon><BookText :size="14" :stroke-width="1.6" /></template>
          销冠剧本
        </ElButton>
        <ElDropdown trigger="click">
          <ElButton>
            <template #icon><Download :size="14" :stroke-width="1.6" /></template>
            导出
          </ElButton>
          <template #dropdown>
            <ElDropdownMenu>
              <ElDropdownItem @click="doExport('md')">Markdown (.md)</ElDropdownItem>
              <ElDropdownItem @click="doExport('json')">JSON (.json)</ElDropdownItem>
              <ElDropdownItem @click="doExport('jsonl')">JSONL (.jsonl)</ElDropdownItem>
            </ElDropdownMenu>
          </template>
        </ElDropdown>
        <ElButton type="danger" plain @click="doDelete">
          <template #icon><Trash2 :size="14" :stroke-width="1.6" /></template>
          删除
        </ElButton>
      </div>
    </header>

    <!-- C1 · 销冠 prompt 透视抽屉 -->
    <ElDrawer
      v-model="inspectOpen"
      title="销冠剧本（注入到本场 sales prompt 顶部的 Handbook 强约束块）"
      direction="rtl"
      size="640px"
    >
      <div v-if="inspectLoading" class="dm-text-muted">加载中…</div>
      <template v-else-if="inspectData">
        <div class="inspect-meta">
          <div
            v-for="it in inspectMetaItems"
            :key="it.k"
            class="inspect-meta-row"
          >
            <span class="inspect-meta-k">{{ it.k }}</span>
            <span class="inspect-meta-v">{{ it.v }}</span>
          </div>
        </div>
        <pre class="inspect-block">{{ inspectData.handbook_block }}</pre>
      </template>
    </ElDrawer>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!detail" class="loading">未找到会话</div>

    <template v-else>
      <!-- 元信息卡 -->
      <section class="meta-card card">
        <div class="meta-item meta-item-persona">
          <span class="dm-text-overline">客户</span>
          <div class="meta-persona">
            <PersonaAvatar
              :avatar-key="detail.persona?.avatar_key ?? null"
              :name="detail.persona?.name || '客户'"
              :size="32"
            />
            <span class="dm-text-body-strong">
              {{ detail.persona?.name || '—' }}
            </span>
          </div>
        </div>
        <div class="meta-item">
          <span class="dm-text-overline">主题</span>
          <span class="dm-text-body">{{ detail.session.topic || '—' }}</span>
        </div>
        <div class="meta-item">
          <span class="dm-text-overline">结果</span>
          <ElTag
            v-if="detail.outcome"
            :type="OUTCOME_TAG_TYPE[detail.outcome] || 'info'"
            effect="plain"
            size="small"
          >
            {{ detail.outcome }}
          </ElTag>
          <span v-else class="dm-text-muted">—</span>
        </div>
        <div class="meta-item">
          <span class="dm-text-overline">轮数</span>
          <span class="dm-text-number-lg">
            {{ detail.metrics.total_rounds }}
          </span>
          <span class="dm-text-small dm-text-muted">
            / {{ detail.session.max_rounds }}
          </span>
        </div>
        <div class="meta-item">
          <span class="dm-text-overline">开始</span>
          <span class="dm-text-caption mono">
            {{ (detail.session.started_at || '—').replace('T', ' ').slice(0, 19) }}
          </span>
        </div>
        <div class="meta-item">
          <span class="dm-text-overline">结束</span>
          <span class="dm-text-caption mono">
            {{ (detail.session.ended_at || '—').replace('T', ' ').slice(0, 19) }}
          </span>
        </div>
      </section>

      <!-- Tabs -->
      <section class="tab-card card">
        <ElTabs v-model="activeTab" class="detail-tabs">

          <!-- ============ 对话 ============ -->
          <ElTabPane label="对话" name="dialogue">
            <div v-if="streamItems.length" class="dialogue-actions">
              <span class="dm-text-small dm-text-muted">
                共 {{ streamItems.length }} 条 turn
              </span>
              <span style="flex: 1" />
              <ElButton size="small" type="primary" plain @click="openCollectDialog">
                <ElIcon><Bookmark :size="14" /></ElIcon>
                <span style="margin-left: 6px">收藏为案例</span>
              </ElButton>
            </div>

            <DialogueStream
              v-if="streamItems.length"
              :items="streamItems"
              :persona-name="detail.persona?.name || '客户'"
              :persona-avatar-key="detail.persona?.avatar_key ?? null"
              :auto-scroll="false"
              class="dialogue-stream"
            />
            <ElEmpty v-else description="无对话记录" />

            <!-- Stage 14：销冠工具调用轨迹 -->
            <section v-if="toolCallEntries.length" class="tool-calls-section">
              <div class="tool-calls-head">
                <ElIcon><Wrench :size="14" /></ElIcon>
                <span>销冠工具调用</span>
                <span class="dm-text-muted dm-text-small">
                  共 {{ toolCallEntries.length }} 次，覆盖
                  {{ new Set(toolCallEntries.map(e => e.turnIdx)).size }} 个 turn
                </span>
              </div>
              <ElCollapse v-model="openToolCalls" class="tool-calls-collapse">
                <ElCollapseItem
                  v-for="(e, i) in toolCallEntries"
                  :key="toolCallKey(e, i)"
                  :name="toolCallKey(e, i)"
                >
                  <template #title>
                    <div class="tc-title">
                      <ElTag size="small" effect="plain">turn {{ e.turnIdx }}</ElTag>
                      <span class="tc-name mono">{{ e.name }}</span>
                      <ElTag v-if="!e.ok" type="danger" size="small">失败</ElTag>
                      <span class="dm-text-muted dm-text-small">
                        loop {{ e.loop }}
                      </span>
                    </div>
                  </template>

                  <div class="tc-block">
                    <div class="tc-sub">入参</div>
                    <pre class="tc-pre">{{ JSON.stringify(e.arguments, null, 2) }}</pre>
                  </div>
                  <div class="tc-block">
                    <div class="tc-sub">返回（前 800 字）</div>
                    <pre class="tc-pre tc-pre-result">{{ e.resultPreview || '—' }}</pre>
                  </div>
                </ElCollapseItem>
              </ElCollapse>
            </section>
          </ElTabPane>

          <!-- ============ Coach ============ -->
          <ElTabPane label="Coach 复盘" name="coach">
            <ElEmpty v-if="!detail.coach_review" description="本会话未生成 Coach 复盘" />
            <ElCollapse v-else v-model="openCoachPanels" class="coach-collapse">
              <ElCollapseItem
                v-for="p in COACH_PANELS"
                :key="p.key"
                :title="p.title"
                :name="p.key"
              >
                <div v-if="isEmptyVal(coachField(p.key))" class="dm-text-muted dm-text-small">
                  —
                </div>

                <template v-else-if="p.kind === 'text'">
                  <p class="coach-text dm-text-body">{{ coachField(p.key) }}</p>
                </template>

                <template v-else-if="p.kind === 'list'">
                  <ul class="coach-list">
                    <li
                      v-for="(it, i) in (coachField(p.key) as string[])"
                      :key="i"
                      class="dm-text-body"
                    >
                      {{ it }}
                    </li>
                  </ul>
                </template>

                <template v-else-if="p.kind === 'list_of_objects'">
                  <div
                    v-for="(it, i) in (coachField(p.key) as Record<string, any>[])"
                    :key="i"
                    class="coach-obj"
                  >
                    <div class="coach-obj-head">
                      <ElTag size="small" effect="plain">
                        R{{ it.round ?? '-' }}
                      </ElTag>
                      <span class="dm-text-body-strong">
                        {{ it.strategy || it.action || '—' }}
                      </span>
                    </div>
                    <div v-if="it.evidence" class="coach-obj-quote dm-text-caption">
                      "{{ it.evidence }}"
                    </div>
                    <div
                      v-if="it.why_effective || it.why_failed"
                      class="dm-text-caption"
                    >
                      {{ it.why_effective || it.why_failed }}
                    </div>
                  </div>
                </template>

                <template v-else-if="p.kind === 'rebuttals'">
                  <div
                    v-for="(it, i) in (coachField(p.key) as Record<string, any>[])"
                    :key="i"
                    class="coach-obj"
                  >
                    <div class="dm-text-body-strong">
                      遇到：{{ it.objection || '—' }}
                    </div>
                    <div class="coach-obj-quote dm-text-caption">
                      → {{ it.rebuttal_template || it.rebuttal || '—' }}
                    </div>
                  </div>
                </template>
              </ElCollapseItem>
            </ElCollapse>
          </ElTabPane>

          <!-- ============ Judge ============ -->
          <ElTabPane name="judge">
            <template #label>
              <span>Judge</span>
              <span class="dm-text-small dm-text-muted">
                · {{ detail.metrics.judge_count }} 次
              </span>
            </template>

            <ElEmpty v-if="!detail.judge_evaluations.length" description="本会话未生成 Judge 评估" />
            <template v-else>
              <div class="judge-row">
                <div class="judge-radar-wrap card-inner">
                  <div class="card-inner-title dm-text-overline">末轮五维评分</div>
                  <v-chart :option="radarOption" autoresize class="judge-radar" />
                </div>
                <div class="judge-trend-wrap card-inner">
                  <div class="card-inner-title dm-text-overline">综合质量趋势</div>
                  <v-chart :option="trendOption" autoresize class="judge-trend" />
                </div>
              </div>

              <div class="judge-meta">
                <div class="judge-meta-item">
                  <span class="dm-text-overline">末轮结果</span>
                  <ElTag
                    size="small"
                    effect="plain"
                    :type="lastJudge?.feedback?.end_status === 'CONTINUE' ? 'info' : 'warning'"
                  >
                    {{ lastJudge?.feedback?.end_status || 'CONTINUE' }}
                  </ElTag>
                </div>
                <div class="judge-meta-item">
                  <span class="dm-text-overline">末轮综合质量</span>
                  <span class="dm-text-number-lg">
                    {{ fmtScore(lastJudge?.feedback?.dialogue_quality_score) }}
                  </span>
                </div>
              </div>

              <div v-if="lastJudge?.feedback?.reason" class="judge-reason card-inner">
                <div class="card-inner-title dm-text-overline">Judge 说明</div>
                <p class="dm-text-body">{{ lastJudge.feedback.reason }}</p>
              </div>

              <div class="judge-instr">
                <div v-if="lastJudge?.feedback?.sales_instruction" class="card-inner">
                  <div class="card-inner-title dm-text-overline">销冠下一步指令</div>
                  <p class="dm-text-body">{{ lastJudge.feedback.sales_instruction }}</p>
                </div>
                <div v-if="lastJudge?.feedback?.persona_instruction" class="card-inner">
                  <div class="card-inner-title dm-text-overline">人设下一步指令</div>
                  <p class="dm-text-body">{{ lastJudge.feedback.persona_instruction }}</p>
                </div>
              </div>
            </template>
          </ElTabPane>

          <!-- ============ 画像 ============ -->
          <ElTabPane label="终态画像" name="memory">
            <ElEmpty
              v-if="!detail.session_memory || !Object.keys(detail.session_memory).length"
              description="本会话未生成画像快照"
            />
            <div v-else class="mem-grid">
              <div
                v-for="f in MEM_FIELDS"
                :key="f.key"
                class="card-inner"
              >
                <div class="card-inner-title dm-text-overline">{{ f.label }}</div>
                <div
                  v-if="isEmptyVal((detail.session_memory as any)[f.key])"
                  class="dm-text-muted dm-text-small"
                >
                  —
                </div>
                <p
                  v-else-if="f.kind === 'text'"
                  class="dm-text-body"
                >
                  {{ (detail.session_memory as any)[f.key] }}
                </p>
                <ul v-else class="mem-list">
                  <li
                    v-for="(it, i) in ((detail.session_memory as any)[f.key] as string[])"
                    :key="i"
                    class="dm-text-body"
                  >
                    {{ it }}
                  </li>
                </ul>
              </div>
            </div>
          </ElTabPane>
        </ElTabs>
      </section>
    </template>

    <!-- Stage 11：收藏为案例 dialog（manual 轨） -->
    <ElDialog
      v-model="collectVisible"
      title="收藏为销售案例"
      width="560px"
      append-to-body
    >
      <ElForm :model="collectForm" label-position="top">
        <ElFormItem label="选择目标 turn（围绕其上下文抽取）" required>
          <ElSelect
            v-model="collectForm.turn_idx"
            filterable
            placeholder="选择一条精彩对话"
            style="width: 100%"
          >
            <ElOption
              v-for="opt in salesTurnOptions"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="上下文扩展轮数">
          <ElInputNumber
            v-model="collectForm.context_radius"
            :min="0"
            :max="10"
            controls-position="right"
            style="width: 160px"
          />
          <span class="dm-text-small dm-text-muted" style="margin-left: 8px">
            前后各扩展 N 条 turn 一起入库
          </span>
        </ElFormItem>
        <ElFormItem label="标题（留空自动生成）">
          <ElInput v-model="collectForm.title" placeholder="例如：[拒绝转化] 用价值锚定破价" />
        </ElFormItem>
        <ElFormItem label="为什么是好案例">
          <ElInput
            v-model="collectForm.why_excellent"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            placeholder="说明亮点：策略 / 措辞 / 节奏 …"
          />
        </ElFormItem>
        <ElFormItem label="标签">
          <ElSelect
            v-model="collectForm.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="回车添加"
            style="width: 100%"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="collectVisible = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="collectSubmitting"
          @click="submitCollect"
        >
          收藏
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped lang="scss">
.page {
  padding: var(--dm-space-6) var(--dm-space-7);
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-4);
}

.topbar {
  display: flex;
  align-items: center;
  gap: var(--dm-space-4);
}
.title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}
.title { margin: 0; }
.sid {
  color: var(--dm-text-muted);
}
.actions {
  display: flex;
  gap: var(--dm-space-2);
}
.mono { font-family: var(--dm-font-mono); }

/* 销冠 prompt 透视抽屉 */
.inspect-meta {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 12px;
  margin-bottom: 16px;
  padding: 12px 14px;
  background: var(--dm-bg-soft);
  border-radius: 8px;
  font-size: var(--dm-fs-small);
}
.inspect-meta-k {
  color: var(--dm-text-muted);
}
.inspect-meta-v {
  font-family: var(--dm-font-mono);
}
.inspect-block {
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--dm-bg-code, #0f1115);
  color: var(--dm-text-code, #e6e6e6);
  padding: 14px 16px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.55;
  max-height: calc(100vh - 260px);
  overflow: auto;
}

.loading {
  padding: var(--dm-space-9);
  text-align: center;
  color: var(--dm-text-muted);
}

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-md);
}

.meta-card {
  display: grid;
  grid-template-columns: 1.4fr 2fr 0.8fr 0.8fr 1.2fr 1.2fr;
  gap: var(--dm-space-4);
  padding: var(--dm-space-4) var(--dm-space-5);
}
.meta-item {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-1);
  min-width: 0;
  span { word-break: break-word; }
}
.meta-persona {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tab-card {
  flex: 1;
  min-height: 0;
  padding: 0 var(--dm-space-4) var(--dm-space-4);
}
.detail-tabs {
  :deep(.el-tabs__header) {
    margin: 0;
    padding-top: var(--dm-space-2);
    border-bottom: 1px solid var(--dm-border);
  }
  :deep(.el-tabs__nav-wrap::after) { background: transparent; }
}

.dialogue-stream { max-height: 70vh; }
.dialogue-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0 12px;
}

// Stage 14：工具调用块
.tool-calls-section {
  margin-top: 18px;
  border-top: 1px dashed var(--dm-border);
  padding-top: 14px;
}
.tool-calls-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: var(--dm-fw-medium);
  font-size: 13.5px;
  margin-bottom: 8px;
}
.tool-calls-collapse :deep(.el-collapse-item__header) {
  font-weight: var(--dm-fw-regular);
}
.tc-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tc-name {
  color: #4f46e5;
  font-weight: var(--dm-fw-medium);
}
.tc-block { margin-bottom: 10px; }
.tc-sub {
  font-size: 11.5px;
  color: var(--dm-text-muted);
  margin-bottom: 4px;
  letter-spacing: 0.4px;
}
.tc-pre {
  background: var(--dm-bg-subtle, #f7f6f3);
  padding: 8px 10px;
  border-radius: 6px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.55;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.tc-pre-result {
  max-height: 240px;
  overflow: auto;
}
.mono {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}

// Coach
.coach-collapse :deep(.el-collapse-item__header) {
  font-weight: var(--dm-fw-medium);
}
.coach-text { margin: 0; white-space: pre-wrap; }
.coach-list { margin: 0; padding-left: var(--dm-space-5); }
.coach-list li { margin-bottom: var(--dm-space-1); }
.coach-obj {
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  padding: var(--dm-space-2) var(--dm-space-3);
  margin-bottom: var(--dm-space-2);
}
.coach-obj-head {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
  margin-bottom: var(--dm-space-1);
}
.coach-obj-quote {
  color: var(--dm-text-secondary);
  font-style: italic;
  margin-bottom: var(--dm-space-1);
}

// Judge
.card-inner {
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  padding: var(--dm-space-3) var(--dm-space-4);
}
.card-inner-title {
  margin-bottom: var(--dm-space-2);
}
.judge-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--dm-space-3);
  margin-top: var(--dm-space-3);
}
.judge-radar-wrap, .judge-trend-wrap {
  min-height: 280px;
}
.judge-radar, .judge-trend {
  width: 100%;
  height: 240px;
}
.judge-meta {
  display: flex;
  gap: var(--dm-space-6);
  margin-top: var(--dm-space-3);
  padding: 0 var(--dm-space-2);
}
.judge-meta-item {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-1);
}
.judge-reason {
  margin-top: var(--dm-space-3);
}
.judge-instr {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--dm-space-3);
  margin-top: var(--dm-space-3);
}

// Memory
.mem-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--dm-space-3);
  margin-top: var(--dm-space-3);
}
.mem-list { margin: 0; padding-left: var(--dm-space-5); }
.mem-list li { margin-bottom: var(--dm-space-1); }

@media (max-width: 1024px) {
  .meta-card { grid-template-columns: repeat(2, 1fr); }
  .judge-row { grid-template-columns: 1fr; }
  .judge-instr { grid-template-columns: 1fr; }
  .mem-grid { grid-template-columns: 1fr; }
}
</style>
