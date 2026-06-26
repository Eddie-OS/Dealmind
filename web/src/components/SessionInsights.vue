<script setup lang="ts">
/**
 * 会话洞察面板（Stage 6b）
 *
 * 三个 tab：
 *   1. 实时画像   — Session Memory 字段卡片
 *   2. Judge 提示 — sales_score 雷达图 + 最新 instruction 卡片
 *   3. RAG 命中   — 按 sales turn 倒序展示产品/企业知识库命中
 *
 * Props:
 *   sessionMemory   Record | null
 *   judgeFeedback   Record | null
 *   ragHitsByTurn   RagHitsForTurn[]
 *
 * 设计：
 *   - 所有色彩 / 字号 / 间距 走 design tokens
 *   - 雷达图主色 = --dm-text，辅色 = --dm-chart-grid，与 Notion 黑白调一致
 */
import { computed, ref } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { RadarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import type { RagHitsForTurn } from '@/stores/liveSession'

use([CanvasRenderer, RadarChart, TitleComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  sessionMemory: Record<string, any> | null
  judgeFeedback: Record<string, any> | null
  ragHitsByTurn: RagHitsForTurn[]
}>()

const activeTab = ref<'profile' | 'judge' | 'rag'>('profile')

// ============================================================
// Tab 1 — 实时画像
// ============================================================
interface ProfileField {
  key: string
  label: string
  kind: 'text' | 'list'
}

const PROFILE_FIELDS: ProfileField[] = [
  { key: 'current_need', label: '当前需求', kind: 'text' },
  { key: 'main_objections', label: '核心异议', kind: 'list' },
  { key: 'budget_boundary', label: '预算边界', kind: 'text' },
  { key: 'emotional_state', label: '情绪状态', kind: 'text' },
  { key: 'mentioned_competitors', label: '提及竞品', kind: 'list' },
  { key: 'decision_constraints', label: '决策约束', kind: 'list' },
  { key: 'do_not_repeat', label: '避免重复', kind: 'list' },
  { key: 'next_best_action', label: '下一步建议', kind: 'text' },
]

function pickField(key: string): unknown {
  return props.sessionMemory?.[key]
}

function isEmptyValue(v: unknown): boolean {
  if (v === null || v === undefined) return true
  if (typeof v === 'string') return v.trim() === ''
  if (Array.isArray(v)) return v.length === 0
  return false
}

// ============================================================
// Tab 2 — Judge 雷达
// ============================================================
const SCORE_AXES: { key: string; label: string }[] = [
  { key: 'responsiveness', label: '响应度' },
  { key: 'specificity', label: '具体度' },
  { key: 'evidence_usage', label: '证据使用' },
  { key: 'objection_handling', label: '异议处理' },
  { key: 'closing_progress', label: '推进度' },
]

const radarOption = computed(() => {
  const score = (props.judgeFeedback?.sales_score || {}) as Record<string, any>
  const values = SCORE_AXES.map((a) => {
    const v = Number(score[a.key] ?? 0)
    return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0
  })
  return {
    tooltip: { trigger: 'item' },
    radar: {
      indicator: SCORE_AXES.map((a) => ({ name: a.label, max: 1 })),
      radius: '62%',
      axisName: {
        color: '#525252',
        fontSize: 12,
      },
      splitLine: { lineStyle: { color: '#ececec' } },
      splitArea: { areaStyle: { color: ['#fafaf8', '#ffffff'] } },
      axisLine: { lineStyle: { color: '#ececec' } },
    },
    series: [
      {
        name: '销冠表现',
        type: 'radar',
        data: [
          {
            value: values,
            name: '本轮评分',
            symbol: 'circle',
            symbolSize: 5,
            lineStyle: { color: '#1a1a1a', width: 2 },
            itemStyle: { color: '#1a1a1a' },
            areaStyle: { color: 'rgba(26, 26, 26, 0.08)' },
          },
        ],
      },
    ],
  }
})

const judgeMeta = computed(() => {
  const j = props.judgeFeedback || {}
  return {
    quality: typeof j.dialogue_quality_score === 'number'
      ? j.dialogue_quality_score.toFixed(2)
      : '-',
    end_status: j.end_status || 'CONTINUE',
    reason: j.reason || '',
    sales_instruction: j.sales_instruction || '',
    persona_instruction: j.persona_instruction || '',
  }
})

// ============================================================
// Tab 3 — RAG 命中（倒序，最新在顶）
// ============================================================
const reversedRagHits = computed(() =>
  [...props.ragHitsByTurn].sort((a, b) => b.round_idx - a.round_idx),
)

function formatScore(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—'
  return s.toFixed(3)
}

function truncate(text: string | undefined, n = 240): string {
  if (!text) return ''
  return text.length > n ? text.slice(0, n) + '…' : text
}
</script>

<template>
  <div class="insights">
    <el-tabs v-model="activeTab" class="insights-tabs">
      <!-- ============ Tab 1：实时画像 ============ -->
      <el-tab-pane label="实时画像" name="profile">
        <div v-if="!sessionMemory" class="empty">
          等待第一次 memory_update…
        </div>
        <div v-else class="profile-grid">
          <div
            v-for="f in PROFILE_FIELDS"
            :key="f.key"
            class="profile-card"
          >
            <div class="profile-label dm-text-overline">{{ f.label }}</div>
            <div
              v-if="isEmptyValue(pickField(f.key))"
              class="profile-empty dm-text-small"
            >
              —
            </div>
            <div
              v-else-if="f.kind === 'text'"
              class="profile-value dm-text-body"
            >
              {{ pickField(f.key) }}
            </div>
            <ul v-else class="profile-list">
              <li
                v-for="(item, i) in (pickField(f.key) as string[])"
                :key="i"
                class="dm-text-body"
              >
                {{ item }}
              </li>
            </ul>
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ Tab 2：Judge 提示 ============ -->
      <el-tab-pane label="Judge 提示" name="judge">
        <div v-if="!judgeFeedback" class="empty">
          等待第一次 judge_feedback…
        </div>
        <template v-else>
          <div class="judge-header">
            <span class="dm-text-overline">综合质量</span>
            <span class="judge-score dm-text-number-lg">
              {{ judgeMeta.quality }}
            </span>
            <el-tag
              :type="judgeMeta.end_status === 'CONTINUE' ? 'info' : 'warning'"
              size="small"
              effect="plain"
            >
              {{ judgeMeta.end_status }}
            </el-tag>
          </div>
          <div class="radar-wrap">
            <v-chart
              :option="radarOption"
              autoresize
              class="radar"
            />
          </div>
          <div v-if="judgeMeta.reason" class="judge-reason">
            <div class="dm-text-overline">判官说明</div>
            <div class="dm-text-caption">{{ judgeMeta.reason }}</div>
          </div>
          <div class="judge-cards">
            <div class="judge-card">
              <div class="dm-text-overline">销冠下一步指令</div>
              <div class="dm-text-body">
                {{ judgeMeta.sales_instruction || '—' }}
              </div>
            </div>
            <div class="judge-card">
              <div class="dm-text-overline">人设下一步指令</div>
              <div class="dm-text-body">
                {{ judgeMeta.persona_instruction || '—' }}
              </div>
            </div>
          </div>
        </template>
      </el-tab-pane>

      <!-- ============ Tab 3：RAG 命中 ============ -->
      <el-tab-pane name="rag">
        <template #label>
          <span>RAG 命中</span>
          <el-tag
            v-if="reversedRagHits.length"
            size="small"
            effect="plain"
            round
            class="rag-badge"
          >
            {{ reversedRagHits.length }}
          </el-tag>
        </template>
        <div v-if="!reversedRagHits.length" class="empty">
          销冠还没说话…
        </div>
        <div v-else class="rag-list">
          <div
            v-for="group in reversedRagHits"
            :key="group.round_idx"
            class="rag-group"
          >
            <div class="rag-group-head">
              <span class="dm-text-overline">第 {{ group.round_idx }} 轮</span>
              <span class="dm-text-small">
                Q: {{ truncate(group.query, 80) }}
              </span>
            </div>

            <!-- 产品 KB 命中 -->
            <div class="rag-section">
              <div class="rag-section-title">
                <span class="rag-dot product"></span>
                <span class="dm-text-overline">产品知识库</span>
                <span class="dm-text-small">
                  {{ group.product.length }} 条
                </span>
                <el-tag
                  v-if="group.product_fallback"
                  size="small"
                  effect="plain"
                  type="warning"
                >
                  fallback
                </el-tag>
              </div>
              <div v-if="!group.product.length" class="rag-empty dm-text-small">
                未命中
              </div>
              <div
                v-for="hit in group.product"
                :key="hit.id || Math.random()"
                class="rag-chunk"
              >
                <div class="rag-chunk-meta">
                  <span class="dm-text-body-strong">
                    {{ hit.filename || '未知文件' }}
                  </span>
                  <span v-if="hit.section" class="dm-text-small">
                    · {{ hit.section }}
                  </span>
                  <span class="dm-text-small rag-score">
                    score {{ formatScore(hit.score) }}
                  </span>
                </div>
                <div class="rag-chunk-text dm-text-caption">
                  {{ hit.text }}
                </div>
              </div>
            </div>

            <!-- 企业 KB 命中 -->
            <div class="rag-section">
              <div class="rag-section-title">
                <span class="rag-dot enterprise"></span>
                <span class="dm-text-overline">企业知识库</span>
                <span class="dm-text-small">
                  {{ group.enterprise.length }} 条
                </span>
              </div>
              <div
                v-if="!group.enterprise.length"
                class="rag-empty dm-text-small"
              >
                未命中
              </div>
              <div
                v-for="hit in group.enterprise"
                :key="hit.id || Math.random()"
                class="rag-chunk"
              >
                <div class="rag-chunk-meta">
                  <span class="dm-text-body-strong">
                    {{ hit.filename || '未知文件' }}
                  </span>
                  <span v-if="hit.section" class="dm-text-small">
                    · {{ hit.section }}
                  </span>
                  <span class="dm-text-small rag-score">
                    score {{ formatScore(hit.score) }}
                  </span>
                </div>
                <div class="rag-chunk-text dm-text-caption">
                  {{ hit.text }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped lang="scss">
.insights {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--dm-bg-card);
  border-radius: var(--dm-radius-md);
  border: 1px solid var(--dm-border);
  overflow: hidden;
}

.insights-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;

  :deep(.el-tabs__header) {
    margin: 0;
    padding: 0 var(--dm-space-4);
    border-bottom: 1px solid var(--dm-border);
  }

  :deep(.el-tabs__nav-wrap::after) {
    background: transparent;
  }

  :deep(.el-tabs__content) {
    flex: 1;
    overflow-y: auto;
    padding: var(--dm-space-4);
  }
}

.empty {
  padding: var(--dm-space-8) 0;
  text-align: center;
  color: var(--dm-text-muted);
  font-size: var(--dm-fs-caption);
}

// ===== Tab 1 =====
.profile-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--dm-space-3);
}
.profile-card {
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  padding: var(--dm-space-3) var(--dm-space-4);
}
.profile-label {
  margin-bottom: var(--dm-space-1);
}
.profile-empty {
  color: var(--dm-text-disabled);
}
.profile-value {
  color: var(--dm-text);
  word-break: break-word;
}
.profile-list {
  list-style: disc;
  margin: var(--dm-space-1) 0 0;
  padding-left: var(--dm-space-5);
  li {
    color: var(--dm-text);
    margin-bottom: var(--dm-space-1);
  }
}

