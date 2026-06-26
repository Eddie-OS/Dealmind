<script setup lang="ts">
/**
 * 对话现场（Stage 6a v1）
 *
 * 路由：/simulation/live/:id
 *
 * 布局（蓝图 §6a 主要任务 3）：
 *   左 6: 会话信息（persona 卡片 + 产品/企业 KB + 当前阶段 + 轮次 + 中断按钮）
 *   中 12: 滚动对话流（DialogueStream）
 *   右 6: 占位"实时数据"区域（Stage 6b 填充）
 *
 * mounted → store.bind(id) 触发 WS 连接 + REST detail 拉取
 * unmounted → store.unbind() 关 WS
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElButton,
  ElEmpty,
  ElMessageBox,
  ElResult,
  ElTag,
} from 'element-plus'
import {
  ArrowLeft,
  ArrowRightFromLine,
  BarChart3,
  History,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  Square,
} from '@lucide/vue'

import DialogueStream from '@/components/DialogueStream.vue'
import LiveInsightsPanel from '@/components/LiveInsightsPanel.vue'
import { personasApi, type Persona } from '@/api/personas'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import { useLiveSessionStore } from '@/stores/liveSession'

const route = useRoute()
const router = useRouter()
const store = useLiveSessionStore()

const sessionIdParam = computed(() => String(route.params.id || ''))

const persona = ref<Persona | null>(null)
const productKb = ref<KnowledgeBase | null>(null)
const enterpriseKb = ref<KnowledgeBase | null>(null)

const cancelling = ref(false)

// ===== 已用时长计时器 =====
const now = ref(Date.now())
let clockTimer: number | null = null

const elapsedText = computed(() => {
  const startStr = store.sessionInfo?.started_at
  if (!startStr) return '—'
  const start = new Date(startStr).getTime()
  if (Number.isNaN(start)) return '—'
  const endStr = store.sessionInfo?.ended_at
  const end = store.isFinished && endStr ? new Date(endStr).getTime() : now.value
  let sec = Math.max(0, Math.floor((end - start) / 1000))
  const h = Math.floor(sec / 3600); sec -= h * 3600
  const m = Math.floor(sec / 60); sec -= m * 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`
})

const startedAtText = computed(() => {
  const s = store.sessionInfo?.started_at
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

// ===== 压力画像（取参考设计的 5 个核心维度，来自 persona.pressure） =====
const PRESSURE_KEYS = [
  { key: 'price_sensitivity', label: '价格敏感度' },
  { key: 'trust_threshold', label: '信任阈值' },
  { key: 'patience', label: '耐心' },
  { key: 'competitor_awareness', label: '竞品意识' },
  { key: 'skepticism', label: '怀疑度' },
] as const

const pressureBars = computed(() => {
  const p = persona.value?.pressure
  if (!p) return []
  return PRESSURE_KEYS.map((d) => {
    const raw = Number((p as any)[d.key] ?? 0)
    const val = Math.round(Math.max(0, Math.min(1, raw)) * 100)
    return { label: d.label, val }
  })
})

function togglePause(): void {
  if (store.paused) store.resume()
  else store.pause()
}

async function loadAuxInfo() {
  const info = store.sessionInfo
  if (!info) return
  persona.value = null
  productKb.value = null
  enterpriseKb.value = null
  if (info.persona_id) {
    try { persona.value = await personasApi.detail(info.persona_id) }
    catch (_e) { /* persona 已删除：保留默认占位 */ }
  }
  if (info.product_kb_id) {
    try {
      const res = await kbApi.list('product')
      productKb.value = res.items.find((k) => k.id === info.product_kb_id) || null
    } catch (_e) { /* ignore */ }
  }
  if (info.enterprise_kb_id) {
    try {
      const res = await kbApi.list('enterprise')
      enterpriseKb.value = res.items.find((k) => k.id === info.enterprise_kb_id) || null
    } catch (_e) { /* ignore */ }
  }
}

