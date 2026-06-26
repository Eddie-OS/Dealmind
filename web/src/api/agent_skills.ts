/**
 * 销冠技能配置 API（Stage 14）
 *
 * 后端：src/api/routes_agent_skills.py
 *   GET    /api/agent-skills/tools     可用工具列表 + enabled 标志
 *   GET    /api/agent-skills/config    当前配置
 *   PATCH  /api/agent-skills/config    部分更新
 *   POST   /api/agent-skills/test_tool 独立测试一个工具
 */
import { http } from './http'

export type ToolCategory = 'rag' | 'web' | 'mcp' | 'custom' | string

export interface ToolParamProperty {
  type?: string
  description?: string
  default?: unknown
  minimum?: number
  maximum?: number
  title?: string
  enum?: unknown[]
}

export interface ToolParameters {
  type: 'object'
  properties: Record<string, ToolParamProperty>
  required?: string[]
}

export interface ToolInfo {
  name: string
  description: string
  category: ToolCategory
  parameters: ToolParameters
  enabled: boolean
}

export interface ToolsListResp {
  tools: ToolInfo[]
  total: number
}

export interface McpServerCfg {
  name: string
  command?: string
  args?: string[]
  enabled?: boolean
  [k: string]: unknown
}

export interface SkillsConfig {
  enabled_tools: string[]
  max_tool_loops: number
  tool_top_k_default: number
  web_search_provider: string
  web_search_api_key: string
  mcp_servers: McpServerCfg[]
  extra_config: Record<string, unknown>
  updated_at?: string | null
}

export interface SkillsConfigUpdate {
  enabled_tools?: string[]
  max_tool_loops?: number
  tool_top_k_default?: number
  web_search_provider?: string
  web_search_api_key?: string
  mcp_servers?: McpServerCfg[]
  extra_config?: Record<string, unknown>
}

export interface TestToolReq {
  name: string
  arguments: Record<string, unknown>
  product_kb_id?: number | null
  enterprise_kb_id?: number | null
}

export interface TestToolResp {
  ok: boolean
  name: string
  arguments: Record<string, unknown>
  result: unknown
  error?: string | null
}

export interface TestWebSearchReq {
  query?: string
  top_k?: number
  provider?: string
  api_key?: string
}

export interface TestWebSearchResp {
  ok: boolean
  provider: string
  query: string
  error?: string | null
  result?: any
}

// ---------- MCP ----------

export interface McpServerCfgPayload {
  name: string
  command: string
  args?: string[]
  env?: Record<string, string>
  enabled?: boolean
}

export interface McpToolInfo {
  name: string
  description: string
  input_schema: Record<string, any>
}

export interface McpProbeResp {
  ok: boolean
  name: string
  server_info: Record<string, any>
  protocol_version?: string | null
  tools: McpToolInfo[]
  tool_count: number
  error?: string | null
}

export interface McpCallToolReq {
  server_name?: string
  server_cfg?: McpServerCfgPayload
  tool_name: string
  arguments?: Record<string, any>
}

export interface McpContentItem {
  type?: string
  text?: string
  [k: string]: any
}

export interface McpCallToolResp {
  ok: boolean
  is_error: boolean
  content: McpContentItem[]
  error?: string | null
}

export const agentSkillsApi = {
  tools: () =>
    http.get<ToolsListResp>('/api/agent-skills/tools').then((r) => r.data),
  config: () =>
    http.get<SkillsConfig>('/api/agent-skills/config').then((r) => r.data),
  updateConfig: (payload: SkillsConfigUpdate) =>
    http
      .patch<SkillsConfig>('/api/agent-skills/config', payload)
      .then((r) => r.data),
  testTool: (payload: TestToolReq) =>
    http
      .post<TestToolResp>('/api/agent-skills/test_tool', payload)
      .then((r) => r.data),
  testWebSearch: (payload: TestWebSearchReq) =>
    http
      .post<TestWebSearchResp>('/api/agent-skills/test_web_search', payload)
      .then((r) => r.data),
  mcpProbe: (cfg: McpServerCfgPayload) =>
    http.post<McpProbeResp>('/api/agent-skills/mcp/probe', cfg).then((r) => r.data),
  mcpCallTool: (payload: McpCallToolReq) =>
    http
      .post<McpCallToolResp>('/api/agent-skills/mcp/call_tool', payload)
      .then((r) => r.data),
}
