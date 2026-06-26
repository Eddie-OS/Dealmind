<script setup lang="ts">
/**
 * 会话历史（Stage 7）
 *
 * 顶部：persona / status / outcome 三筛选 + 刷新
 * 中部：el-table 列：ID、Persona、产品 KB、Topic、Outcome（着色 tag）、轮数、综合质量、开始时间、操作
 * 操作列：查看详情 / 导出 ▼ / 删除
 * 底部：el-pagination 分页
 *
 * 所有操作 → 调 sessionsApi。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
} from 'element-plus'
import {
  ArrowRightFromLine,
  RefreshCcw,
  RotateCcw,
  Trash2,
  Download,
  Search,
  Copy,
  Microscope,
  Package,
} from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import {
  sessionsApi,
  type SessionInfo,
  type SessionStatus,
  type ExportFormat,
} from '@/api/sessions'
import { personasApi, type Persona } from '@/api/personas'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import PersonaAvatar from '@/components/PersonaAvatar.vue'

const router = useRouter()

// ============================================================
// 数据 + 筛选
// ============================================================

const loading = ref(false)
const rows = ref<SessionInfo[]>([])
const total = ref(0)

const filters = reactive<{
  persona_id: number | null
  status: SessionStatus | null
  outcome: string | null
  page: number
  size: number
}>({
  persona_id: null,
  status: null,
  outcome: null,
  page: 1,
  size: 20,
})

const personas = ref<Persona[]>([])
const productKbs = ref<KnowledgeBase[]>([])
const enterpriseKbs = ref<KnowledgeBase[]>([])

// 状态枚举（与后端 _run_blocking 中 SessionRunner.status 取值对齐）
const STATUS_OPTIONS: { label: string; value: SessionStatus }[] = [
  { label: '待启动', value: 'pending' },
  { label: '进行中', value: 'running' },
  { label: '已完成', value: 'done' },
  { label: '已中断', value: 'cancelled' },
  { label: '失败',   value: 'failed' },
]

// 结果枚举（与 schema.py StatusType 对齐）
const OUTCOME_OPTIONS: { label: string; value: string }[] = [
  { label: 'CONTINUE',  value: 'CONTINUE' },
  { label: 'DEAL_DONE', value: 'DEAL_DONE' },
  { label: 'WALK_AWAY', value: 'WALK_AWAY' },
  { label: 'COMPLAINT', value: 'COMPLAINT' },
  { label: 'TIMEOUT',   value: 'TIMEOUT' },
  { label: 'CANCELLED', value: 'CANCELLED' },
]

const STATUS_TAG_TYPE: Record<
  SessionStatus,
  'info' | 'warning' | 'success' | 'danger' | 'primary'
> = {
  pending: 'info',
  running: 'warning',
  done: 'success',
  cancelled: 'info',
  failed: 'danger',
}

const STATUS_LABEL: Record<SessionStatus, string> = {
  pending: '待启动',
  running: '进行中',
  done: '已完成',
  cancelled: '已中断',
  failed: '失败',
}

const OUTCOME_TAG_TYPE: Record<
  string,
  'info' | 'warning' | 'success' | 'danger' | 'primary'
> = {
  DEAL_DONE: 'success',
  WALK_AWAY: 'warning',
  COMPLAINT: 'danger',
  TIMEOUT: 'info',
  CANCELLED: 'info',
  CONTINUE: 'primary',
}

// ============================================================
// 加载
// ============================================================

async function loadRows(): Promise<void> {
  loading.value = true
  try {
    const res = await sessionsApi.list({
      persona_id: filters.persona_id,
      status: filters.status,
      outcome: filters.outcome,
      page: filters.page,
      size: filters.size,
    })
    rows.value = res.items
    total.value = res.total
  } catch (e: any) {
    ElMessage.error('加载会话失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function loadAux(): Promise<void> {
  const [pr, pk, ek] = await Promise.allSettled([
    personasApi.list({ limit: 200 }),
    kbApi.list('product'),
    kbApi.list('enterprise'),
  ])
  if (pr.status === 'fulfilled') personas.value = pr.value.items
  else console.warn('[history] personas load failed:', pr.reason)
  if (pk.status === 'fulfilled') productKbs.value = pk.value.items
  else console.warn('[history] product KB load failed:', pk.reason)
  if (ek.status === 'fulfilled') enterpriseKbs.value = ek.value.items
  else console.warn('[history] enterprise KB load failed:', ek.reason)
}

function personaLabel(id: number | null | undefined): string {
  if (id == null) return '—'
  const p = personas.value.find((x) => x.id === id)
  return p ? p.name : `#${id}`
}

function personaInfo(id: number | null | undefined): {
  name: string
  avatar_key: string | null
} {
  if (id == null) return { name: '—', avatar_key: null }
  const p = personas.value.find((x) => x.id === id)
  return p
    ? { name: p.name, avatar_key: p.avatar_key }
    : { name: `#${id}`, avatar_key: null }
}

function kbLabel(id: number | null | undefined, kind: 'product' | 'enterprise'): string {
  if (id == null) return '—'
  const pool = kind === 'product' ? productKbs.value : enterpriseKbs.value
  const k = pool.find((x) => x.id === id)
  return k ? k.name : `#${id}`
}

function fmtTime(ts: string | null): string {
  if (!ts) return '—'
  return ts.replace('T', ' ').slice(0, 19)
}

function qualityScore(row: SessionInfo): string {
  // summary.outcome 有时存了 dialogue_quality_score（Stage 7 detail 端点更准；列表表展示 outcome 即可）
  // 这里用 total_rounds + outcome 简洁展示
  const o = row.summary?.outcome
  return o ? `${o}` : '—'
}

// ============================================================
// 行操作
// ============================================================

function gotoDetail(row: SessionInfo): void {
  router.push(`/simulation/detail/${row.id}`)
}

function gotoLive(row: SessionInfo): void {
  router.push(`/simulation/live/${row.id}`)
}

function doExport(row: SessionInfo, format: ExportFormat): void {
  const url = sessionsApi.exportUrl(row.id, format)
  const a = document.createElement('a')
  a.href = url
  a.download = `${row.id}.${format}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ============================================================
// 批量选择 / 批量导出 / 分析
// ============================================================

const selectedRows = ref<SessionInfo[]>([])
const bulkLoading = ref(false)

function onSelectionChange(rows: SessionInfo[]): void {
  selectedRows.value = rows
}

function shortId(id: string): string {
  // session_20260528_205919_p1 → ...205919_p1（保留最有信息的尾部）
  if (id.length <= 18) return id
  return '…' + id.slice(-15)
}

async function copyId(id: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(id)
    } else {
      const ta = document.createElement('textarea')
      ta.value = id
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('ID 已复制')
  } catch (e: any) {
    ElMessage.warning('复制失败：' + (e?.message || e))
  }
}

async function bulkExport(
  format: ExportFormat,
  includeAnalysis: boolean,
): Promise<void> {
  if (selectedRows.value.length === 0) {
    ElMessage.warning('请先勾选要导出的会话')
    return
  }
  const ids = selectedRows.value.map((r) => r.id)
  bulkLoading.value = true
  try {
    await sessionsApi.bulkExport({
      session_ids: ids,
      format,
      include_analysis: includeAnalysis,
    })
    ElMessage.success(
      `已导出 ${ids.length} 个会话` +
        (includeAnalysis ? '（含分析报告）' : ''),
    )
  } catch (e: any) {
    ElMessage.error(
      '批量导出失败：' + (e?.response?.data?.detail || e?.message || e),
    )
  } finally {
    bulkLoading.value = false
  }
}

function gotoAnalysis(row: SessionInfo): void {
  router.push({
    name: 'batch-analysis',
    query: { session_id: row.id },
  })
}

async function doDelete(row: SessionInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除会话 ${row.id}？\n关联 turns / evaluations / outputs 文件都会清除，操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch (_e) {
    return
  }
  try {
    const res = await sessionsApi.del(row.id)
    ElMessage.success(
      `已删除${res.removed_outputs ? '（含 outputs/）' : ''}`,
    )
    await loadRows()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

function resetFilters(): void {
  filters.persona_id = null
  filters.status = null
  filters.outcome = null
  filters.page = 1
  loadRows()
}

function onFilterChange(): void {
  filters.page = 1
  loadRows()
}

function onPageChange(p: number): void {
  filters.page = p
  loadRows()
}

const isEmpty = computed(() => !loading.value && rows.value.length === 0)

onMounted(async () => {
  await loadAux()
  await loadRows()
})
</script>

<template>
  <div class="page">
    <DmPageHeader
      title="会话历史"
      subtitle="所有已存档的销冠模拟对话 · 可筛选 / 批量导出 / 分析"
    >
      <template #actions>
        <ElDropdown
          trigger="click"
          :disabled="selectedRows.length === 0 || bulkLoading"
        >
          <ElButton
            :type="selectedRows.length > 0 ? 'primary' : 'default'"
            plain
            :loading="bulkLoading"
            :disabled="selectedRows.length === 0"
          >
            <template #icon>
              <Package :size="14" :stroke-width="1.6" />
            </template>
            批量导出
            <span v-if="selectedRows.length > 0" class="bulk-count">
              （{{ selectedRows.length }}）
            </span>
          </ElButton>
          <template #dropdown>
            <ElDropdownMenu>
              <ElDropdownItem @click="bulkExport('md', true)">
                Markdown · 含分析报告
              </ElDropdownItem>
              <ElDropdownItem @click="bulkExport('json', true)">
                JSON · 含分析报告
              </ElDropdownItem>
              <ElDropdownItem divided @click="bulkExport('md', false)">
                仅会话 Markdown
              </ElDropdownItem>
              <ElDropdownItem @click="bulkExport('json', false)">
                仅会话 JSON
              </ElDropdownItem>
              <ElDropdownItem @click="bulkExport('jsonl', false)">
                仅会话 JSONL
              </ElDropdownItem>
            </ElDropdownMenu>
          </template>
        </ElDropdown>
        <ElButton @click="loadRows">
          <template #icon><RefreshCcw :size="14" :stroke-width="1.6" /></template>
          刷新
        </ElButton>
        <ElButton type="primary" @click="router.push('/simulation/new')">
          <template #icon><ArrowRightFromLine :size="14" :stroke-width="1.6" /></template>
          新建对话
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 筛选 -->
    <section class="filter-bar">
      <ElSelect
        v-model="filters.persona_id"
        clearable
        placeholder="客户人设"
        class="f-persona"
        filterable
        @change="onFilterChange"
        @clear="onFilterChange"
      >
        <ElOption
          v-for="p in personas"
          :key="p.id"
          :label="p.name"
          :value="p.id"
        >
          <div class="opt-with-avatar">
            <PersonaAvatar :avatar-key="p.avatar_key" :name="p.name" :size="22" />
            <span>{{ p.name }}</span>
          </div>
        </ElOption>
      </ElSelect>

      <ElSelect
        v-model="filters.status"
        clearable
        placeholder="状态"
        class="f-status"
        @change="onFilterChange"
        @clear="onFilterChange"
      >
        <ElOption
          v-for="s in STATUS_OPTIONS"
          :key="s.value"
          :label="s.label"
          :value="s.value"
        />
      </ElSelect>

      <ElSelect
        v-model="filters.outcome"
        clearable
        placeholder="结果"
        class="f-outcome"
        @change="onFilterChange"
        @clear="onFilterChange"
      >
        <ElOption
          v-for="o in OUTCOME_OPTIONS"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </ElSelect>

      <ElButton text @click="resetFilters">
        <template #icon><Search :size="14" :stroke-width="1.6" /></template>
        重置
      </ElButton>

      <div class="spacer" />

      <span class="dm-text-small dm-text-muted">
        共 {{ total }} 条
      </span>
    </section>

    <!-- 表格 -->
    <section class="table-wrap card">
      <DmEmpty
        v-if="isEmpty"
        title="还没有会话"
        description="去 '新建对话' 跑一场试试"
      />
      <ElTable
        v-else
        v-loading="loading"
        :data="rows"
        row-key="id"
        size="default"
        stripe
        @selection-change="onSelectionChange"
        @row-click="gotoDetail"
      >
        <ElTableColumn type="selection" width="42" :selectable="() => true" />

        <ElTableColumn label="ID" width="170">
          <template #default="{ row }">
            <ElTooltip :content="row.id" placement="top">
              <span class="id-cell" @click.stop>
                <span class="mono dm-text-caption">{{ shortId(row.id) }}</span>
                <ElButton
                  class="id-copy"
                  size="small"
                  text
                  @click.stop="copyId(row.id)"
                >
                  <Copy :size="12" :stroke-width="1.6" />
                </ElButton>
              </span>
            </ElTooltip>
          </template>
        </ElTableColumn>

        <ElTableColumn label="客户人设" min-width="180">
          <template #default="{ row }">
            <div class="persona-cell">
              <PersonaAvatar
                :avatar-key="personaInfo(row.persona_id).avatar_key"
                :name="personaInfo(row.persona_id).name"
                :size="28"
              />
              <span class="persona-cell-name">
                {{ personaInfo(row.persona_id).name }}
              </span>
            </div>
          </template>
        </ElTableColumn>

        <ElTableColumn label="产品 KB" min-width="160">
          <template #default="{ row }">
            <ElTooltip
              v-if="row.product_kb_id"
              :content="kbLabel(row.product_kb_id, 'product')"
              placement="top"
            >
              <span class="ellipsis">
                {{ kbLabel(row.product_kb_id, 'product') }}
              </span>
            </ElTooltip>
            <span v-else class="dm-text-muted">—</span>
          </template>
        </ElTableColumn>

        <ElTableColumn label="主题" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.topic || '—' }}</span>
          </template>
        </ElTableColumn>

        <ElTableColumn label="手册" width="100" align="center">
          <template #default="{ row }">
            <ElTag
              v-if="row.handbook_id"
              type="success"
              size="small"
              effect="plain"
            >
              已绑 #{{ row.handbook_id }}
            </ElTag>
            <ElTag v-else type="info" size="small" effect="plain">
              未绑
            </ElTag>
          </template>
        </ElTableColumn>

        <ElTableColumn label="结果" min-width="120">
          <template #default="{ row }">
            <ElTag
              v-if="row.summary?.outcome"
              :type="OUTCOME_TAG_TYPE[row.summary.outcome] || 'info'"
              effect="plain"
              size="small"
            >
              {{ row.summary.outcome }}
            </ElTag>
            <ElTag
              v-else
              :type="STATUS_TAG_TYPE[row.status] || 'info'"
              effect="plain"
              size="small"
            >
              {{ STATUS_LABEL[row.status] }}
            </ElTag>
          </template>
        </ElTableColumn>

        <ElTableColumn label="轮数" width="80" align="right">
          <template #default="{ row }">
            <span class="dm-numeric">
              {{ row.summary?.total_rounds ?? 0 }}
            </span>
          </template>
        </ElTableColumn>

        <ElTableColumn label="开始时间" min-width="170">
          <template #default="{ row }">
            <span class="dm-text-caption mono">
              {{ fmtTime(row.started_at) }}
            </span>
          </template>
        </ElTableColumn>

        <ElTableColumn
          label="操作"
          width="380"
          fixed="right"
          align="right"
        >
          <template #default="{ row }">
            <div class="op-bar" @click.stop>
              <ElButton
                v-if="row.status === 'running'"
                size="small"
                text
                @click="gotoLive(row)"
              >
                现场
              </ElButton>
              <ElButton
                v-else-if="['done', 'cancelled', 'failed'].includes(row.status)"
                size="small"
                text
                @click="gotoLive(row)"
              >
                <template #icon>
                  <RotateCcw :size="14" :stroke-width="1.6" />
                </template>
                回放
              </ElButton>
              <ElButton size="small" text @click="gotoDetail(row)">
                复盘
              </ElButton>
              <ElButton
                size="small"
                text
                type="primary"
                @click="gotoAnalysis(row)"
              >
                <template #icon>
                  <Microscope :size="14" :stroke-width="1.6" />
                </template>
                分析
              </ElButton>
              <ElDropdown size="small" trigger="click">
                <ElButton size="small" text>
                  <template #icon><Download :size="14" :stroke-width="1.6" /></template>
                  导出
                </ElButton>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem @click="doExport(row, 'md')">
                      Markdown (.md)
                    </ElDropdownItem>
                    <ElDropdownItem @click="doExport(row, 'json')">
                      JSON (.json)
                    </ElDropdownItem>
                    <ElDropdownItem @click="doExport(row, 'jsonl')">
                      JSONL (.jsonl)
                    </ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
              <ElButton
                size="small"
                text
                type="danger"
                @click="doDelete(row)"
              >
                <template #icon><Trash2 :size="14" :stroke-width="1.6" /></template>
              </ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>

      <!-- 分页 -->
      <div v-if="!isEmpty" class="pager">
        <ElPagination
          background
          layout="prev, pager, next, sizes, total"
          :total="total"
          :page-size="filters.size"
          :current-page="filters.page"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="onPageChange"
          @size-change="(s: number) => { filters.size = s; filters.page = 1; loadRows() }"
        />
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.page {
  padding: var(--dm-space-7);
  min-height: 100%;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--dm-space-3);
  margin-bottom: var(--dm-space-4);
}
.f-persona  { width: 220px; }
.f-status   { width: 140px; }
.f-outcome  { width: 160px; }
.spacer { flex: 1; }

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-md);
  padding: var(--dm-space-3);
}
.table-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-3);
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--dm-space-2);
}
.op-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: var(--dm-space-1);
  flex-wrap: nowrap;
}
.op-bar :deep(.el-button) {
  flex: 0 0 auto;
  white-space: nowrap;
}
.mono { font-family: var(--dm-font-mono); }

.id-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
}
.id-copy {
  padding: 0 4px !important;
  height: 22px;
  min-height: 22px;
  opacity: 0.45;
  transition: opacity 120ms ease;
}
.id-cell:hover .id-copy {
  opacity: 1;
}

.bulk-count {
  margin-left: 4px;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  display: inline-block;
}

/* el-table 行高密度调一下，更贴近 Notion */
:deep(.el-table) {
  font-size: var(--dm-fs-body);
  background: transparent;
  cursor: pointer;
}
:deep(.el-table th.el-table__cell) {
  background: var(--dm-bg-elevated);
  color: var(--dm-text-muted);
  font-weight: var(--dm-fw-medium);
  font-size: var(--dm-fs-small);
}
:deep(.el-table tr:hover > td.el-table__cell) {
  background: var(--dm-bg-selected) !important;
}

.persona-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.persona-cell-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.opt-with-avatar {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
