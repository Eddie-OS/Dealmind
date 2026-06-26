<script setup lang="ts">
/**
 * 销冠技能配置（Stage 14）
 *
 * 3 块：
 *  1. 全局参数：max_tool_loops / tool_top_k_default / web_search_provider+key
 *  2. 工具列表：每个工具一张卡，开关 + 描述 + 参数 schema + 「测试」按钮
 *  3. 测试结果抽屉：传 query/top_k → 调 /test_tool 看真实返回
 */
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElSelect,
  ElOption,
  ElSkeleton,
  ElSwitch,
  ElTag,
} from 'element-plus'
import {
  RefreshCcw,
  Wrench,
  Play,
  Save,
  Sparkles,
  Server,
  Plus,
  Trash2,
  Activity,
} from '@lucide/vue'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  agentSkillsApi,
  type McpServerCfgPayload,
  type McpToolInfo,
  type SkillsConfig,
  type ToolInfo,
} from '@/api/agent_skills'

// ============================================================
// 状态
// ============================================================

const loadingTools = ref(true)
const loadingConfig = ref(true)
const savingConfig = ref(false)
const tools = ref<ToolInfo[]>([])
const config = ref<SkillsConfig | null>(null)

// 拷贝一份用于编辑，避免直接改远端引用
const edit = ref<SkillsConfig>({
  enabled_tools: [],
  max_tool_loops: 3,
  tool_top_k_default: 3,
  web_search_provider: 'tavily',
  web_search_api_key: '',
  mcp_servers: [],
  extra_config: {},
})

const enabledSet = computed(() => new Set(edit.value.enabled_tools))

// 测试工具抽屉
const drawerVisible = ref(false)
const drawerTool = ref<ToolInfo | null>(null)
const drawerArgs = ref<Record<string, any>>({})
const drawerProductKb = ref<number | null>(null)
const drawerEnterpriseKb = ref<number | null>(null)
const drawerTesting = ref(false)
const drawerResult = ref<any>(null)
const drawerError = ref<string | null>(null)

// Web Search 联通性测试
const testingWeb = ref(false)
const webTestResp = ref<{ ok: boolean; provider: string; error?: string | null; result?: any } | null>(null)

// ============================================================
// MCP servers
// ============================================================
interface McpRowState {
  cfg: McpServerCfgPayload
  probing: boolean
  probeError: string | null
  tools: McpToolInfo[]
  toolsExpanded: boolean
}
const mcpRows = ref<McpRowState[]>([])

// 新增 server 对话框
const mcpDialogVisible = ref(false)
const mcpForm = ref<McpServerCfgPayload>({
  name: '',
  command: '',
  args: [],
  env: {},
  enabled: true,
})
const mcpArgsText = ref('')

// MCP tool 测试抽屉
const mcpToolDrawerVisible = ref(false)
const mcpToolDrawerRow = ref<McpRowState | null>(null)
const mcpToolDrawerTool = ref<McpToolInfo | null>(null)
const mcpToolDrawerArgs = ref<Record<string, any>>({})
const mcpToolDrawerTesting = ref(false)
const mcpToolDrawerResult = ref<any>(null)
const mcpToolDrawerError = ref<string | null>(null)

function syncMcpRowsFromEdit() {
  mcpRows.value = (edit.value.mcp_servers || []).map((s: any) => ({
    cfg: {
      name: String(s.name || ''),
      command: String(s.command || ''),
      args: Array.isArray(s.args) ? s.args.map(String) : [],
      env: (s.env && typeof s.env === 'object') ? s.env : {},
      enabled: s.enabled !== false,
    },
    probing: false,
    probeError: null,
    tools: [],
    toolsExpanded: false,
  }))
}

function openAddMcpDialog() {
  mcpForm.value = { name: '', command: '', args: [], env: {}, enabled: true }
  mcpArgsText.value = ''
  mcpDialogVisible.value = true
}

