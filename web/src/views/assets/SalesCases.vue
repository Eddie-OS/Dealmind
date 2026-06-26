<script setup lang="ts">
/**
 * 销售案例集（Stage 11）
 *
 * 设计：
 * - 顶部：4 source tab + 关键字搜索 + 总数统计
 * - 卡片网格：title / scene / source / persona_tags / 来源文件 / 创建时间
 * - 详情抽屉：dialogue_excerpt + why_excellent + raw_content（preset 多用此字段）
 *           + 编辑 title/why/tags + 删除
 * - 顶部右上角：刷新 + 重跑 preset 预填（开发辅助）
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElCol,
  ElDrawer,
  ElEmpty,
  ElIcon,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElPagination,
  ElRow,
  ElSelect,
  ElOption,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
} from 'element-plus'
import {
  RefreshCcw,
  Search,
  Trash2,
  Save,
  Sparkles,
  FileText,
  User,
} from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import {
  casesApi,
  type CaseListResponse,
  type CaseSource,
  type CaseSourcesResp,
  type SalesCase,
} from '@/api/cases'

// ============================================================
// 列表 / 筛选状态
// ============================================================

const SOURCE_OPTIONS: Array<{ key: '' | CaseSource; label: string }> = [
  { key: '', label: '全部' },
  { key: 'preset', label: 'Preset 预填' },
  { key: 'judge_auto', label: 'Judge 高分' },
  { key: 'coach_auto', label: 'Coach 策略' },
  { key: 'manual', label: '手动收藏' },
]

const SOURCE_TAG_TYPE: Record<CaseSource, string> = {
  preset: 'info',
  judge_auto: 'success',
  coach_auto: 'warning',
  manual: 'primary',
}

const SOURCE_TAG_LABEL: Record<CaseSource, string> = {
  preset: 'Preset',
  judge_auto: 'Judge',
  coach_auto: 'Coach',
  manual: 'Manual',
}

const filters = reactive({
  source: '' as '' | CaseSource,
  keyword: '',
})
const page = ref(1)
const pageSize = ref(12)

const loading = ref(false)
const listResp = ref<CaseListResponse>({
  items: [], total: 0, page: 1, page_size: 12,
})
const sourcesResp = ref<CaseSourcesResp>({
  total: 0,
  by_source: { preset: 0, judge_auto: 0, coach_auto: 0, manual: 0 },
})

const items = computed(() => listResp.value.items)

// ============================================================
// 详情抽屉
// ============================================================

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<SalesCase | null>(null)
// 可编辑字段
const edit = reactive<{ title: string; why_excellent: string; tags: string[] }>(
  { title: '', why_excellent: '', tags: [] },
)
const editingDirty = ref(false)

watch(
  () => detail.value,
  (val) => {
    edit.title = val?.title ?? ''
    edit.why_excellent = val?.why_excellent ?? ''
    edit.tags = Array.isArray(val?.tags) ? [...(val!.tags || [])] : []
    editingDirty.value = false
  },
)

watch(
  () => [edit.title, edit.why_excellent, [...edit.tags].join('|')],
  () => {
    if (!detail.value) return
    const t = detail.value
    editingDirty.value =
      edit.title !== (t.title ?? '') ||
      edit.why_excellent !== (t.why_excellent ?? '') ||
      JSON.stringify(edit.tags) !== JSON.stringify(t.tags ?? [])
  },
)

// ============================================================
// 加载逻辑
// ============================================================

async function loadList() {
  loading.value = true
  try {
    const resp = await casesApi.list({
      source: filters.source || undefined,
      keyword: filters.keyword || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    listResp.value = resp
  } catch (e: unknown) {
    ElMessage.error('加载案例列表失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadSources() {
  try {
    sourcesResp.value = await casesApi.sources()
  } catch (e: unknown) {
    // 静默
    console.warn('sources 计数加载失败', e)
  }
}

async function refreshAll() {
  await Promise.all([loadList(), loadSources()])
}

function onSourceTabChange(name: string) {
  filters.source = name as '' | CaseSource
  page.value = 1
  loadList()
}

function onSearchEnter() {
  page.value = 1
  loadList()
}

function onPageChange(p: number) {
  page.value = p
  loadList()
}

function onPageSizeChange(s: number) {
  pageSize.value = s
  page.value = 1
  loadList()
}

// ============================================================
// 卡片点击 / 详情 / 编辑 / 删除
// ============================================================

async function openDetail(c: SalesCase) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await casesApi.detail(c.id)
  } catch (e: unknown) {
    ElMessage.error('加载详情失败：' + (e as Error).message)
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function saveEdit() {
  if (!detail.value) return
  try {
    const updated = await casesApi.update(detail.value.id, {
      title: edit.title.trim() || detail.value.title,
      why_excellent: edit.why_excellent,
      tags: edit.tags,
    })
    detail.value = updated
    // 刷新列表中对应项
    const idx = listResp.value.items.findIndex((x) => x.id === updated.id)
    if (idx >= 0) listResp.value.items.splice(idx, 1, updated)
    editingDirty.value = false
    ElMessage.success('已保存')
  } catch (e: unknown) {
    ElMessage.error('保存失败：' + (e as Error).message)
  }
}

async function deleteCase(c: SalesCase, fromDetail = false) {
  try {
    await ElMessageBox.confirm(
      `确认删除案例「${c.title}」？此操作不可恢复。`,
      '删除案例',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await casesApi.del(c.id)
    ElMessage.success('已删除')
    if (fromDetail) detailVisible.value = false
    await refreshAll()
  } catch (e: unknown) {
    ElMessage.error('删除失败：' + (e as Error).message)
  }
}

async function reseedPreset() {
  try {
    const r = await casesApi.reseedPreset()
    if (r.inserted > 0) {
      ElMessage.success(`已重新导入 ${r.inserted} 条 preset 案例`)
    } else {
      ElMessage.info('案例表非空，跳过 preset 预填')
    }
    await refreshAll()
  } catch (e: unknown) {
    ElMessage.error('预填失败：' + (e as Error).message)
  }
}

// ============================================================
// 辅助渲染
// ============================================================

function shortDate(iso?: string | null): string {
  if (!iso) return '—'
  return String(iso).slice(0, 16).replace('T', ' ')
}

function previewBody(c: SalesCase): string {
  if (c.why_excellent && c.why_excellent.trim()) return c.why_excellent
  const first = c.dialogue_excerpt?.[0]
  if (first && first.content) return first.content
  if (c.raw_content) return c.raw_content
  return '（暂无摘要）'
}

function turnSpeakerLabel(s: string): string {
  return s === 'sales' ? '销冠' : s === 'persona' ? '客户' : s
}

onMounted(() => {
  refreshAll()
})
</script>

<template>
  <div class="sales-cases">
    <DmPageHeader
      title="销售案例集"
      subtitle="三轨自动入库：Judge 高分整场 + Coach 标记策略 + 手动收藏；启动时自动预填训练资料"
    >
      <template #actions>
        <ElButton @click="refreshAll" :loading="loading">
          <ElIcon><RefreshCcw /></ElIcon>
          <span style="margin-left: 6px">刷新</span>
        </ElButton>
        <ElButton type="primary" plain @click="reseedPreset">
          <ElIcon><Sparkles /></ElIcon>
          <span style="margin-left: 6px">重跑预填</span>
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 筛选 / 搜索 -->
    <ElCard class="filter-bar" shadow="never">
      <div class="filter-row">
        <ElTabs
          v-model="filters.source"
          @tab-change="onSourceTabChange"
          class="source-tabs"
        >
          <ElTabPane
            v-for="opt in SOURCE_OPTIONS"
            :key="opt.key || 'all'"
            :name="opt.key"
          >
            <template #label>
              <span style="display: inline-flex; gap: 6px; align-items: center">
                <span>{{ opt.label }}</span>
                <span class="tab-badge">
                  {{
                    opt.key === ''
                      ? sourcesResp.total
                      : sourcesResp.by_source[opt.key as CaseSource] ?? 0
                  }}
                </span>
              </span>
            </template>
          </ElTabPane>
        </ElTabs>

        <ElInput
          v-model="filters.keyword"
          placeholder="按标题/场景/正文搜索…"
          style="max-width: 320px; margin-left: auto"
          clearable
          @keyup.enter="onSearchEnter"
          @clear="onSearchEnter"
        >
          <template #prefix>
            <ElIcon><Search /></ElIcon>
          </template>
        </ElInput>

        <ElButton @click="onSearchEnter">搜索</ElButton>
      </div>
    </ElCard>

    <!-- 列表 -->
    <div v-if="loading && items.length === 0" class="loading-hint">
      加载中…
    </div>

    <DmEmpty
      v-else-if="!loading && items.length === 0"
      title="尚未沉淀销售案例"
      description="跑一场对话或手动从会话详情收藏，即可在此见到案例。也可点「重跑预填」从训练资料导入。"
    />

    <ElRow v-else :gutter="16" class="card-grid">
      <ElCol
        v-for="c in items"
        :key="c.id"
        :xs="24"
        :sm="12"
        :md="8"
        :lg="6"
      >
        <ElCard
          class="case-card"
          shadow="hover"
          body-style="padding: 16px;"
          @click="openDetail(c)"
        >
          <div class="card-head">
            <ElTag
              :type="(SOURCE_TAG_TYPE[c.source] as any) || 'info'"
              size="small"
              effect="plain"
            >
              {{ SOURCE_TAG_LABEL[c.source] || c.source }}
            </ElTag>
            <span class="card-date">{{ shortDate(c.created_at) }}</span>
          </div>

          <div class="card-title" :title="c.title">{{ c.title }}</div>
          <div v-if="c.scene" class="card-scene">{{ c.scene }}</div>

          <p class="card-body">{{ previewBody(c) }}</p>

          <div class="card-tags">
            <ElTag
              v-for="t in c.tags?.slice(0, 4) ?? []"
              :key="'tg-' + t"
              size="small"
              type="info"
              effect="plain"
            >
              {{ t }}
            </ElTag>
            <ElTag
              v-for="pt in c.persona_tags?.slice(0, 2) ?? []"
              :key="'pt-' + pt"
              size="small"
              effect="plain"
            >
              {{ pt }}
            </ElTag>
          </div>

          <div class="card-meta">
            <span v-if="c.file_source" class="meta-item">
              <ElIcon><FileText :size="14" /></ElIcon>
              <span class="meta-text">{{ c.file_source }}</span>
            </span>
            <span v-else-if="c.session_id" class="meta-item">
              <ElIcon><User :size="14" /></ElIcon>
              <span class="meta-text">{{ c.session_id }}</span>
            </span>
            <span class="meta-spacer" />
            <ElTooltip content="删除案例" placement="top">
              <ElButton
                size="small"
                text
                @click.stop="deleteCase(c)"
                class="meta-del"
              >
                <ElIcon><Trash2 :size="14" /></ElIcon>
              </ElButton>
            </ElTooltip>
          </div>
        </ElCard>
      </ElCol>
    </ElRow>

    <div v-if="listResp.total > 0" class="pagination-bar">
      <ElPagination
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[12, 24, 48, 96]"
        :total="listResp.total"
        background
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </div>

    <!-- 详情抽屉 -->
    <ElDrawer
      v-model="detailVisible"
      :title="detail?.title || '案例详情'"
      size="780px"
      direction="rtl"
    >
      <template v-if="detail" #default>
        <div v-if="detailLoading" class="loading-hint">加载中…</div>

        <div v-else class="detail-body">
          <div class="detail-header">
            <ElTag
              :type="(SOURCE_TAG_TYPE[detail.source] as any) || 'info'"
              size="small"
            >
              {{ SOURCE_TAG_LABEL[detail.source] }}
            </ElTag>
            <span v-if="detail.scene" class="detail-scene">
              · {{ detail.scene }}
            </span>
            <span v-if="detail.file_source" class="detail-file">
              · 来源 {{ detail.file_source }}
            </span>
            <span v-if="detail.session_id" class="detail-file">
              · session {{ detail.session_id }}
            </span>
          </div>

          <section class="detail-section">
            <h3>标题</h3>
            <ElInput v-model="edit.title" placeholder="案例标题" />
          </section>

          <section class="detail-section">
            <h3>为什么是好案例</h3>
            <ElInput
              v-model="edit.why_excellent"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 12 }"
              placeholder="可手写说明，亦可保留 Judge/Coach 自动生成的理由"
            />
          </section>

          <section class="detail-section">
            <h3>标签</h3>
            <ElSelect
              v-model="edit.tags"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="回车添加，便于后续筛选"
              style="width: 100%"
            >
              <ElOption
                v-for="t in edit.tags"
                :key="'opt-' + t"
                :value="t"
                :label="t"
              />
            </ElSelect>
          </section>

          <section
            v-if="detail.persona_tags && detail.persona_tags.length"
            class="detail-section"
          >
            <h3>人设标签</h3>
            <div class="readonly-tags">
              <ElTag
                v-for="pt in detail.persona_tags"
                :key="'pdtg-' + pt"
                effect="plain"
                size="small"
              >
                {{ pt }}
              </ElTag>
            </div>
          </section>

          <section
            v-if="detail.dialogue_excerpt && detail.dialogue_excerpt.length"
            class="detail-section"
          >
            <h3>对话片段</h3>
            <div class="dialogue-list">
              <div
                v-for="(t, i) in detail.dialogue_excerpt"
                :key="'turn-' + i"
                class="dialogue-turn"
                :class="t.speaker"
              >
                <div class="turn-header">
                  <strong>{{ turnSpeakerLabel(t.speaker) }}</strong>
                  <span class="turn-idx">#{{ t.idx }}</span>
                  <span v-if="t.stage" class="turn-stage">{{ t.stage }}</span>
                </div>
                <div class="turn-content">{{ t.content }}</div>
              </div>
            </div>
          </section>

          <section
            v-if="detail.raw_content && detail.source === 'preset'"
            class="detail-section"
          >
            <h3>原文摘录</h3>
            <pre class="raw-text">{{ detail.raw_content }}</pre>
          </section>
        </div>
      </template>

      <template #footer>
        <div class="drawer-footer">
          <ElButton danger plain @click="detail && deleteCase(detail, true)">
            <ElIcon><Trash2 /></ElIcon>
            <span style="margin-left: 6px">删除</span>
          </ElButton>
          <span style="flex: 1" />
          <ElButton @click="detailVisible = false">关闭</ElButton>
          <ElButton type="primary" :disabled="!editingDirty" @click="saveEdit">
            <ElIcon><Save /></ElIcon>
            <span style="margin-left: 6px">保存</span>
          </ElButton>
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped lang="scss">
.sales-cases {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar :deep(.el-card__body) {
  padding: 8px 16px 0;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.source-tabs {
  flex: 1;
  min-width: 0;
}
.source-tabs :deep(.el-tabs__header) {
  margin: 0;
}
.tab-badge {
  display: inline-block;
  min-width: 22px;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  font-size: 11px;
  text-align: center;
  border-radius: 9px;
  background: var(--dm-bg-muted, #f1f5f9);
  color: var(--dm-text-secondary, #475569);
}

.loading-hint {
  padding: 40px;
  text-align: center;
  color: var(--dm-text-tertiary, #94a3b8);
}

.card-grid {
  row-gap: 16px;
}

.case-card {
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  height: 100%;
}
.case-card:hover {
  border-color: var(--dm-border-strong);
  box-shadow: var(--dm-shadow-xs);
}
.case-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 248px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-date {
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--dm-text-primary, #1a202c);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-scene {
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
}
.card-body {
  margin: 0;
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 200px;
  overflow: hidden;
}
.meta-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}
.meta-spacer {
  flex: 1;
}
.meta-del :deep(.el-icon) {
  color: var(--dm-text-tertiary, #94a3b8);
}
.meta-del:hover :deep(.el-icon) {
  color: var(--el-color-danger);
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 4px 0 8px;
}

/* 抽屉 */
.detail-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-bottom: 12px;
}
.detail-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
}
.detail-scene, .detail-file {
  color: var(--dm-text-tertiary, #94a3b8);
}

.detail-section h3 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--dm-text-secondary, #475569);
  letter-spacing: 0.02em;
}
.readonly-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dialogue-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 480px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid var(--dm-border, #e2e8f0);
  border-radius: 8px;
  background: var(--dm-bg-muted, #f8fafc);
}
.dialogue-turn {
  padding: 10px 12px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid var(--dm-border, #e2e8f0);
}
.dialogue-turn.sales {
  border-left: 3px solid var(--el-color-primary);
}
.dialogue-turn.persona {
  border-left: 3px solid var(--el-color-warning);
}
.turn-header {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--dm-text-secondary, #475569);
  margin-bottom: 6px;
}
.turn-idx {
  color: var(--dm-text-tertiary, #94a3b8);
}
.turn-stage {
  font-size: 11px;
  color: var(--dm-text-tertiary, #94a3b8);
  background: var(--dm-bg-muted, #f1f5f9);
  padding: 1px 6px;
  border-radius: 4px;
}
.turn-content {
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: var(--dm-text-primary, #1a202c);
}

.raw-text {
  max-height: 320px;
  overflow: auto;
  background: var(--dm-bg-muted, #f8fafc);
  border: 1px solid var(--dm-border, #e2e8f0);
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: var(--dm-text-secondary, #475569);
}

.drawer-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
</style>