// ===== Tab 2 =====
.judge-header {
  display: flex;
  align-items: center;
  gap: var(--dm-space-3);
  margin-bottom: var(--dm-space-2);
}
.judge-score {
  color: var(--dm-text);
}
.radar-wrap {
  width: 100%;
  height: 240px;
  margin: var(--dm-space-2) 0 var(--dm-space-4);
}
.radar {
  width: 100%;
  height: 100%;
}
.judge-reason {
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  padding: var(--dm-space-3);
  margin-bottom: var(--dm-space-3);
}
.judge-cards {
  display: grid;
  gap: var(--dm-space-3);
}
.judge-card {
  background: var(--dm-bg-elevated);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  padding: var(--dm-space-3) var(--dm-space-4);
}

// ===== Tab 3 =====
.rag-badge {
  margin-left: var(--dm-space-1);
}
.rag-list {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-4);
}
.rag-group {
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius);
  background: var(--dm-bg-elevated);
  padding: var(--dm-space-3);
}
.rag-group-head {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-1);
  margin-bottom: var(--dm-space-3);
  padding-bottom: var(--dm-space-2);
  border-bottom: 1px dashed var(--dm-border);
}
.rag-section + .rag-section {
  margin-top: var(--dm-space-3);
  padding-top: var(--dm-space-3);
  border-top: 1px dashed var(--dm-border);
}
.rag-section-title {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
  margin-bottom: var(--dm-space-2);
}
.rag-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  &.product    { background: var(--dm-info); }
  &.enterprise { background: var(--dm-success); }
}
.rag-empty {
  color: var(--dm-text-disabled);
  padding-left: var(--dm-space-3);
}
.rag-chunk {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-sm);
  padding: var(--dm-space-2) var(--dm-space-3);
  margin-bottom: var(--dm-space-2);
  &:last-child { margin-bottom: 0; }
}
.rag-chunk-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--dm-space-2);
  margin-bottom: var(--dm-space-1);
}
.rag-score {
  margin-left: auto;
  color: var(--dm-text-muted);
  font-family: var(--dm-font-mono);
}
.rag-chunk-text {
  color: var(--dm-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
