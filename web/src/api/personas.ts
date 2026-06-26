/**
 * Persona 人设库 API
 * 8 个接口（7 业务 + 1 元数据） + 类型定义 + 9 维参数 metadata
 */
import { http } from './http'

export type PersonaFormat = 'structured' | 'prompt_based'

export interface PressureProfile {
  price_sensitivity: number
  trust_threshold: number
  patience: number
  competitor_awareness: number
  decision_power: number
  emotion_volatility: number
  need_urgency: number
  skepticism: number
  bargaining_aggressiveness: number
}

export interface PersonaProfileFields {
  age?: number | null
  occupation?: string | null
  budget?: string | number | null
  personality?: string
  pain_points?: string[]
  objection_style?: string
  purchase_goal?: string
}

export interface Persona {
  id: number
  name: string
  format_type: PersonaFormat
  prompt_text: string | null
  profile: PersonaProfileFields
  pressure: PressureProfile
  source: string | null
  tags: string[]
  locale: string
  pressure_extracted: boolean
  avatar_key: string | null
  // v0.2.1 真实性 / 地区一致性补丁
  country_code: string | null
  country_name: string | null
  currency: string | null
  market_domains: string[]
  created_at: string
  updated_at: string
}

export interface CountryOption {
  code: string
  label: string
  name_cn: string
  name_en: string
  currency: string
  currency_symbol: string
  default_market_domains: string[]
}

export interface PersonaListResponse {
  items: Persona[]
  total: number
}

export interface PersonaListQuery {
  format_type?: PersonaFormat
  tag?: string
  search?: string
  limit?: number
}

export interface PersonaCreatePayload {
  name: string
  format_type: PersonaFormat
  prompt_text?: string | null
  profile?: PersonaProfileFields
  pressure?: PressureProfile
  source?: string | null
  tags?: string[]
  locale?: string
  avatar_key?: string | null
}

export type PersonaUpdatePayload = Partial<PersonaCreatePayload> & {
  pressure_extracted?: boolean
  // v0.2.1 — 编辑弹窗会下发的 4 个新字段
  country_code?: string | null
  country_name?: string | null
  currency?: string | null
  market_domains?: string[] | null
}

export interface PersonaUploadResponse {
  imported: number
  ids: number[]
  items: Persona[]
}

// ===== AI 生成人设 =====
export interface ClarifyOption {
  id: string
  label: string
}
export interface ClarifyQuestion {
  id: string
  prompt: string
  type: 'single' | 'multi'
  options: ClarifyOption[]
}
export interface PersonaGenerateAnswer {
  question: string
  answer: string | string[]
}
export interface PersonaDraft {
  name: string
  format_type: 'prompt_based'
  prompt_text: string
  tags: string[]
  country_code: string | null
  country_name: string | null
  currency: string | null
  market_domains: string[]
  profile: PersonaProfileFields
  pressure: PressureProfile
  avatar_key: string | null
}
export type PersonaGenerateResponse =
  | { status: 'need_clarification'; questions: ClarifyQuestion[] }
  | { status: 'ok'; draft: PersonaDraft }

export interface PersonaGeneratePayload {
  idea: string
  answers?: PersonaGenerateAnswer[]
  skip_clarify?: boolean
}

/** 9 维度定义（label + tooltip 说明），与后端 prompts/pressure_extractor_prompt.md 同步 */
export interface PressureDimension {
  key: keyof PressureProfile
  label: string
  desc: string
}

export const PRESSURE_DIMENSIONS: PressureDimension[] = [
  { key: 'price_sensitivity',       label: '价格敏感度',   desc: '越高越在意价格、越主动砍价比价' },
  { key: 'trust_threshold',         label: '信任阈值',     desc: '越高越需要证据/案例/售后才信任' },
  { key: 'patience',                label: '耐心程度',     desc: '越低越快不耐烦销售啰嗦' },
  { key: 'competitor_awareness',    label: '竞品认知',     desc: '越高越主动拿竞品压价或对比' },
  { key: 'decision_power',          label: '决策权',       desc: '越低越会"再想想/问家人"' },
  { key: 'emotion_volatility',      label: '情绪波动',     desc: '越高越容易被刺激起伏' },
  { key: 'need_urgency',            label: '需求紧迫度',   desc: '越高越倾向立刻解决/今天就买' },
  { key: 'skepticism',              label: '怀疑度',       desc: '越高越质疑销售承诺，要求实证' },
  { key: 'bargaining_aggressiveness', label: '砍价强度',   desc: '越高砍价越狠、越不接受原价' },
]

export const DEFAULT_PRESSURE: PressureProfile = {
  price_sensitivity: 0.5,
  trust_threshold: 0.5,
  patience: 0.5,
  competitor_awareness: 0.5,
  decision_power: 0.5,
  emotion_volatility: 0.5,
  need_urgency: 0.5,
  skepticism: 0.5,
  bargaining_aggressiveness: 0.5,
}

export const personasApi = {
  list: (params?: PersonaListQuery) =>
    http.get<PersonaListResponse>('/api/personas', { params }).then((r) => r.data),

  detail: (id: number) =>
    http.get<Persona>(`/api/personas/${id}`).then((r) => r.data),

  create: (payload: PersonaCreatePayload) =>
    http.post<Persona>('/api/personas', payload).then((r) => r.data),

  generate: (payload: PersonaGeneratePayload) =>
    http
      .post<PersonaGenerateResponse>('/api/personas/generate', payload)
      .then((r) => r.data),

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http
      .post<PersonaUploadResponse>('/api/personas/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  extractPressure: (id: number) =>
    http.post<Persona>(`/api/personas/${id}/extract_pressure`).then((r) => r.data),

  update: (id: number, payload: PersonaUpdatePayload) =>
    http.patch<Persona>(`/api/personas/${id}`, payload).then((r) => r.data),

  remove: (id: number) =>
    http.delete<void>(`/api/personas/${id}`).then(() => undefined),

  // v0.2.1：国家清单（编辑弹窗的下拉框用）
  listCountries: () =>
    http
      .get<{ countries: CountryOption[] }>('/api/personas/meta/countries')
      .then((r) => r.data.countries),
}