async function confirmAddMcp() {
  const name = (mcpForm.value.name || '').trim()
  const command = (mcpForm.value.command || '').trim()
  if (!name || !command) {
    ElMessage.warning('请填写 name 和 command')
    return
  }
  if (mcpRows.value.some((r) => r.cfg.name === name)) {
    ElMessage.warning(`已存在同名 server：${name}`)
    return
  }
  const args = mcpArgsText.value
    .split(/\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
  const cfg: McpServerCfgPayload = {
    name,
    command,
    args,
    env: mcpForm.value.env || {},
    enabled: true,
  }
  mcpRows.value.push({
    cfg,
    probing: false,
    probeError: null,
    tools: [],
    toolsExpanded: false,
  })
  // 同步回 edit.mcp_servers
  edit.value.mcp_servers = mcpRows.value.map((r) => ({ ...r.cfg }))
  mcpDialogVisible.value = false
  ElMessage.success(`已添加 ${name}（记得点保存配置持久化）`)
}

async function deleteMcpRow(row: McpRowState) {
  try {
    await ElMessageBox.confirm(
      `确认移除 MCP server「${row.cfg.name}」？该操作不会立即落库，需要点保存配置才生效。`,
      '移除确认',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  mcpRows.value = mcpRows.value.filter((r) => r !== row)
  edit.value.mcp_servers = mcpRows.value.map((r) => ({ ...r.cfg }))
}

function toggleMcpEnabled(row: McpRowState, on: boolean) {
  row.cfg.enabled = on
  edit.value.mcp_servers = mcpRows.value.map((r) => ({ ...r.cfg }))
}

async function probeMcpRow(row: McpRowState) {
  row.probing = true
  row.probeError = null
  row.tools = []
  try {
    const resp = await agentSkillsApi.mcpProbe(row.cfg)
    if (!resp.ok) {
      row.probeError = resp.error || '探活失败'
      ElMessage.warning(`「${row.cfg.name}」探活失败`)
    } else {
      row.tools = resp.tools || []
      row.toolsExpanded = true
      ElMessage.success(`「${row.cfg.name}」OK，发现 ${row.tools.length} 个 tool`)
    }
  } finally {
    row.probing = false
  }
}

function openMcpToolDrawer(row: McpRowState, tool: McpToolInfo) {
  mcpToolDrawerRow.value = row
  mcpToolDrawerTool.value = tool
  mcpToolDrawerArgs.value = buildDefaultMcpArgs(tool)
  mcpToolDrawerResult.value = null
  mcpToolDrawerError.value = null
  mcpToolDrawerVisible.value = true
}

function buildDefaultMcpArgs(tool: McpToolInfo): Record<string, any> {
  const out: Record<string, any> = {}
  const props = tool.input_schema?.properties || {}
  for (const [k, v] of Object.entries<any>(props)) {
    if (v?.default !== undefined) out[k] = v.default
    else if (v?.type === 'integer' || v?.type === 'number') out[k] = v?.minimum ?? 0
    else if (v?.type === 'boolean') out[k] = false
    else out[k] = ''
  }
  return out
}

async function runMcpTool() {
  if (!mcpToolDrawerRow.value || !mcpToolDrawerTool.value) return
  mcpToolDrawerTesting.value = true
  mcpToolDrawerResult.value = null
  mcpToolDrawerError.value = null
  try {
    const resp = await agentSkillsApi.mcpCallTool({
      server_cfg: mcpToolDrawerRow.value.cfg,
      tool_name: mcpToolDrawerTool.value.name,
      arguments: mcpToolDrawerArgs.value,
    })
    if (resp.ok && !resp.is_error) {
      mcpToolDrawerResult.value = resp.content || []
    } else {
      mcpToolDrawerError.value = resp.error || 'tool 返回 is_error=true'
      if (resp.content?.length) mcpToolDrawerResult.value = resp.content
    }
  } finally {
    mcpToolDrawerTesting.value = false
  }
}

function mcpParamKeys(tool: McpToolInfo): string[] {
  return Object.keys(tool.input_schema?.properties || {})
}

// ============================================================
// 加载
// ============================================================

async function loadAll() {
  await Promise.all([loadTools(), loadConfig()])
}

async function loadTools() {
  loadingTools.value = true
  try {
    const resp = await agentSkillsApi.tools()
    tools.value = resp.tools || []
  } catch {
    tools.value = []
  } finally {
    loadingTools.value = false
  }
}

async function loadConfig() {
  loadingConfig.value = true
  try {
    const cfg = await agentSkillsApi.config()
    config.value = cfg
    edit.value = {
      enabled_tools: [...(cfg.enabled_tools || [])],
      max_tool_loops: cfg.max_tool_loops,
      tool_top_k_default: cfg.tool_top_k_default,
      web_search_provider: cfg.web_search_provider || 'tavily',
      web_search_api_key: cfg.web_search_api_key || '',
      mcp_servers: cfg.mcp_servers || [],
      extra_config: cfg.extra_config || {},
    }
    syncMcpRowsFromEdit()
  } catch {
    // 全局拦截器已弹错误提示
  } finally {
    loadingConfig.value = false
  }
}

onMounted(loadAll)

// ============================================================
// 操作
// ============================================================

function toggleTool(name: string, on: boolean) {
  const set = new Set(edit.value.enabled_tools)
  if (on) set.add(name)
  else set.delete(name)
  edit.value.enabled_tools = Array.from(set)
}

async function saveAll() {
  savingConfig.value = true
  try {
    // 用 mcpRows 当真相，写回 edit.mcp_servers
    edit.value.mcp_servers = mcpRows.value.map((r) => ({ ...r.cfg }))
    const cfg = await agentSkillsApi.updateConfig({
      enabled_tools: edit.value.enabled_tools,
      max_tool_loops: edit.value.max_tool_loops,
      tool_top_k_default: edit.value.tool_top_k_default,
      web_search_provider: edit.value.web_search_provider,
      web_search_api_key: edit.value.web_search_api_key,
      mcp_servers: edit.value.mcp_servers,
    })
    config.value = cfg
    ElMessage.success('配置已保存')
    await loadTools()
  } finally {
    savingConfig.value = false
  }
}

function openTestDrawer(tool: ToolInfo) {
  drawerTool.value = tool
  drawerArgs.value = buildDefaultArgs(tool)
  drawerResult.value = null
  drawerError.value = null
  drawerVisible.value = true
}

function buildDefaultArgs(tool: ToolInfo): Record<string, any> {
  const args: Record<string, any> = {}
  const props = tool.parameters?.properties || {}
  for (const [k, v] of Object.entries(props)) {
    if (v?.default !== undefined) {
      args[k] = v.default
    } else if (v?.type === 'integer' || v?.type === 'number') {
      args[k] = v?.minimum ?? 0
    } else if (v?.type === 'boolean') {
      args[k] = false
    } else {
      args[k] = ''
    }
  }
  // 给 query 一个示例默认值，方便用户一键测
  if ('query' in args && !args.query) args.query = '价格 vs 友商'
  if ('top_k' in args && !args.top_k) args.top_k = 3
  return args
}

async function testWebSearch() {
  testingWeb.value = true
  webTestResp.value = null
  try {
    const resp = await agentSkillsApi.testWebSearch({
      query: '华为 MatePad 12X 价格 vs iPad',
      top_k: 3,
      provider: edit.value.web_search_provider,
      api_key: edit.value.web_search_api_key || undefined,
    })
    webTestResp.value = resp
    if (resp.ok) ElMessage.success('Web Search 联通成功')
    else ElMessage.warning('Web Search 测试失败：见下方提示')
  } finally {
    testingWeb.value = false
  }
}

async function runTest() {
  if (!drawerTool.value) return
  drawerTesting.value = true
  drawerResult.value = null
  drawerError.value = null
  try {
    const resp = await agentSkillsApi.testTool({
      name: drawerTool.value.name,
      arguments: drawerArgs.value,
      product_kb_id: drawerProductKb.value,
      enterprise_kb_id: drawerEnterpriseKb.value,
    })
    if (resp.ok) {
      drawerResult.value = resp.result
    } else {
      drawerError.value = resp.error || '工具调用失败'
    }
  } finally {
    drawerTesting.value = false
  }
}

// ============================================================
// 衍生数据
// ============================================================

function paramKeys(tool: ToolInfo): string[] {
  return Object.keys(tool.parameters?.properties || {})
}

function paramHint(tool: ToolInfo, key: string): string {
  const p = tool.parameters?.properties?.[key]
  if (!p) return ''
  const parts: string[] = [p.type || 'any']
  if (p.default !== undefined) parts.push(`默认=${p.default}`)
  if (p.minimum !== undefined || p.maximum !== undefined) {
    parts.push(`范围 ${p.minimum ?? '?'} ~ ${p.maximum ?? '?'}`)
  }
  return parts.join(' · ')
}

function categoryTag(c: string): 'success' | 'info' | 'warning' | 'primary' | 'danger' {
  switch (c) {
    case 'rag': return 'primary'
    case 'web': return 'success'
    case 'mcp': return 'warning'
    default: return 'info'
  }
}

const enabledCount = computed(() => edit.value.enabled_tools.length)
</script>

<template>
  <div class="page-wrap">
    <DmPageHeader title="销冠技能" subtitle="给销冠 Agent 配置可调用的检索工具（RAG / Web Search / MCP）">
      <template #actions>
        <ElButton :icon="RefreshCcw" @click="loadAll">刷新</ElButton>
        <ElButton type="primary" :icon="Save" :loading="savingConfig" @click="saveAll">
          保存配置
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 1. 全局参数 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Sparkles /></ElIcon>
          <span>全局参数</span>
          <span class="block-hint">
            当前启用 {{ enabledCount }} 个工具
            <span v-if="config?.updated_at" class="dm-text-muted">
              · 更新于 {{ config.updated_at }}
            </span>
          </span>
        </div>
      </template>

      <ElSkeleton v-if="loadingConfig" :rows="3" animated />

      <ElForm v-else label-position="top" class="global-form">
        <ElFormItem label="单轮最大工具调用次数（max_tool_loops）">
          <ElInputNumber
            v-model="edit.max_tool_loops"
            :min="0"
            :max="8"
            controls-position="right"
            style="width: 160px"
          />
          <span class="form-hint">
            0 = 关闭工具自助检索（销冠 Agent 走原来的预 RAG 注入路径）
          </span>
        </ElFormItem>

        <ElFormItem label="工具默认 top_k（tool_top_k_default）">
          <ElInputNumber
            v-model="edit.tool_top_k_default"
            :min="1"
            :max="10"
            controls-position="right"
            style="width: 160px"
          />
          <span class="form-hint">仅作为前端默认值参考，实际 top_k 由 LLM 在工具入参里指定</span>
        </ElFormItem>

        <ElFormItem label="Web Search Provider">
          <ElSelect v-model="edit.web_search_provider" style="width: 200px">
            <ElOption label="Tavily" value="tavily" />
            <ElOption label="SerpAPI" value="serpapi" />
            <ElOption label="Bing（暂未接入）" value="bing" disabled />
          </ElSelect>
          <span class="form-hint">
            推荐 Tavily：免费额度大、返回带 LLM 摘要；SerpAPI 走 Google。
          </span>
        </ElFormItem>

        <ElFormItem label="Web Search API Key">
          <div class="key-row">
            <ElInput
              v-model="edit.web_search_api_key"
              type="password"
              show-password
              placeholder="必须填，否则销冠所有 web_search 调用都会返回 error"
              style="max-width: 360px"
            />
            <ElButton
              size="default"
              :icon="Play"
              :loading="testingWeb"
              @click="testWebSearch"
            >
              测试联通
            </ElButton>
          </div>
          <ElAlert
            v-if="!edit.web_search_api_key"
            type="warning"
            :closable="false"
            show-icon
            style="margin-top: 8px; max-width: 720px;"
          >
            <template #title>
              ⚠️ Key 未配置 — 销冠的 web_search 工具完全不可用
            </template>
            <div style="font-size: 13px; line-height: 1.6;">
              · LLM 训练数据有截止时间，**不知道最近新发布的型号 / 政策 / 友商动态**；<br/>
              · 客户一旦问到这类问题，销冠只能基于老知识回答（甚至会说"还没上市"）；<br/>
              · 推荐去
              <a href="https://app.tavily.com/" target="_blank" rel="noopener">app.tavily.com</a>
              注册 Tavily 账号（含 1000 次/月免费额度），把 API Key 粘到上方输入框，保存后立即生效。
            </div>
          </ElAlert>
          <div v-if="webTestResp" class="web-test-result" :class="{ err: !webTestResp.ok }">
            <template v-if="webTestResp.ok">
              <div class="web-test-line">
                ✅ {{ webTestResp.provider }} 联通 OK · 返回
                {{ (webTestResp.result?.results || []).length }} 条结果
              </div>
              <div v-if="webTestResp.result?.answer" class="web-test-answer">
                <span class="web-test-tag">摘要</span>
                {{ webTestResp.result.answer }}
              </div>
              <ul class="web-test-list">
                <li v-for="(it, i) in (webTestResp.result?.results || []).slice(0, 3)" :key="i">
                  <a :href="it.url" target="_blank" rel="noopener">{{ it.title || it.url }}</a>
                  <div class="web-test-snippet">{{ it.snippet }}</div>
                </li>
              </ul>
            </template>
            <template v-else>
              ❌ {{ webTestResp.error || '测试失败' }}
            </template>
          </div>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <!-- 2. 工具列表 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Wrench /></ElIcon>
          <span>可用工具</span>
          <span class="block-hint">共 {{ tools.length }} 个</span>
        </div>
      </template>

      <ElSkeleton v-if="loadingTools" :rows="4" animated />

      <ElEmpty v-else-if="!tools.length" description="未注册任何工具" :image-size="80" />

      <div v-else class="tool-grid">
        <div v-for="t in tools" :key="t.name" class="tool-card">
          <div class="tool-head">
            <div class="tool-title">
              <span class="tool-name mono">{{ t.name }}</span>
              <ElTag :type="categoryTag(t.category)" size="small" effect="light">
                {{ t.category }}
              </ElTag>
            </div>
            <ElSwitch
              :model-value="enabledSet.has(t.name)"
              @update:model-value="(v: any) => toggleTool(t.name, Boolean(v))"
            />
          </div>

          <div class="tool-desc">{{ t.description }}</div>

          <div class="tool-params">
            <div class="sub-title-tiny">入参</div>
            <div v-if="!paramKeys(t).length" class="dm-text-muted">（无入参）</div>
            <div
              v-for="k in paramKeys(t)"
              :key="k"
              class="param-row"
            >
              <span class="param-key mono">{{ k }}</span>
              <span class="param-meta">{{ paramHint(t, k) }}</span>
              <span class="param-desc">
                {{ t.parameters.properties[k]?.description || '' }}
              </span>
            </div>
          </div>

          <div class="tool-actions">
            <ElButton size="small" :icon="Play" @click="openTestDrawer(t)">
              测试
            </ElButton>
          </div>
        </div>
      </div>
    </ElCard>

    <!-- MCP Servers（Phase C） -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Server /></ElIcon>
          <span>MCP Servers</span>
          <span class="block-hint">
            stdio 协议外接，已配置 {{ mcpRows.length }} 个
          </span>
          <span style="flex: 1" />
          <ElButton size="small" :icon="Plus" type="primary" plain @click="openAddMcpDialog">
            添加 server
          </ElButton>
        </div>
      </template>

      <ElEmpty
        v-if="!mcpRows.length"
        description="还没添加任何 MCP server。常见示例：npx -y @modelcontextprotocol/server-everything"
        :image-size="80"
      />

      <div v-else class="mcp-list">
        <div v-for="row in mcpRows" :key="row.cfg.name" class="mcp-card">
          <div class="mcp-head">
            <div class="mcp-title">
              <ElTag size="small" effect="plain" type="warning">MCP</ElTag>
              <span class="mcp-name">{{ row.cfg.name }}</span>
              <span v-if="row.tools.length" class="dm-text-muted dm-text-small">
                · {{ row.tools.length }} tools
              </span>
            </div>
            <div class="mcp-actions">
              <ElSwitch
                :model-value="row.cfg.enabled !== false"
                @update:model-value="(v: any) => toggleMcpEnabled(row, Boolean(v))"
              />
              <ElButton
                size="small"
                :icon="Activity"
                :loading="row.probing"
                @click="probeMcpRow(row)"
              >
                探活并列工具
              </ElButton>
              <ElButton
                size="small"
                :icon="Trash2"
                type="danger"
                plain
                @click="deleteMcpRow(row)"
              >
                移除
              </ElButton>
            </div>
          </div>

          <div class="mcp-cmd mono">
            $ {{ row.cfg.command }}<span v-if="row.cfg.args?.length">
              {{ (row.cfg.args || []).join(' ') }}</span>
          </div>

          <div v-if="row.probeError" class="mcp-err">
            探活失败：{{ row.probeError }}
          </div>

          <div v-if="row.toolsExpanded && row.tools.length" class="mcp-tools">
            <div class="sub-title-tiny">该 server 暴露的 tools</div>
            <div
              v-for="t in row.tools"
              :key="t.name"
              class="mcp-tool-item"
            >
              <div class="mcp-tool-title">
                <span class="mono">{{ t.name }}</span>
                <ElButton size="small" :icon="Play" link @click="openMcpToolDrawer(row, t)">
                  测试
                </ElButton>
              </div>
              <div v-if="t.description" class="dm-text-small dm-text-muted">
                {{ t.description }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="mcp-note dm-text-small dm-text-muted">
        提示：MCP server 在主进程通过 stdio 子进程方式启动，每次探活/测试约 1-3s 开销。
        本轮暂未把 MCP tools 自动注入 LLM tool 列表（避免对话延迟），如有需求下一阶段加 lazy 注册。
      </div>
    </ElCard>

    <!-- 添加 MCP server dialog -->
    <ElDialog v-model="mcpDialogVisible" title="添加 MCP server" width="540">
      <ElForm label-position="top">
        <ElFormItem label="别名 name（必填，全局唯一）">
          <ElInput v-model="mcpForm.name" placeholder="例如 my-fs / search-everything" />
        </ElFormItem>
        <ElFormItem label="命令 command（必填，绝对路径或在 PATH 中可用）">
          <ElInput v-model="mcpForm.command" placeholder="例如 npx 或 python" />
        </ElFormItem>
        <ElFormItem label="参数 args（空格分隔）">
          <ElInput
            v-model="mcpArgsText"
            type="textarea"
            :rows="2"
            placeholder="例如 -y @modelcontextprotocol/server-everything"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="mcpDialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="confirmAddMcp">添加</ElButton>
      </template>
    </ElDialog>

    <!-- MCP 工具测试抽屉 -->
    <ElDrawer
      v-model="mcpToolDrawerVisible"
      direction="rtl"
      size="560"
      :title="
        mcpToolDrawerTool && mcpToolDrawerRow
          ? '测试 MCP 工具：' + mcpToolDrawerRow.cfg.name + ' / ' + mcpToolDrawerTool.name
          : '测试 MCP 工具'
      "
    >
      <template v-if="mcpToolDrawerTool && mcpToolDrawerRow">
        <div class="drawer-desc">{{ mcpToolDrawerTool.description || '（无描述）' }}</div>

        <ElForm label-position="top" class="drawer-form">
          <ElFormItem
            v-for="k in mcpParamKeys(mcpToolDrawerTool)"
            :key="k"
            :label="k + '（' + (mcpToolDrawerTool.input_schema?.properties?.[k]?.type || 'any') + '）'"
          >
            <ElInputNumber
              v-if="mcpToolDrawerTool.input_schema?.properties?.[k]?.type === 'integer'
                || mcpToolDrawerTool.input_schema?.properties?.[k]?.type === 'number'"
              v-model="mcpToolDrawerArgs[k]"
              controls-position="right"
              style="width: 160px"
            />
            <ElInput v-else v-model="mcpToolDrawerArgs[k]" />
            <div
              v-if="mcpToolDrawerTool.input_schema?.properties?.[k]?.description"
              class="form-hint"
            >
              {{ mcpToolDrawerTool.input_schema.properties[k].description }}
            </div>
          </ElFormItem>
        </ElForm>

        <div class="drawer-actions">
          <ElButton type="primary" :icon="Play" :loading="mcpToolDrawerTesting" @click="runMcpTool">
            运行
          </ElButton>
        </div>

        <div class="drawer-result">
          <div class="sub-title">运行结果</div>
          <div v-if="mcpToolDrawerError" class="result-err">
            {{ mcpToolDrawerError }}
          </div>
          <pre
            v-if="mcpToolDrawerResult"
            class="result-pre"
          >{{ JSON.stringify(mcpToolDrawerResult, null, 2) }}</pre>
          <div v-else-if="!mcpToolDrawerError" class="dm-text-muted">
            点击「运行」查看结果
          </div>
        </div>
      </template>
    </ElDrawer>

    <!-- 3. 测试抽屉 -->
    <ElDrawer
      v-model="drawerVisible"
      direction="rtl"
      size="520"
      :title="drawerTool ? '测试工具：' + drawerTool.name : '测试工具'"
    >
      <template v-if="drawerTool">
        <div class="drawer-desc">{{ drawerTool.description }}</div>

        <ElForm label-position="top" class="drawer-form">
          <ElFormItem
            v-for="k in paramKeys(drawerTool)"
            :key="k"
            :label="k + '（' + (drawerTool.parameters.properties[k]?.type || 'any') + '）'"
          >
            <ElInputNumber
              v-if="drawerTool.parameters.properties[k]?.type === 'integer' || drawerTool.parameters.properties[k]?.type === 'number'"
              v-model="drawerArgs[k]"
              :min="drawerTool.parameters.properties[k]?.minimum"
              :max="drawerTool.parameters.properties[k]?.maximum"
              controls-position="right"
              style="width: 160px"
            />
            <ElInput v-else v-model="drawerArgs[k]" />
            <div v-if="drawerTool.parameters.properties[k]?.description" class="form-hint">
              {{ drawerTool.parameters.properties[k]?.description }}
            </div>
          </ElFormItem>

          <ElFormItem
            v-if="drawerTool.name === 'search_product_kb'"
            label="product_kb_id（上下文，可选）"
          >
            <ElInputNumber v-model="drawerProductKb" :min="1" style="width: 160px" />
          </ElFormItem>
          <ElFormItem
            v-if="drawerTool.name === 'search_enterprise_kb'"
            label="enterprise_kb_id（上下文，可选）"
          >
            <ElInputNumber v-model="drawerEnterpriseKb" :min="1" style="width: 160px" />
          </ElFormItem>
        </ElForm>

        <div class="drawer-actions">
          <ElButton type="primary" :icon="Play" :loading="drawerTesting" @click="runTest">
            运行
          </ElButton>
        </div>

        <div class="drawer-result">
          <div class="sub-title">运行结果</div>
          <div v-if="drawerError" class="result-err">{{ drawerError }}</div>
          <pre v-else-if="drawerResult" class="result-pre">{{ JSON.stringify(drawerResult, null, 2) }}</pre>
          <div v-else class="dm-text-muted">点击「运行」查看结果</div>
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped lang="scss">
.page-wrap {
  padding: 24px 28px 60px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.block-card {
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 12px;
}

.block-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;

  .block-hint {
    font-weight: 400;
    color: var(--dm-text-muted, #8b8a87);
    font-size: 12px;
    margin-left: 4px;
  }
}

.sub-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dm-text-muted, #8b8a87);
  margin: 14px 0 8px;
  letter-spacing: 0.5px;
}
.sub-title-tiny {
  font-size: 11px;
  font-weight: 600;
  color: var(--dm-text-muted, #8b8a87);
  margin: 8px 0 4px;
  letter-spacing: 0.5px;
}

.mono {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
}

.dm-text-muted {
  color: var(--dm-text-muted, #8b8a87);
}

.global-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 24px;
}
.form-hint {
  font-size: 12px;
  color: var(--dm-text-muted, #8b8a87);
  margin-left: 12px;
}

.key-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.web-test-result {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  font-size: 12.5px;
  line-height: 1.55;
  max-width: 720px;

  &.err {
    background: #fef2f2;
    border-color: #fecaca;
    color: #b91c1c;
  }
}
.web-test-line { font-weight: 600; }
.web-test-answer {
  margin-top: 6px;
  padding: 6px 8px;
  background: #fff;
  border: 1px dashed #a7f3d0;
  border-radius: 6px;
}
.web-test-tag {
  background: #10b981;
  color: #fff;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 11px;
  margin-right: 6px;
}
.web-test-list {
  margin: 8px 0 0;
  padding-left: 18px;

  li { margin-bottom: 6px; }
  a {
    color: #0369a1;
    text-decoration: none;
    &:hover { text-decoration: underline; }
  }
}
.web-test-snippet {
  color: #475569;
  font-size: 12px;
  margin-top: 2px;
}

.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}

.tool-card {
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--dm-bg-surface, #fff);
}

.tool-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tool-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tool-name {
  font-weight: 600;
}
.tool-desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--dm-text, #2c2b29);
}
.tool-params {
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 6px;
  padding: 8px 10px;
}
.param-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
  padding: 2px 0;
}
.param-key {
  min-width: 70px;
  color: #4f46e5;
}
.param-meta {
  color: var(--dm-text-muted, #8b8a87);
  white-space: nowrap;
}
.param-desc {
  color: var(--dm-text, #2c2b29);
}
.tool-actions {
  display: flex;
  justify-content: flex-end;
}

.drawer-desc {
  font-size: 13px;
  color: var(--dm-text, #2c2b29);
  margin-bottom: 14px;
}
.drawer-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.drawer-actions {
  margin: 12px 0 6px;
}
.drawer-result {
  border-top: 1px dashed var(--dm-border, #ebebea);
  padding-top: 8px;
}
.result-pre {
  background: #0f172a;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.55;
  padding: 12px;
  border-radius: 6px;
  max-height: 360px;
  overflow: auto;
}
.result-err {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12.5px;
}

// ===== MCP =====
.mcp-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mcp-card {
  border: 1px solid var(--dm-border, #ebebea);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--dm-bg-surface, #fff);
}
.mcp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.mcp-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-name {
  font-weight: 600;
  font-size: 14px;
}
.mcp-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mcp-cmd {
  background: #0f172a;
  color: #e2e8f0;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  margin: 8px 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.mcp-err {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12.5px;
  margin-bottom: 6px;
}
.mcp-tools {
  background: var(--dm-bg-subtle, #f7f6f3);
  border-radius: 8px;
  padding: 8px 10px;
  margin-top: 6px;
}
.mcp-tool-item {
  padding: 4px 0;
  border-bottom: 1px dashed var(--dm-border, #ebebea);

  &:last-child {
    border-bottom: none;
  }
}
.mcp-tool-title {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: space-between;
}
.mcp-note {
  margin-top: 12px;
  padding: 8px 10px;
  background: #fffbeb;
  border: 1px dashed #fde68a;
  border-radius: 6px;
}
</style>