watch(() => store.sessionInfo, loadAuxInfo, { immediate: false })

onMounted(async () => {
  const id = sessionIdParam.value
  if (!id) {
    router.replace('/simulation/new')
    return
  }
  await store.bind(id)
  await loadAuxInfo()
  clockTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  store.unbind()
  if (clockTimer !== null) { window.clearInterval(clockTimer); clockTimer = null }
})

async function onCancel() {
  try {
    await ElMessageBox.confirm(
      '确认中断当前会话？引擎会跑完当前轮后干净停止。',
      '中断会话',
      { type: 'warning', confirmButtonText: '中断', cancelButtonText: '继续运行' },
    )
  } catch { return }
  cancelling.value = true
  try {
    await store.cancel()
  } finally {
    cancelling.value = false
  }
}

function backToNew() {
  router.push('/simulation/new')
}

function backToHistory() {
  router.push('/simulation/history')
}

function gotoReview() {
  if (sessionIdParam.value) {
    router.push(`/simulation/detail/${sessionIdParam.value}`)
  } else {
    router.push('/simulation/history')
  }
}

const personaName = computed(() => persona.value?.name || '客户')

const statusBadge = computed(() => {
  if (store.status === 'running' && store.paused) {
    return { type: 'info', text: '已暂停', dot: false, running: false }
  }
  switch (store.status) {
    case 'running':   return { type: 'info', text: '运行中', dot: true, running: true }
    case 'pending':   return { type: 'info', text: '排队中', dot: false, running: false }
    case 'done':      return { type: 'success', text: '已完成', dot: false, running: false }
    case 'cancelled': return { type: 'info', text: '已中断', dot: false, running: false }
    case 'failed':    return { type: 'danger', text: '失败', dot: false, running: false }
    default:          return { type: 'info', text: store.status, dot: false, running: false }
  }
})

const sessionInfoOutcome = computed(() => store.summary?.outcome || store.sessionInfo?.summary?.outcome || '')
</script>

