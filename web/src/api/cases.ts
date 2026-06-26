/**
 * Sales Cases API（Stage 11）
 *
 * 后端：src/api/routes_cases.py + routes_sessions.py
 *   GET    /api/cases
 *   GET    /api/cases/sources
 *   GET    /api/cases/{id}
 *   PATCH  /api/cases/{id}
 *   DELETE /api/cases/{id}
 *   POST   /api/cases/reseed_preset
 *   POST   /api/sessions/{id}/cases       ← 手动收藏 turn 为案例
 */
import { http } from './http'

export type CaseSource = 'judge_auto' | 'coach_auto' | 'manual' | 'preset'

export interface CaseDialogueTurn {
  idx: number
  speaker: 'sales' | 'persona' | string
  content: string
  stage?: string
}

export interface SalesCase {
  id: number
  source: CaseSource
  title: string
  scene: string | null
  session_id: string | null
  persona_id: number | null
  persona_tags: string[]
  dialogue_excerpt: CaseDialogueTurn[]
  raw_content: string | null
  why_excellent: string | null
  tags: string[]
  votes: number
  file_source: string | null
  created_at: string
  updated_at: string
}

export interface CaseListParams {
  source?: CaseSource
  persona_id?: number
  session_id?: string
  tag?: string
  keyword?: string
  page?: number
  page_size?: number
}

export interface CaseListResponse {
  items: SalesCase[]
  total: number
  page: number
  page_size: number
}

export interface CaseSourcesResp {
  total: number
  by_source: Record<CaseSource, number>
}

export interface CaseUpdatePayload {
  title?: string
  scene?: string
  why_excellent?: string
  tags?: string[]
  persona_tags?: string[]
  votes?: number
}

export interface CollectAsCasePayload {
  turn_idx: number
  title?: string
  why_excellent?: string
  tags?: string[]
  context_radius?: number
}

export interface CollectAsCaseResp {
  ok: boolean
  case: SalesCase
}

export const casesApi = {
  list: (params: CaseListParams = {}) =>
    http
      .get<CaseListResponse>('/api/cases', { params })
      .then((r) => r.data),

  sources: () =>
    http.get<CaseSourcesResp>('/api/cases/sources').then((r) => r.data),

  detail: (id: number) =>
    http.get<SalesCase>(`/api/cases/${id}`).then((r) => r.data),

  update: (id: number, payload: CaseUpdatePayload) =>
    http.patch<SalesCase>(`/api/cases/${id}`, payload).then((r) => r.data),

  del: (id: number) =>
    http
      .delete<{ ok: boolean; deleted_id: number }>(`/api/cases/${id}`)
      .then((r) => r.data),

  reseedPreset: () =>
    http
      .post<{ inserted: number }>('/api/cases/reseed_preset')
      .then((r) => r.data),

  collectFromSession: (sessionId: string, payload: CollectAsCasePayload) =>
    http
      .post<CollectAsCaseResp>(
        `/api/sessions/${encodeURIComponent(sessionId)}/cases`,
        payload,
      )
      .then((r) => r.data),
}
