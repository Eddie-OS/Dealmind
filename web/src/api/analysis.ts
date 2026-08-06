/**
 * Handbook Analysis · 分析任务 API client
 *
 * 对应后端 src/api/routes_analysis.py
 */
import { http } from './http'
import { getToken } from '@/router'

// ============================================================
// types
// ============================================================

export type AnalysisJobStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface AnalysisJob {
  id: number
  batch_id: number | null
  session_id: string | null
  handbook_id: number | null
  status: AnalysisJobStatus
  progress: number
  total_turns: number
  classified_turns: number
  error_msg: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string
}

export interface CategoryCoverage {
  label: string
  hits: number
  sessions_covered: number
  avg_quality: number
}

export interface WeakCategory {
  category_id: string
  label: string
  hits: number
  avg_quality: number
  reason: string
}

export interface StrongCategory {
  category_id: string
  label: string
  hits: number
  avg_quality: number
}

export interface CoverageGroupStat {
  covered: number
  total: number
  coverage_pct: number
  hits: number
  weighted_avg_quality: number
}

export interface TurnLabel {
  category_id: string
  label: string
  confidence: number
}

export interface TurnHighlight {
  session_id: string
  turn_idx: number
  sales_content: string
  customer_question: string
  persona_id: number | null
  persona_name: string
  persona_cluster: string | null
  primary_label: { category_id: string; label: string } | null
  labels: TurnLabel[]
  scores: Record<string, number>
  avg_quality: number
  issues: string[]
  suggestion: string
  reference_text: string
  why_good?: string[]
  why_bad?: string[]
}

export interface ExcellentTurn {
  session_id: string
  turn_idx: number
  sales_content: string
  customer_question: string
  persona_id: number | null
  persona_name: string
  group: string
  handbook_label: string
  is_off_handbook: boolean
  excellence_score: number
  behavioral_score: number
  purchase_signal_before: number
  purchase_signal_after: number
  attitude_after: string
  status_after: string
  reference_text: string
  why_good: string[]
}

export interface ExcellentGroup {
  key: string
  label: string
  count: number
  items: ExcellentTurn[]
}

export interface ExcellentByGroup {
  groups: ExcellentGroup[]
  total: number
}

export interface RevisionQuote {
  content: string
  customer_question: string
  persona_name: string
  // 开场板块不打分（起手破冰套说服力分无意义），此时为 null，前端隐藏分数
  score: number | null
  session_id: string
  turn_idx: number
}

export interface HandbookRevision {
  category_id: string
  group: string
  label: string
  handbook_text: string
  coverage: { covered: boolean; hits: number; sessions: number; avg_quality: number }
  top_quotes: RevisionQuote[]
  status: string
  assessment: string
  suggestion: string
  revised_text: string
  fact_warnings?: string[]
  quality_flag?: string
}

export interface IssueCount {
  text: string
  count: number
}

export interface WeakCategoryV2 extends WeakCategory {
  issue_top?: IssueCount[]
  suggestion_samples?: string[]
}

export interface StrongCategoryV2 extends StrongCategory {
  highlight_reason?: string
}

export type RevisionKind = 'add_missing' | 'improve_existing' | 'global_dim'

export interface RevisionProposal {
  kind: RevisionKind
  category_id?: string
  category_label?: string
  dimension?: string
  dimension_label?: string
  severity: 'high' | 'medium' | 'low'
  original: string
  evidence: string
  suggestion: string
  issue_top?: IssueCount[]
  suggestion_samples?: string[]
}

export interface CustomerVoiceSample {
  session_id: string
  turn_idx: number
  content: string
}

export interface CustomerVoiceGroup {
  persona_id: number | null
  persona_name: string
  persona_cluster: string
  samples: CustomerVoiceSample[]
  sample_count: number
}

export interface KeyNumber {
  value: string
  context: string
  source_group: string
  source_text: string
}

export interface EngagementTokenHit {
  token: string
  count: number
}

export interface EngagementMetrics {
  total_sales_turns: number
  handbook_mention_rate: number
  handbook_mention_count: number
  punt_rate: number
  punt_count: number
  parse_fail_rate: number
  parse_fail_count: number
  repetition_rate: number
  repetition_count: number
  avg_length: number
  token_count: number
  top_hit_tokens: EngagementTokenHit[]
  punt_examples: string[]
  duplicate_examples: string[]
}

export interface PlaybookPersonaStat {
  persona: string
  persona_label: string
  total: number
  covered: number
  coverage_pct: number
  hits: number
  avg_quality: number
}

export interface ConversationPersonaItem {
  persona: string
  persona_label: string
  sessions: number
  outcomes: Record<string, number>
  own_cats_total: number
  own_cats_covered: number
  own_coverage_pct: number
}

export interface ConversationPersonaBreakdown {
  distribution: ConversationPersonaItem[]
  session_total: number
  classified: number
}

export interface AnalysisSummary {
  version?: string
  doc_type?: string
  playbook_persona_breakdown?: PlaybookPersonaStat[]
  conversation_persona_breakdown?: ConversationPersonaBreakdown
  generated_at?: string
  handbook_id: number | null
  handbook_name: string | null
  session_ids: string[]
  session_count: number
  total_classifications: number
  categories_total: number
  categories_covered: number
  coverage_pct: number
  category_coverage: Record<string, CategoryCoverage>
  coverage_by_group?: Record<string, CoverageGroupStat>
  uncovered_categories: string[]
  weak_categories: WeakCategoryV2[]
  strong_categories: StrongCategoryV2[]
  dim_avg: Record<string, number>
  outcome_join: Record<string, number>
  excellent_turns?: TurnHighlight[]
  excellent_by_group?: ExcellentByGroup
  problematic_turns?: TurnHighlight[]
  revision_proposals?: RevisionProposal[]
  handbook_revisions?: HandbookRevision[]
  customer_voice?: CustomerVoiceGroup[]
  key_numbers?: KeyNumber[]
  engagement?: EngagementMetrics
  methodology?: Methodology
  note?: string
}

