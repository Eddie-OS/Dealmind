<script setup lang="ts">
/**
 * 批量测试（Stage 9）
 *
 * 三块：
 *  1. 任务列表 el-table（含进度条 + 状态 tag + 操作列）
 *  2. 创建 dialog：name + persona 多选 + 产品 KB + 企业 KB + 主题 + 开场白 + 轮数
 *  3. 详情 el-drawer：实时进度 + WS 日志 + 关联 session 列表（可跳转复盘）
 *
 * WS：详情抽屉打开时连 `/ws/batch/{id}`，进度事件实时刷新右侧；
 * 抽屉关闭即断开 ws（不影响 batch 继续跑，跑完 DB 自然更新）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElCheckbox,
  ElCheckboxGroup,
  ElDialog,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElProgress,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
} from 'element-plus'
import {
  Activity,
  Ban,
  Eye,
  Play,
  Plus,
  RefreshCcw,
  Trash2,
} from '@lucide/vue'

import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  batchApi,
  connectBatchWs,
  type BatchEvent,
  type BatchInfo,
  type BatchLanguage,
  type BatchSessionRow,
  type BatchStatus,
  type CreateBatchPayload,
} from '@/api/batch'
import { personasApi, type Persona } from '@/api/personas'
import { kbApi, type KnowledgeBase } from '@/api/kb'
import { handbookApi, type Handbook } from '@/api/handbook'

const router = useRouter()

// ============================================================
// 列表
// ============================================================

const loading = ref(false)
const rows = ref<BatchInfo[]>([])
const total = ref(0)
const page = ref(1)
const size = 20

let refreshTimer: number | null = null

async function loadList(): Promise<void> {
  loading.value = true
  try {
    const r = await batchApi.list({ page: page.value, size })
    rows.value = r.items
    total.value = r.total
  } catch (e: any) {
    ElMessage.error('加载批量任务失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function startPolling(): void {
  stopPolling()
  refreshTimer = window.setInterval(() => {
    if (
      rows.value.some(
        (r) => r.runtime_status === 'running' || r.is_active || r.can_resume,
      )
    ) {
      loadList()
    }
  }, 5_000)
}

function stopPolling(): void {
  if (refreshTimer !== null) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// ============================================================
// 辅助资料
// ============================================================

const personas = ref<Persona[]>([])
const productKbs = ref<KnowledgeBase[]>([])
const enterpriseKbs = ref<KnowledgeBase[]>([])
const handbooks = ref<Handbook[]>([])

async function loadAux(): Promise<void> {
  const [pr, pk, ek, hb] = await Promise.allSettled([
    personasApi.list({ limit: 200 }),
    kbApi.list('product'),
    kbApi.list('enterprise'),
    handbookApi.list(),
  ])
  if (pr.status === 'fulfilled') personas.value = pr.value.items
  if (pk.status === 'fulfilled') productKbs.value = pk.value.items
  if (ek.status === 'fulfilled') enterpriseKbs.value = ek.value.items
  if (hb.status === 'fulfilled') handbooks.value = hb.value.items
}

function personaLabel(id: number | null | undefined): string {
  if (id == null) return '—'
  return personas.value.find((p) => p.id === id)?.name || `#${id}`
}

function kbLabel(id: number | null | undefined, kind: 'product' | 'enterprise'): string {
  if (id == null) return '—'
  const pool = kind === 'product' ? productKbs.value : enterpriseKbs.value
  return pool.find((k) => k.id === id)?.name || `#${id}`
}

// ============================================================
// 状态着色
// ============================================================

const STATUS_TAG_TYPE: Record<
  BatchStatus,
  'info' | 'warning' | 'success' | 'danger' | 'primary'
> = {
  pending: 'info',
  running: 'warning',
  completed: 'success',
  cancelled: 'info',
  failed: 'danger',
}
const STATUS_LABEL: Record<BatchStatus, string> = {
  pending: '待启动',
  running: '进行中',
  completed: '已完成',
  cancelled: '已中断',
  failed: '失败',
}

function fmtTime(ts: string | null): string {
  return ts ? ts.replace('T', ' ').slice(0, 19) : '—'
}

function progressPct(row: BatchInfo): number {
  if (!row.total_count) return 0
  const done = row.completed_count + row.failed_count + row.cancelled_count
  return Math.min(100, Math.round((done / row.total_count) * 100))
}

function rowStatusLabel(row: BatchInfo): string {
  if (row.can_resume) {
    const n = row.remaining_count ?? row.total_count - row.completed_count
    return `可续跑（剩 ${n}）`
  }
  return STATUS_LABEL[row.runtime_status as BatchStatus] || row.runtime_status
}

function rowStatusTagType(row: BatchInfo): 'info' | 'warning' | 'success' | 'danger' | 'primary' {
  if (row.can_resume) return 'primary'
  return STATUS_TAG_TYPE[row.runtime_status as BatchStatus] || 'info'
}

// ============================================================
// 创建 dialog
// ============================================================

const createOpen = ref(false)
const creating = ref(false)
const LANGUAGE_OPTIONS: { value: BatchLanguage; label: string }[] = [
  { value: 'zh-CN', label: '普通话（简体中文）' },
  { value: 'en-US', label: 'English (US)' },
  { value: 'es-ES', label: 'Español' },
  { value: 'ar-SA', label: 'العربية' },
  { value: 'id-ID', label: 'Bahasa Indonesia' },
]

const form = reactive<CreateBatchPayload & { _selectedPersonas: number[] }>({
  name: '',
  persona_ids: [],
  product_kb_id: null,
  enterprise_kb_id: null,
  handbook_id: null,
  topic: '华为 MatePad 销售模拟',
  language: 'zh-CN',
  max_rounds: 30,
  judge_interval: 6,
  memory_interval: 6,
  _selectedPersonas: [],
})

function openCreate(): void {
  form.name = `批量测试-${new Date().toLocaleString('zh-CN', { hour12: false }).slice(5)}`
  form._selectedPersonas = []
  form.product_kb_id = productKbs.value[0]?.id ?? null
  form.enterprise_kb_id = enterpriseKbs.value[0]?.id ?? null
  // Handbook 默认：与后端 resolve_default_handbook_id 一致——
  // 全库只有一份 ready 时自动选上，多份留空让用户主动选
  const readyHb = handbooks.value.filter((h) => h.status === 'ready')
  form.handbook_id = readyHb.length === 1 ? readyHb[0].id : null
  form.topic = '华为 MatePad 销售模拟'
  form.language = 'zh-CN'
  form.max_rounds = 30
  form.judge_interval = 6
  form.memory_interval = 6
  createOpen.value = true
}

const personaSearch = ref('')
const filteredPersonas = computed(() => {
  const q = personaSearch.value.trim().toLowerCase()
  if (!q) return personas.value
  return personas.value.filter(
    (p) =>
      p.name.toLowerCase().includes(q) ||
      (p.tags || []).some((t) => t.toLowerCase().includes(q)),
  )
})

function selectAllPersonas(): void {
  form._selectedPersonas = filteredPersonas.value.map((p) => p.id)
}
function clearAllPersonas(): void {
  form._selectedPersonas = []
}

async function submitCreate(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('请填写任务名')
    return
  }
  if (form._selectedPersonas.length === 0) {
    ElMessage.warning('请至少选 1 个人设')
    return
  }
  creating.value = true
  try {
    const payload: CreateBatchPayload = {
      name: form.name.trim(),
      persona_ids: [...form._selectedPersonas],
      product_kb_id: form.product_kb_id || null,
      enterprise_kb_id: form.enterprise_kb_id || null,
      handbook_id: form.handbook_id || null,
      topic: form.topic?.trim() || '学习平板销售模拟',
      language: form.language || 'zh-CN',
      max_rounds: form.max_rounds,
      judge_interval: form.judge_interval,
      memory_interval: form.memory_interval,
    }
    const res = await batchApi.create(payload)
    ElMessage.success(`批量任务已启动 (#${res.id})`)
    createOpen.value = false
    await loadList()
    openDrawer(res.id)
  } catch (e: any) {
    ElMessage.error('创建失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    creating.value = false
  }
}

// ============================================================
// 详情抽屉 + WS
// ============================================================

const drawerOpen = ref(false)
const drawerLoading = ref(false)
const currentBatch = ref<BatchInfo | null>(null)
const subSessions = ref<BatchSessionRow[]>([])
const wsEvents = ref<BatchEvent[]>([])
let wsHandle: ReturnType<typeof connectBatchWs> | null = null
let drawerRefreshTimer: number | null = null

async function refreshDrawer(): Promise<void> {
  if (!currentBatch.value) return
  const id = currentBatch.value.id
  try {
    const [b, s] = await Promise.all([
      batchApi.detail(id),
      batchApi.sessions(id),
    ])
    currentBatch.value = b
    subSessions.value = s.items
  } catch (e: any) {
    console.warn('[batch detail] refresh fail:', e)
  }
}

async function openDrawer(batchId: number): Promise<void> {
  drawerOpen.value = true
  drawerLoading.value = true
  wsEvents.value = []
  subSessions.value = []
  try {
    const b = await batchApi.detail(batchId)
    currentBatch.value = b
    const s = await batchApi.sessions(batchId)
    subSessions.value = s.items

    // 进行中 / 刚续跑：订阅 WS 进度
    if (b.is_active || b.can_resume) {
      connectWs(batchId)
    }
    // 即使有 WS，也每 5s 兜底 refresh 一次（避免错过事件）
    drawerRefreshTimer = window.setInterval(refreshDrawer, 5_000)
  } catch (e: any) {
    ElMessage.error('加载详情失败：' + (e?.message || e))
  } finally {
    drawerLoading.value = false
  }
}

function connectWs(batchId: number): void {
  closeWs()
  wsHandle = connectBatchWs(batchId, {
    onEvent: (evt) => {
      wsEvents.value.push(evt)
      // 关键事件即时刷新
      if (
        evt.type === 'session_close' ||
        evt.type === 'batch_done' ||
        evt.type === 'batch_start'
      ) {
        refreshDrawer()
      }
    },
    onClose: () => {
      // 主动 / 被动关都行，不报错
    },
  })
}

function closeWs(): void {
  if (wsHandle) {
    wsHandle.close()
    wsHandle = null
  }
}

function onDrawerClose(): void {
  closeWs()
  if (drawerRefreshTimer !== null) {
    clearInterval(drawerRefreshTimer)
    drawerRefreshTimer = null
  }
  currentBatch.value = null
  wsEvents.value = []
  subSessions.value = []
  // 刷新主列表以拿最新进度
  loadList()
}

watch(drawerOpen, (v) => {
  if (!v) onDrawerClose()
})

// ============================================================
// 操作
// ============================================================

async function doResume(row: BatchInfo): Promise<void> {
  const left = row.remaining_count ?? row.total_count - row.completed_count
  try {
    await ElMessageBox.confirm(
      `从已完成场次接着跑？\n当前 ${row.completed_count}/${row.total_count}，剩余约 ${left} 场。`,
      '续跑确认',
      { confirmButtonText: '续跑', cancelButtonText: '取消', type: 'info' },
    )
  } catch { return }
  try {
    const res = await batchApi.resume(row.id)
    ElMessage.success(
      res.resumed
        ? `已续跑，剩余 ${res.remaining_count ?? left} 场`
        : (res as { message?: string }).message || '任务已全部完成',
    )
    if (currentBatch.value?.id === row.id) {
      await refreshDrawer()
      if (res.resumed) connectWs(row.id)
    }
    loadList()
  } catch (e: any) {
    ElMessage.error('续跑失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

async function doCancel(row: BatchInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认中断批量任务「${row.name}」？\n当前场会立即停下，已完成场次的会话保留。`,
      '中断确认',
      { confirmButtonText: '中断', cancelButtonText: '保持运行', type: 'warning' },
    )
  } catch { return }
  try {
    await batchApi.cancel(row.id)
    ElMessage.success('已请求中断')
    if (currentBatch.value?.id === row.id) refreshDrawer()
    loadList()
  } catch (e: any) {
    ElMessage.error('中断失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

async function doDelete(row: BatchInfo): Promise<void> {
  if (row.is_active) {
    ElMessage.warning('请先中断再删')
    return
  }
  if (row.can_resume) {
    ElMessage.warning('任务可续跑，请先续跑完成或点「中断」后再删')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除批量任务「${row.name}」？\n关联的 ${row.session_ids.length} 场 session 不会被删，可在「会话历史」单独管理。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    await batchApi.del(row.id)
    ElMessage.success('已删除')
    loadList()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

function gotoSessionDetail(sid: string): void {
  router.push(`/simulation/detail/${sid}`)
}

function gotoSessionLive(sid: string): void {
  router.push(`/simulation/live/${sid}`)
}

// ============================================================
// 生命周期
// ============================================================

const isEmpty = computed(() => !loading.value && rows.value.length === 0)

onMounted(async () => {
  await loadAux()
  await loadList()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
  onDrawerClose()
})
</script>

<template>
  <div class="page">
    <DmPageHeader
      title="批量测试"
      subtitle="一次性选多个客户人设跑同一组销冠 · 顺序串行 · 中途可中断"
    >
      <template #actions>
        <ElButton @click="loadList" :loading="loading">
          <template #icon><RefreshCcw :size="14" :stroke-width="1.6" /></template>
          刷新
        </ElButton>
        <ElButton type="primary" @click="openCreate">
          <template #icon><Plus :size="14" :stroke-width="1.6" /></template>
          新建批量任务
        </ElButton>
      </template>
    </DmPageHeader>

    <section class="table-wrap card">
      <ElEmpty
        v-if="isEmpty"
        description="还没有批量任务，点右上角「新建批量任务」试试"
        :image-size="100"
      />
      <ElTable
        v-else
        v-loading="loading"
        :data="rows"
        row-key="id"
        size="default"
        stripe
        @row-click="openDrawer(($event as BatchInfo).id)"
      >
        <ElTableColumn label="ID" width="64" align="right">
          <template #default="{ row }">
            <span class="mono dm-text-caption">#{{ row.id }}</span>
          </template>
        </ElTableColumn>

        <ElTableColumn label="名称" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="cell-name">
              <strong>{{ row.name }}</strong>
              <span class="dm-text-small dm-text-muted">
                {{ row.persona_ids.length }} 人设 · {{ row.max_rounds }} 轮上限
              </span>
            </div>
          </template>
        </ElTableColumn>

        <ElTableColumn label="产品 KB" min-width="140">
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

        <ElTableColumn label="进度" min-width="220">
          <template #default="{ row }">
            <div class="progress-cell">
              <ElProgress
                :percentage="progressPct(row)"
                :stroke-width="6"
                :show-text="false"
                :status="
                  row.failed_count > 0
                    ? 'exception'
                    : progressPct(row) === 100
                      ? 'success'
                      : undefined
                "
              />
              <span class="dm-text-caption mono">
                {{ row.completed_count }}/{{ row.total_count }}
                <span v-if="row.failed_count" class="err">·失 {{ row.failed_count }}</span>
                <span v-if="row.cancelled_count" class="cancel">·中 {{ row.cancelled_count }}</span>
              </span>
            </div>
          </template>
        </ElTableColumn>

        <ElTableColumn label="状态" min-width="100">
          <template #default="{ row }">
            <ElTag
              :type="rowStatusTagType(row)"
              effect="plain"
              size="small"
            >
              {{ rowStatusLabel(row) }}
            </ElTag>
          </template>
        </ElTableColumn>

        <ElTableColumn label="开始时间" min-width="160">
          <template #default="{ row }">
            <span class="dm-text-caption mono">{{ fmtTime(row.started_at) }}</span>
          </template>
        </ElTableColumn>

        <ElTableColumn label="操作" width="220" fixed="right" align="right">
          <template #default="{ row }">
            <div class="op-bar" @click.stop>
              <ElButton size="small" text @click="openDrawer(row.id)">
                <template #icon><Eye :size="14" :stroke-width="1.6" /></template>
                详情
              </ElButton>
              <ElButton
                v-if="row.can_resume"
                size="small"
                text
                type="primary"
                @click="doResume(row)"
              >
                <template #icon><Play :size="14" :stroke-width="1.6" /></template>
                续跑
              </ElButton>
              <ElButton
                v-else-if="row.is_active"
                size="small"
                text
                type="warning"
                @click="doCancel(row)"
              >
                <template #icon><Ban :size="14" :stroke-width="1.6" /></template>
                中断
              </ElButton>
              <ElButton
                size="small"
                text
                type="danger"
                :disabled="row.is_active"
                @click="doDelete(row)"
              >
                <template #icon><Trash2 :size="14" :stroke-width="1.6" /></template>
              </ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>
    </section>

    <!-- ===== 创建 dialog ===== -->
    <ElDialog
      v-model="createOpen"
      title="新建批量任务"
      width="760px"
      :close-on-click-modal="false"
      :destroy-on-close="true"
    >
      <ElForm label-width="88px" label-position="right" size="default">
        <ElFormItem label="任务名">
          <ElInput v-model="form.name" placeholder="给批量任务起个名" />
        </ElFormItem>

        <ElFormItem label="参与人设">
          <div class="persona-picker">
            <div class="persona-toolbar">
              <ElInput
                v-model="personaSearch"
                placeholder="搜人设名 / 标签…"
                clearable
                class="search"
              />
              <ElButton size="small" text @click="selectAllPersonas">
                全选 ({{ filteredPersonas.length }})
              </ElButton>
              <ElButton size="small" text @click="clearAllPersonas">
                清空
              </ElButton>
              <span class="dm-text-small dm-text-muted spacer-right">
                已选 {{ form._selectedPersonas.length }}
              </span>
            </div>
            <div class="persona-grid">
              <ElCheckboxGroup v-model="form._selectedPersonas">
                <ElCheckbox
                  v-for="p in filteredPersonas"
                  :key="p.id"
                  :value="p.id"
                  border
                  size="small"
                  class="persona-chip"
                >
                  <span class="chip-name">{{ p.name }}</span>
                  <span
                    v-if="p.tags?.length"
                    class="chip-tag dm-text-small dm-text-muted"
                  >
                    {{ p.tags.slice(0, 2).join('·') }}
                  </span>
                </ElCheckbox>
              </ElCheckboxGroup>
            </div>
          </div>
        </ElFormItem>

        <ElFormItem label="产品 KB">
          <ElSelect
            v-model="form.product_kb_id"
            clearable
            placeholder="（可选）"
            class="full"
          >
            <ElOption
              v-for="k in productKbs"
              :key="k.id"
              :label="k.name"
              :value="k.id"
            />
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="产品手册">
          <ElSelect
            v-model="form.handbook_id"
            clearable
            placeholder="（可选）注入销冠 prompt 强约束"
            class="full"
          >
            <ElOption
              v-for="h in handbooks"
              :key="h.id"
              :label="`${h.name}（v${h.version_no} · ${h.status}）`"
              :value="h.id"
              :disabled="h.status !== 'ready'"
            />
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="企业 KB">
          <ElSelect
            v-model="form.enterprise_kb_id"
            clearable
            placeholder="（可选）"
            class="full"
          >
            <ElOption
              v-for="k in enterpriseKbs"
              :key="k.id"
              :label="k.name"
              :value="k.id"
            />
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="主题">
          <ElInput v-model="form.topic" maxlength="200" show-word-limit />
        </ElFormItem>

        <ElFormItem label="对话语言">
          <ElSelect v-model="form.language" class="full">
            <ElOption
              v-for="o in LANGUAGE_OPTIONS"
              :key="o.value"
              :value="o.value"
              :label="o.label"
            />
          </ElSelect>
          <div class="lang-hint dm-text-small dm-text-muted">
            开场白由 AI 按所选语言自动生成，无需手动设置。
          </div>
        </ElFormItem>

        <div class="row-3">
          <ElFormItem label="最大轮数" label-position="top">
            <ElInputNumber
              v-model="form.max_rounds"
              :min="8"
              :max="80"
              controls-position="right"
              class="full"
            />
          </ElFormItem>
          <ElFormItem label="Judge 间隔" label-position="top">
            <ElInputNumber
              v-model="form.judge_interval"
              :min="1"
              :max="10"
              controls-position="right"
              class="full"
            />
          </ElFormItem>
          <ElFormItem label="Memory 间隔" label-position="top">
            <ElInputNumber
              v-model="form.memory_interval"
              :min="1"
              :max="10"
              controls-position="right"
              class="full"
            />
          </ElFormItem>
        </div>
        <p class="dm-text-caption dm-text-muted perf-hint">
          批量运行时服务端会覆盖为更高并发 / 更大间隔（默认 8 路并行、Judge/Memory 每 6 轮），44 场约 2 小时内完成。
        </p>
      </ElForm>

      <template #footer>
        <ElButton @click="createOpen = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="creating"
          @click="submitCreate"
        >
          <template #icon><Play :size="14" :stroke-width="1.6" /></template>
          创建并启动
        </ElButton>
      </template>
    </ElDialog>

    <!-- ===== 详情抽屉 ===== -->
    <ElDrawer
      v-model="drawerOpen"
      :title="currentBatch ? `批量任务详情 · ${currentBatch.name}` : '加载中…'"
      direction="rtl"
      size="60%"
      :destroy-on-close="true"
    >
      <div v-if="currentBatch" v-loading="drawerLoading" class="drawer">
        <!-- 进度面板 -->
        <div class="card status-panel">
          <div class="status-head">
            <ElTag
              :type="rowStatusTagType(currentBatch)"
              effect="plain"
            >
              {{ rowStatusLabel(currentBatch) }}
            </ElTag>
            <span class="dm-text-small dm-text-muted">
              #{{ currentBatch.id }} · 创建于 {{ fmtTime(currentBatch.created_at) }}
            </span>
            <div class="spacer-right">
              <ElButton
                v-if="currentBatch.can_resume"
                size="small"
                type="primary"
                @click="doResume(currentBatch)"
              >
                <template #icon><Play :size="14" :stroke-width="1.6" /></template>
                续跑
              </ElButton>
              <ElButton
                v-else-if="currentBatch.is_active"
                size="small"
                type="warning"
                @click="doCancel(currentBatch)"
              >
                <template #icon><Ban :size="14" :stroke-width="1.6" /></template>
                中断
              </ElButton>
              <ElButton size="small" @click="refreshDrawer">
                <template #icon><RefreshCcw :size="14" :stroke-width="1.6" /></template>
                刷新
              </ElButton>
            </div>
          </div>

          <ElProgress
            :percentage="progressPct(currentBatch)"
            :stroke-width="10"
            :status="
              currentBatch.failed_count > 0
                ? 'exception'
                : progressPct(currentBatch) === 100
                  ? 'success'
                  : undefined
            "
          />

          <div class="metric-row">
            <div class="metric"><span class="m-l">总数</span><span class="m-v">{{ currentBatch.total_count }}</span></div>
            <div class="metric"><span class="m-l">已完成</span><span class="m-v ok">{{ currentBatch.completed_count }}</span></div>
            <div class="metric"><span class="m-l">失败</span><span class="m-v err">{{ currentBatch.failed_count }}</span></div>
            <div class="metric"><span class="m-l">中断</span><span class="m-v">{{ currentBatch.cancelled_count }}</span></div>
            <div class="metric">
              <span class="m-l">当前</span>
              <span class="m-v mono">
                {{ currentBatch.current_index + 1 }}/{{ currentBatch.total_count }}
                <span v-if="currentBatch.is_active && currentBatch.current_round != null">
                  · R{{ currentBatch.current_round }}
                </span>
              </span>
            </div>
          </div>

          <div v-if="currentBatch.summary?.outcome_dist" class="outcome-row">
            <span class="dm-text-small dm-text-muted">Outcome：</span>
            <ElTag
              v-for="(n, k) in currentBatch.summary.outcome_dist"
              :key="k"
              size="small"
              effect="plain"
              class="oc-tag"
            >
              {{ k }} · {{ n }}
            </ElTag>
          </div>
        </div>

        <!-- 子 session 列表 -->
        <div class="card">
          <div class="sub-head">
            <h4>关联 Session（{{ subSessions.length }}/{{ currentBatch.total_count }})</h4>
          </div>
          <ElTable :data="subSessions" size="small" stripe>
            <ElTableColumn label="#" width="48" align="right">
              <template #default="{ row }">{{ row.batch_index + 1 }}</template>
            </ElTableColumn>
            <ElTableColumn label="客户" min-width="120">
              <template #default="{ row }">{{ personaLabel(row.persona_id) }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="90">
              <template #default="{ row }">
                <ElTag
                  size="small"
                  effect="plain"
                  :type="row.status === 'done' ? 'success' : row.status === 'failed' ? 'danger' : 'info'"
                >
                  {{ row.status }}
                </ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="Outcome" min-width="110">
              <template #default="{ row }">
                <span v-if="row.outcome" class="mono dm-text-small">{{ row.outcome }}</span>
                <span v-else class="dm-text-muted">—</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="轮数" width="64" align="right">
              <template #default="{ row }">{{ row.total_rounds }}</template>
            </ElTableColumn>
            <ElTableColumn label="开始" min-width="140">
              <template #default="{ row }">
                <span class="dm-text-caption mono">{{ fmtTime(row.started_at) }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="140" align="right">
              <template #default="{ row }">
                <ElButton
                  v-if="row.status === 'running'"
                  size="small"
                  text
                  @click="gotoSessionLive(row.id)"
                >
                  现场
                </ElButton>
                <ElButton size="small" text @click="gotoSessionDetail(row.id)">
                  复盘
                </ElButton>
              </template>
            </ElTableColumn>
          </ElTable>
        </div>

        <!-- 实时事件流（仅 active 时收到） -->
        <div v-if="wsEvents.length" class="card events">
          <div class="sub-head">
            <h4>
              <Activity :size="14" :stroke-width="1.6" class="ev-icon" />
              事件流（{{ wsEvents.length }}）
            </h4>
          </div>
          <ul class="ev-list mono dm-text-caption">
            <li
              v-for="(e, i) in wsEvents.slice(-50).reverse()"
              :key="i"
              class="ev-item"
              :class="`ev-${e.type}`"
            >
              <span class="ev-tag">{{ e.type }}</span>
              <span v-if="e.data?.idx != null">[{{ e.data.idx + 1 }}/{{ e.data.total }}]</span>
              <span v-if="e.data?.persona_id">p{{ e.data.persona_id }}</span>
              <span v-if="e.data?.outcome">→ {{ e.data.outcome }}</span>
              <span v-if="e.data?.status && e.data?.status !== e.data?.outcome">({{ e.data.status }})</span>
              <span v-if="e.data?.message" class="ev-msg">{{ e.data.message }}</span>
            </li>
          </ul>
        </div>
      </div>
    </ElDrawer>
  </div>
</template>

<style scoped lang="scss">
.page {
  padding: var(--dm-space-7);
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-5);
}
.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-md);
  padding: var(--dm-space-4);
}
.table-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-3);
}
.cell-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  .err { color: var(--dm-text-danger, #9b2c2c); }
  .cancel { color: var(--dm-text-muted); }
}
.op-bar {
  display: flex;
  justify-content: flex-end;
  gap: var(--dm-space-1);
}
.mono { font-family: var(--dm-font-mono); }
.ellipsis {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 100%; display: inline-block;
}

/* el-table 行密度 */
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

