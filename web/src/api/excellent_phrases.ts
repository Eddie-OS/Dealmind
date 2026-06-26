/**
 * 优秀话术库 API
 *
 * 后端：src/api/routes_excellent_phrases.py
 *   GET    /api/excellent-phrases
 *   GET    /api/excellent-phrases/groups
 *   DELETE /api/excellent-phrases/{id}
 */
import { http } from './http'

export interface ExcellentPhrase {
  id: number
  analysis_job_id: number | null
  session_id: string | null
  handbook_id: number | null
  turn_idx: number | null
  group_key: string | null
  group_label: string | null
  handbook_label: string | null
  persona_name: string | null
  customer_question: string | null
  sales_content: string
  excellence_score: number
  purchase_signal_before: number | null
  purchase_signal_after: number | null
  is_off_handbook: boolean
  why_good: string[]
  source: string
  created_at: string
  updated_at: string
}

export interface PhraseListParams {
  group_key?: string
  keyword?: string
  min_score?: number
  page?: number
  page_size?: number
}

export interface PhraseListResponse {
  items: ExcellentPhrase[]
  total: number
  page: number
  page_size: number
}

export interface PhraseGroup {
  key: string
  label: string
  count: number
}

export interface PhraseGroupsResp {
  groups: PhraseGroup[]
  total: number
}

export const excellentPhrasesApi = {
  list: (params: PhraseListParams = {}) =>
    http
      .get<PhraseListResponse>('/api/excellent-phrases', { params })
      .then((r) => r.data),

  groups: () =>
    http
      .get<PhraseGroupsResp>('/api/excellent-phrases/groups')
      .then((r) => r.data),

  del: (id: number) =>
    http
      .delete<{ deleted: boolean; id: number }>(`/api/excellent-phrases/${id}`)
      .then((r) => r.data),
}
