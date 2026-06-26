<script setup lang="ts">
/**
 * 对话流（Stage 6a）
 *
 * Props:
 *   items: Array<LiveTurn | StageMarker>  — turns 与 stage 切换标记混排
 *   personaName?: string  — 用于头像 / 显示标签
 *   autoScroll?: boolean  — 默认 true；新事件来到自动滚动到底部
 *   live?: boolean        — 现场会话进行中：开启「打字机逐字显现 + 正在思考占位」
 *
 * 设计（Notion 风）：
 *   - persona 卡片：极淡暖中性、左对齐
 *   - sales 卡片：极淡冷中性、右对齐
 *   - 区分靠对齐 + 头像，配色克制不刺眼
 *   - opening turn (idx=0 & is_opening) 加 "开场" 角标
 *   - stage 切换插水平虚线 + 阶段名
 *   - live=true 时：最新一轮发言逐字显现；等待下一位发言时显示动态「正在思考…」
 */
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ShoppingBag, ArrowRightFromLine, Scale } from '@lucide/vue'
import type { LiveTurn, StageMarker, JudgeMarker, StreamItem } from '@/stores/liveSession'
import PersonaAvatar from '@/components/PersonaAvatar.vue'

const props = withDefaults(
  defineProps<{
    items: StreamItem[]
    personaName?: string
    personaAvatarKey?: string | null
    autoScroll?: boolean
    live?: boolean
    replay?: boolean
  }>(),
  {
    personaName: '客户',
    personaAvatarKey: null,
    autoScroll: true,
    live: false,
    replay: false,
  },
)

const scrollRoot = ref<HTMLElement | null>(null)

function isTurn(it: StreamItem): it is LiveTurn {
  return (it as LiveTurn).speaker !== undefined
}

function isStage(it: StreamItem): it is StageMarker {
  return (it as StageMarker).kind === 'stage'
}

function isJudge(it: StreamItem): it is JudgeMarker {
  return (it as JudgeMarker).kind === 'judge'
}