/* ===== 创建 dialog ===== */
.persona-picker {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-2);
}
.persona-toolbar {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
  .search { width: 220px; }
  .spacer-right { margin-left: auto; }
}
.persona-grid {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-sm);
  padding: var(--dm-space-3);
}
:deep(.el-checkbox-group) {
  display: flex;
  flex-wrap: wrap;
  gap: var(--dm-space-2);
}
.persona-chip {
  margin: 0 !important;
  .chip-name { margin-right: 6px; }
  .chip-tag { font-size: 11px; }
}
.row-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--dm-space-3);
  :deep(.el-form-item) {
    margin-bottom: 0;
    flex-direction: column;
    align-items: flex-start;
  }
  :deep(.el-form-item__label) {
    width: auto !important;
    text-align: left;
    line-height: 1.4;
    padding-bottom: 6px;
    color: var(--dm-text-secondary);
    font-size: var(--dm-fs-small);
  }
  :deep(.el-form-item__content) { width: 100%; }
  :deep(.el-input-number) { width: 100%; }
}
.lang-hint {
  margin-top: 4px;
}
.full { width: 100%; }
.perf-hint {
  margin: 0;
  padding: 10px 14px;
  background: var(--dm-bg-muted);
  border-radius: var(--dm-radius-sm);
  line-height: 1.6;
}

