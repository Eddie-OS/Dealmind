/**
 * Batch API（Stage 9）
 *
 * 后端：src/api/routes_batch.py + ws_batch.py
 *   GET    /api/batch                    分页 + status 过滤
 *   POST   /api/batch                    创建并立即启动
 *   GET    /api/batch/{id}               单条详情 + 实时进度
 *   GET    /api/batch/{id}/sessions      关联 session 列表
 *   POST   /api/batch/{id}/cancel        请求中断
 *   POST   /api/batch/{id}/resume        续跑未完成场次
 *   DELETE /api/batch/{id}               删 batch（不级联删 session）
 *   WS     /ws/batch/{id}                进度事件流
 */
import { http } from './http'

export type BatchStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'failed'

export interface BatchInfo {
  id: number
  name: string
  product_kb_id: number | null
  enterprise_kb_id: number | null
  handbook_id: number | null
  provider_id: number | null
  topic: string | null
  opening_line: string | null
  max_rounds: number
  judge_interval: number
  memory_interval: number
  total_count: number
  completed_count: number
  failed_count: number
  cancelled_count: number
  current_index: number
  current_session_id: string | null
  status: BatchStatus
  error_msg: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string

  persona_ids: number[]
  session_ids: string[]
  config: Record<string, any>
  summary: {
    outcome_dist?: Record<string, number>
    errors?: Array<{
      idx: number
      persona_id: number
      session_id: string | null
      error: string | null
    }>
    duration_sec?: number
  }

  // 运行时聚合（活跃 runner 存在时才有，否则等同 DB 字段）
  runtime_status: BatchStatus
  is_active: boolean
  current_round?: number
  live_completed?: number
  live_failed?: number
  live_cancelled?: number

  /** DB=running 但内存无 runner（后端重启/崩溃） */
  stale_running?: boolean
  can_resume?: boolean
  remaining_count?: number
}

export interface BatchListParams {
  status?: BatchStatus | null
  page?: number
  size?: number
}

export interface BatchListResponse {
  items: BatchInfo[]
  total: number
  page: number
  size: number
}

export type BatchLanguage = 'zh-CN' | 'en-US' | 'es-ES' | 'ar-SA' | 'id-ID'

export interface CreateBatchPayload {
  name: string
  persona_ids: number[]
  product_kb_id?: number | null
  enterprise_kb_id?: number | null
  handbook_id?: number | null
  topic?: string
  language?: BatchLanguage
  max_rounds?: number
  judge_interval?: number
  memory_interval?: number
}

export interface CreateBatchResponse extends BatchInfo {
  ws_url: string
}

export interface BatchSessionRow {
  batch_index: number
  id: string
  persona_id: number | null
  status: string
  outcome: string | null
  total_rounds: number
  started_at: string | null
  ended_at: string | null
  error: string | null
}

export interface BatchSessionListResponse {
  items: BatchSessionRow[]
  total: number
}

export const batchApi = {
  list: (params: BatchListParams = {}) =>
    http
      .get<BatchListResponse>('/api/batch', {
        params: {
          status: params.status ?? undefined,
          page: params.page ?? 1,
          size: params.size ?? 20,
        },
      })
      .then((r) => r.data),

  create: (payload: CreateBatchPayload) =>
    http.post<CreateBatchResponse>('/api/batch', payload).then((r) => r.data),

  detail: (id: number) =>
    http.get<BatchInfo>(`/api/batch/${id}`).then((r) => r.data),

  sessions: (id: number) =>
    http
      .get<BatchSessionListResponse>(`/api/batch/${id}/sessions`)
      .then((r) => r.data),

  cancel: (id: number) =>
    http
      .post<{ batch_id: number; status: string; cancel_requested: boolean }>(
        `/api/batch/${id}/cancel`,
      )
      .then((r) => r.data),

  resume: (id: number) =>
    http
      .post<CreateBatchResponse & { resumed: boolean; remaining_count?: number }>(
        `/api/batch/${id}/resume`,
      )
      .then((r) => r.data),

  del: (id: number) =>
    http
      .delete<{ batch_id: number; deleted: boolean }>(`/api/batch/${id}`)
      .then((r) => r.data),
}

// ============================================================
// WebSocket 事件 / 连接器
// ============================================================

export type BatchEventType =
  | 'batch_start'
  | 'session_open'
  | 'session_close'
  | 'batch_done'
  | 'log'
  | 'pong'

export interface BatchEvent<T = any> {
  type: BatchEventType
  data: T
}

export function batchWsUrl(id: number): string {
  // 与 vite proxy 对齐：用相对协议 + 当前 host
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/batch/${id}`
}

export interface BatchSocketHandlers {
  onEvent: (evt: BatchEvent) => void
  onOpen?: () => void
  onClose?: (ev: CloseEvent) => void
  onError?: (ev: Event) => void
}

/** 创建一个 WebSocket 订阅 batch 进度，返回带 close / sendCancel 的 handle */
export function connectBatchWs(
  id: number,
  handlers: BatchSocketHandlers,
): { close: () => void; sendCancel: () => void; sendPing: () => void } {
  const ws = new WebSocket(batchWsUrl(id))

  ws.addEventListener('open', () => handlers.onOpen?.())
  ws.addEventListener('close', (ev) => handlers.onClose?.(ev))
  ws.addEventListener('error', (ev) => handlers.onError?.(ev))
  ws.addEventListener('message', (ev) => {
    try {
      const evt = JSON.parse(ev.data) as BatchEvent
      handlers.onEvent(evt)
    } catch (err) {
      console.warn('[batch ws] bad json:', ev.data, err)
    }
  })

  return {
    close: () => {
      try { ws.close() } catch { /* noop */ }
    },
    sendCancel: () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'cancel' }))
      }
    },
    sendPing: () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      }
    },
  }
}