export interface MethodologyItem {
  name: string
  desc: string
}

export interface MethodologySection {
  key: string
  title: string
  desc: string
  items: MethodologyItem[]
}

export interface Methodology {
  version: string
  intro: string
  sections: MethodologySection[]
}

export interface AnalysisJobDetail extends AnalysisJob {
  summary: AnalysisSummary | Record<string, never>
}

export interface TurnClassification {
  id: number
  session_id: string
  turn_idx: number
  category_id: string
  confidence: number
  scores: Record<string, number> | null
  issues: string[] | null
  suggestion: string
  reference_text: string
  created_at: string
}

export interface PersonaTopConcern {
  category_id: string
  label: string
  count: number
}

export interface PersonaInsight {
  id: number
  persona_id: number | null
  persona_cluster: string | null
  top_concerns: PersonaTopConcern[] | null
  sample_objections: string[] | null
  deal_rate: number | null
  avg_quality: number | null
  created_at: string
}

export interface CreateAnalysisPayload {
  batch_id?: number | null
  session_id?: string | null
  handbook_id?: number | null
}

// ============================================================
// API
// ============================================================

export const analysisApi = {
  create: (payload: CreateAnalysisPayload) =>
    http
      .post<{ job_id: number; job: AnalysisJob }>('/api/analysis/jobs', payload)
      .then((r) => r.data),

  list: (params?: {
    batch_id?: number
    session_id?: string
    handbook_id?: number
    status?: AnalysisJobStatus
    limit?: number
  }) =>
    http
      .get<{ items: AnalysisJob[]; total: number }>('/api/analysis/jobs', {
        params,
      })
      .then((r) => r.data),

  detail: (jobId: number) =>
    http
      .get<{ job: AnalysisJobDetail }>(`/api/analysis/jobs/${jobId}`)
      .then((r) => r.data.job),

  turns: (jobId: number, params?: { category_id?: string; limit?: number }) =>
    http
      .get<{ items: TurnClassification[]; total: number }>(
        `/api/analysis/jobs/${jobId}/turns`,
        { params },
      )
      .then((r) => r.data),

  personaInsights: (jobId: number) =>
    http
      .get<{ items: PersonaInsight[]; total: number }>(
        `/api/analysis/jobs/${jobId}/persona_insights`,
      )
      .then((r) => r.data),

  cancel: (jobId: number) =>
    http
      .post<{ cancelled: boolean }>(`/api/analysis/jobs/${jobId}/cancel`)
      .then((r) => r.data),

  remove: (jobId: number) =>
    http
      .delete<{ deleted: boolean }>(`/api/analysis/jobs/${jobId}`)
      .then((r) => r.data),

  /** 单份分析报告导出 URL（md/json 走 <a download>；html 走新标签预览/打印 PDF）
   *  注意：这些链接是浏览器直连（<a href> / window.open），不走 axios 拦截器，
   *  无法带 Authorization 头，因此把登录 token 以查询参数形式附上（后端中间件支持 ?token= 兜底）。 */
  exportUrl: (jobId: number, format: 'md' | 'json' | 'html' = 'md') => {
    const token = getToken()
    const auth = token ? `&token=${encodeURIComponent(token)}` : ''
    return `/api/analysis/jobs/${jobId}/export?format=${format}${auth}`
  },

  /** 找该 session 最新一份已完成的分析任务（供 SessionHistory "分析" 按钮兜底） */
  findBySession: async (sessionId: string): Promise<AnalysisJob | null> => {
    const r = await http
      .get<{ items: AnalysisJob[]; total: number }>('/api/analysis/jobs', {
        params: {
          session_id: sessionId,
          status: 'completed',
          limit: 1,
        },
      })
      .then((rr) => rr.data)
    return r.items[0] || null
  },
}

// ============================================================
// display helpers
// ============================================================

export const STATUS_LABEL: Record<AnalysisJobStatus, string> = {
  pending: '待开始',
  running: '分析中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const STATUS_TYPE: Record<
  AnalysisJobStatus,
  'info' | 'primary' | 'success' | 'danger' | 'warning'
> = {
  pending: 'info',
  running: 'primary',
  completed: 'success',
  failed: 'danger',
  cancelled: 'warning',
}

export const DIM_LABEL: Record<string, string> = {
  accuracy: '口径对齐',
  specificity: '具体度',
  delivery: '表达力',
  customer_fit: '客户契合',
  closing_push: '推进力',
  risk_compliance: '底线合规',
}

export const GROUP_LABEL: Record<string, string> = {
  intro: '① 一句话定位',
  sell: '③ 卖点',
  comp: '③ 竞品对比',
  param: '⑤ 核心参数',
  faq: '⑨ FAQ',
  demo: '⑩ 演示动作',
}

export const REVISION_KIND_LABEL: Record<RevisionKind, string> = {
  add_missing: '补充缺失',
  improve_existing: '改进既有',
  global_dim: '全局规则',
}

export const REVISION_KIND_TYPE: Record<
  RevisionKind,
  'info' | 'success' | 'warning' | 'danger' | 'primary'
> = {
  add_missing: 'danger',
  improve_existing: 'warning',
  global_dim: 'primary',
}

export const SEVERITY_LABEL: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
}

export const SEVERITY_TYPE: Record<
  string,
  'info' | 'success' | 'warning' | 'danger' | 'primary'
> = {
  high: 'danger',
  medium: 'warning',
  low: 'info',
}

export function categoryGroup(categoryId: string): string {
  return categoryId.split('_')[0]
}
