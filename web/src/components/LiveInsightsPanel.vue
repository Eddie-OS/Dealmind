<script setup lang="ts">
/**
 * 对话现场 · 右栏实时洞察面板
 *
 * 四张堆叠卡片（全部基于真实落库 / 推流数据）：
 *   1. 产品知识命中  ← ragHitsByTurn[].product（产品知识库 RAG 命中）
 *   2. 销售经验命中  ← ragHitsByTurn[].enterprise（企业知识库 = 销售方法论/经验）
 *   3. 当前会话画像  ← sessionMemory + persona
 *   4. Judge 下一步指令 ← judgeFeedback
 *
 * 设计：Notion 黑白调，环形图主色 = 深灰，未命中 = 浅灰。
 */
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ArrowRight, RefreshCcw } from '@lucide/vue'
import type { RagHit, RagHitsForTurn } from '@/stores/liveSession'
import type { Persona } from '@/api/personas'

use([CanvasRenderer, PieChart, TooltipComponent])

const props = defineProps<{
  sessionMemory: Record<string, any> | null
  judgeFeedback: Record<string, any> | null
  ragHitsByTurn: RagHitsForTurn[]
  persona: Persona | null
}>()

// ============================================================
// 命中聚合（产品 / 销售经验各一份）
// ============================================================
const KEY_HIT_THRESHOLD = 0.5

interface HitStat {
  hitRate: number      // 0~1：命中该轴的 sales 轮占比
  total: number        // 命中条数（chunk 总数）
  key: number          // 关键命中（score >= 阈值）
  partial: number      // 部分命中（score < 阈值 / 无 score）
  miss: number         // 未命中轮数
  rounds: number       // 总检索轮数
  top: { label: string; full: string; count: number }[]
}

/** 取单条命中的"具体条目内容"片段：用切片正文(text)，去掉开头 "Slide 3:/Page 12" 之类来源前缀，折叠空白。 */
function hitContent(h: RagHit): string {
  const raw = (h.text || '').replace(/\s+/g, ' ').trim()
  const cleaned = raw
    .replace(/^(?:slide|page|paragraph|幻灯片|页|第)\s*\d+\s*[:：.、)\-]*\s*/i, '')
    .trim()
  return cleaned || raw
}

function aggregate(axis: 'product' | 'enterprise'): HitStat {
  const groups = props.ragHitsByTurn
  const rounds = groups.length
  let withHit = 0
  let total = 0
  let key = 0
  let partial = 0
  const freq = new Map<string, { full: string; count: number }>()
  for (const g of groups) {
    const hits: RagHit[] = (g[axis] || []) as RagHit[]
    if (hits.length > 0) withHit += 1
    for (const h of hits) {
      total += 1
      const s = typeof h.score === 'number' ? h.score : null
      if (s !== null && s >= KEY_HIT_THRESHOLD) key += 1
      else partial += 1
      const full =
        hitContent(h) ||
        (h.section && h.section.trim()) ||
        (h.filename && h.filename.trim()) ||
        '未知片段'
      // 同一条 chunk（按 id，缺失则按内容）跨轮去重，累计命中次数
      const dedupeKey = (h.id && String(h.id)) || full
      const cur = freq.get(dedupeKey) || { full, count: 0 }
      cur.count += 1
      freq.set(dedupeKey, cur)
    }
  }
  const top = [...freq.values()]
    .sort((a, b) => b.count - a.count)
    .slice(0, 4)
    .map(({ full, count }) => ({
      label: full.length > 48 ? full.slice(0, 48) + '…' : full,
      full,
      count,
    }))
  return {
    hitRate: rounds > 0 ? withHit / rounds : 0,
    total,
    key,
    partial,
    miss: Math.max(0, rounds - withHit),
    rounds,
    top,
  }
}

const productStat = computed(() => aggregate('product'))
const experienceStat = computed(() => aggregate('enterprise'))

function donutOption(stat: HitStat, color: string) {
  const pct = Math.round(stat.hitRate * 100)
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [
      {
        type: 'pie',
        radius: ['76%', '94%'],
        center: ['50%', '50%'],
        silent: false,
        label: { show: false },
        labelLine: { show: false },
        data: [
          { value: pct, name: '命中', itemStyle: { color, borderRadius: 4 } },
          { value: 100 - pct, name: '未命中', itemStyle: { color: '#eceae5' } },
        ],
      },
    ],
  }
}

const productDonut = computed(() => donutOption(productStat.value, '#1a1a1a'))
const experienceDonut = computed(() => donutOption(experienceStat.value, '#1a1a1a'))