/* ===== 详情抽屉 ===== */
.drawer {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-4);
}
.status-panel {
  display: flex;
  flex-direction: column;
  gap: var(--dm-space-3);
}
.status-head {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
  .spacer-right { margin-left: auto; display: flex; gap: var(--dm-space-2); }
}
.metric-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--dm-space-3);
  padding-top: var(--dm-space-2);
}
.metric {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: var(--dm-space-2) var(--dm-space-3);
  background: var(--dm-bg-elevated);
  border-radius: var(--dm-radius-sm);
  .m-l {
    font-size: var(--dm-fs-small);
    color: var(--dm-text-muted);
  }
  .m-v {
    font-size: var(--dm-fs-h4);
    font-weight: var(--dm-fw-bold);
    color: var(--dm-text);
    &.ok  { color: #2d7a3e; }
    &.err { color: #9b2c2c; }
  }
}
.outcome-row {
  display: flex;
  align-items: center;
  gap: var(--dm-space-2);
  flex-wrap: wrap;
}
.oc-tag { font-family: var(--dm-font-mono); }
.sub-head {
  margin-bottom: var(--dm-space-3);
  h4 {
    margin: 0;
    font-size: var(--dm-fs-h4);
    color: var(--dm-text);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .ev-icon { color: var(--dm-text-muted); }
}
.events {
  background: var(--dm-bg-elevated);
}
.ev-list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 260px;
  overflow-y: auto;
}
.ev-item {
  padding: 4px 0;
  border-bottom: 1px dashed var(--dm-border);
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
  color: var(--dm-text);
}
.ev-tag {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: 4px;
  padding: 0 6px;
  font-size: 11px;
  color: var(--dm-text-muted);
}
.ev-batch_done .ev-tag { color: #2d7a3e; }
.ev-session_open .ev-tag { color: #1e5fa8; }
.ev-session_close .ev-tag { color: #9a6c1a; }
.ev-log .ev-tag { color: #9b2c2c; }
.ev-msg { color: var(--dm-text-muted); }
</style>
