<script setup lang="ts">
/**
 * 批量报告（Stage 10）
 *
 * 顶部：批量任务选择器 + 4 数字卡 + 导出 Training Guide
 * 中部：
 *   - Outcome 分布饼图
 *   - 销冠五维雷达
 *   - 销冠 per-session 质量分折线（quality + 5 维堆叠均值）
 *   - RAG 命中漏斗（doughnut）+ chunks 柱状
 * 下部：
 *   - Persona 表现对比条形（avg_quality + 标记 deal_count）
 *   - 高频异议 Top-15 横向条形
 *   - 异议详情表（hover 展开 personas / outcomes）
 *
 * 切换批量任务时自动重新拉 5 个接口，空数据用 ElEmpty 占位。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElEmpty,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
} from 'element-plus'
import { Download, FileText, RefreshCcw } from '@lucide/vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import DmPageHeader from '@/components/DmPageHeader.vue'
import PersonaAvatar from '@/components/PersonaAvatar.vue'
import { batchApi, type BatchInfo } from '@/api/batch'
import {
  batchReportApi,
  type BatchReportOverview,
  type ObjectionsResp,
  type PersonaComparisonResp,
  type PlaybookStatsResp,
  type RagStatsResp,
  type SalesRadarResp,
} from '@/api/batch_report'

use([
  CanvasRenderer,
  BarChart, LineChart, PieChart, RadarChart,
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, RadarComponent,
])

const route = useRoute()
const router = useRouter()

// ============================================================
// 批量任务选择
// ============================================================

const batches = ref<BatchInfo[]>([])
const selectedId = ref<number | null>(null)

async function loadBatches(): Promise<void> {
  try {
    const r = await batchApi.list({ size: 100 })
    batches.value = r.items
    // 优先 URL ?id=，否则取第一个已完成的，再否则取第一个
    const qid = Number(route.query.id)
    if (qid && r.items.find((b) => b.id === qid)) {
      selectedId.value = qid
    } else {
      const firstCompleted = r.items.find((b) => b.status === 'completed')
      selectedId.value = (firstCompleted || r.items[0])?.id ?? null
    }
  } catch (e: any) {
    ElMessage.error('加载批量任务列表失败：' + (e?.message || e))
  }
}

watch(selectedId, (v) => {
  if (v != null) {
    router.replace({ query: { ...route.query, id: String(v) } })
    loadReport()
  }
})

// ============================================================
// 5 个聚合数据
// ============================================================

const loading = ref(false)
const overview = ref<BatchReportOverview | null>(null)
const radar = ref<SalesRadarResp | null>(null)
const personaCmp = ref<PersonaComparisonResp | null>(null)
const objections = ref<ObjectionsResp | null>(null)
const rag = ref<RagStatsResp | null>(null)
const playbook = ref<PlaybookStatsResp | null>(null)

async function loadReport(): Promise<void> {
  if (selectedId.value == null) return
  const id = selectedId.value
  loading.value = true
  try {
    const [o, r, p, obj, rs, pb] = await Promise.allSettled([
      batchReportApi.overview(id),
      batchReportApi.salesRadar(id),
      batchReportApi.personaComparison(id),
      batchReportApi.objections(id, 20),
      batchReportApi.ragStats(id),
      batchReportApi.playbookStats(id),
    ])
    overview.value = o.status === 'fulfilled' ? o.value : null
    radar.value = r.status === 'fulfilled' ? r.value : null
    personaCmp.value = p.status === 'fulfilled' ? p.value : null
    objections.value = obj.status === 'fulfilled' ? obj.value : null
    rag.value = rs.status === 'fulfilled' ? rs.value : null
    playbook.value = pb.status === 'fulfilled' ? pb.value : null
    const fail = [o, r, p, obj, rs, pb].filter((x) => x.status === 'rejected')
    if (fail.length) console.warn('[batch-report] partial failures:', fail)
  } finally {
    loading.value = false
  }
}

function downloadTrainingGuide(): void {
  if (selectedId.value == null) {
    ElMessage.warning('请先选择批量任务')
    return
  }
  const a = document.createElement('a')
  a.href = batchReportApi.exportUrl(selectedId.value)
  a.download = `training_guide_batch_${selectedId.value}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ============================================================
// 4 数字卡
// ============================================================

const stats = computed(() => {
  const o = overview.value
  return [
    {
      label: '完成场次',
      value: o ? `${o.completed_count}/${o.total_count}` : '—',
      hint: o ? `失败 ${o.failed_count} · 中断 ${o.cancelled_count}` : '—',
    },
    {
      label: '成交率',
      value: o ? `${(o.deal_rate * 100).toFixed(1)}%` : '—',
      hint: o ? `${o.deal_count} 场 DEAL_DONE` : '—',
    },
    {
      label: '平均轮数',
      value: o ? o.avg_rounds.toFixed(1) : '—',
      hint: o ? `上限 ${o.max_rounds}` : '—',
    },
    {
      label: '平均质量',
      value: o ? o.avg_quality.toFixed(2) : '—',
      hint: '0~10 分（Judge 综合）',
    },
  ]
})

// ============================================================
// 图 1: outcome 饼图（来自 overview）
// ============================================================

const OUTCOME_COLORS: Record<string, string> = {
  DEAL_DONE: '#2d7a3e',
  WALK_AWAY: '#9a6c1a',
  COMPLAINT: '#9b2c2c',
  TIMEOUT:   '#888888',
  CANCELLED: '#bfbfbf',
  CONTINUE:  '#1e5fa8',
  UNKNOWN:   '#d4d3cf',
  ERROR:     '#9b2c2c',
}

const outcomeOption = computed(() => {
  const dist = overview.value?.outcome_dist || []
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', right: 8, top: 'middle',
              textStyle: { fontSize: 12, color: '#525252' } },
    series: [{
      type: 'pie',
      radius: ['46%', '72%'],
      center: ['38%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: false }, labelLine: { show: false },
      data: dist.map((d) => ({
        name: d.outcome, value: d.count,
        itemStyle: { color: OUTCOME_COLORS[d.outcome] || '#888888' },
      })),
    }],
  }
})
const outcomeHasData = computed(() => (overview.value?.outcome_dist || []).length > 0)

// ============================================================
// 图 2: 销冠雷达
// ============================================================

const radarOption = computed(() => {
  const dims = radar.value?.dimensions || []
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: dims.map((d) => ({ name: d.label, max: 10 })),
      shape: 'polygon',
      splitNumber: 5,
      axisName: { color: '#525252', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#fafaf7', '#ffffff'] } },
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLine: { lineStyle: { color: '#ececec' } },
    },
    series: [{
      type: 'radar',
      areaStyle: { color: 'rgba(26, 26, 26, 0.12)' },
      lineStyle: { color: '#1a1a1a', width: 2 },
      itemStyle: { color: '#1a1a1a' },
      symbolSize: 5,
      data: [{
        name: '本批次平均',
        value: dims.map((d) => d.avg),
      }],
    }],
  }
})
const radarHasData = computed(() => (radar.value?.dimensions || []).length > 0)

// ============================================================
// 图 3: per-session quality 折线
// ============================================================

const qualityLineOption = computed(() => {
  const arr = radar.value?.per_session || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any[]) => {
        const i = params[0]?.dataIndex
        const row = arr[i]
        if (!row) return ''
        return (
          `<b>${row.session_id.slice(-12)}</b><br/>`
          + `outcome: ${row.outcome}<br/>`
          + `quality: ${row.quality?.toFixed(2) ?? '—'}`
        )
      },
    },
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: 'category',
      data: arr.map((_, i) => `S${i + 1}`),
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: {
      type: 'value', min: 0, max: 10,
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    series: [{
      name: 'quality',
      type: 'line',
      smooth: true,
      data: arr.map((r) => r.quality ?? 0),
      itemStyle: { color: '#1a1a1a' },
      lineStyle: { color: '#1a1a1a', width: 2 },
      areaStyle: { color: 'rgba(26, 26, 26, 0.06)' },
    }],
  }
})
const qualityLineHasData = computed(
  () => (radar.value?.per_session || []).length > 0,
)

// ============================================================
// 图 4: RAG 命中漏斗 + chunks
// ============================================================

const ragPieOption = computed(() => {
  const r = rag.value
  if (!r) return {}
  const used = r.used_any_kb
  const notUsed = Math.max(0, r.sales_turns_total - used)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 轮 ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 12, color: '#525252' } },
    series: [{
      type: 'pie',
      radius: ['50%', '72%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: {
        show: true,
        formatter: '{b}\n{d}%',
        color: '#525252',
        fontSize: 11,
      },
      data: [
        { name: '用了 KB', value: used, itemStyle: { color: '#1a1a1a' } },
        { name: '未用 KB', value: notUsed, itemStyle: { color: '#d4d3cf' } },
      ],
    }],
  }
})
const ragHasData = computed(() => (rag.value?.sales_turns_total || 0) > 0)

const ragBarOption = computed(() => {
  const r = rag.value
  if (!r) return {}
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 16, top: 16, bottom: 24 },
    xAxis: { type: 'value', axisLabel: { color: '#888888', fontSize: 11 },
             splitLine: { lineStyle: { color: '#ececec' } } },
    yAxis: {
      type: 'category',
      data: ['企业 chunks', '产品 chunks'],
      axisLabel: { color: '#525252', fontSize: 12 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
    },
    series: [{
      type: 'bar',
      barWidth: 18,
      data: [
        { value: r.enterprise_chunks, itemStyle: { color: '#9a6c1a' } },
        { value: r.product_chunks,    itemStyle: { color: '#1e5fa8' } },
      ],
      label: { show: true, position: 'right', color: '#525252' },
    }],
  }
})

// ============================================================
// business_stages v0.2：剧本动作覆盖率 + 阶段配比
// ============================================================

const STAGE_COLORS: Record<string, string> = {
  S1: '#1e5fa8',
  S2: '#2d7a3e',
  S3: '#9a6c1a',
  S4: '#9b2c2c',
  S5: '#6b7280',
}

// 阶段配比柱图：actual vs expected 并排展示，⚠️ 偏差超阈值红色标记
const stageBalanceOption = computed(() => {
  const items = playbook.value?.stage_distribution || []
  if (!items.length) return {}
  const labels = items.map((it) => `${it.stage_id} ${it.stage_cn}`)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        const i = params[0]?.dataIndex
        const it = items[i]
        if (!it) return ''
        const warn = it.outside_tolerance ? '<span style="color:#dc2626"> ⚠ 超阈值</span>' : ''
        return (
          `<b>${it.stage_id} · ${it.stage_cn}</b>${warn}<br/>`
          + `实际：${it.actual_count} 轮 (${(it.actual_ratio * 100).toFixed(1)}%)<br/>`
          + `期望：${(it.expected_ratio * 100).toFixed(1)}%<br/>`
          + `偏差：${(it.delta * 100 >= 0 ? '+' : '') + (it.delta * 100).toFixed(1)}%`
        )
      },
    },
    legend: { bottom: 0, textStyle: { fontSize: 12, color: '#525252' } },
    grid: { left: 40, right: 16, top: 16, bottom: 50 },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: '#525252', fontSize: 11, interval: 0,
                   rotate: labels.length > 4 ? 18 : 0 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
    },
    yAxis: {
      type: 'value', min: 0, max: 1,
      axisLabel: {
        color: '#888888', fontSize: 11,
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
      },
      splitLine: { lineStyle: { color: '#ececec' } },
    },
    series: [
      {
        name: '实际占比', type: 'bar', barWidth: 16,
        data: items.map((it) => ({
          value: it.actual_ratio,
          itemStyle: {
            color: it.outside_tolerance ? '#dc2626' : (STAGE_COLORS[it.stage_id] || '#1a1a1a'),
          },
        })),
        label: {
          show: true, position: 'top', color: '#525252', fontSize: 10,
          formatter: (p: any) => `${(p.value * 100).toFixed(0)}%`,
        },
      },
      {
        name: '期望权重', type: 'bar', barWidth: 16,
        data: items.map((it) => it.expected_ratio),
        itemStyle: { color: '#d4d3cf' },
        label: {
          show: true, position: 'top', color: '#888', fontSize: 10,
          formatter: (p: any) => `${(p.value * 100).toFixed(0)}%`,
        },
      },
    ],
  }
})
const stageBalanceHasData = computed(
  () => (playbook.value?.stage_distribution || []).some((s) => s.actual_count > 0),
)

// 剧本动作覆盖率：横向条形，按阶段着色
const actionUsageOption = computed(() => {
  const items = (playbook.value?.action_usage || []).slice(0, 22)
  if (!items.length) return {}
  const arr = [...items].reverse()
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const it = arr[p.dataIndex]
        return (
          `<b>[${it.stage_id}] ${it.cn}</b><br/>`
          + `action_id: <code>${it.action_id}</code><br/>`
          + `命中: ${it.count} 轮`
        )
      },
    },
    grid: { left: 200, right: 32, top: 8, bottom: 8 },
    xAxis: { type: 'value', minInterval: 1,
             axisLabel: { color: '#888888', fontSize: 11 },
             splitLine: { lineStyle: { color: '#ececec' } } },
    yAxis: {
      type: 'category',
      data: arr.map((it) => `[${it.stage_id}] ${it.cn}`),
      axisLabel: { color: '#525252', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
    },
    series: [{
      type: 'bar', barWidth: 12,
      data: arr.map((it) => ({
        value: it.count,
        itemStyle: { color: STAGE_COLORS[it.stage_id] || '#888' },
      })),
      label: { show: true, position: 'right', color: '#525252', fontSize: 11 },
    }],
  }
})
const actionUsageHasData = computed(() => (playbook.value?.action_usage || []).length > 0)

const playbookCoverageRate = computed(() => {
  const cov = playbook.value?.stage_coverage || []
  if (!cov.length) return 0
  const sum = cov.reduce((acc, s) => acc + s.coverage_rate, 0)
  return sum / cov.length
})

// ============================================================
// 图 5: Persona 对比柱状
// ============================================================

const personaBarOption = computed(() => {
  const items = personaCmp.value?.items || []
  if (!items.length) return {}
  const labels = items.map((p) => p.persona_name)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        const i = params[0]?.dataIndex
        const it = items[i]
        if (!it) return ''
        return (
          `<b>${it.persona_name}</b><br/>`
          + `场次: ${it.sessions}<br/>`
          + `成交: ${it.deal_count} (${(it.deal_rate * 100).toFixed(1)}%)<br/>`
          + `平均质量: ${it.avg_quality ?? '—'}<br/>`
          + `平均轮数: ${it.avg_rounds}`
        )
      },
    },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#525252' } },
    grid: { left: 40, right: 16, top: 16, bottom: 60 },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: '#525252', fontSize: 11, interval: 0, rotate: labels.length > 5 ? 25 : 0 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
    },
    yAxis: [
      { type: 'value', name: '场次', max: Math.max(...items.map((p) => p.sessions)) + 1,
        axisLabel: { color: '#888888', fontSize: 11 },
        splitLine: { lineStyle: { color: '#ececec' } } },
      { type: 'value', name: '质量', min: 0, max: 10, position: 'right',
        axisLabel: { color: '#888888', fontSize: 11 },
        splitLine: { show: false } },
    ],
    series: [
      {
        name: '场次', type: 'bar', barWidth: 16, yAxisIndex: 0,
        data: items.map((p) => p.sessions),
        itemStyle: { color: '#d4d3cf' },
      },
      {
        name: '成交', type: 'bar', barWidth: 16, yAxisIndex: 0,
        data: items.map((p) => p.deal_count),
        itemStyle: { color: '#2d7a3e' },
      },
      {
        name: '平均质量', type: 'line', smooth: true, yAxisIndex: 1,
        data: items.map((p) => p.avg_quality ?? 0),
        itemStyle: { color: '#1a1a1a' },
        lineStyle: { color: '#1a1a1a', width: 2 },
        symbolSize: 5,
      },
    ],
  }
})
const personaBarHasData = computed(() => (personaCmp.value?.items || []).length > 0)

// ============================================================
// 图 6: 异议 Top-15 横向条形
// ============================================================

const objectionsBarOption = computed(() => {
  const items = (objections.value?.items || []).slice(0, 15)
  if (!items.length) return {}
  items.reverse() // 让排名 1 在最上
  return {
    tooltip: { trigger: 'item',
      formatter: (p: any) => {
        const it = items[p.dataIndex]
        return (
          `<b>${it.text}</b><br/>出现: ${it.count} 场<br/>`
          + `客户: ${it.personas.join(' · ') || '—'}`
        )
      },
    },
    grid: { left: 180, right: 32, top: 8, bottom: 8 },
    xAxis: { type: 'value', minInterval: 1,
             axisLabel: { color: '#888888', fontSize: 11 },
             splitLine: { lineStyle: { color: '#ececec' } } },
    yAxis: {
      type: 'category',
      data: items.map((it) => it.text.length > 22 ? it.text.slice(0, 22) + '…' : it.text),
      axisLabel: { color: '#525252', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
    },
    series: [{
      type: 'bar',
      barWidth: 14,
      data: items.map((it) => it.count),
      itemStyle: { color: '#9a6c1a' },
      label: { show: true, position: 'right', color: '#525252', fontSize: 11 },
    }],
  }
})
const objectionsHasData = computed(() => (objections.value?.items || []).length > 0)

// ============================================================
// 操作
// ============================================================

function gotoSessionDetail(sid: string): void {
  router.push(`/simulation/detail/${sid}`)
}

onMounted(async () => {
  await loadBatches()
  if (selectedId.value != null) await loadReport()
})
</script>

<template>
  <div class="page">
    <DmPageHeader
      title="批量报告"
      subtitle="某次批量测试的全维度复盘 · 6+ 图表 · 一键导出销冠 Training Guide"
    >
      <template #actions>
        <ElButton @click="loadReport" :loading="loading">
          <template #icon><RefreshCcw :size="14" :stroke-width="1.6" /></template>
          刷新
        </ElButton>
        <ElButton
          type="primary"
          :disabled="!overview"
          @click="downloadTrainingGuide"
        >
          <template #icon><FileText :size="14" :stroke-width="1.6" /></template>
          导出 Training Guide
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 批量任务选择 -->
    <section class="selector-bar">
      <span class="dm-text-small dm-text-muted">批量任务：</span>
      <ElSelect
        v-model="selectedId"
        placeholder="选择已完成的批量任务"
        filterable
        clearable
        class="batch-select"
      >
        <ElOption
          v-for="b in batches"
          :key="b.id"
          :label="`#${b.id} · ${b.name}  ·  ${b.status} · ${b.completed_count}/${b.total_count}`"
          :value="b.id"
        />
      </ElSelect>
      <span v-if="overview" class="dm-text-small dm-text-muted spacer-right">
        {{ overview.completed_count }} 成功 · {{ overview.failed_count }} 失败 ·
        {{ overview.cancelled_count }} 中断 · 总耗时 {{ overview.duration_sec.toFixed(0) }}s
      </span>
    </section>

    <!-- 没选 batch -->
    <ElEmpty
      v-if="!selectedId"
      description="请在上面选择一个批量任务"
      :image-size="120"
    />

    <template v-else>
      <!-- 4 数字卡 -->
      <section class="stat-grid">
        <div v-for="s in stats" :key="s.label" class="stat-card">
          <div class="stat-label dm-text-overline">{{ s.label }}</div>
          <div class="stat-value dm-text-number-xl">{{ s.value }}</div>
          <div class="stat-hint dm-text-small">{{ s.hint }}</div>
        </div>
      </section>

      <!-- 中段图：3 列布局 -->
      <section class="chart-grid-3">
        <div class="card chart-card">
          <div class="chart-head"><h3 class="dm-text-h3">Outcome 分布</h3></div>
          <div class="chart-body">
            <ElEmpty v-if="!outcomeHasData" description="无数据" :image-size="60" />
            <v-chart v-else :option="outcomeOption" autoresize class="echart" />
          </div>
        </div>

        <div class="card chart-card">
          <div class="chart-head"><h3 class="dm-text-h3">销冠五维雷达</h3></div>
          <div class="chart-body">
            <ElEmpty v-if="!radarHasData" description="无 Judge 评分" :image-size="60" />
            <v-chart v-else :option="radarOption" autoresize class="echart" />
          </div>
        </div>

        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">每场质量分</h3>
            <span class="dm-text-small dm-text-muted">
              共 {{ radar?.per_session?.length || 0 }} 场
            </span>
          </div>
          <div class="chart-body">
            <ElEmpty v-if="!qualityLineHasData" description="无数据" :image-size="60" />
            <v-chart v-else :option="qualityLineOption" autoresize class="echart" />
          </div>
        </div>
      </section>

      <!-- RAG 漏斗 + chunks 柱：两列 -->
      <section class="chart-grid-2">
        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">RAG 使用率</h3>
            <span v-if="rag" class="dm-text-small dm-text-muted">
              命中率 {{ (rag.hit_rate * 100).toFixed(1) }}%
            </span>
          </div>
          <div class="chart-body">
            <ElEmpty v-if="!ragHasData" description="无销冠 turns" :image-size="60" />
            <v-chart v-else :option="ragPieOption" autoresize class="echart" />
          </div>
        </div>

        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">RAG Chunks 总量</h3>
            <span v-if="rag" class="dm-text-small dm-text-muted">
              平均 {{ rag.avg_chunks_per_turn.toFixed(2) }} chunks/轮
            </span>
          </div>
          <div class="chart-body">
            <ElEmpty v-if="!ragHasData" description="无销冠 turns" :image-size="60" />
            <v-chart v-else :option="ragBarOption" autoresize class="echart" />
          </div>
        </div>
      </section>

      <!-- business_stages v0.2：阶段配比 + 剧本动作覆盖率 -->
      <section class="chart-grid-2">
        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">5 阶段配比偏离</h3>
            <span v-if="playbook" class="dm-text-small dm-text-muted">
              实际 vs YAML 期望权重 · ⚠ 表示超阈值
            </span>
          </div>
          <div class="chart-body">
            <ElEmpty v-if="!stageBalanceHasData" description="销冠未输出阶段数据" :image-size="60" />
            <v-chart v-else :option="stageBalanceOption" autoresize class="echart" />
          </div>
        </div>

        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">剧本动作命中 Top-22</h3>
            <span v-if="playbook" class="dm-text-small dm-text-muted">
              平均覆盖 {{ (playbookCoverageRate * 100).toFixed(0) }}% ·
              {{ playbook.with_playbook }}/{{ playbook.total_sales_turns }} 轮已自报
            </span>
          </div>
          <div class="chart-body chart-body-tall">
            <ElEmpty v-if="!actionUsageHasData" description="销冠未自报任何 playbook_action" :image-size="60" />
            <v-chart v-else :option="actionUsageOption" autoresize class="echart" />
          </div>
        </div>
      </section>

      <!-- 剧本覆盖率明细表（哪些 action 漏掉了） -->
      <section v-if="playbook && playbook.stage_coverage.length" class="card">
        <div class="chart-head">
          <h4 class="dm-text-h4">各阶段剧本覆盖率明细</h4>
          <span class="dm-text-small dm-text-muted">
            根据 prompts/business_stages.yaml 的 allowed_playbook_actions 比对
          </span>
        </div>
        <ElTable :data="playbook.stage_coverage" size="small" stripe>
          <ElTableColumn label="阶段" width="180">
            <template #default="{ row }">
              <ElTag size="small" effect="plain" round
                     :style="{ borderColor: STAGE_COLORS[row.stage_id], color: STAGE_COLORS[row.stage_id] }">
                {{ row.stage_id }}
              </ElTag>
              <span class="stage-cell-cn">{{ row.stage_cn }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="覆盖率" width="110" align="right">
            <template #default="{ row }">
              {{ (row.coverage_rate * 100).toFixed(0) }}%
            </template>
          </ElTableColumn>
          <ElTableColumn label="已使用" min-width="240">
            <template #default="{ row }">
              <ElTag v-for="a in row.used" :key="a" size="small" effect="plain" type="success" class="action-chip">
                {{ a }}
              </ElTag>
              <span v-if="!row.used.length" class="dm-text-small dm-text-muted">（无）</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="漏掉" min-width="240">
            <template #default="{ row }">
              <ElTag v-for="a in row.missed" :key="a" size="small" effect="plain" type="danger" class="action-chip">
                {{ a }}
              </ElTag>
              <span v-if="!row.missed.length" class="dm-text-small dm-text-muted">（全覆盖 ✓）</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </section>

      <!-- Persona 对比 -->
      <section class="card chart-card chart-persona">
        <div class="chart-head">
          <h3 class="dm-text-h3">Persona 表现对比</h3>
          <span class="dm-text-small dm-text-muted">
            按 deal_rate ↓ / quality ↓ 排序
          </span>
        </div>
        <div class="chart-body chart-body-tall">
          <ElEmpty v-if="!personaBarHasData" description="无 persona 关联" :image-size="60" />
          <v-chart v-else :option="personaBarOption" autoresize class="echart" />
        </div>
      </section>

      <!-- Persona 详情表 -->
      <section v-if="personaBarHasData" class="card">
        <div class="chart-head"><h4 class="dm-text-h4">Persona 表现明细</h4></div>
        <ElTable :data="personaCmp?.items || []" size="small" stripe>
          <ElTableColumn label="客户" min-width="180">
            <template #default="{ row }">
              <div class="persona-cell">
                <PersonaAvatar
                  :avatar-key="row.persona_avatar_key"
                  :name="row.persona_name"
                  :size="26"
                />
                <span class="persona-cell-name">{{ row.persona_name }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="标签" min-width="200">
            <template #default="{ row }">
              <ElTag v-for="t in row.tags?.slice(0, 3)" :key="t" size="small" effect="plain" class="tag-chip">
                {{ t }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="场次" width="70" align="right" prop="sessions" />
          <ElTableColumn label="成交" width="70" align="right" prop="deal_count" />
          <ElTableColumn label="成交率" width="90" align="right">
            <template #default="{ row }">{{ (row.deal_rate * 100).toFixed(1) }}%</template>
          </ElTableColumn>
          <ElTableColumn label="平均质量" width="100" align="right">
            <template #default="{ row }">{{ row.avg_quality ?? '—' }}</template>
          </ElTableColumn>
          <ElTableColumn label="平均轮数" width="100" align="right" prop="avg_rounds" />
          <ElTableColumn label="进入复盘" width="120" align="right">
            <template #default="{ row }">
              <ElButton
                v-if="row.session_ids?.[0]"
                size="small"
                text
                @click="gotoSessionDetail(row.session_ids[0])"
              >
                看 #1 场
              </ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
      </section>

      <!-- 异议排行 + 详情表 -->
      <section class="chart-grid-2">
        <div class="card chart-card">
          <div class="chart-head">
            <h3 class="dm-text-h3">高频异议 Top-15</h3>
            <span v-if="objections" class="dm-text-small dm-text-muted">
              总沉淀 {{ objections.total_unique }} 类 · {{ objections.total_records }} 条记录
            </span>
          </div>
          <div class="chart-body chart-body-tall">
            <ElEmpty v-if="!objectionsHasData" description="无异议数据" :image-size="60" />
            <v-chart v-else :option="objectionsBarOption" autoresize class="echart" />
          </div>
        </div>

        <div class="card chart-card">
          <div class="chart-head"><h3 class="dm-text-h3">异议详情</h3></div>
          <div class="obj-table-wrap">
            <ElEmpty v-if="!objectionsHasData" description="无异议" :image-size="60" />
            <ElTable v-else :data="objections?.items || []" size="small" stripe max-height="420">
              <ElTableColumn label="#" width="48" align="right">
                <template #default="{ $index }">{{ $index + 1 }}</template>
              </ElTableColumn>
              <ElTableColumn label="异议内容" min-width="240" show-overflow-tooltip>
                <template #default="{ row }">{{ row.text }}</template>
              </ElTableColumn>
              <ElTableColumn label="次数" width="70" align="right" prop="count" />
              <ElTableColumn label="客户" min-width="160">
                <template #default="{ row }">
                  <ElTooltip
                    v-if="row.personas?.length"
                    :content="row.personas.join(' · ')"
                    placement="top"
                  >
                    <span class="ellipsis">{{ row.personas.join(' · ') }}</span>
                  </ElTooltip>
                  <span v-else class="dm-text-muted">—</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="进入" width="80" align="right">
                <template #default="{ row }">
                  <ElButton
                    v-if="row.session_ids?.[0]"
                    size="small"
                    text
                    @click="gotoSessionDetail(row.session_ids[0])"
                  >
                    看
                  </ElButton>
                </template>
              </ElTableColumn>
            </ElTable>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped lang="scss">
.page {
  padding: var(--dm-space-7);
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-5);
}
.selector-bar {
  display: flex;
  align-items: center;
  gap: var(--dm-space-3);
}
.batch-select { width: 460px; }
.spacer-right { margin-left: auto; }

/* 数字卡 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--dm-space-4);
}
@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
}
.stat-card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-md);
  padding: var(--dm-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-2);
}
.stat-label { color: var(--dm-text-muted); }
.stat-value { color: var(--dm-text); }
.stat-hint  { color: var(--dm-text-disabled); }

/* 卡通用 */
.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-md);
}
.chart-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.chart-head {
  display: flex;
  align-items: center;
  gap: var(--dm-space-3);
  padding: var(--dm-space-4) var(--dm-space-5) 0;
  h3, h4 { margin: 0; flex: 1; }
}
.chart-body {
  flex: 1;
  padding: var(--dm-space-3);
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.chart-body-tall { min-height: 380px; }
.echart {
  width: 100%;
  height: 100%;
  min-height: 260px;
}

/* 网格 */
.chart-grid-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: var(--dm-space-4);
}
@media (max-width: 1100px) {
  .chart-grid-3 { grid-template-columns: 1fr; }
}
.chart-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--dm-space-4);
}
@media (max-width: 1100px) {
  .chart-grid-2 { grid-template-columns: 1fr; }
}
.chart-persona { min-height: 400px; }

/* 异议详情表 */
.obj-table-wrap {
  padding: var(--dm-space-2);
}
.tag-chip { margin-right: 4px; }

/* business_stages v0.2：playbook 区块 */
.action-chip {
  margin-right: 4px;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}
.stage-cell-cn {
  margin-left: 8px;
  font-size: 13px;
  color: var(--dm-text);
}
.ellipsis {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  display: inline-block; max-width: 100%;
}

/* el-table 风格统一 */
:deep(.el-table) {
  font-size: var(--dm-fs-body);
  background: transparent;
}
:deep(.el-table th.el-table__cell) {
  background: var(--dm-bg-elevated);
  color: var(--dm-text-muted);
  font-weight: var(--dm-fw-medium);
  font-size: var(--dm-fs-small);
}

.persona-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.persona-cell-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