// ============================================================
// 当前会话画像
// ============================================================
function asText(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (Array.isArray(v)) return v.filter(Boolean).join('、')
  return String(v).trim()
}

const decisionRole = computed(() => {
  const p = props.persona
  return (
    asText(p?.profile?.occupation) ||
    asText(p?.profile?.purchase_goal) ||
    asText(p?.name) ||
    '—'
  )
})

const profileRows = computed(() => {
  const m = props.sessionMemory || {}
  const p = props.persona
  // 成交阻力：用人设砍价强度 / 价格敏感度估个高/中/低
  const resistanceVal = Math.max(
    p?.pressure?.price_sensitivity ?? 0,
    p?.pressure?.bargaining_aggressiveness ?? 0,
  )
  return [
    { label: '决策角色', value: decisionRole.value },
    { label: '核心关注', value: asText(m.current_need) || '—' },
    {
      label: '决策风格',
      value: asText(p?.profile?.objection_style) || asText(p?.profile?.personality) || '—',
    },
    { label: '压力来源', value: asText(m.main_objections) || '—' },
    { label: '成交阻力', value: levelLabel(resistanceVal) },
    { label: '情绪状态', value: asText(m.emotional_state) || '—' },
  ]
})

function levelLabel(v: number): string {
  if (!v) return '—'
  if (v >= 0.66) return '高'
  if (v >= 0.33) return '中'
  return '低'
}

// ============================================================
// Judge 下一步指令
// ============================================================
const judge = computed(() => {
  const j = props.judgeFeedback || {}
  return {
    has: !!props.judgeFeedback,
    goal: j.sales_instruction || '',
    persona: j.persona_instruction || '',
    reason: j.reason || '',
    quality:
      typeof j.dialogue_quality_score === 'number'
        ? j.dialogue_quality_score.toFixed(1)
        : '—',
    endStatus: j.end_status || 'CONTINUE',
  }
})
</script>

<template>
  <div class="insights-pro">
    <!-- ============ 产品知识命中 ============ -->
    <section class="card hit-card">
      <div class="card-head">
        <h3 class="dm-text-h3">产品知识命中</h3>
        <span class="view-all">查看全部 <ArrowRight :size="12" :stroke-width="1.8" /></span>
      </div>
      <div class="hit-body">
        <div class="donut-wrap">
          <v-chart :option="productDonut" autoresize class="donut" />
          <div class="donut-center">
            <span class="donut-pct">{{ Math.round(productStat.hitRate * 100) }}%</span>
            <span class="donut-cap">命中率</span>
          </div>
        </div>
        <div class="hit-stats">
          <div class="hit-stat"><span>命中条数</span><b>{{ productStat.total }}</b></div>
          <div class="hit-stat"><span>关键命中</span><b>{{ productStat.key }}</b></div>
          <div class="hit-stat"><span>部分命中</span><b>{{ productStat.partial }}</b></div>
          <div class="hit-stat"><span>未命中</span><b>{{ productStat.miss }}</b></div>
        </div>
      </div>
      <div v-if="productStat.top.length" class="top-list">
        <div class="top-title">Top 命中知识</div>
        <div v-for="(t, i) in productStat.top" :key="i" class="top-row">
          <span class="top-dot" />
          <span class="top-label" :title="t.full">{{ t.label }}</span>
          <span v-if="t.count > 1" class="top-count">×{{ t.count }}</span>
        </div>
      </div>
      <div v-else class="empty-mini">尚无产品知识命中</div>
    </section>

    <!-- ============ 销售经验命中 ============ -->
    <section class="card hit-card">
      <div class="card-head">
        <h3 class="dm-text-h3">销售经验命中</h3>
        <span class="view-all">查看全部 <ArrowRight :size="12" :stroke-width="1.8" /></span>
      </div>
      <div class="hit-body">
        <div class="donut-wrap">
          <v-chart :option="experienceDonut" autoresize class="donut" />
          <div class="donut-center">
            <span class="donut-pct">{{ Math.round(experienceStat.hitRate * 100) }}%</span>
            <span class="donut-cap">命中率</span>
          </div>
        </div>
        <div class="hit-stats">
          <div class="hit-stat"><span>命中条数</span><b>{{ experienceStat.total }}</b></div>
          <div class="hit-stat"><span>关键命中</span><b>{{ experienceStat.key }}</b></div>
          <div class="hit-stat"><span>部分命中</span><b>{{ experienceStat.partial }}</b></div>
          <div class="hit-stat"><span>未命中</span><b>{{ experienceStat.miss }}</b></div>
        </div>
      </div>
      <div v-if="experienceStat.top.length" class="top-list">
        <div class="top-title">Top 命中经验</div>
        <div v-for="(t, i) in experienceStat.top" :key="i" class="top-row">
          <span class="top-dot exp" />
          <span class="top-label" :title="t.full">{{ t.label }}</span>
          <span v-if="t.count > 1" class="top-count">×{{ t.count }}</span>
        </div>
      </div>
      <div v-else class="empty-mini">尚无销售经验命中</div>
    </section>

    <!-- ============ 当前会话画像 ============ -->
    <section class="card">
      <div class="card-head">
        <h3 class="dm-text-h3">当前会话画像</h3>
      </div>
      <div class="kv-grid">
        <div v-for="(r, i) in profileRows" :key="i" class="kv-row">
          <span class="kv-k">{{ r.label }}</span>
          <span class="kv-v">{{ r.value }}</span>
        </div>
      </div>
    </section>

    <!-- ============ Judge 下一步指令 ============ -->
    <section class="card judge-card">
      <div class="card-head">
        <h3 class="dm-text-h3">Judge 下一步指令</h3>
        <RefreshCcw :size="14" :stroke-width="1.6" class="judge-refresh" />
      </div>
      <template v-if="judge.has">
        <div class="judge-block">
          <span class="judge-tag">目标</span>
          <span class="judge-text">{{ judge.goal || '—' }}</span>
        </div>
        <div class="judge-block">
          <span class="judge-tag">策略</span>
          <span class="judge-text">{{ judge.reason || judge.persona || '—' }}</span>
        </div>
        <div class="judge-block">
          <span class="judge-tag">预计效果</span>
          <span class="judge-text">
            综合质量 {{ judge.quality }} · {{ judge.endStatus }}
          </span>
        </div>
      </template>
      <div v-else class="empty-mini">等待第一次 Judge 评估…</div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.insights-pro {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow-y: auto;
  padding-right: 2px;
}

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-lg);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 0 0 auto;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-head h3 { margin: 0; font-size: 15px; font-weight: var(--dm-fw-bold); }
.judge-refresh { color: var(--dm-text-muted); cursor: default; }
.view-all {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}

