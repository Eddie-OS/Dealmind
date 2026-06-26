<script setup lang="ts">
/**
 * 向量库管理（蓝图 §Stage 5）
 *
 * 布局：
 *   顶部 — Embedding 模型卡片（backend / model / dim / 总占用）
 *   下方 — Collection 表（含统计 + 操作：重建 / 清空）
 * 状态：
 *   重建后启动 polling（每 2s 拉一次列表，直到 chunk_count 稳定）
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElEmpty,
  ElIcon,
  ElMessage,
  ElMessageBox,
  ElPopconfirm,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
} from 'element-plus'
import { Database, RefreshCcw, Trash2, RotateCcw, Cpu, HardDrive, Info } from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import {
  COLLECTION_LABEL,
  fmtBytes,
  vectorApi,
  type CollectionInfo,
  type CollectionListResponse,
} from '@/api/vector'

const data = ref<CollectionListResponse | null>(null)
const loading = ref(false)
const actionLoading = ref<string | null>(null)
let pollingTimer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  loading.value = true
  try {
    data.value = await vectorApi.listCollections()
    // 启动/停止 polling
    const hasActivity = data.value.items.some((c) => c.chunk_count !== c.db_chunk_count)
    if (hasActivity) startPolling()
    else stopPolling()
  } catch (e: any) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function startPolling(intervalMs = 2500) {
  if (pollingTimer) return
  pollingTimer = setInterval(() => {
    refresh().catch(() => undefined)
  }, intervalMs)
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
}

onMounted(() => refresh())
onUnmounted(() => stopPolling())

async function handleRebuild(col: CollectionInfo) {
  try {
    await ElMessageBox.confirm(
      `确定重建「${COLLECTION_LABEL[col.name] || col.name}」索引？\n会清空向量数据并把 ${col.kb_file_count} 个文件复位为待索引，后台自动重新嵌入。`,
      '重建索引',
      { confirmButtonText: '重建', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  actionLoading.value = col.name
  try {
    const res = await vectorApi.rebuild(col.name)
    ElMessage.success(
      `已重建：${res.message}（涉及 ${res.affected_kbs} 个 KB / ${res.affected_files} 个文件）`,
    )
    await refresh()
    startPolling()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '重建失败')
  } finally {
    actionLoading.value = null
  }
}

async function handleClear(col: CollectionInfo) {
  actionLoading.value = col.name
  try {
    const res = await vectorApi.clear(col.name)
    ElMessage.success(
      `已清空：${res.message}（涉及 ${res.affected_files} 个文件状态回退）`,
    )
    await refresh()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '清空失败')
  } finally {
    actionLoading.value = null
  }
}

const totalChunks = computed(() =>
  (data.value?.items || []).reduce((s, c) => s + (c.chunk_count || 0), 0),
)
const totalKBs = computed(() =>
  (data.value?.items || []).reduce((s, c) => s + (c.kb_count || 0), 0),
)
</script>

<template>
  <div class="vector-admin">
    <DmPageHeader
      title="向量库管理"
      subtitle="查看 Chroma collection 索引状态、重建或清空向量数据"
    >
      <template #actions>
        <ElButton :icon="RefreshCcw" :loading="loading" @click="refresh">刷新</ElButton>
      </template>
    </DmPageHeader>

    <!-- Embedding 模型 + 总览卡 -->
    <div class="overview-grid">
      <ElCard class="dm-card overview-card" shadow="never">
        <div class="overview-head">
          <ElIcon><Cpu :size="16" /></ElIcon>
          <span>Embedding 模型</span>
        </div>
        <div v-if="data?.embedder" class="overview-body">
          <div class="kv">
            <span class="k">后端</span>
            <ElTag size="small" :type="data.embedder.backend === 'sentence_transformers' ? 'success' : 'warning'">
              {{ data.embedder.backend }}
            </ElTag>
          </div>
          <div class="kv"><span class="k">模型</span><span class="v mono">{{ data.embedder.model }}</span></div>
          <div class="kv"><span class="k">维度</span><span class="v mono">{{ data.embedder.dim ?? '-' }}</span></div>
          <div v-if="data.embedder.hf_endpoint" class="kv">
            <span class="k">HF 镜像</span><span class="v mono">{{ data.embedder.hf_endpoint }}</span>
          </div>
          <div v-if="data.embedder.error" class="kv error">
            <span class="k">错误</span>
            <ElTooltip :content="data.embedder.error" placement="top">
              <span class="v mono">{{ data.embedder.error.slice(0, 60) }}…</span>
            </ElTooltip>
          </div>
        </div>
      </ElCard>

      <ElCard class="dm-card overview-card" shadow="never">
        <div class="overview-head">
          <ElIcon><Database :size="16" /></ElIcon>
          <span>向量总览</span>
        </div>
        <div v-if="data" class="overview-body">
          <div class="kv"><span class="k">Collection 数</span><span class="v mono">{{ data.total }}</span></div>
          <div class="kv"><span class="k">活跃 KB 数</span><span class="v mono">{{ totalKBs }}</span></div>
          <div class="kv"><span class="k">总切片数</span><span class="v mono">{{ totalChunks }}</span></div>
        </div>
      </ElCard>

      <ElCard class="dm-card overview-card" shadow="never">
        <div class="overview-head">
          <ElIcon><HardDrive :size="16" /></ElIcon>
          <span>磁盘占用</span>
        </div>
        <div v-if="data" class="overview-body">
          <div class="kv">
            <span class="k">Chroma 数据目录</span>
            <ElTooltip :content="data.chroma_dir" placement="top">
              <span class="v mono path">…{{ data.chroma_dir.split(/[\\/]/).slice(-3).join('/') }}</span>
            </ElTooltip>
          </div>
          <div class="kv"><span class="k">物理占用</span><span class="v mono">{{ fmtBytes(data.chroma_dir_bytes) }}</span></div>
        </div>
      </ElCard>
    </div>

    <!-- Collection 表 -->
    <ElCard class="dm-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span><Database :size="14" /> Collections</span>
          <span class="muted">点击「重建」会清空并自动重新索引；「清空」仅清除向量不重索引</span>
        </div>
      </template>

      <ElTable
        :data="data?.items || []"
        :loading="loading"
        empty-text="暂无 collection 数据"
      >
        <ElTableColumn label="Collection" min-width="200">
          <template #default="{ row }">
            <div class="col-name">
              <span class="name">{{ COLLECTION_LABEL[row.name] || row.name }}</span>
              <span class="key mono">{{ row.name }}</span>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="100">
          <template #default="{ row }">
            <ElTag v-if="row.exists" type="success" size="small">已就绪</ElTag>
            <ElTag v-else type="info" size="small">未启用</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="关联 KB" width="240">
          <template #default="{ row }">
            <div v-if="row.kbs.length" class="kb-pills">
              <ElTag
                v-for="kb in row.kbs"
                :key="kb.id"
                size="small"
                effect="plain"
                type="info"
              >
                {{ kb.name }} · {{ kb.file_count }}/{{ kb.chunk_count }}
              </ElTag>
            </div>
            <span v-else class="muted">无</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="向量切片" width="160" align="right">
          <template #default="{ row }">
            <div class="chunk-cell mono">
              <span>{{ row.chunk_count }}</span>
              <ElTooltip
                v-if="row.chunk_count !== row.db_chunk_count"
                placement="top"
                :content="`Chroma=${row.chunk_count} · DB 记录=${row.db_chunk_count}（索引中或不一致）`"
              >
                <ElIcon class="warn-icon"><Info :size="14" /></ElIcon>
              </ElTooltip>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="向量估算" width="120" align="right">
          <template #default="{ row }">
            <span class="mono muted">{{ fmtBytes(row.estimated_vector_bytes) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="200" align="center">
          <template #default="{ row }">
            <div class="ops">
              <ElButton
                size="small"
                type="primary"
                :icon="RotateCcw"
                :loading="actionLoading === row.name"
                :disabled="!row.exists || row.kb_file_count === 0"
                @click="handleRebuild(row)"
              >
                重建
              </ElButton>
              <ElPopconfirm
                :title="`确定清空『${COLLECTION_LABEL[row.name] || row.name}』向量数据？`"
                confirm-button-text="清空"
                cancel-button-text="取消"
                confirm-button-type="danger"
                @confirm="handleClear(row)"
              >
                <template #reference>
                  <ElButton
                    size="small"
                    :icon="Trash2"
                    :loading="actionLoading === row.name"
                    :disabled="!row.exists || row.chunk_count === 0"
                    text
                    type="danger"
                  >
                    清空
                  </ElButton>
                </template>
              </ElPopconfirm>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<style scoped lang="scss">
.vector-admin {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.overview-card { border: 1px solid var(--dm-border); border-radius: 12px; }
.overview-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--dm-text);
  font-size: 14px;
  margin-bottom: 12px;
}
.overview-body { display: flex; flex-direction: column; gap: 8px; }
.kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.kv .k { color: var(--dm-text-muted); }
.kv .v { color: var(--dm-text); word-break: break-all; max-width: 60%; text-align: right; }
.kv.error .v { color: var(--el-color-danger); }
.kv .v.path { font-size: 12px; }
.mono { font-family: var(--dm-font-mono, ui-monospace, 'JetBrains Mono', Consolas, monospace); }
.dm-card { border: 1px solid var(--dm-border); border-radius: 12px; }
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--dm-text);
  gap: 8px;
  span { display: inline-flex; align-items: center; gap: 6px; }
}
.muted { color: var(--dm-text-muted); font-size: 12px; font-weight: 400; }
.col-name { display: flex; flex-direction: column; gap: 2px; }
.col-name .name { font-weight: 600; color: var(--dm-text); }
.col-name .key { font-size: 12px; color: var(--dm-text-muted); }
.kb-pills { display: flex; flex-wrap: wrap; gap: 4px; }
.chunk-cell { display: inline-flex; align-items: center; gap: 4px; justify-content: flex-end; }
.warn-icon { color: var(--el-color-warning); }
.ops { display: inline-flex; gap: 8px; }
</style>
