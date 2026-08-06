/**
 * Batch Report API（Stage 10）
 *
 * 后端：src/api/routes_batch_report.py
 *   GET /api/batch/{id}/report/overview
 *   GET /api/batch/{id}/report/objections?top=20
 *   GET /api/batch/{id}/report/persona_comparison
 *   GET /api/batch/{id}/report/sales_radar
 *   GET /api/batch/{id}/report/rag_stats
 *   GET /api/batch/{id}/report/export        → 下载 Training Guide .md
 */
import { http } from './http'
import { getToken } from '@/router'

export interface BatchReportOverview {
  batch_id: number
  batch_name: string | null
  status: string
  total_count: number
  completed_count: number
  failed_count: number
  cancelled_count: number
  duration_sec: number
  deal_count: number
  deal_rate: number
  avg_rounds: number
  avg_quality: number
  outcome_dist: Array<{ outcome: string; count: number }>
  max_rounds: number
  started_at: string | null
  ended_at: string | null
}

export interface ObjectionItem {
  text: string
  // 命中固定主题时为主题名，长尾相似度簇为 null
  theme?: string | null
  count: number
  // 该主题/簇下的代表性原始措辞（频次倒序）
  variants?: Array<{ text: string; count: number }>
  personas: string[]
  outcomes: Array<{ outcome: string; count: number }>
  session_ids: string[]
}
export interface ObjectionsResp {
  batch_id: number
  items: ObjectionItem[]
  total_unique: number
  total_records: number
}

export interface PersonaComparisonItem {
  persona_id: number
  persona_name: string
  persona_avatar_key?: string | null
  tags: string[]
  sessions: number
  deal_count: number
  deal_rate: number
  avg_quality: number | null
  avg_rounds: number
  outcomes: Array<{ outcome: string; count: number }>
  session_ids: string[]
}
export interface PersonaComparisonResp {
  batch_id: number
  items: PersonaComparisonItem[]
}

export interface RadarDim {
  key: string
  label: string
  avg: number
  samples: number
}
export interface RadarPerSession {
  session_id: string
  persona_id: number | null
  outcome: string
  quality: number | null
  responsiveness: number | null
  specificity: number | null
  evidence_usage: number | null
  objection_handling: number | null
  closing_progress: number | null
}
export interface SalesRadarResp {
  batch_id: number
  dimensions: RadarDim[]
  per_session: RadarPerSession[]
}

export interface RagStatsResp {
  batch_id: number
  sales_turns_total: number
  used_product_kb: number
  used_enterprise_kb: number
  used_both_kb: number
  used_any_kb: number
  hit_rate: number
  product_chunks: number
  enterprise_chunks: number
  chunks_total: number
  avg_chunks_per_turn: number
  fallback_turns: number
  sessions_with_rag: number
  sessions_total: number
}

// ============================================================
// business_stages v0.2：剧本动作覆盖率
// ============================================================

export interface StageDistributionItem {
  stage_id: string
  stage_cn: string
  actual_count: number
  actual_ratio: number
  expected_ratio: number
  delta: number
  outside_tolerance: boolean
}

export interface ActionUsageItem {
  action_id: string
  stage_id: string
  cn: string
  count: number
}

export interface StageCoverageItem {
  stage_id: string
  stage_cn: string
  used: string[]
  missed: string[]
  coverage_rate: number
}

export interface DealQuality {
  deal_sessions: number
  self_closed: number          // 成交但销冠从未进入 S4/S5（自我成交）
  closed_by_sales: number
  self_close_rate: number      // 自我成交占比（越高 = deal_rate 含金量越低）
  max_stage_dist: Array<{ stage_id: string; count: number }>
}

export interface PlaybookStatsResp {
  batch_id: number
  total_sales_turns: number
  with_playbook: number
  without_playbook: number
  stage_distribution: StageDistributionItem[]
  action_usage: ActionUsageItem[]
  stage_coverage: StageCoverageItem[]
  deal_quality?: DealQuality
}

export const batchReportApi = {
  overview: (id: number) =>
    http
      .get<BatchReportOverview>(`/api/batch/${id}/report/overview`)
      .then((r) => r.data),

  objections: (id: number, top = 20) =>
    http
      .get<ObjectionsResp>(`/api/batch/${id}/report/objections`, {
        params: { top },
      })
      .then((r) => r.data),

  personaComparison: (id: number) =>
    http
      .get<PersonaComparisonResp>(`/api/batch/${id}/report/persona_comparison`)
      .then((r) => r.data),

  salesRadar: (id: number) =>
    http
      .get<SalesRadarResp>(`/api/batch/${id}/report/sales_radar`)
      .then((r) => r.data),

  ragStats: (id: number) =>
    http.get<RagStatsResp>(`/api/batch/${id}/report/rag_stats`).then((r) => r.data),

  playbookStats: (id: number) =>
    http
      .get<PlaybookStatsResp>(`/api/batch/${id}/report/playbook_stats`)
      .then((r) => r.data),

  /** 仅返回 URL，给 <a download> 用。
   *  浏览器直连不走 axios 拦截器，token 以查询参数附上（后端中间件支持 ?token= 兜底）。 */
  exportUrl: (id: number) => {
    const token = getToken()
    const auth = token ? `?token=${encodeURIComponent(token)}` : ''
    return `/api/batch/${id}/report/export${auth}`
  },
}
