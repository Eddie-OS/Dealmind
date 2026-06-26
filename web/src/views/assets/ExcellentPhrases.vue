<script setup lang="ts">
/**
 * 优秀话术库
 *
 * 展示从分析报告沉淀的「单条优秀销冠话术」（含客户上文、销冠原话、为什么好、
 * 客户购买信号变化）。销冠 Agent 也可通过 search_excellent_phrases 工具检索学习。
 *
 * 设计：
 * - 顶部：分组 tab（135910 + 手册外）+ 关键字搜索 + 最低优秀度筛选
 * - 卡片网格：优秀度评分 / 命中条目 / 客户上文 / 销冠话术 / 为什么好 / 购买信号
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElCol,
  ElIcon,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElPagination,
  ElRow,
  ElSlider,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTooltip,
} from 'element-plus'
import { RefreshCcw, Search, Trash2, Sparkles, TrendingUp } from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import {
  excellentPhrasesApi,
  type ExcellentPhrase,
  type PhraseGroup,
  type PhraseListResponse,
} from '@/api/excellent_phrases'

const filters = reactive({
  group_key: '' as string,
  keyword: '',
  min_score: 0,
})
const page = ref(1)
const pageSize = ref(12)

const loading = ref(false)
const listResp = ref<PhraseListResponse>({
  items: [],
  total: 0,
  page: 1,
  page_size: 12,
})
const groups = ref<PhraseGroup[]>([])
const groupTotal = ref(0)

const items = computed(() => listResp.value.items)

async function loadList() {
  loading.value = true
  try {
    listResp.value = await excellentPhrasesApi.list({
      group_key: filters.group_key || undefined,
      keyword: filters.keyword || undefined,
      min_score: filters.min_score > 0 ? filters.min_score : undefined,
      page: page.value,
      page_size: pageSize.value,
    })
  } catch (e: unknown) {
    ElMessage.error('加载优秀话术失败：' + (e as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadGroups() {
  try {
    const resp = await excellentPhrasesApi.groups()
    groups.value = resp.groups
    groupTotal.value = resp.total
  } catch (e: unknown) {
    console.warn('分组计数加载失败', e)
  }
}

async function refreshAll() {
  await Promise.all([loadList(), loadGroups()])
}

function onGroupTabChange(name: string) {
  filters.group_key = name
  page.value = 1
  loadList()
}

function onSearchEnter() {
  page.value = 1
  loadList()
}

function onScoreChange() {
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

async function deletePhrase(p: ExcellentPhrase) {
  try {
    await ElMessageBox.confirm(
      '确认从优秀话术库中删除这条话术？此操作不可恢复。',
      '删除优秀话术',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await excellentPhrasesApi.del(p.id)
    ElMessage.success('已删除')
    await refreshAll()
  } catch (e: unknown) {
    ElMessage.error('删除失败：' + (e as Error).message)
  }
}

function scoreTone(v: number): string {
  if (v >= 8) return 'success'
  if (v >= 6.5) return 'warning'
  return 'info'
}

function signalDelta(p: ExcellentPhrase): number | null {
  if (p.purchase_signal_before == null || p.purchase_signal_after == null) {
    return null
  }
  return Math.round((p.purchase_signal_after - p.purchase_signal_before) * 100) / 100
}

onMounted(() => {
  refreshAll()
})
</script>

<template>
  <div class="excellent-phrases">
    <DmPageHeader
      title="优秀话术库"
      subtitle="从模拟销售分析中沉淀的单条优秀话术；销冠 Agent 可在新会话中检索学习并化用"
    >
      <template #actions>
        <ElButton @click="refreshAll" :loading="loading">
          <ElIcon><RefreshCcw /></ElIcon>
          <span style="margin-left: 6px">刷新</span>
        </ElButton>
      </template>
    </DmPageHeader>

    <!-- 筛选 / 搜索 -->
    <ElCard class="filter-bar" shadow="never">
      <div class="filter-row">
        <ElTabs
          v-model="filters.group_key"
          @tab-change="onGroupTabChange"
          class="group-tabs"
        >
          <ElTabPane name="">
            <template #label>
              <span class="tab-label">
                <span>全部</span>
                <span class="tab-badge">{{ groupTotal }}</span>
              </span>
            </template>
          </ElTabPane>
          <ElTabPane v-for="g in groups" :key="g.key" :name="g.key">
            <template #label>
              <span class="tab-label">
                <span>{{ g.label }}</span>
                <span class="tab-badge">{{ g.count }}</span>
              </span>
            </template>
          </ElTabPane>
        </ElTabs>

        <div class="score-filter">
          <span class="score-filter-label">最低优秀度</span>
          <ElSlider
            v-model="filters.min_score"
            :min="0"
            :max="10"
            :step="0.5"
            style="width: 120px"
            @change="onScoreChange"
          />
        </div>

        <ElInput
          v-model="filters.keyword"
          placeholder="按话术/客户上文/条目搜索…"
          style="max-width: 280px"
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
    <div v-if="loading && items.length === 0" class="loading-hint">加载中…</div>

    <DmEmpty
      v-else-if="!loading && items.length === 0"
      title="尚未沉淀优秀话术"
      description="跑一次分析报告后，系统会自动把高分优秀话术沉淀到这里，供销冠在新会话中学习。"
    />

    <ElRow v-else :gutter="16" class="card-grid">
      <ElCol v-for="p in items" :key="p.id" :xs="24" :sm="12" :md="8" :lg="6">
        <ElCard class="phrase-card" shadow="hover" body-style="padding: 16px;">
          <div class="card-head">
            <ElTag :type="(scoreTone(p.excellence_score) as any)" size="small" effect="plain">
              {{ p.excellence_score?.toFixed(1) }} / 10
            </ElTag>
            <ElTag
              v-if="p.is_off_handbook"
              size="small"
              type="warning"
              effect="plain"
            >
              手册外金句
            </ElTag>
            <ElTag v-else-if="p.handbook_label" size="small" effect="plain">
              {{ p.handbook_label }}
            </ElTag>
            <span class="card-spacer" />
            <ElTooltip content="从库中删除" placement="top">
              <ElButton size="small" text @click.stop="deletePhrase(p)" class="card-del">
                <ElIcon><Trash2 :size="14" /></ElIcon>
              </ElButton>
            </ElTooltip>
          </div>

          <div v-if="p.customer_question" class="card-cust">
            <span class="cust-label">客户</span>{{ p.customer_question }}
          </div>

          <p class="card-sales">{{ p.sales_content }}</p>

          <ul v-if="p.why_good && p.why_good.length" class="card-why">
            <li v-for="(w, i) in p.why_good.slice(0, 3)" :key="i">{{ w }}</li>
          </ul>

          <div class="card-meta">
            <span v-if="signalDelta(p) !== null" class="meta-signal">
              <ElIcon><TrendingUp :size="13" /></ElIcon>
              购买信号 {{ p.purchase_signal_before?.toFixed(1) }}→{{
                p.purchase_signal_after?.toFixed(1)
              }}
            </span>
            <span class="meta-spacer" />
            <span v-if="p.persona_name" class="meta-persona">{{ p.persona_name }}</span>
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
  </div>
</template>

<style scoped lang="scss">
.excellent-phrases {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar :deep(.el-card__body) {
  padding: 8px 16px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.group-tabs {
  flex: 1;
  min-width: 0;
}
.group-tabs :deep(.el-tabs__header) {
  margin: 0;
}
.tab-label {
  display: inline-flex;
  gap: 6px;
  align-items: center;
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
.score-filter {
  display: flex;
  align-items: center;
  gap: 8px;
}
.score-filter-label {
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
  white-space: nowrap;
}

.loading-hint {
  padding: 40px;
  text-align: center;
  color: var(--dm-text-tertiary, #94a3b8);
}

.card-grid {
  row-gap: 16px;
}
.phrase-card {
  height: 100%;
  border-left: 3px solid var(--dm-border-strong);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.phrase-card:hover {
  border-left-color: var(--dm-text);
  box-shadow: var(--dm-shadow-xs);
}
.phrase-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 240px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-spacer {
  flex: 1;
}
.card-del :deep(.el-icon) {
  color: var(--dm-text-tertiary, #94a3b8);
}
.card-del:hover :deep(.el-icon) {
  color: var(--el-color-danger);
}
.card-cust {
  font-size: 12.5px;
  color: var(--dm-text-secondary, #475569);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cust-label {
  display: inline-block;
  font-size: 11px;
  color: var(--dm-text-tertiary, #94a3b8);
  margin-right: 6px;
}
.card-sales {
  margin: 0;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--dm-text-primary, #1a202c);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}
.card-why {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--dm-text-secondary);
  line-height: 1.5;
}
.card-why li::marker {
  color: var(--dm-success);
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--dm-text-tertiary, #94a3b8);
}
.meta-signal {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--el-color-success);
}
.meta-spacer {
  flex: 1;
}
.meta-persona {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 4px 0 8px;
}
</style>
