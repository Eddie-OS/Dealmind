/**
 * 对话现场状态（Stage 6a）
 *
 * 接收 WsClient 推流来的事件，维护：
 *   - turns: 已收到的 Turn 列表（按 idx + speaker 顺序）
 *   - currentStage: 当前阶段名
 *   - sessionInfo: session_start 数据 + REST detail
 *   - status: pending / running / done / cancelled / failed
 *   - judgeFeedback / sessionMemory / coachReview: 最近一次
 *   - logs: log 事件
 *
 * 暴露 actions：
 *   - bind(sessionId): 连 WS + 拉 detail
 *   - unbind(): 关 WS
 *   - cancel(): 调 REST + 通过 WS 发 cancel（双保险）
 */
import { acceptHMRUpdate, defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import {
  sessionsApi,
  type JudgeEvaluation,
  type SessionInfo,
  type SessionStatus,
} from '@/api/sessions'
import { WsClient, type WsEvent } from '@/api/ws'

export interface LiveTurn {
  idx: number
  speaker: 'persona' | 'sales'
  content: string
  metadata: Record<string, any>
  stage: string
  created_at?: string
}

export interface StageMarker {
  kind: 'stage'
  round_idx: number
  from_stage: string
  to_stage: string
  /** business_stages v0.2：S1-S5 阶段 id（可能与中文名 to_stage 并存） */
  from_stage_id?: string
  to_stage_id?: string
  /** advance / stay / regress —— 用于前端阶段进度条显示"S3 ↩ S2"风格 */
  direction?: 'advance' | 'stay' | 'regress'
  trigger: string
  reason?: string
}

// 内联 Judge Check（嵌入对话流的深色卡片）
export interface JudgeMarker {
  kind: 'judge'
  round_idx: number
  assessment: string          // 评估（reason）
  sales_instruction: string   // 建议提供
  next_goal: string           // 下一步目标
  quality: number | null
  end_status: string
  ts: number
}

export type StreamItem = LiveTurn | StageMarker | JudgeMarker

// Stage 6b：单条 RAG 命中（前端展示用）
export interface RagHit {
  id: string | null
  text: string
  score: number | null
  filename?: string | null
  section?: string | null
  file_id?: number | null
  kb_id?: number | null
  kb_type?: 'product' | 'enterprise' | string | null
}

// 一轮 sales turn 对应的 RAG 命中分组
export interface RagHitsForTurn {
  round_idx: number
  query: string
  product: RagHit[]
  enterprise: RagHit[]
  product_fallback?: boolean
}

function isTurn(item: StreamItem): item is LiveTurn {
  return (item as LiveTurn).speaker !== undefined
}

export const useLiveSessionStore = defineStore('liveSession', () => {
  const sessionId = ref<string>('')
  const sessionInfo = ref<SessionInfo | null>(null)
  const status = ref<SessionStatus>('pending')
  const paused = ref<boolean>(false)

  const items = ref<StreamItem[]>([])
  const currentStage = ref<string>('')
  // business_stages v0.2：S1-S5 阶段 id（与 currentStage 中文名并存）
  const currentStageId = ref<string>('S1')
  const currentRound = ref<number>(0)

  const judgeFeedback = shallowRef<Record<string, any> | null>(null)
  const sessionMemory = shallowRef<Record<string, any> | null>(null)
  const coachReview = shallowRef<Record<string, any> | null>(null)
  const logs = ref<{ level: string; message: string; ts: number }[]>([])

  // Stage 6b：按 sales turn 收集的 RAG 命中（最新在尾部）
  const ragHitsByTurn = ref<RagHitsForTurn[]>([])

  const summary = ref<Record<string, any> | null>(null)

  // 回放：已结束会话以匀速逐句播放（演示用，无 LLM 思考延迟）
  const replayActive = ref(false)
  let replayTimer: number | null = null
  let replayQueue: StreamItem[] = []

  let client: WsClient | null = null

  const turns = computed<LiveTurn[]>(
    () => items.value.filter(isTurn) as LiveTurn[],
  )
  const isRunning = computed(() => status.value === 'running')
  const isFinished = computed(
    () => ['done', 'cancelled', 'failed'].includes(status.value),
  )

  function reset(): void {
    items.value = []
    currentStage.value = ''
    currentStageId.value = 'S1'
    currentRound.value = 0
    judgeFeedback.value = null
    sessionMemory.value = null
    coachReview.value = null
    logs.value = []
    summary.value = null
    sessionInfo.value = null
    status.value = 'pending'
    paused.value = false
    ragHitsByTurn.value = []
  }

  function appendTurn(turn: LiveTurn): void {
    // 防重复：相同 idx + speaker 不重复 push
    const exists = items.value.some(
      (it) => isTurn(it) && it.idx === turn.idx && it.speaker === turn.speaker,
    )
    if (exists) return
    items.value.push(turn)
  }

  function handleEvent(evt: WsEvent): void {
    const data = evt.data || {}
    switch (evt.type) {
      case 'session_start':
        currentStage.value = data.current_stage || ''
        currentStageId.value = data.current_stage_id || 'S1'
        status.value = 'running'
        break
      case 'stage_change':
        items.value.push({
          kind: 'stage',
          round_idx: data.round_idx ?? 0,
          from_stage: data.from_stage || '',
          to_stage: data.to_stage || '',
          from_stage_id: data.from_stage_id || '',
          to_stage_id: data.to_stage_id || '',
          direction: data.direction || 'advance',
          trigger: data.trigger || 'auto',
          reason: data.reason || '',
        })
        currentStage.value = data.to_stage || currentStage.value
        if (data.to_stage_id) currentStageId.value = data.to_stage_id
        break
      case 'persona_turn':
      case 'sales_turn': {
        const t = data.turn || {}
        const meta = t.metadata || {}
        appendTurn({
          idx: t.idx ?? 0,
          speaker: evt.type === 'persona_turn' ? 'persona' : 'sales',
          content: t.content || '',
          metadata: meta,
          stage: data.stage || currentStage.value,
          created_at: t.created_at,
        })
        currentRound.value = data.round_idx ?? currentRound.value
        if (data.stage) currentStage.value = data.stage
        if (data.stage_id) currentStageId.value = data.stage_id
        // Stage 6b：从 sales turn metadata 中抽 rag_hits
        if (evt.type === 'sales_turn') {
          const rag = meta.rag_hits as
            | {
                query?: string
                product?: RagHit[]
                enterprise?: RagHit[]
                product_fallback?: boolean
              }
            | undefined
          if (rag) {
            const turnRound = data.round_idx ?? t.idx ?? 0
            const existing = ragHitsByTurn.value.find(
              (r) => r.round_idx === turnRound,
            )
            if (!existing) {
              ragHitsByTurn.value.push({
                round_idx: turnRound,
                query: rag.query || '',
                product: rag.product || [],
                enterprise: rag.enterprise || [],
                product_fallback: rag.product_fallback ?? false,
              })
            }
          }
        }
        break
      }
      case 'memory_update':
        sessionMemory.value = data.session_memory || null
        break
      case 'judge_feedback': {
        const jf = data.judge_feedback || null
        judgeFeedback.value = jf
        if (jf) {
          items.value.push({
            kind: 'judge',
            round_idx: data.round_idx ?? currentRound.value ?? 0,
            assessment: jf.reason || '',
            sales_instruction: jf.sales_instruction || '',
            next_goal: jf.persona_instruction || '',
            quality:
              typeof jf.dialogue_quality_score === 'number'
                ? jf.dialogue_quality_score
                : null,
            end_status: jf.end_status || 'CONTINUE',
            ts: Date.now(),
          })
        }
        break
      }
      case 'session_status':
        paused.value = !!data.paused
        break
      case 'coach_review':
        coachReview.value = data.coach_review || null
        break
      case 'log':
        logs.value.push({
          level: data.level || 'info',
          message: data.message || '',
          ts: Date.now(),
        })
        break
      case 'session_end':
        summary.value = data
        paused.value = false
        if (data.outcome === 'CANCELLED') status.value = 'cancelled'
        else status.value = 'done'
        break
      default:
        // 未知事件忽略
        break
    }
  }

  const FINISHED_STATUSES: SessionStatus[] = ['done', 'cancelled', 'failed']

  async function bind(id: string): Promise<void> {
    if (sessionId.value === id && client) return
    unbind()
    reset()
    sessionId.value = id

    // 拉 REST detail（如果已结束直接展示，不一定连得上 ws）
    let basic: SessionInfo | null = null
    try {
      basic = await sessionsApi.detail(id)
      sessionInfo.value = basic
      status.value = basic.runtime_status || basic.status
      if (basic.summary) summary.value = basic.summary
    } catch (_e) {
      // 可能还没创建好，由 ws 端容错
    }

    // 已结束会话：live WS 不再回放（runner 已退、队列已空），
    // 改用 REST fullDetail 重建对话流 + 命中/Judge/画像，实现「回放对话现场」。
    const curStatus = (basic?.runtime_status || basic?.status) as SessionStatus | undefined
    if (curStatus && FINISHED_STATUSES.includes(curStatus)) {
      await replayFromDetail(id)
      return
    }

    client = new WsClient(`/ws/session/${encodeURIComponent(id)}/live`, {
      debug: false,
    })
    client.on(handleEvent)
    client.connect()
  }

  /** 从 REST fullDetail 重建已结束会话的对话现场（与 WS 实时事件构建逻辑保持一致）。 */
  async function replayFromDetail(id: string): Promise<void> {
    let detail
    try {
      detail = await sessionsApi.fullDetail(id)
    } catch (_e) {
      return
    }
    if (sessionId.value !== id) return // 期间已切走

    sessionInfo.value = detail.session
    status.value = (detail.session.runtime_status || detail.session.status) as SessionStatus

    // judge 评估按 turn_idx 归组，便于插回对话流对应轮次之后
    const judgeByIdx = new Map<number, JudgeEvaluation[]>()
    for (const j of detail.judge_evaluations || []) {
      if (j.evaluator_role !== 'judge') continue
      const k = j.turn_idx ?? -1
      const arr = judgeByIdx.get(k) || []
      arr.push(j)
      judgeByIdx.set(k, arr)
    }

    const sortedTurns = [...(detail.turns || [])].sort((a, b) => a.idx - b.idx)
    const rebuilt: StreamItem[] = []

    for (const t of sortedTurns) {
      rebuilt.push({
        idx: t.idx,
        speaker: t.role,
        content: t.content || '',
        metadata: t.metadata || {},
        stage: t.stage || '',
        created_at: t.created_at,
      })
      // 对话流、命中、Judge 都在 startPacedReplay 中随播放逐步显现
      for (const j of judgeByIdx.get(t.idx) || []) {
        const f = j.feedback || {}
        rebuilt.push({
          kind: 'judge',
          round_idx: j.turn_idx ?? t.idx,
          assessment: f.reason || '',
          sales_instruction: f.sales_instruction || '',
          next_goal: f.persona_instruction || '',
          quality:
            typeof f.dialogue_quality_score === 'number'
              ? f.dialogue_quality_score
              : null,
          end_status: f.end_status || 'CONTINUE',
          ts: Date.now(),
        })
      }
    }

    // 右栏画像/教练/结果整体上屏；对话流 + 命中 + Judge 随播放逐步显现
    sessionMemory.value = detail.session_memory || null
    coachReview.value = detail.coach_review || null
    if (detail.outcome) {
      summary.value = {
        ...(summary.value || {}),
        outcome: detail.outcome,
        ...(detail.metrics || {}),
      }
    }

    startPacedReplay(rebuilt)
  }

  // ===== 匀速回放播放器 =====
  function stopReplayTimer(): void {
    if (replayTimer !== null) {
      window.clearTimeout(replayTimer)
      replayTimer = null
    }
  }

  /** 每条停留时长：对话按字数给阅读时间（叠加约 1s 逐字动画），稳定可预期。 */
  function pacingFor(it: StreamItem): number {
    if (isTurn(it)) {
      const len = (it.content || '').length
      return Math.min(6500, Math.max(1600, 1100 + len * 28))
    }
    return 1400 // 阶段 / Judge 卡片
  }

  function pushRagFromTurn(t: LiveTurn): void {
    if (t.speaker !== 'sales') return
    const r = (t.metadata || {}).rag_hits as RagHitsForTurn | undefined
    if (!r) return
    if (ragHitsByTurn.value.some((x) => x.round_idx === t.idx)) return
    ragHitsByTurn.value.push({
      round_idx: t.idx,
      query: r.query || '',
      product: r.product || [],
      enterprise: r.enterprise || [],
      product_fallback: r.product_fallback ?? false,
    })
  }

  function revealNextReplayItem(): void {
    const next = replayQueue.shift()
    if (next === undefined) {
      replayActive.value = false
      replayTimer = null
      return
    }
    items.value.push(next)
    if (isTurn(next)) {
      currentRound.value = next.idx
      if (next.stage) currentStage.value = next.stage
      const sid = (next.metadata || {}).stage_id
      if (sid) currentStageId.value = sid
      pushRagFromTurn(next)
    } else if ((next as JudgeMarker).kind === 'judge') {
      const j = next as JudgeMarker
      judgeFeedback.value = {
        reason: j.assessment,
        sales_instruction: j.sales_instruction,
        persona_instruction: j.next_goal,
        dialogue_quality_score: j.quality,
        end_status: j.end_status,
      }
    }
    replayTimer = window.setTimeout(revealNextReplayItem, pacingFor(next))
  }

  function startPacedReplay(full: StreamItem[]): void {
    stopReplayTimer()
    items.value = []
    ragHitsByTurn.value = []
    judgeFeedback.value = null
    currentRound.value = 0
    replayQueue = [...full]
    replayActive.value = full.length > 0
    if (replayQueue.length) revealNextReplayItem()
  }

  /** 重新从头播放当前已结束会话。 */
  function restartReplay(): void {
    if (!sessionId.value) return
    void replayFromDetail(sessionId.value)
  }

  function unbind(): void {
    stopReplayTimer()
    replayActive.value = false
    if (client) {
      client.close()
      client = null
    }
  }

  async function cancel(): Promise<void> {
    if (!sessionId.value) return
    // 双保险：REST 设 flag + ws 推一条 cancel
    try {
      await sessionsApi.cancel(sessionId.value)
    } catch (_e) {
      // 已结束的 session REST 会 404；忽略
    }
    client?.send({ type: 'cancel' })
  }

  function pause(): void {
    if (status.value !== 'running') return
    paused.value = true // 乐观更新，后端 session_status 会再确认
    client?.send({ type: 'pause' })
  }

  function resume(): void {
    paused.value = false
    client?.send({ type: 'resume' })
  }

  return {
    sessionId,
    sessionInfo,
    status,
    paused,
    items,
    turns,
    currentStage,
    currentStageId,
    currentRound,
    judgeFeedback,
    sessionMemory,
    coachReview,
    logs,
    summary,
    ragHitsByTurn,
    isRunning,
    isFinished,
    replayActive,

    bind,
    unbind,
    cancel,
    pause,
    resume,
    restartReplay,
  }
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useLiveSessionStore, import.meta.hot))
}
