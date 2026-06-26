/**
 * Dashboard API（Stage 8）
 *
 * 后端：src/api/routes_dashboard.py
 *   GET /api/dashboard/summary
 *   GET /api/dashboard/trends?days=30
 *   GET /api/dashboard/persona_difficulty?limit=15
 */
import { http } from './http'

export interface OutcomeBucket {
  outcome: string
  count: number
}

export interface DashboardSummary {
  total_sessions: number
  total_personas: number
  avg_quality: number      // 0~10
  deal_rate: number        // 0~1
  outcome_dist: OutcomeBucket[]
  finished_count: number
  deal_count: number
}

export interface DashboardTrends {
  days: string[]           // YYYY-MM-DD，旧 → 新
  sessions: number[]
  quality: number[]
}

export interface PersonaDifficultyItem {
  persona_id: number
  persona_name: string
  sessions: number
  deal_count: number
  avg_quality: number | null
  tags: string[]
}

export interface PersonaDifficultyResp {
  items: PersonaDifficultyItem[]
  total: number
}

export interface ExperiencePoint {
  day: string
  size: number          // 经验库累计规模
  deal_rate: number     // 0~1
  concluded: number
}

export interface TrendLine {
  slope: number
  intercept: number
  x_min: number
  x_max: number
  y_at_min: number
  y_at_max: number
}

export interface ObjectionItem {
  label: string
  count: number
  pct: number           // 0~1
}

export interface DashboardInsights {
  days: string[]
  deal_trend: { days: string[]; deal_rate: (number | null)[] }
  hit_rate: { days: string[]; rate: (number | null)[] }
  experience_vs_deal: { points: ExperiencePoint[]; trend: TrendLine | null }
  objections: ObjectionItem[]
}

export const dashboardApi = {
  insights: (days = 30) =>
    http
      .get<DashboardInsights>('/api/dashboard/insights', { params: { days } })
      .then((r) => r.data),

  summary: () =>
    http.get<DashboardSummary>('/api/dashboard/summary').then((r) => r.data),

  trends: (days = 30) =>
    http
      .get<DashboardTrends>('/api/dashboard/trends', { params: { days } })
      .then((r) => r.data),

  personaDifficulty: (limit = 15) =>
    http
      .get<PersonaDifficultyResp>('/api/dashboard/persona_difficulty', {
        params: { limit },
      })
      .then((r) => r.data),
}
