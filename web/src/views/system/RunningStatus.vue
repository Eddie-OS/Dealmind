<script setup lang="ts">
/**
 * 运行状态（Stage 12）
 *
 * 4 块信息：
 *  1. 系统信息（Python / 平台 / 关键依赖版本 + 关键目录大小）
 *  2. LLM 调用统计（今日核心指标 + 近 7 天柱状）
 *  3. 后台任务（活跃 sessions + batches）
 *  4. 日志查看器（最近 N 行 + 手动刷新 / 自动刷新 / 行数选择 / 关键字过滤）
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElEmpty,
  ElIcon,
  ElInput,
  ElMessage,
  ElSelect,
  ElOption,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElSkeleton,
} from 'element-plus'
import {
  RefreshCcw,
  Search,
  Activity,
  Server,
  HardDrive,
  Cpu,
} from '@lucide/vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  statusApi,
  type LlmStats,
  type SystemInfo,
  type TasksResp,
  type LogsResp,
} from '@/api/status'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
])

// ============================================================
// 状态
// ============================================================

const loadingSystem = ref(true)
const loadingStats = ref(true)
const loadingTasks = ref(true)
const loadingLogs = ref(true)

const system = ref<SystemInfo | null>(null)
const stats = ref<LlmStats | null>(null)
const tasks = ref<TasksResp | null>(null)
const logs = ref<LogsResp | null>(null)

const logLines = ref(200)
const logKeyword = ref('')
const logAuto = ref(false)
let logTimer: ReturnType<typeof setInterval> | null = null

// ============================================================
// 加载
// ============================================================

async function loadSystem() {
  loadingSystem.value = true
  try {
    system.value = await statusApi.system()
  } catch {
    // 全局拦截器已弹错；这里不重复
  } finally {
    loadingSystem.value = false
  }
}

async function loadStats() {
  loadingStats.value = true
  try {
    stats.value = await statusApi.llmStats(7)
  } catch {
  } finally {
    loadingStats.value = false
  }
}

async function loadTasks() {
  loadingTasks.value = true
  try {
    tasks.value = await statusApi.tasks()
  } catch {
  } finally {
    loadingTasks.value = false
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    logs.value = await statusApi.logs(logLines.value)
  } catch {
  } finally {
    loadingLogs.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadSystem(), loadStats(), loadTasks(), loadLogs()])
  ElMessage.success('已刷新')
}

// ============================================================
// 日志自动刷新
// ============================================================

watch(logAuto, (on) => {
  if (logTimer) {
    clearInterval(logTimer)
    logTimer = null
  }
  if (on) {
    logTimer = setInterval(() => loadLogs(), 5000)
  }
})

// ============================================================
// 图表
// ============================================================

const chartOption = computed(() => {
  const days = stats.value?.by_day || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['销冠', '客户', '会话数'], top: 0 },
    grid: { left: 36, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#e5e4e0' } },
      axisLabel: { color: '#888888', fontSize: 11 },
    },
    yAxis: [
      {
        type: 'value',
        name: 'turns',
        axisLine: { show: false },
        splitLine: { lineStyle: { color: '#f1f1f1' } },
      },
      {
        type: 'value',
        name: 'sessions',
        axisLine: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '销冠',
        type: 'bar',
        stack: 'turns',
        data: days.map((d) => d.sales),
        itemStyle: { color: '#3b82f6' },
        barMaxWidth: 28,
      },
      {
        name: '客户',
        type: 'bar',
        stack: 'turns',
        data: days.map((d) => d.persona),
        itemStyle: { color: '#f59e0b' },
        barMaxWidth: 28,
      },
      {
        name: '会话数',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: days.map((d) => d.sessions),
        lineStyle: { color: '#10b981', width: 2 },
        itemStyle: { color: '#10b981' },
      },
    ],
  }
})

// ============================================================
// 派生 / 过滤
// ============================================================

const filteredLogs = computed(() => {
  const all = logs.value?.lines || []
  const kw = logKeyword.value.trim().toLowerCase()
  if (!kw) return all
  return all.filter((ln) => ln.toLowerCase().includes(kw))
})

const sysSizesTable = computed(() => {
  const s = system.value
  if (!s) return []
  return Object.entries(s.sizes_human).map(([k, v]) => ({
    name: k,
    size: v,
    bytes: s.sizes_bytes[k] || 0,
    path: s.paths[k] || '—',
  }))
})

const depsList = computed(() => {
  const d = system.value?.deps || {}
  return Object.entries(d).map(([name, version]) => ({ name, version }))
})

const sessionsList = computed(() => tasks.value?.sessions || [])
const batchesList = computed(() => tasks.value?.batches || [])

function statusTagType(s: string): string {
  switch (s) {
    case 'running': return 'warning'
    case 'done':
    case 'completed': return 'success'
    case 'cancelled':
    case 'failed': return 'danger'
    default: return 'info'
  }
}

onMounted(() => {
  refreshAll()
})

onUnmounted(() => {
  if (logTimer) clearInterval(logTimer)
})
</script>

<template>
  <div class="running-status">
    <DmPageHeader
      title="运行状态"
      subtitle="系统进程 · 关键依赖 · 后台任务 · 日志查看（开发自检）"
    >
      <template #actions>
        <ElButton @click="refreshAll">
          <ElIcon><RefreshCcw /></ElIcon>
          <span style="margin-left: 6px">刷新全部</span>
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 1. 系统信息 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Server /></ElIcon>
          <span>系统信息</span>
        </div>
      </template>

      <ElSkeleton v-if="loadingSystem" :rows="4" animated />

      <template v-else-if="system">
        <div class="kv-grid">
          <div class="kv">
            <span class="k">Python</span>
            <span class="v">
              {{ system.python.implementation }} {{ system.python.version }}
            </span>
          </div>
          <div class="kv">
            <span class="k">平台</span>
            <span class="v">
              {{ system.platform.system }} {{ system.platform.release }} ·
              {{ system.platform.machine }}
            </span>
          </div>
          <div class="kv">
            <span class="k">工作目录</span>
            <span class="v mono">{{ system.paths.cwd }}</span>
          </div>
          <div class="kv">
            <span class="k">项目根</span>
            <span class="v mono">{{ system.paths.project_root }}</span>
          </div>
        </div>

        <div class="sub-title">关键依赖</div>
        <div class="deps">
          <span v-for="d in depsList" :key="d.name" class="dep-pill">
            {{ d.name }} <span class="dep-ver">{{ d.version }}</span>
          </span>
        </div>

        <div class="sub-title">关键目录占用</div>
        <ElTable
          :data="sysSizesTable"
          size="small"
          stripe
          :show-header="true"
          style="width: 100%"
        >
          <ElTableColumn prop="name" label="名称" width="120" />
          <ElTableColumn prop="size" label="占用" width="120" />
          <ElTableColumn prop="path" label="路径">
            <template #default="{ row }">
              <span class="mono">{{ row.path }}</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </template>

      <ElEmpty v-else description="系统信息加载失败" />
    </ElCard>

    <!-- 2. LLM/对话统计 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Activity /></ElIcon>
          <span>对话量统计</span>
          <span v-if="stats?.note" class="block-hint">{{ stats.note }}</span>
        </div>
      </template>

      <ElSkeleton v-if="loadingStats" :rows="3" animated />

      <template v-else-if="stats">
        <div class="metrics-row">
          <div class="metric">
            <div class="metric-label">今日 turn 总数</div>
            <div class="metric-value">{{ stats.today_turns }}</div>
          </div>
          <div class="metric">
            <div class="metric-label">今日销冠发言</div>
            <div class="metric-value">{{ stats.today_sales_turns }}</div>
          </div>
          <div class="metric">
            <div class="metric-label">今日客户发言</div>
            <div class="metric-value">{{ stats.today_persona_turns }}</div>
          </div>
          <div class="metric">
            <div class="metric-label">今日会话数</div>
            <div class="metric-value">{{ stats.today_sessions }}</div>
          </div>
          <div class="metric">
            <div class="metric-label">今日 Judge/Coach</div>
            <div class="metric-value">{{ stats.evaluations_today }}</div>
          </div>
        </div>

        <div class="chart-wrap">
          <VChart :option="chartOption" autoresize style="height: 260px" />
        </div>
      </template>
    </ElCard>

    <!-- 3. 后台任务 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><Cpu /></ElIcon>
          <span>后台任务</span>
          <span class="block-hint" v-if="tasks">
            活跃 sessions {{ tasks.totals.active_sessions }} · batches
            {{ tasks.totals.active_batches }}
          </span>
        </div>
      </template>

      <ElSkeleton v-if="loadingTasks" :rows="3" animated />

      <template v-else-if="tasks">
        <div class="sub-title">SessionRunner</div>
        <ElEmpty
          v-if="!sessionsList.length"
          description="当前无活跃 session"
          :image-size="48"
        />
        <ElTable v-else :data="sessionsList" size="small" stripe style="width: 100%">
          <ElTableColumn prop="session_id" label="session_id" min-width="280">
            <template #default="{ row }">
              <span class="mono">{{ row.session_id }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="status" label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="(statusTagType(row.status) as any)" size="small">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="queue_size" label="事件队列" width="100" />
          <ElTableColumn prop="cancelled" label="cancelled" width="100">
            <template #default="{ row }">
              <ElTag v-if="row.cancelled" type="danger" size="small">已请求</ElTag>
              <span v-else class="dm-text-muted">—</span>
            </template>
          </ElTableColumn>
        </ElTable>

        <div class="sub-title" style="margin-top: 18px">BatchRunner</div>
        <ElEmpty
          v-if="!batchesList.length"
          description="当前无活跃 batch"
          :image-size="48"
        />
        <ElTable v-else :data="batchesList" size="small" stripe style="width: 100%">
          <ElTableColumn prop="batch_id" label="batch_id" width="100" />
          <ElTableColumn prop="status" label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="(statusTagType(row.status) as any)" size="small">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="进度" width="160">
            <template #default="{ row }">
              {{ row.completed + row.failed + row.cancelled }} / {{ row.total }}
              <span class="dm-text-muted" style="margin-left: 4px">
                (✓{{ row.completed }} ✗{{ row.failed }} ⊘{{ row.cancelled }})
              </span>
            </template>
          </ElTableColumn>
          <ElTableColumn
            prop="current_session_id"
            label="当前 session"
            min-width="280"
          >
            <template #default="{ row }">
              <span class="mono">{{ row.current_session_id || '—' }}</span>
            </template>
          </ElTableColumn>
        </ElTable>
      </template>
    </ElCard>

    <!-- 4. 日志查看器 -->
    <ElCard shadow="never" class="block-card">
      <template #header>
        <div class="block-head">
          <ElIcon><HardDrive /></ElIcon>
          <span>日志（{{ logs?.file || 'logs/app.log' }}）</span>
          <span v-if="logs?.exists" class="block-hint">
            返回 {{ logs?.returned }} / 共 {{ logs?.total_lines }} 行
          </span>
        </div>
      </template>

      <div class="log-controls">
        <ElSelect
          v-model="logLines"
          style="width: 110px"
          @change="loadLogs"
        >
          <ElOption :value="100" label="100 行" />
          <ElOption :value="200" label="200 行" />
          <ElOption :value="500" label="500 行" />
          <ElOption :value="1000" label="1000 行" />
        </ElSelect>
        <ElInput
          v-model="logKeyword"
          placeholder="过滤关键字（前端实时过滤）"
          clearable
          style="max-width: 280px"
        >
          <template #prefix><ElIcon><Search /></ElIcon></template>
        </ElInput>
        <ElButton :loading="loadingLogs" @click="loadLogs">
          <ElIcon><RefreshCcw /></ElIcon>
          <span style="margin-left: 4px">刷新</span>
        </ElButton>
        <span class="auto-switch">
          自动刷新（5s）
          <ElSwitch v-model="logAuto" />
        </span>
      </div>

      <ElSkeleton v-if="loadingLogs && !logs" :rows="6" animated />

      <ElEmpty
        v-else-if="!logs?.exists"
        :description="`日志文件不存在: ${logs?.file || ''}`"
      />

      <ElEmpty
        v-else-if="!filteredLogs.length"
        description="无匹配日志"
      />

      <pre v-else class="log-pre">{{ filteredLogs.join('\n') }}</pre>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.running-status {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.block-card :deep(.el-card__body) {
  padding: 16px 20px 20px;
}
.block-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--dm-text-secondary, #475569);
}
.block-hint {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--dm-text-tertiary, #94a3b8);
}

.sub-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dm-text-tertiary, #94a3b8);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin: 14px 0 8px;
}

.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
}
.kv {
  display: flex;
  gap: 8px;
  font-size: 13px;
}
.k {
  width: 80px;
  flex-shrink: 0;
  color: var(--dm-text-tertiary, #94a3b8);
}
.v { color: var(--dm-text-primary, #1a202c); word-break: break-all; }
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.deps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dep-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid var(--dm-border, #e2e8f0);
  font-size: 12px;
  color: var(--dm-text-secondary, #475569);
  background: var(--dm-bg, #fff);
}
.dep-ver {
  color: var(--dm-text-tertiary, #94a3b8);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.metrics-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.metric {
  padding: 12px 16px;
  border: 1px solid var(--dm-border, #e2e8f0);
  border-radius: 8px;
  background: var(--dm-bg-muted, #f8fafc);
}
.metric-label {
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
  margin-bottom: 6px;
}
.metric-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--dm-text-primary, #1a202c);
  font-variant-numeric: tabular-nums;
}

.chart-wrap {
  margin-top: 8px;
}

.log-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.auto-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--dm-text-secondary, #475569);
  margin-left: auto;
}

.log-pre {
  margin: 0;
  padding: 12px 14px;
  background: #0f172a;
  color: #cbd5e1;
  font-size: 12px;
  line-height: 1.55;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 60vh;
  overflow: auto;
}
</style>