function fmtTime(ts: number | undefined): string {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

const total = computed(() => props.items.length)

// ============================================================
// 打字机逐字显现（仅 live 现场生效）
// ============================================================
function turnKey(t: LiveTurn): string {
  return `${t.speaker}-${t.idx}`
}

// 每条 turn 当前已显现的字符数；未登记表示尚未处理
const revealed = reactive<Record<string, number>>({})
const typingKey = ref<string | null>(null)
let timer: number | null = null
let processed = 0

const isTyping = computed(() => typingKey.value !== null)

function scrollToBottom(): void {
  if (!props.autoScroll) return
  const el = scrollRoot.value
  if (el) el.scrollTop = el.scrollHeight
}

function stopTimer(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function revealFull(t: LiveTurn): void {
  revealed[turnKey(t)] = (t.content || '').length
}

function startTyping(t: LiveTurn): void {
  const key = turnKey(t)
  const full = (t.content || '').length
  if (full === 0) {
    revealed[key] = 0
    typingKey.value = null
    return
  }
  typingKey.value = key
  revealed[key] = 0
  const step = Math.max(1, Math.ceil(full / 40)) // 约 1 秒读完整轮
  stopTimer()
  timer = window.setInterval(() => {
    const cur = (revealed[key] ?? 0) + step
    if (cur >= full) {
      revealed[key] = full
      stopTimer()
      typingKey.value = null
    } else {
      revealed[key] = cur
    }
    scrollToBottom()
  }, 28)
}

// 处理新到达的 items：live 时只让「最后一条」打字，其余直接整段显现
function processItems(): void {
  const items = props.items
  for (let i = processed; i < items.length; i++) {
    const it = items[i]
    if (!isTurn(it)) continue
    const key = turnKey(it)
    if (key in revealed) continue
    const isLast = i === items.length - 1
    // 现场进行中 or 匀速回放：最后一条逐字显现，其余整段
    if ((props.live || props.replay) && isLast) startTyping(it)
    else revealFull(it)
  }
  processed = items.length
}

function displayContent(t: LiveTurn): string {
  const key = turnKey(t)
  const n = revealed[key]
  const full = t.content || ''
  if (n === undefined) return full // 尚未登记（非 live 历史）直接全显
  return n >= full.length ? full : full.slice(0, n)
}

watch(
  total,
  async () => {
    processItems()
    await nextTick()
    scrollToBottom()
  },
  { immediate: true },
)

// live / replay 结束 → 立刻把当前正在打字的整段补全，避免半截
function revealAllNow(): void {
  stopTimer()
  typingKey.value = null
  for (const it of props.items) {
    if (isTurn(it)) revealFull(it)
  }
}
watch(
  () => props.live,
  (now) => {
    if (!now) revealAllNow()
  },
)
watch(
  () => props.replay,
  (now) => {
    if (!now) revealAllNow()
  },
)

onBeforeUnmount(stopTimer)

// ============================================================
// 「正在思考…」占位气泡
// ============================================================
const lastTurn = computed<LiveTurn | null>(() => {
  for (let i = props.items.length - 1; i >= 0; i--) {
    const it = props.items[i]
    if (isTurn(it)) return it
  }
  return null
})

// 下一位发言者：销冠 ↔ 消费者 交替；尚无 turn 时由销冠开场
const thinkingSpeaker = computed<'persona' | 'sales'>(() => {
  const lt = lastTurn.value
  if (!lt) return 'sales'
  return lt.speaker === 'sales' ? 'persona' : 'sales'
})

// 现场进行中、且当前没有正在逐字显现 → 显示思考占位
const showThinking = computed(() => props.live && !isTyping.value)

watch(showThinking, async () => {
  await nextTick()
  scrollToBottom()
})

function truncate(s: string | undefined | null, n = 36): string {
  if (!s) return '-'
  return s.length > n ? s.slice(0, n) + '…' : s
}

function isOpening(turn: LiveTurn): boolean {
  return turn.idx === 0 && Boolean(turn.metadata?.is_opening)
}
</script>

<template>
  <div ref="scrollRoot" class="dialogue-stream">
    <template v-if="!items.length && !live && !replay">
      <div class="empty">
        <span class="dm-text-body-muted">等待会话开始…</span>
      </div>
    </template>

    <template v-for="(it, i) in items" :key="i">
      <!-- 阶段切换分隔线 -->
      <div
        v-if="isStage(it)"
        class="stage-marker"
        :class="{ 'stage-regress': it.direction === 'regress' }"
      >
        <span class="stage-dot" />
        <span class="stage-label">
          <template v-if="it.direction === 'regress'">
            阶段倒退
          </template>
          <template v-else>
            阶段切换
          </template>
          · Round {{ it.round_idx }}
          <span class="stage-from">
            <template v-if="it.from_stage_id">[{{ it.from_stage_id }}] </template>{{ it.from_stage || '-' }}
          </span>
          <span class="stage-arrow-wrap">
            <ArrowRightFromLine
              v-if="it.direction !== 'regress'"
              :size="12"
              :stroke-width="1.6"
              class="stage-arrow"
            />
            <span v-else class="stage-arrow regress-arrow">↩</span>
          </span>
          <span class="stage-to">
            <template v-if="it.to_stage_id">[{{ it.to_stage_id }}] </template>{{ it.to_stage }}
          </span>
          <span v-if="it.trigger === 'judge'" class="stage-trigger">Judge</span>
          <span v-if="it.reason" class="stage-reason">· {{ truncate(it.reason, 40) }}</span>
        </span>
      </div>

      <!-- 内联 Judge Check（深色卡片，嵌入对话流） -->
      <div v-else-if="isJudge(it)" class="judge-check">
        <div class="judge-check-head">
          <span class="judge-check-icon"><Scale :size="15" :stroke-width="1.8" /></span>
          <span class="judge-check-title">Judge Check</span>
          <span class="judge-check-time">{{ fmtTime(it.ts) }}</span>
        </div>
        <ul class="judge-check-list">
          <li v-if="it.assessment">{{ it.assessment }}</li>
          <li v-if="it.sales_instruction">
            <b>建议提供：</b>{{ it.sales_instruction }}
          </li>
          <li v-if="it.next_goal">
            <b>下一步目标：</b>{{ it.next_goal }}
          </li>
          <li v-if="!it.assessment && !it.sales_instruction && !it.next_goal">
            综合质量 {{ it.quality ?? '—' }} · {{ it.end_status }}
          </li>
        </ul>
      </div>

      <!-- Turn 卡片 -->
      <div
        v-else-if="isTurn(it)"
        class="turn-row"
        :class="{
          'turn-persona': it.speaker === 'persona',
          'turn-sales': it.speaker === 'sales',
        }"
      >
        <div class="avatar">
          <PersonaAvatar
            v-if="it.speaker === 'persona'"
            :avatar-key="personaAvatarKey"
            :name="personaName"
            :size="32"
          />
          <span v-else class="avatar-sales">
            <ShoppingBag :size="16" :stroke-width="1.6" />
          </span>
        </div>

        <div class="bubble">
          <div class="bubble-header">
            <span class="speaker">
              {{ it.speaker === 'persona' ? personaName : '销冠' }}
            </span>
            <span class="round dm-text-small">
              Round {{ it.idx }}{{ isOpening(it) ? ' · 开场' : '' }}
            </span>
          </div>
          <div class="content">{{ displayContent(it)
            }}<span v-if="typingKey === `${it.speaker}-${it.idx}`" class="caret" /></div>
          <div class="metadata dm-text-small">
            <template v-if="it.speaker === 'persona'">
              <span>intent: {{ truncate(it.metadata?.intent) }}</span>
              <span>attitude: {{ truncate(it.metadata?.attitude) }}</span>
              <span>buy: {{ it.metadata?.purchase_signal ?? '-' }}</span>
              <span>status: {{ it.metadata?.status || 'CONTINUE' }}</span>
              <span v-if="it.metadata?.walk_away_reason" class="warn">
                ⚠ {{ it.metadata.walk_away_reason }}
              </span>
            </template>
            <template v-else>
              <span>intent: {{ truncate(it.metadata?.intent) }}</span>
              <span>
                RAG:
                {{ it.metadata?.used_product_context ? '✓' : '–' }}
              </span>
              <span>next: {{ truncate(it.metadata?.next_action) }}</span>
              <!-- business_stages v0.2：销冠剧本动作徽章 -->
              <span
                v-if="it.metadata?.playbook_action"
                class="playbook-badge"
                :title="`本轮使用的剧本动作（business_stages v0.2）：${it.metadata.playbook_action}`"
              >
                <template v-if="it.metadata?.stage_id">
                  [{{ it.metadata.stage_id }}]
                </template>
                {{ it.metadata.playbook_action }}
              </span>
            </template>
          </div>
        </div>
      </div>
    </template>

    <!-- 正在思考占位气泡（仅现场进行中） -->
    <div
      v-if="showThinking"
      class="turn-row thinking"
      :class="{
        'turn-persona': thinkingSpeaker === 'persona',
        'turn-sales': thinkingSpeaker === 'sales',
      }"
    >
      <div class="avatar">
        <PersonaAvatar
          v-if="thinkingSpeaker === 'persona'"
          :avatar-key="personaAvatarKey"
          :name="personaName"
          :size="32"
        />
        <span v-else class="avatar-sales">
          <ShoppingBag :size="16" :stroke-width="1.6" />
        </span>
      </div>
      <div class="bubble bubble-thinking">
        <div class="bubble-header">
          <span class="speaker">
            {{ thinkingSpeaker === 'persona' ? personaName : '销冠' }}
          </span>
        </div>
        <div class="thinking-line">
          <span class="dots"><i /><i /><i /></span>
          <span class="thinking-text">正在思考…</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.dialogue-stream {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 4px 24px;
}

