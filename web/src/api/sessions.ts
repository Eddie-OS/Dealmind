/**
 * Sessions API（Stage 6a + 7）
 *
 * 后端：src/api/routes_sessions.py
 *   POST   /api/sessions
 *   POST   /api/sessions/{id}/start
 *   POST   /api/sessions/{id}/cancel
 *   GET    /api/sessions/{id}
 *   GET    /api/sessions                        (Stage 7 列表 + 筛选 + 分页)
 *   GET    /api/sessions/{id}/detail            (Stage 7 完整复盘数据)
 *   GET    /api/sessions/{id}/export?format=    (Stage 7 json|md|jsonl)
 *   DELETE /api/sessions/{id}                   (Stage 7 删 DB + outputs)
 */
import { http } from './http'

export type FirstSpeaker = 'sales' | 'persona'
export type SessionStatus = 'pending' | 'running' | 'done' | 'cancelled' | 'failed'

export interface SessionConfig {
  who_speaks_first: FirstSpeaker
  judge_interval: number
  memory_interval: number
  max_rounds_floor: number
  opening_template_idx?: number | null
}

export interface SessionSummary {
  outcome?: string
  total_rounds?: number
  persona_turns?: number
  sales_turns?: number
  error?: string
}

export interface SessionInfo {
  id: string
  persona_id: number | null
  product_kb_id: number | null
  enterprise_kb_id: number | null
  handbook_id: number | null
  provider_id: number | null
  topic: string
  opening_line: string
  max_rounds: number
  status: SessionStatus
  config: SessionConfig
  summary: SessionSummary
  runtime_status: SessionStatus | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string
}

export type ConversationLanguage =
  | 'zh-CN'
  | 'en-US'
  | 'es-ES'
  | 'ar-SA'
  | 'id-ID'

export interface CreateSessionPayload {
  persona_id: number
  topic?: string
  product_kb_id?: number | null
  enterprise_kb_id?: number | null
  handbook_id?: number | null
  max_rounds?: number
  judge_interval?: number
  memory_interval?: number
  who_speaks_first?: FirstSpeaker
  opening_line?: string | null
  opening_template_idx?: number | null
  max_rounds_floor?: number | null
  language?: ConversationLanguage
}

export interface StartSessionResponse {
  session_id: string
  runtime_status: string
  ws_url: string
  message?: string
}

/** 与后端 src/session.py 中 OPENING_TEMPLATES 严格保持一致 */
export const OPENING_TEMPLATES = [
  '您好，欢迎光临，请问今天想看点什么？',
  'Hi，需要我帮您介绍一下吗？',
  '您好，随便看看也没关系，有需要随时叫我～',
  '欢迎光临！这边有刚到的新品，要不要看一下？',
  '您好，这边有什么我可以帮您的吗？',
]

// ============================================================
// Stage 7：历史 / 复盘 / 导出
// ============================================================

export interface SessionListParams {
  persona_id?: number | null
  status?: SessionStatus | null
  outcome?: string | null
  page?: number
  size?: number
}

export interface SessionListResponse {
  items: SessionInfo[]
  total: number
  page: number
  size: number
}

export interface TurnRecord {
  id: number
  session_id: string
  idx: number
  role: 'persona' | 'sales'
  content: string
  stage: string | null
  metadata: Record<string, any>
  created_at: string
}

export interface JudgeEvaluation {
  id: number
  session_id: string
  turn_idx: number | null
  evaluator_role: 'judge' | 'coach'
  score: Record<string, any> | null
  feedback: Record<string, any> | null
  created_at: string
}

export interface PersonaBrief {
  id: number
  name: string
  format_type: 'prompt_based' | 'structured'
  tags?: string[]
  locale?: string
  [k: string]: any
}

export interface SessionDetail {
  session: SessionInfo
  persona: PersonaBrief | null
  turns: TurnRecord[]
  judge_evaluations: JudgeEvaluation[]
  coach_review: Record<string, any> | null
  session_memory: Record<string, any>
  session_memory_round: number | null
  outcome: string | null
  metrics: {
    total_rounds: number
    persona_turns: number
    sales_turns: number
    judge_count: number
  }
}

export type ExportFormat = 'json' | 'md' | 'jsonl'

export const sessionsApi = {
  create: (payload: CreateSessionPayload) =>
    http.post<SessionInfo>('/api/sessions', payload).then((r) => r.data),

  start: (id: string) =>
    http.post<StartSessionResponse>(`/api/sessions/${encodeURIComponent(id)}/start`)
      .then((r) => r.data),

  cancel: (id: string) =>
    http.post<{ session_id: string; runtime_status: string; cancelled: boolean }>(
      `/api/sessions/${encodeURIComponent(id)}/cancel`,
    ).then((r) => r.data),

  detail: (id: string) =>
    http.get<SessionInfo>(`/api/sessions/${encodeURIComponent(id)}`).then((r) => r.data),

  // ===== Stage 7 =====

  list: (params: SessionListParams = {}) =>
    http
      .get<SessionListResponse>('/api/sessions', {
        params: {
          persona_id: params.persona_id ?? undefined,
          status: params.status ?? undefined,
          outcome: params.outcome ?? undefined,
          page: params.page ?? 1,
          size: params.size ?? 20,
        },
      })
      .then((r) => r.data),

  promptInspect: (id: string) =>
    http
      .get<{
        session_id: string
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
      }>(`/api/sessions/${encodeURIComponent(id)}/prompt_inspect`)
      .then((r) => r.data),

  fullDetail: (id: string) =>
    http
      .get<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}/detail`)
      .then((r) => r.data),

  del: (id: string) =>
    http
      .delete<{ session_id: string; deleted: boolean; removed_outputs: boolean }>(
        `/api/sessions/${encodeURIComponent(id)}`,
      )
      .then((r) => r.data),

  /** 导出 URL（用 <a download> 触发浏览器下载，走 axios baseURL 的同源代理） */
  exportUrl: (id: string, format: ExportFormat) =>
    `/api/sessions/${encodeURIComponent(id)}/export?format=${format}`,

  /**
   * 批量导出（zip）：sessions/{id}.{fmt} + 可选 analysis/{id}.md/.json
   *
   * 后端：POST /api/sessions/bulk_export
   * 返回二进制 zip，前端拿 blob 走浏览器下载
   */
  bulkExport: async (payload: {
    session_ids: string[]
    format?: ExportFormat
    include_analysis?: boolean
  }) => {
    const res = await http.post('/api/sessions/bulk_export', payload, {
      responseType: 'blob',
    })
    const blob = res.data as Blob
    // 后端在 headers 写了 Content-Disposition，但浏览器 axios 拿不到（CORS暴露），
    // 用 payload.session_ids.length 拼一份文件名
    const filename = `sessions-bulk-${payload.session_ids.length}.zip`
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    return { ok: true, filename, size: blob.size }
  },
}
