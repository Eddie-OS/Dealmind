/**
 * 销冠 Agent 配置中心（Stage 15a）
 *
 * 后端：src/api/routes_agent_profile.py
 *   GET    /api/agent-profile/sales
 *   PATCH  /api/agent-profile/sales
 *   GET    /api/agent-profile/sales/versions?limit=50
 *   POST   /api/agent-profile/sales/restore   { version_no }
 *   POST   /api/agent-profile/sales/try       { customer_opening, ... }
 */
import { http } from './http'

export interface AgentProfile {
  id: number
  name: string
  role_description: string
  system_prompt: string
  opening_lines: string[]
  default_session_params: Record<string, any>
  model_override: Record<string, any>
  extra: Record<string, any>
  created_at?: string | null
  updated_at?: string | null
}

export interface AgentProfileUpdate {
  role_description?: string
  system_prompt?: string
  opening_lines?: string[]
  default_session_params?: Record<string, any>
  model_override?: Record<string, any>
  version_comment?: string
}

export interface AgentProfileVersion {
  id: number
  version_no: number
  comment?: string | null
  created_at: string
  snapshot: {
    role_description?: string
    system_prompt?: string
    opening_lines?: string[]
    default_session_params?: Record<string, any>
    model_override?: Record<string, any>
  }
}

export interface VersionsResp {
  name: string
  versions: AgentProfileVersion[]
  total: number
}

export interface TryReq {
  customer_opening: string
  topic?: string
  product_kb_id?: number | null
  enterprise_kb_id?: number | null
  persona_name?: string
  persona_age?: number | null
  round_idx?: number
  max_rounds?: number
  stage?: string
}

export interface TryRespToolCall {
  loop: number
  name: string
  arguments: Record<string, any>
  result_preview: string
  ok: boolean
}

export interface TryResp {
  ok: boolean
  content: string
  strategy: Record<string, any>
  tool_mode?: string | null
  tool_calls: TryRespToolCall[]
  used_product_kb: string[]
  used_enterprise_kb: string[]
  error?: string | null
}

export interface TryNextHistoryItem {
  speaker: 'persona' | 'sales'
  content: string
}

export interface TryNextReq {
  history: TryNextHistoryItem[]
  customer_next: string
  topic?: string
  product_kb_id?: number | null
  enterprise_kb_id?: number | null
  persona_name?: string
  persona_age?: number | null
  max_rounds?: number
  stage?: string
}

export interface KbCard {
  id?: number | null
  name?: string | null
  kb_type: string
  file_count: number
  chunk_count: number
  last_uploaded_at?: string | null
  is_default_bound: boolean
}

export interface RecentUpload {
  kb_id: number
  kb_name?: string | null
  kb_type: string
  filename: string
  status: string
  chunk_count: number
  created_at: string
}

export interface MemoryResp {
  product_kb: KbCard
  enterprise_kb: KbCard
  sales_cases: { total: number; by_source: Record<string, number> }
  recent_uploads: RecentUpload[]
  bound_defaults: Record<string, any>
}

export interface ProviderSnapshot {
  id?: number | null
  name?: string | null
  provider_type?: string | null
  base_url?: string | null
  model_name?: string | null
  temperature?: number | null
  is_default: boolean
  source: 'db_default' | 'env' | 'override'
}

export interface EffectiveConfigResp {
  global_default: ProviderSnapshot
  override_provider?: ProviderSnapshot | null
  effective_model: string
  effective_temperature: number
  effective_max_tokens?: number | null
  has_any_override: boolean
}

export const agentProfileApi = {
  get: () =>
    http.get<AgentProfile>('/api/agent-profile/sales').then((r) => r.data),
  update: (payload: AgentProfileUpdate) =>
    http
      .patch<AgentProfile>('/api/agent-profile/sales', payload)
      .then((r) => r.data),
  versions: (limit = 50) =>
    http
      .get<VersionsResp>('/api/agent-profile/sales/versions', { params: { limit } })
      .then((r) => r.data),
  restore: (version_no: number) =>
    http
      .post<AgentProfile>('/api/agent-profile/sales/restore', { version_no })
      .then((r) => r.data),
  tryTurn: (payload: TryReq) =>
    http
      .post<TryResp>('/api/agent-profile/sales/try', payload, { timeout: 90_000 })
      .then((r) => r.data),
  tryNext: (payload: TryNextReq) =>
    http
      .post<TryResp>('/api/agent-profile/sales/try_next', payload, { timeout: 90_000 })
      .then((r) => r.data),
  memory: () =>
    http.get<MemoryResp>('/api/agent-profile/sales/memory').then((r) => r.data),
  effectiveConfig: () =>
    http
      .get<EffectiveConfigResp>('/api/agent-profile/sales/effective_config')
      .then((r) => r.data),
}