.empty {
  margin: 60px auto;
  text-align: center;
}

/* Stage 分隔 */
.stage-marker {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  position: relative;
}
.stage-marker::before,
.stage-marker::after {
  content: '';
  flex: 1 1 auto;
  height: 1px;
  background: var(--dm-border);
}
.stage-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--dm-text-muted);
}
.stage-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  white-space: nowrap;
}
.stage-from { color: var(--dm-text-muted); }
.stage-arrow { color: var(--dm-text-muted); }
.stage-to {
  color: var(--dm-text);
  font-weight: var(--dm-fw-medium);
}
.stage-trigger {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--dm-bg-muted);
  color: var(--dm-text-secondary);
  margin-left: 4px;
}
.stage-reason {
  color: var(--dm-text-muted);
  font-size: 11px;
  margin-left: 2px;
}
.stage-arrow-wrap {
  display: inline-flex;
  align-items: center;
}
.regress-arrow {
  font-size: 13px;
  font-weight: 700;
  color: var(--dm-danger);
}
.stage-regress::before,
.stage-regress::after {
  background: rgba(155, 44, 44, 0.22);
}
.stage-regress .stage-dot {
  background: var(--dm-danger);
}
.stage-regress .stage-label {
  color: var(--dm-danger);
}

/* business_stages v0.2：playbook 徽章（中性化） */
.playbook-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--dm-bg-muted);
  color: var(--dm-text-secondary);
  border: 1px solid var(--dm-border);
  font-weight: var(--dm-fw-medium);
  font-size: 11px;
  letter-spacing: 0.02em;
}