<template>
  <div class="live-session">
    <!-- 顶部条 -->
    <div class="topbar">
      <div class="left">
        <ElButton text @click="backToNew">
          <template #icon><ArrowLeft :size="16" :stroke-width="1.6" /></template>
          新建对话
        </ElButton>
        <span class="divider">/</span>
        <span class="session-id">{{ sessionIdParam }}</span>
        <ElTag
          :type="statusBadge.type as any"
          effect="plain"
          size="small"
          round
          class="status-tag"
          :class="{ 'tag-running': statusBadge.running }"
        >
          <span v-if="statusBadge.dot" class="pulse" />
          {{ statusBadge.text }}
        </ElTag>
      </div>
      <div class="right">
        <ElButton text @click="backToHistory">
          <template #icon><History :size="16" :stroke-width="1.6" /></template>
          会话历史
        </ElButton>
      </div>
    </div>

    <!-- 三栏 -->
    <div class="three-col">
      <!-- 左 -->
      <aside class="col col-left">
        <section class="card">
          <div class="card-head">
            <h3 class="dm-text-h3">会话信息</h3>
            <ElTag
              :type="statusBadge.type as any"
              effect="plain"
              size="small"
              round
              class="status-tag"
              :class="{ 'tag-running': statusBadge.running }"
            >
              <span v-if="statusBadge.dot" class="pulse" />
              {{ statusBadge.text }}
            </ElTag>
          </div>
          <div class="kv">
            <div class="kv-row">
              <span class="k">产品</span>
              <span class="v">{{ productKb?.name || store.sessionInfo?.topic || '—' }}</span>
            </div>
            <div class="kv-row">
              <span class="k">Persona</span>
              <span class="v">{{ persona?.name || '—' }}</span>
            </div>
            <div class="kv-row">
              <span class="k">当前阶段</span>
              <span class="v stage-name">
                <template v-if="store.currentStageId">[{{ store.currentStageId }}] </template>{{ store.currentStage || '—' }}
              </span>
            </div>
            <div class="kv-row">
              <span class="k">轮次</span>
              <span class="v">
                {{ store.currentRound || 0 }} / {{ store.sessionInfo?.max_rounds ?? '—' }}
              </span>
            </div>
            <div class="kv-row">
              <span class="k">开始时间</span>
              <span class="v">{{ startedAtText }}</span>
            </div>
            <div class="kv-row">
              <span class="k">已用时长</span>
              <span class="v mono">{{ elapsedText }}</span>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <h3 class="dm-text-h3">压力画像</h3>
            <span class="dm-text-small dm-text-muted">人设基线</span>
          </div>
          <div v-if="pressureBars.length" class="pressure-list">
            <div v-for="b in pressureBars" :key="b.label" class="pressure-row">
              <div class="pressure-label">{{ b.label }}</div>
              <div class="pressure-slider">
                <div class="slider-track">
                  <div class="slider-fill" :style="{ width: b.val + '%' }" />
                  <span class="slider-thumb" :style="{ left: b.val + '%' }" />
                </div>
                <div class="slider-ticks">
                  <span>低</span><span>中</span><span>高</span><span>极高</span>
                </div>
              </div>
            </div>
          </div>
          <ElEmpty v-else description="无压力画像数据" :image-size="48" />
        </section>

        <div class="col-controls">
          <template v-if="store.isRunning">
            <button class="ctrl-btn ctrl-pause" @click="togglePause">
              <Play v-if="store.paused" :size="15" :stroke-width="1.8" />
              <Pause v-else :size="15" :stroke-width="1.8" />
              {{ store.paused ? '继续' : '暂停' }}
            </button>
            <button class="ctrl-btn ctrl-stop" :disabled="cancelling" @click="onCancel">
              <Square :size="14" :stroke-width="1.8" />
              终止模拟
            </button>
          </template>
          <template v-else>
            <button
              class="ctrl-btn ctrl-pause"
              :disabled="store.replayActive"
              @click="store.restartReplay()"
            >
              <RotateCcw :size="15" :stroke-width="1.8" />
              {{ store.replayActive ? '回放中…' : '重播对话' }}
            </button>
            <button class="ctrl-btn ctrl-stop" @click="backToNew">
              <ArrowRightFromLine :size="15" :stroke-width="1.8" />
              再开一场
            </button>
          </template>
        </div>
      </aside>

      <!-- 中 -->
      <main class="col col-mid">
        <div class="card stream-card">
          <div class="stream-header">
            <h3 class="dm-text-h3">
              <MessageCircle :size="16" :stroke-width="1.6" />
              实时对话流
            </h3>
            <div class="dm-text-small stream-count">
              {{ store.turns.length }} 轮
            </div>
          </div>

          <DialogueStream
            :items="store.items"
            :persona-name="personaName"
            :persona-avatar-key="persona?.avatar_key ?? null"
            :live="store.isRunning"
            :replay="store.replayActive"
            class="stream-body"
          />

          <div v-if="store.isRunning" class="auto-drive">
            <span class="auto-dot" />
            系统自动驱动对话中 · 销冠与客户由 AI 实时演绎，无需手动输入
          </div>
          <div v-else-if="store.replayActive" class="auto-drive">
            <span class="auto-dot" />
            正在匀速回放对话 · 第 {{ store.currentRound }} 轮
          </div>

          <!-- 结束后操作面板（回放进行中先隐藏，放完再出现） -->
          <div v-if="store.isFinished && !store.replayActive" class="finish-panel">
            <ElResult
              :icon="store.status === 'failed' ? 'error' : 'success'"
              :title="store.status === 'cancelled'
                ? '会话已中断'
                : store.status === 'failed'
                  ? '会话异常结束'
                  : '会话完成'"
              :sub-title="sessionInfoOutcome ? `outcome=${sessionInfoOutcome}` : ''"
            >
              <template #extra>
                <ElButton @click="backToNew">再开一场</ElButton>
                <ElButton @click="store.restartReplay()">
                  <template #icon><RotateCcw :size="16" :stroke-width="1.6" /></template>
                  重播对话
                </ElButton>
                <ElButton type="primary" @click="gotoReview">
                  <template #icon><BarChart3 :size="16" :stroke-width="1.6" /></template>
                  查看复盘
                </ElButton>
              </template>
            </ElResult>
          </div>
        </div>
      </main>

      <!-- 右 -->
      <aside class="col col-right">
        <LiveInsightsPanel
          :session-memory="store.sessionMemory"
          :judge-feedback="store.judgeFeedback"
          :rag-hits-by-turn="store.ragHitsByTurn"
          :persona="persona"
          class="insights-panel"
        />
      </aside>
    </div>
  </div>