/* ===== 命中卡（图4 风格） ===== */
.hit-card { gap: 14px; }
.hit-body {
  display: flex;
  align-items: center;
  gap: 18px;
}
.donut-wrap {
  position: relative;
  width: 104px;
  height: 104px;
  flex: 0 0 104px;
}
.donut { width: 100%; height: 100%; }
.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.donut-pct {
  font-size: 27px;
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
  line-height: 1;
  letter-spacing: -0.01em;
}
.donut-cap {
  font-size: 11px;
  color: var(--dm-text-muted);
  margin-top: 3px;
}
.hit-stats {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hit-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  b {
    color: var(--dm-text);
    font-size: 16px;
    font-weight: var(--dm-fw-semibold);
    font-variant-numeric: tabular-nums;
  }
}

/* ===== Top list ===== */
.top-list {
  border-top: 1px solid var(--dm-border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.top-title {
  font-size: var(--dm-fs-small);
  font-weight: var(--dm-fw-semibold);
  font-style: italic;
  color: var(--dm-text);
  margin-bottom: 1px;
}
.top-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  font-size: var(--dm-fs-body);
  color: var(--dm-text-secondary);
}
.top-dot {
  flex: 0 0 5px;
  width: 5px; height: 5px;
  margin-top: 7px;
  border-radius: 50%;
  background: #1a1a1a;
  &.exp { background: #1a1a1a; }
}
.top-label {
  flex: 1 1 auto;
  min-width: 0;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.top-count {
  flex: 0 0 auto;
  margin-top: 1px;
  font-size: 11px;
  color: var(--dm-text-muted);
  font-variant-numeric: tabular-nums;
}

.empty-mini {
  color: var(--dm-text-disabled);
  font-size: var(--dm-fs-small);
  padding: 4px 0;
}

/* ===== 当前会话画像 ===== */
.kv-grid {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.kv-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
}
.kv-k {
  flex: 0 0 64px;
  color: var(--dm-text-muted);
  font-size: var(--dm-fs-small);
}
.kv-v {
  flex: 1 1 auto;
  color: var(--dm-text);
  font-size: var(--dm-fs-body);
  text-align: right;
  word-break: break-word;
}

/* ===== Judge 指令 ===== */
.judge-card { gap: 10px; }
.judge-block {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.judge-tag {
  flex: 0 0 52px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  padding-top: 1px;
}
.judge-text {
  flex: 1 1 auto;
  font-size: var(--dm-fs-body);
  color: var(--dm-text);
  line-height: 1.5;
  word-break: break-word;
}
</style>
