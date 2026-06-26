<script setup lang="ts">
/**
 * 首页总览 · 数据看板（Stage 8）
 *
 * 布局：
 *   顶部 4 张大数字卡（el-statistic 风格）：总会话数 / Persona 总数 / 平均质量分 / 成交率
 *   中部 2 张图：
 *     - 30 天会话量 + 平均质量分 双轴折线
 *     - outcome 分布饼图
 *   下部 1 张图：
 *     - Persona 难度横向条形（按 avg_quality 升序，最难的客户在最上）
 *
 * 空数据走 el-empty 占位，不爆错。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElEmpty,
  ElMessage,
  ElTag,
} from 'element-plus'
import {
  RefreshCcw,
  ArrowRightFromLine,
  Activity,
  Users,
  Gauge,
  Trophy,
} from '@lucide/vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  dashboardApi,
  type DashboardSummary,
  type DashboardTrends,
  type DashboardInsights,
  type PersonaDifficultyItem,
} from '@/api/dashboard'

use([
  CanvasRenderer,
  BarChart, LineChart, PieChart, ScatterChart,
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, DataZoomComponent,
])

const router = useRouter()

const loading = ref(false)
const summary = ref<DashboardSummary | null>(null)
const trends = ref<DashboardTrends | null>(null)
const insights = ref<DashboardInsights | null>(null)
const persona = ref<PersonaDifficultyItem[]>([])

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [s, t, ins, p] = await Promise.all([
      dashboardApi.summary(),
      dashboardApi.trends(30),
      dashboardApi.insights(60),
      dashboardApi.personaDifficulty(15),
    ])
    summary.value = s
    trends.value = t
    insights.value = ins
    persona.value = p.items
  } catch (e: any) {
    ElMessage.error('看板加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

// 裁掉首尾空值日，保留中间断点（折线 connectNulls 连接）
function trimSeries(
  days: string[],
  values: (number | null)[],
): { days: string[]; values: (number | null)[] } {
  let lo = 0
  let hi = values.length - 1
  while (lo <= hi && values[lo] === null) lo++
  while (hi >= lo && values[hi] === null) hi--
  if (lo > hi) return { days: [], values: [] }
  return { days: days.slice(lo, hi + 1), values: values.slice(lo, hi + 1) }
}

// ============================================================
// 4 大卡片
// ============================================================
const stats = computed(() => {
  const s = summary.value
  return [
    {
      key: 'sessions',
      label: '总会话数',
      value: s ? s.total_sessions : '—',
      hint: s
        ? `${s.finished_count} 场已结束`
        : '尚无数据',
      icon: Activity,
    },
    {
      key: 'personas',
      label: 'Persona 总数',
      value: s ? s.total_personas : '—',
      hint: '已入库人设',
      icon: Users,
    },
    {
      key: 'quality',
      label: '平均质量分',
      value: s ? s.avg_quality.toFixed(2) : '—',
      hint: 'Judge 五维加权（0~10）',
      icon: Gauge,
    },
    {
      key: 'deal',
      label: '成交率',
      value: s ? `${(s.deal_rate * 100).toFixed(1)}%` : '—',
      hint: s
        ? `${s.deal_count}/${s.finished_count || '—'}`
        : '尚无数据',
      icon: Trophy,
    },
  ]
})

// ============================================================
// 趋势折线（双轴：左=会话数，右=平均质量）
// ============================================================
const trendsHasData = computed(() => {
  const t = trends.value
  if (!t) return false
  return t.sessions.some((n) => n > 0) || t.quality.some((q) => q > 0)
})

const trendOption = computed(() => {
  const t = trends.value
  if (!t) return {}
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['会话数', '平均质量'],
      bottom: 0,
      textStyle: { color: '#525252', fontSize: 12 },
    },
    grid: { left: 48, right: 56, top: 24, bottom: 36 },
    xAxis: {
      type: 'category',
      data: t.days.map((d) => d.slice(5)), // MM-DD 更简洁
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
      boundaryGap: false,
    },
    yAxis: [
      {
        type: 'value',
        name: '会话数',
        nameTextStyle: { color: '#888888', fontSize: 11 },
        min: 0,
        splitLine: { lineStyle: { color: '#ececec' } },
        axisLabel: { color: '#888888', fontSize: 11 },
      },
      {
        type: 'value',
        name: '平均质量',
        nameTextStyle: { color: '#888888', fontSize: 11 },
        min: 0,
        max: 10,
        splitLine: { show: false },
        axisLabel: { color: '#888888', fontSize: 11 },
      },
    ],
    series: [
      {
        name: '会话数',
        type: 'line',
        smooth: true,
        data: t.sessions,
        yAxisIndex: 0,
        itemStyle: { color: '#1a1a1a' },
        lineStyle: { color: '#1a1a1a', width: 2 },
        areaStyle: { color: 'rgba(26, 26, 26, 0.06)' },
        symbolSize: 4,
      },
      {
        name: '平均质量',
        type: 'line',
        smooth: true,
        data: t.quality,
        yAxisIndex: 1,
        itemStyle: { color: '#9a6c1a' },
        lineStyle: { color: '#9a6c1a', width: 2, type: 'dashed' },
        symbolSize: 4,
      },
    ],
  }
})

// ============================================================
// outcome 分布饼图
// ============================================================
const OUTCOME_COLORS: Record<string, string> = {
  DEAL_DONE: '#2d7a3e',
  WALK_AWAY: '#9a6c1a',
  COMPLAINT: '#9b2c2c',
  TIMEOUT:   '#888888',
  CANCELLED: '#bfbfbf',
  CONTINUE:  '#1e5fa8',
  UNKNOWN:   '#d4d3cf',
}

const outcomeHasData = computed(() =>
  !!summary.value && summary.value.outcome_dist.length > 0,
)

const outcomeOption = computed(() => {
  const dist = summary.value?.outcome_dist || []
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: {
      orient: 'vertical',
      right: 16,
      top: 'middle',
      textStyle: { color: '#525252', fontSize: 12 },
    },
    series: [
      {
        type: 'pie',
        radius: ['46%', '72%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: { show: false },
        labelLine: { show: false },
        data: dist.map((d) => ({
          name: d.outcome,
          value: d.count,
          itemStyle: { color: OUTCOME_COLORS[d.outcome] || '#888888' },
        })),
      },
    ],
  }
})

// ============================================================
// Persona 难度横向条形
// ============================================================
const personaHasData = computed(() => persona.value.length > 0)

const personaOption = computed(() => {
  const items = [...persona.value].filter(
    (p) => p.avg_quality !== null,
  )
  // ECharts category 轴：上到下 = 数组末到首；我们要"最难"在上，
  // 所以 reverse 排序后再喂数据
  items.reverse()
  const names = items.map((p) => p.persona_name)
  const data = items.map((p) => ({
    value: p.avg_quality ?? 0,
    persona: p,
    itemStyle: {
      color: (p.avg_quality ?? 10) < 5
        ? '#9b2c2c'
        : (p.avg_quality ?? 10) < 7
          ? '#9a6c1a'
          : '#2d7a3e',
    },
  }))
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const it: PersonaDifficultyItem = p.data.persona
        return (
          `<b>${it.persona_name}</b><br/>` +
          `平均质量: ${it.avg_quality ?? '—'}<br/>` +
          `会话数: ${it.sessions}<br/>` +
          `成交: ${it.deal_count}/${it.sessions}` +
          (it.tags?.length ? `<br/>标签: ${it.tags.slice(0, 3).join(' · ')}` : '')
        )
      },
    },
    grid: { left: 140, right: 32, top: 16, bottom: 16 },
    xAxis: {
      type: 'value',
      min: 0,
      max: 10,
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#525252', fontSize: 12 },
    },
    series: [
      {
        type: 'bar',
        data,
        barWidth: 14,
        label: {
          show: true,
          position: 'right',
          color: '#525252',
          fontSize: 11,
          formatter: (p: any) => `${(p.value as number).toFixed(2)}`,
        },
      },
    ],
  }
})

// ============================================================
// 经验库增长与成交率关系（散点 + 线性趋势）
// ============================================================
const experienceHasData = computed(
  () => (insights.value?.experience_vs_deal.points.length ?? 0) >= 2,
)

const experienceOption = computed(() => {
  const evd = insights.value?.experience_vs_deal
  if (!evd) return {}
  const points = evd.points.map((p) => [p.size, +(p.deal_rate * 100).toFixed(1), p.day])
  const trend = evd.trend
  const series: any[] = [
    {
      name: '每日',
      type: 'scatter',
      data: points,
      symbolSize: 10,
      itemStyle: { color: '#1a1a1a', opacity: 0.78 },
    },
  ]
  if (trend) {
    series.push({
      name: '趋势',
      type: 'line',
      data: [
        [trend.x_min, +(trend.y_at_min * 100).toFixed(1)],
        [trend.x_max, +(trend.y_at_max * 100).toFixed(1)],
      ],
      showSymbol: false,
      lineStyle: { color: '#888888', width: 1.5, type: 'dashed' },
      tooltip: { show: false },
      silent: true,
      z: 1,
    })
  }
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (p.seriesName === '趋势') return ''
        const [size, rate, day] = p.data
        return `${day}<br/>经验库规模: <b>${size}</b><br/>成交率: <b>${rate}%</b>`
      },
    },
    grid: { left: 48, right: 24, top: 24, bottom: 44 },
    xAxis: {
      type: 'value',
      name: '经验库规模',
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: '#888888', fontSize: 11 },
      min: 0,
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: '成交率',
      min: 0,
      max: 100,
      nameTextStyle: { color: '#888888', fontSize: 11 },
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLabel: { color: '#888888', fontSize: 11, formatter: '{value}%' },
    },
    series,
  }
})

// ============================================================
// 常见异议排行（横向条形，取 Top5）
// ============================================================
const objectionHasData = computed(
  () => (insights.value?.objections.length ?? 0) > 0,
)

const objectionOption = computed(() => {
  const items = (insights.value?.objections ?? []).slice(0, 5)
  // 横向条形：ECharts 自下而上，反转使占比最高在最上
  const rev = [...items].reverse()
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) =>
        `${p.name}<br/>占比: <b>${p.value}%</b><br/>出现次数: ${p.data.count}`,
    },
    grid: { left: 120, right: 56, top: 12, bottom: 24 },
    xAxis: {
      type: 'value',
      min: 0,
      axisLabel: { color: '#888888', fontSize: 11, formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#ececec' } },
    },
    yAxis: {
      type: 'category',
      data: rev.map((o) => o.label),
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisTick: { show: false },
      axisLabel: { color: '#525252', fontSize: 12 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 12,
        data: rev.map((o) => ({
          value: +(o.pct * 100).toFixed(1),
          count: o.count,
        })),
        itemStyle: { color: '#1a1a1a', borderRadius: [0, 6, 6, 0] },
        label: {
          show: true,
          position: 'right',
          color: '#525252',
          fontSize: 11,
          formatter: '{c}%',
        },
      },
    ],
  }
})

// ============================================================
// 成交率趋势（折线，%）
// ============================================================
const dealTrendData = computed(() => {
  const t = insights.value?.deal_trend
  if (!t) return { days: [] as string[], values: [] as (number | null)[] }
  return trimSeries(t.days, t.deal_rate)
})
const dealTrendHasData = computed(() =>
  dealTrendData.value.values.some((v) => v !== null),
)
const dealTrendOption = computed(() =>
  pctLineOption(dealTrendData.value.days, dealTrendData.value.values, '成交率', '#1a1a1a'),
)

// ============================================================
// 经验库命中率（折线，%）
// ============================================================
const hitRateData = computed(() => {
  const h = insights.value?.hit_rate
  if (!h) return { days: [] as string[], values: [] as (number | null)[] }
  return trimSeries(h.days, h.rate)
})
const hitRateHasData = computed(() =>
  hitRateData.value.values.some((v) => v !== null),
)
const hitRateOption = computed(() =>
  pctLineOption(hitRateData.value.days, hitRateData.value.values, '命中率', '#2d7a3e'),
)

function pctLineOption(
  days: string[],
  values: (number | null)[],
  name: string,
  color: string,
) {
  const data = values.map((v) => (v === null ? null : +(v * 100).toFixed(1)))
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: any) => (v == null ? '—' : `${v}%`),
    },
    grid: { left: 48, right: 24, top: 20, bottom: 28 },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.slice(5)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: '#ececec' } },
      axisLabel: { color: '#888888', fontSize: 11, formatter: '{value}%' },
    },
    series: [
      {
        name,
        type: 'line',
        smooth: true,
        connectNulls: true,
        data,
        symbolSize: 5,
        itemStyle: { color },
        lineStyle: { color, width: 2 },
        areaStyle: { color: 'rgba(26, 26, 26, 0.05)' },
      },
    ],
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="dashboard">
    <DmPageHeader
      title="首页总览"
      subtitle="销冠模拟系统的实时运营指标 · 全部数据来自已落库会话"
    >
      <template #actions>
        <ElButton @click="loadAll" :loading="loading">
          <template #icon><RefreshCcw :size="14" :stroke-width="1.6" /></template>
          刷新
        </ElButton>
        <ElButton type="primary" @click="router.push('/simulation/new')">
          <template #icon><ArrowRightFromLine :size="14" :stroke-width="1.6" /></template>
          新建对话
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- ============ 4 大数字卡 ============ -->
    <section class="stat-grid">
      <div
        v-for="s in stats"
        :key="s.key"
        class="stat-card"
      >
        <div class="stat-head">
          <component :is="s.icon" :size="16" :stroke-width="1.6" class="stat-icon" />
          <span class="stat-label dm-text-overline">{{ s.label }}</span>
        </div>
        <div class="stat-value dm-text-number-xl">{{ s.value }}</div>
        <div class="stat-hint dm-text-small">{{ s.hint }}</div>
      </div>
    </section>

    <!-- ============ 中部 2 图 ============ -->
    <section class="chart-row-2">
      <div class="card chart-card chart-trend">
        <div class="chart-head">
          <h3 class="dm-text-h3">近 30 天会话量 / 质量趋势</h3>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!trendsHasData"
            description="过去 30 天还没有数据，去跑一场试试"
            :image-size="80"
          />
          <v-chart v-else :option="trendOption" autoresize class="echart" />
        </div>
      </div>

      <div class="card chart-card chart-outcome">
        <div class="chart-head">
          <h3 class="dm-text-h3">Outcome 分布</h3>
          <ElTag
            v-if="summary"
            size="small"
            effect="plain"
          >
            共 {{ summary.finished_count }} 场已结束
          </ElTag>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!outcomeHasData"
            description="还没有可统计的 outcome"
            :image-size="80"
          />
          <v-chart v-else :option="outcomeOption" autoresize class="echart" />
        </div>
      </div>
    </section>

    <!-- ============ 底部 Persona 难度 ============ -->
    <section class="card chart-card chart-persona">
      <div class="chart-head">
        <h3 class="dm-text-h3">Persona 难度排行</h3>
        <span class="dm-text-small dm-text-muted">
          按平均质量分升序 · 越低代表客户越难搞 · 最多 15 条
        </span>
      </div>
      <div class="chart-body chart-body-tall">
        <ElEmpty
          v-if="!personaHasData"
          description="还没有可用 persona 评分数据"
          :image-size="80"
        />
        <v-chart v-else :option="personaOption" autoresize class="echart" />
      </div>
    </section>

    <!-- ============ 运营分析：经验库 × 成交 / 异议 ============ -->
    <section class="chart-row-2 chart-row-even">
      <div class="card chart-card">
        <div class="chart-head">
          <h3 class="dm-text-h3">经验库增长与成交率关系</h3>
          <span class="dm-text-small dm-text-muted">每点 = 一天 · 横轴累计经验库条数 · 虚线为趋势</span>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!experienceHasData"
            description="经验库与成交样本不足"
            :image-size="80"
          />
          <v-chart v-else :option="experienceOption" autoresize class="echart" />
        </div>
      </div>

      <div class="card chart-card">
        <div class="chart-head">
          <h3 class="dm-text-h3">常见异议排行</h3>
          <span class="dm-text-small dm-text-muted">按客户意图占比 · Top5</span>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!objectionHasData"
            description="还没有可统计的客户异议"
            :image-size="80"
          />
          <v-chart v-else :option="objectionOption" autoresize class="echart" />
        </div>
      </div>
    </section>

    <!-- ============ 运营分析：成交率趋势 / 命中率 ============ -->
    <section class="chart-row-2 chart-row-even">
      <div class="card chart-card">
        <div class="chart-head">
          <h3 class="dm-text-h3">成交率趋势</h3>
          <span class="dm-text-small dm-text-muted">按日 · 当日成交 / 有结论会话</span>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!dealTrendHasData"
            description="还没有成交趋势数据"
            :image-size="80"
          />
          <v-chart v-else :option="dealTrendOption" autoresize class="echart" />
        </div>
      </div>

      <div class="card chart-card">
        <div class="chart-head">
          <h3 class="dm-text-h3">经验库命中率</h3>
          <span class="dm-text-small dm-text-muted">按日 · 销售话术被知识/经验库检索命中占比</span>
        </div>
        <div class="chart-body">
          <ElEmpty
            v-if="!hitRateHasData"
            description="还没有命中率数据"
            :image-size="80"
          />
          <v-chart v-else :option="hitRateOption" autoresize class="echart" />
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.dashboard {
  padding: var(--dm-space-7);
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-5);
  min-height: 100%;
}

/* ===== 4 大数字卡 ===== */
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
  padding: var(--dm-space-5) var(--dm-space-6);
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-2);
  transition: border-color var(--dm-transition);

  &:hover { border-color: var(--dm-border-strong); }
}
.stat-head {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
}
.stat-icon { color: var(--dm-text-muted); }
.stat-label { color: var(--dm-text-muted); }
.stat-value { color: var(--dm-text); }
.stat-hint { color: var(--dm-text-disabled); }

/* ===== 通用 chart card ===== */
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

  h3 { margin: 0; flex: 1; }
}
.chart-body {
  flex: 1;
  padding: var(--dm-space-3) var(--dm-space-2);
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.chart-body-tall { min-height: 440px; }
.echart {
  width: 100%;
  height: 100%;
  min-height: 280px;
}

/* ===== 中部 2 图 ===== */
.chart-row-2 {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--dm-space-4);
}
@media (max-width: 1100px) {
  .chart-row-2 { grid-template-columns: 1fr; }
}
.chart-row-even { grid-template-columns: 1fr 1fr; }
@media (max-width: 1100px) {
  .chart-row-even { grid-template-columns: 1fr; }
}
.chart-row-even .chart-card { min-height: 340px; }
.chart-trend { min-height: 340px; }
.chart-outcome { min-height: 340px; }
</style>