</template>

<style scoped lang="scss">
.live-session {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
}
.topbar .left { display: flex; align-items: center; gap: 8px; }
.topbar .right { display: flex; align-items: center; gap: 8px; }
.topbar .divider { color: var(--dm-text-muted); }
.session-id {
  font-family: var(--dm-font-mono, ui-monospace);
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}
.status-tag { display: inline-flex; align-items: center; gap: 5px; }
/* 运行中：灰绿色 + 呼吸 */
.tag-running.status-tag {
  --grn: #5f8a6e;
  color: #4d7a5d !important;
  border-color: rgba(95, 138, 110, 0.45) !important;
  background: rgba(95, 138, 110, 0.1) !important;
}
.pulse {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #5f8a6e;
  box-shadow: 0 0 0 0 rgba(95, 138, 110, 0.6);
  animation: pulse 1.6s infinite;
}
@keyframes pulse {
  0%   { box-shadow: 0 0 0 0 rgba(95, 138, 110, 0.5); }
  70%  { box-shadow: 0 0 0 7px rgba(95, 138, 110, 0); }
  100% { box-shadow: 0 0 0 0 rgba(95, 138, 110, 0); }
}

.three-col {
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  gap: 16px;
  flex: 1 1 auto;
  min-height: 0;
}
@media (max-width: 1280px) {
  .three-col { grid-template-columns: 260px 1fr 280px; }
}
@media (max-width: 1024px) {
  .three-col { grid-template-columns: 1fr; }
}

