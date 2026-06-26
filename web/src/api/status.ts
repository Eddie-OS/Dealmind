/**
 * 运行状态 API（Stage 12）
 *
 * 后端：src/api/routes_status.py
 *   GET /api/status/system
 *   GET /api/status/logs?lines=200
 *   GET /api/status/llm_stats?days=7
 *   GET /api/status/tasks
 *   GET /health   ← 顶部健康检查（已存在）
 */
import { http } from './http'

export interface SystemInfo {
  python: { version: string; implementation: string; executable: string }
  platform: { system: string; release: string; machine: string }
  deps: Record<string, string>
  paths: Record<string, string>
  sizes_bytes: Record<string, number>
  sizes_human: Record<string, string>
}

export interface LogsResp {
  file: string
  exists: boolean
  total_lines?: number
  returned?: number
  lines: string[]
}

export interface LlmStatsDay {
  date: string
  total: number
  sales: number
  persona: number
  sessions: number
}

export interface LlmStats {
  today_turns: number
  today_sales_turns: number
  today_persona_turns: number
  today_sessions: number
  evaluations_today: number
  by_day: LlmStatsDay[]
  note?: string
}

export interface SessionRunnerInfo {
  session_id: string
  status: string
  queue_size: number
  cancelled?: boolean
}

export interface BatchRunnerInfo {
  batch_id: number
  status: string
  completed: number
  failed: number
  cancelled: number
  total: number
  current_session_id?: string | null
  queue_size?: number
}

export interface TasksResp {
  sessions: SessionRunnerInfo[]
  batches: BatchRunnerInfo[]
  totals: {
    sessions: number
    batches: number
    active_sessions: number
    active_batches: number
  }
}

export interface HealthResp {
  status: string
  service: string
  version: string
  time: string
}

export const statusApi = {
  system: () =>
    http.get<SystemInfo>('/api/status/system').then((r) => r.data),
  logs: (lines = 200) =>
    http
      .get<LogsResp>('/api/status/logs', { params: { lines } })
      .then((r) => r.data),
  llmStats: (days = 7) =>
    http
      .get<LlmStats>('/api/status/llm_stats', { params: { days } })
      .then((r) => r.data),
  tasks: () => http.get<TasksResp>('/api/status/tasks').then((r) => r.data),
  health: () =>
    http
      .get<HealthResp>('/health', { timeout: 4000, silent: true })
      .then((r) => r.data),
}
