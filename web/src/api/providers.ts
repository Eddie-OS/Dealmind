/**
 * LLM Providers API
 * 6 个接口 + 类型定义 + 6 种 provider_type 预设
 */
import { http } from './http'

export type ProviderType =
  | 'deepseek'
  | 'openai'
  | 'qwen'
  | 'moonshot'
  | 'zhipu'
  | 'custom'

export interface Provider {
  id: number
  name: string
  provider_type: ProviderType
  base_url: string
  api_key: string
  model_name: string
  temperature: number
  max_retries: number
  is_active: boolean
  is_default: boolean
  extra_config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ProviderCreate {
  name: string
  provider_type: ProviderType
  base_url: string
  api_key: string
  model_name: string
  temperature?: number
  max_retries?: number
  is_active?: boolean
  is_default?: boolean
  extra_config?: Record<string, unknown>
}

export type ProviderUpdate = Partial<Omit<ProviderCreate, 'name'>> & {
  name?: string
}

export interface ProviderTestRequest {
  provider_id?: number
  base_url?: string
  api_key?: string
  model_name?: string
}

export interface ProviderTestResponse {
  ok: boolean
  latency_ms: number
  reply: string
  error: string | null
}

export interface ProviderTypePreset {
  type: ProviderType
  label: string
  base_url: string
  default_model: string
  api_key_hint: string
  /** 该 provider 常用模型清单（UI 提供下拉选择，可手动覆盖） */
  model_options?: { value: string; label: string }[]
}

export const PROVIDER_PRESETS: ProviderTypePreset[] = [
  {
    type: 'deepseek',
    label: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-v4-pro',
    api_key_hint: 'sk-xxxxxxxx',
    model_options: [
      { value: 'deepseek-v4-pro',   label: 'deepseek-v4-pro（旗舰 · 默认思考模式 · 推荐）' },
      { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash（轻量快速 · 批量任务首选）' },
      { value: 'deepseek-chat',     label: 'deepseek-chat（兼容老别名 = v4-flash 非思考 · 即将废弃）' },
      { value: 'deepseek-reasoner', label: 'deepseek-reasoner（兼容老别名 = v4-flash 思考 · 即将废弃）' },
    ],
  },
  {
    type: 'openai',
    label: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o-mini',
    api_key_hint: 'sk-xxxxxxxx',
    model_options: [
      { value: 'gpt-4o-mini', label: 'gpt-4o-mini' },
      { value: 'gpt-4o',      label: 'gpt-4o' },
      { value: 'o3-mini',     label: 'o3-mini' },
    ],
  },
  {
    type: 'qwen',
    label: '通义千问',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen-plus',
    api_key_hint: 'sk-xxxxxxxx',
    model_options: [
      { value: 'qwen-plus', label: 'qwen-plus' },
      { value: 'qwen-max',  label: 'qwen-max' },
    ],
  },
  {
    type: 'moonshot',
    label: 'Moonshot',
    base_url: 'https://api.moonshot.cn/v1',
    default_model: 'moonshot-v1-8k',
    api_key_hint: 'sk-xxxxxxxx',
    model_options: [
      { value: 'moonshot-v1-8k',   label: 'moonshot-v1-8k' },
      { value: 'moonshot-v1-32k',  label: 'moonshot-v1-32k' },
      { value: 'moonshot-v1-128k', label: 'moonshot-v1-128k' },
    ],
  },
  {
    type: 'zhipu',
    label: '智谱 GLM',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    default_model: 'glm-4-plus',
    api_key_hint: 'xxxxxxxx.xxxxxxxx',
    model_options: [
      { value: 'glm-4-plus', label: 'glm-4-plus' },
      { value: 'glm-4',      label: 'glm-4' },
    ],
  },
  {
    type: 'custom',
    label: '自定义',
    base_url: '',
    default_model: '',
    api_key_hint: '任意 OpenAI 兼容服务',
  },
]

export function getPreset(type: ProviderType): ProviderTypePreset | undefined {
  return PROVIDER_PRESETS.find((p) => p.type === type)
}

export const providersApi = {
  list: () => http.get<Provider[]>('/api/providers').then((r) => r.data),

  create: (payload: ProviderCreate) =>
    http.post<Provider>('/api/providers', payload).then((r) => r.data),

  update: (id: number, payload: ProviderUpdate) =>
    http.patch<Provider>(`/api/providers/${id}`, payload).then((r) => r.data),

  remove: (id: number) =>
    http.delete<{ ok: boolean }>(`/api/providers/${id}`).then((r) => r.data),

  setDefault: (id: number) =>
    http.post<Provider>(`/api/providers/${id}/default`).then((r) => r.data),

  test: (payload: ProviderTestRequest) =>
    http
      .post<ProviderTestResponse>('/api/providers/test', payload)
      .then((r) => r.data),
}