.col { min-width: 0; display: flex; flex-direction: column; gap: 12px; }

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.card h3 {
  margin: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.kv {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv-row { display: flex; justify-content: space-between; gap: 8px; }
.kv-row .k { color: var(--dm-text-muted); font-size: var(--dm-fs-small); }
.kv-row .v {
  color: var(--dm-text);
  font-size: var(--dm-fs-body);
  text-align: right;
  word-break: break-word;
  max-width: 60%;
}
.stage-name {
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
}
.mono { font-variant-numeric: tabular-nums; }

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-head h3 { margin: 0; }

/* ===== 压力画像（图2：单色滑块 + 四档刻度） ===== */
.pressure-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pressure-row { display: flex; flex-direction: column; gap: 8px; }
.pressure-label {
  font-size: var(--dm-fs-body);
  color: var(--dm-text);
}
.pressure-slider { display: flex; flex-direction: column; gap: 5px; }
.slider-track {
  position: relative;
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #e6e4df;
}
.slider-fill {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  border-radius: 2px;
  background: #1a1a1a;
}
.slider-thumb {
  position: absolute;
  top: 50%;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #1a1a1a;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 0 2px var(--dm-bg-card);
}
.slider-ticks {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--dm-text-muted);
}
.slider-ticks span { flex: 0 0 auto; }
.slider-ticks span:first-child { margin-left: -2px; }

/* ===== 左栏底部控制（图3：暂停 outline + 终止 黑底） ===== */
.col-controls {
  margin-top: auto;
  padding-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ctrl-btn {
  width: 100%;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: var(--dm-radius);
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  font-family: inherit;
  cursor: pointer;
  transition: background var(--dm-transition), border-color var(--dm-transition);
}
.ctrl-pause {
  background: var(--dm-bg-card);
  color: var(--dm-text);
  border: 1px solid var(--dm-border-strong, #d6d3cc);
}
.ctrl-pause:hover { background: var(--dm-bg-muted, #f5f4f1); }
.ctrl-stop {
  background: #1a1a1a;
  color: #ffffff;
  border: 1px solid #1a1a1a;
}
.ctrl-stop:hover { background: #000000; }
.ctrl-stop:disabled { opacity: 0.6; cursor: not-allowed; }

/* ===== 中栏自动驱动提示 ===== */
.auto-drive {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: var(--dm-radius);
  background: var(--dm-bg-muted, #f6f5f2);
  color: var(--dm-text-muted);
  font-size: var(--dm-fs-small);
}
.auto-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #5f8a6e;
  box-shadow: 0 0 0 0 rgba(95, 138, 110, 0.5);
  animation: auto-pulse 1.6s infinite;
}
@keyframes auto-pulse {
  0% { box-shadow: 0 0 0 0 rgba(95, 138, 110, 0.45); }
  70% { box-shadow: 0 0 0 7px rgba(95, 138, 110, 0); }
  100% { box-shadow: 0 0 0 0 rgba(95, 138, 110, 0); }
}

.persona-head { display: flex; align-items: center; gap: 10px; }
.avatar-big {
  width: 40px; height: 40px;
  border-radius: var(--dm-radius-full);
  background: var(--dm-bg-inverse);
  color: var(--dm-text-inverse);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--dm-fw-semibold);
}
.persona-name { font-weight: var(--dm-fw-semibold); }

.tags { display: flex; flex-wrap: wrap; gap: 4px; }

.kb-list { display: flex; flex-direction: column; gap: 6px; }
.kb-row { display: flex; align-items: center; gap: 8px; }
.kb-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: transparent;
  color: var(--dm-text-secondary);
  border: 1px solid var(--dm-border-strong);
}
.kb-tag.product { color: var(--dm-text); border-color: var(--dm-text); }
.kb-tag.enterprise { color: var(--dm-text-secondary); border-color: var(--dm-border-strong); }
.kb-note { color: var(--dm-text-muted); }

/* 中栏对话流卡片 */
.stream-card {
  flex: 1 1 auto;
  min-height: 0;
  position: relative;
}
.stream-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.stream-count { color: var(--dm-text-muted); }

.stream-body {
  flex: 1 1 auto;
  min-height: 0;
}

.finish-panel {
  position: absolute;
  inset: auto 16px 16px;
  background: var(--dm-bg-card);
  border-top: 1px solid var(--dm-border);
  padding: 12px;
  border-radius: var(--dm-radius-lg);
}

/* 右栏：实时洞察 */
.insights-panel { flex: 1 1 auto; min-height: 0; }
.logs-card { flex: 0 0 auto; }
.placeholder-list {
  padding-left: 18px;
  color: var(--dm-text-muted);
  font-size: var(--dm-fs-small);
  line-height: 1.6;
}

.mini-section { display: flex; flex-direction: column; gap: 4px; }
.mini-title {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  font-weight: var(--dm-fw-medium);
}
.mini-pre {
  margin: 0;
  font-size: 11px;
  line-height: 1.4;
  background: var(--dm-bg-muted);
  border-radius: var(--dm-radius);
  padding: 8px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.logs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--dm-fs-small);
}
.log-line { display: flex; gap: 6px; align-items: baseline; }
.log-level {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: var(--dm-fw-medium);
  background: rgba(0, 0, 0, 0.06);
  color: var(--dm-text-secondary);
}
.log-level[data-level='error'] { background: rgba(239, 68, 68, 0.12); color: #b91c1c; }
.log-level[data-level='warn']  { background: rgba(245, 158, 11, 0.14); color: #b45309; }
</style>