/* 内联 Judge Check 深色卡片 */
.judge-check {
  align-self: stretch;
  background: #2f2f2f;
  color: #f3f3f3;
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.judge-check-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.judge-check-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #e8e8e8;
}
.judge-check-title {
  font-weight: var(--dm-fw-semibold);
  font-size: var(--dm-fs-body);
  color: #ffffff;
  flex: 1 1 auto;
}
.judge-check-time {
  font-size: var(--dm-fs-small);
  color: #9a9a9a;
  font-variant-numeric: tabular-nums;
}
.judge-check-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.judge-check-list li {
  font-size: var(--dm-fs-body);
  line-height: 1.55;
  color: #e3e3e3;
  word-break: break-word;
}
.judge-check-list li b { color: #ffffff; font-weight: var(--dm-fw-medium); }

/* Turn 行 */
.turn-row {
  display: flex;
  gap: 10px;
  max-width: 88%;
}
.turn-persona {
  align-self: flex-start;
  flex-direction: row;
}
.turn-sales {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.avatar {
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  border-radius: var(--dm-radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--dm-text-secondary);
  overflow: visible;
}
.avatar-sales {
  width: 100%;
  height: 100%;
  border-radius: var(--dm-radius-full);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #37352f;
  color: #ffffff;
}

.bubble {
  flex: 1 1 auto;
  min-width: 0;
  border: 1px solid var(--dm-border);
  border-radius: 12px;
  padding: 10px 14px;
  background: var(--dm-bg-card);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
/* 极淡中性着色：消费者偏暖、销冠偏冷，区分但不刺眼 */
.turn-persona .bubble {
  border-top-left-radius: 4px;
  background: #f7f5f0;
  border-color: #ece9e1;
}
.turn-sales .bubble {
  border-top-right-radius: 4px;
  background: #f3f5f7;
  border-color: #e2e6ea;
}

.bubble-header {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.speaker {
  font-weight: var(--dm-fw-semibold);
  font-size: var(--dm-fs-body);
  color: var(--dm-text);
}
.round {
  color: var(--dm-text-muted);
}

.content {
  font-size: var(--dm-fs-body);
  line-height: 1.6;
  color: var(--dm-text);
  word-break: break-word;
  white-space: pre-wrap;
}

/* 打字机光标 */
.caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 1px;
  vertical-align: text-bottom;
  background: var(--dm-text-secondary);
  animation: caret-blink 1s steps(1) infinite;
}
@keyframes caret-blink {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}

.metadata {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  color: var(--dm-text-muted);
  font-variant-numeric: tabular-nums;
}
.metadata .warn {
  color: var(--dm-warning);
  font-weight: var(--dm-fw-medium);
}

/* 正在思考占位 */
.thinking .bubble-thinking {
  gap: 8px;
}
.thinking-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.thinking-text {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}
.dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--dm-text-muted);
  opacity: 0.35;
  animation: dot-pulse 1.2s ease-in-out infinite;
}
.dots i:nth-child(2) { animation-delay: 0.2s; }
.dots i:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 0.9; transform: translateY(-2px); }
}
</style>
