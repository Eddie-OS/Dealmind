<script setup lang="ts">
/**
 * KBManager: 知识库管理公共组件
 *
 * 蓝图 §Stage 4：产品/企业 KB 共用同一组件，通过 props.type 区分。
 * 布局：
 *   左 8（KB 列表 + 新建按钮） + 右 16（文件管理 + 检索测试）
 * polling：上传后/有 pending/indexing 时 store 自动每 2s 拉一次
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElCol,
  ElDialog,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElPopconfirm,
  ElRow,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
  ElUpload,
  type FormInstance,
  type UploadInstance,
  type UploadRawFile,
} from 'element-plus'
import {
  Plus,
  Trash2,
  Search,
  Upload as UploadIcon,
  Database,
  FileText,
  RefreshCcw,
  Info,
} from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import { useKBStore } from '@/stores/kb'
import {
  STATUS_LABEL,
  STATUS_TAG_TYPE,
  SUPPORTED_FILE_TYPES,
  type KBFile,
  type KBQueryHit,
  type KBType,
  type KnowledgeBase,
} from '@/api/kb'

const props = withDefaults(
  defineProps<{
    type: KBType
    title: string
    subtitle?: string
  }>(),
  { subtitle: '' },
)

const store = useKBStore()

const bucket = computed(() => store.buckets[props.type])
const list = computed<KnowledgeBase[]>(() => bucket.value.list)
const files = computed<KBFile[]>(() => bucket.value.files)
const selectedId = computed(() => bucket.value.selectedId)
const selectedKB = computed(() =>
  list.value.find((k) => k.id === selectedId.value) || null,
)

// ===== 初始化 =====
onMounted(async () => {
  await store.fetchKBs(props.type)
  if (bucket.value.selectedId != null) {
    await store.selectKB(props.type, bucket.value.selectedId)
  }
  if (!store.embedder) {
    store.fetchEmbedder().catch(() => undefined)
  }
})
onUnmounted(() => store.stopPolling(props.type))

// ===== 选中 KB =====
async function handleSelect(kbId: number) {
  await store.selectKB(props.type, kbId)
}

async function refreshFiles() {
  await store.fetchFiles(props.type)
}

// ===== 新建 KB =====
const createDialogVisible = ref(false)
const createForm = reactive({ name: '', description: '' })
const createFormRef = ref<FormInstance>()
const createLoading = ref(false)
function openCreateDialog() {
  createForm.name = ''
  createForm.description = ''
  createDialogVisible.value = true
}
async function submitCreate() {
  await createFormRef.value?.validate()
  createLoading.value = true
  try {
    const kb = await store.createKB({
      name: createForm.name.trim(),
      kb_type: props.type,
      description: createForm.description.trim() || null,
    })
    ElMessage.success(`已创建知识库：${kb.name}`)
    createDialogVisible.value = false
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '创建失败'
    ElMessage.error(String(msg))
  } finally {
    createLoading.value = false
  }
}

// ===== 删 KB =====
async function handleDeleteKB(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `确定删除知识库「${kb.name}」？此操作将清空其全部文件和向量数据。`,
      '删除知识库',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await store.deleteKB(props.type, kb.id)
  ElMessage.success(`已删除：${kb.name}`)
}

// ===== 上传 =====
const uploadRef = ref<UploadInstance>()
const uploadAccept = SUPPORTED_FILE_TYPES.join(',')
const pendingFiles = ref<UploadRawFile[]>([])
const uploading = ref(false)

function handleFileChange(file: any, fileList: any[]) {
  pendingFiles.value = fileList.map((f) => f.raw).filter(Boolean) as UploadRawFile[]
}

async function submitUpload() {
  if (!selectedId.value) {
    ElMessage.warning('请先选择一个知识库')
    return
  }
  if (pendingFiles.value.length === 0) {
    ElMessage.warning('请先选择要上传的文件')
    return
  }
  uploading.value = true
  try {
    const res = await store.uploadFiles(props.type, pendingFiles.value as File[])
    ElMessage.success(`已上传 ${res.imported} 个文件，开始后台索引`)
    uploadRef.value?.clearFiles()
    pendingFiles.value = []
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '上传失败'
    ElMessage.error(String(msg))
  } finally {
    uploading.value = false
  }
}

// ===== 删文件 =====
async function handleDeleteFile(f: KBFile) {
  await store.removeFile(props.type, f.id)
  ElMessage.success(`已删除：${f.filename}`)
}

// ===== 检索测试 =====
const queryText = ref('')
const topK = ref(3)
const queryHits = ref<KBQueryHit[]>([])
const queryError = ref<string | null>(null)

async function runQuery() {
  if (!queryText.value.trim()) {
    ElMessage.warning('请输入检索文本')
    return
  }
  if (!selectedId.value) {
    ElMessage.warning('请先选择知识库')
    return
  }
  queryError.value = null
  try {
    queryHits.value = await store.runQuery(props.type, queryText.value.trim(), topK.value)
    if (!queryHits.value.length) {
      ElMessage.info('暂无命中结果')
    }
  } catch (e: any) {
    queryError.value = e?.message || '检索失败'
    ElMessage.error(queryError.value)
  }
}

// ===== utils =====
function fmtSize(bytes: number | null): string {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function fmtScore(s: number | null): string {
  if (s == null) return '-'
  return s.toFixed(3)
}
</script>

<template>
  <div class="kb-manager">
    <DmPageHeader :title="title" :subtitle="subtitle">
      <template #actions>
        <div v-if="store.embedder" class="embedder-info">
          <ElIcon><Info :size="14" /></ElIcon>
          <span>{{ store.embedder.backend }} · {{ store.embedder.model }} · {{ store.embedder.dim }}d</span>
        </div>
        <ElButton :icon="Plus" type="primary" @click="openCreateDialog">新建知识库</ElButton>
      </template>
    </DmPageHeader>

    <ElRow :gutter="20" class="main-grid">
      <!-- 左侧：KB 列表 -->
      <ElCol :span="8">
        <ElCard class="dm-card kb-list-card" shadow="never">
          <template #header>
            <div class="card-head">
              <span><Database :size="14" /> 知识库列表</span>
              <span class="muted">共 {{ list.length }} 个</span>
            </div>
          </template>
          <DmEmpty v-if="!list.length && !store.loading" title="还没有知识库" description="点击右上方「新建知识库」开始" />
          <ul v-else class="kb-list">
            <li
              v-for="kb in list"
              :key="kb.id"
              class="kb-row"
              :class="{ active: kb.id === selectedId }"
              @click="handleSelect(kb.id)"
            >
              <div class="kb-row-main">
                <div class="kb-row-name">{{ kb.name }}</div>
                <div v-if="kb.description" class="kb-row-desc">{{ kb.description }}</div>
                <div class="kb-row-meta">
                  <span>{{ kb.file_count }} 文件</span>
                  <span>·</span>
                  <span>{{ kb.chunk_count }} 切片</span>
                </div>
              </div>
              <ElPopconfirm
                title="确定删除这个知识库？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm.stop="handleDeleteKB(kb)"
              >
                <template #reference>
                  <ElButton
                    text
                    type="danger"
                    :icon="Trash2"
                    size="small"
                    class="row-del"
                    @click.stop
                  />
                </template>
              </ElPopconfirm>
            </li>
          </ul>
        </ElCard>
      </ElCol>

      <!-- 右侧：文件表 + 检索测试 -->
      <ElCol :span="16">
        <ElCard class="dm-card files-card" shadow="never">
          <template #header>
            <div class="card-head">
              <span>
                <FileText :size="14" />
                <template v-if="selectedKB"> {{ selectedKB.name }} · 文件 </template>
                <template v-else> 文件管理 </template>
              </span>
              <ElButton text :icon="RefreshCcw" size="small" @click="refreshFiles">
                刷新
              </ElButton>
            </div>
          </template>

          <DmEmpty
            v-if="!selectedKB"
            title="请选择左侧一个知识库"
            description="选中后可上传文件 / 查看索引状态 / 检索测试"
          />

          <div v-else>
            <!-- 上传区 -->
            <div class="upload-zone">
              <ElUpload
                ref="uploadRef"
                drag
                multiple
                :auto-upload="false"
                :accept="uploadAccept"
                :on-change="handleFileChange"
                :show-file-list="true"
              >
                <ElIcon class="upload-icon" :size="32"><UploadIcon /></ElIcon>
                <div class="upload-text">拖拽文件到此处，或<em>点击选择</em></div>
                <template #tip>
                  <div class="upload-tip">支持 {{ SUPPORTED_FILE_TYPES.join(' / ') }}，单文件 ≤ 50 MB</div>
                </template>
              </ElUpload>
              <div class="upload-actions">
                <ElButton
                  type="primary"
                  :loading="uploading"
                  :disabled="!pendingFiles.length"
                  @click="submitUpload"
                >
                  开始上传 {{ pendingFiles.length ? `(${pendingFiles.length})` : '' }}
                </ElButton>
              </div>
            </div>

            <!-- 文件列表 -->
            <ElTable
              :data="files"
              size="default"
              empty-text="该知识库还没有文件"
              :loading="bucket.filesLoading"
              class="files-table"
              row-key="id"
            >
              <ElTableColumn prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
              <ElTableColumn prop="file_type" label="类型" width="80">
                <template #default="{ row }">
                  <ElTag size="small" type="info" effect="plain">.{{ row.file_type }}</ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="大小" width="110">
                <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="chunk_count" label="切片" width="80" />
              <ElTableColumn label="状态" width="120">
                <template #default="{ row }">
                  <ElTooltip
                    v-if="row.status === 'failed' && row.error_msg"
                    :content="row.error_msg"
                    placement="top"
                  >
                    <ElTag :type="STATUS_TAG_TYPE[row.status]" size="small">
                      {{ STATUS_LABEL[row.status] }}
                    </ElTag>
                  </ElTooltip>
                  <ElTag v-else :type="STATUS_TAG_TYPE[row.status]" size="small">
                    {{ STATUS_LABEL[row.status] }}
                  </ElTag>
                </template>
              </ElTableColumn>
              <ElTableColumn label="操作" width="80" align="center">
                <template #default="{ row }">
                  <ElPopconfirm
                    title="删除此文件及对应向量？"
                    confirm-button-text="删除"
                    cancel-button-text="取消"
                    @confirm="handleDeleteFile(row)"
                  >
                    <template #reference>
                      <ElButton text type="danger" :icon="Trash2" size="small" />
                    </template>
                  </ElPopconfirm>
                </template>
              </ElTableColumn>
            </ElTable>

            <!-- 检索测试 -->
            <div class="query-zone">
              <div class="query-zone-head">
                <Search :size="14" />
                <span>检索测试</span>
                <span class="muted">仅查询本知识库</span>
              </div>
              <div class="query-input">
                <ElInput
                  v-model="queryText"
                  placeholder="输入想要检索的问题或关键词，如：华为 MatePad 12X 价格 / 如何开场白吸引顾客"
                  clearable
                  @keyup.enter="runQuery"
                />
                <ElInput
                  v-model.number="topK"
                  type="number"
                  :min="1"
                  :max="20"
                  class="topk-input"
                />
                <ElButton type="primary" :icon="Search" :loading="store.querying" @click="runQuery">
                  检索
                </ElButton>
              </div>
              <div v-if="queryHits.length" class="query-results">
                <div v-for="(hit, i) in queryHits" :key="hit.id || i" class="hit-card">
                  <div class="hit-meta">
                    <span class="hit-rank">#{{ i + 1 }}</span>
                    <span class="hit-score">score {{ fmtScore(hit.score) }}</span>
                    <span class="hit-file">{{ hit.metadata.filename }}</span>
                    <span class="hit-section">· {{ hit.metadata.section || '-' }}</span>
                  </div>
                  <div class="hit-text">{{ hit.text }}</div>
                </div>
              </div>
              <div v-else-if="queryText && !store.querying" class="query-empty muted">
                按回车 / 点检索查看结果
              </div>
            </div>
          </div>
        </ElCard>
      </ElCol>
    </ElRow>

    <!-- 新建 KB Dialog -->
    <ElDialog
      v-model="createDialogVisible"
      title="新建知识库"
      width="520px"
      :close-on-click-modal="false"
    >
      <ElForm ref="createFormRef" :model="createForm" label-width="80px" :rules="{
        name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
      }">
        <ElFormItem label="名称" prop="name">
          <ElInput v-model="createForm.name" placeholder="如：iPhone 16 Pro / 谈判心法" />
        </ElFormItem>
        <ElFormItem label="描述">
          <ElInput
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选，简短说明这个 KB 的用途"
          />
        </ElFormItem>
        <ElFormItem label="类型">
          <ElTag>{{ props.type === 'product' ? '产品知识库' : '企业知识库' }}</ElTag>
          <span class="muted" style="margin-left: 8px">由当前页面决定</span>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="createDialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="createLoading" @click="submitCreate">创建</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped lang="scss">
.kb-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.embedder-info {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--dm-border);
  border-radius: 999px;
  background: var(--dm-surface);
  font-size: 12px;
  color: var(--dm-text-muted);
}
.main-grid {
  width: 100%;
}
.dm-card {
  border: 1px solid var(--dm-border);
  border-radius: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--dm-text);
  gap: 8px;
  span {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
}
.muted {
  color: var(--dm-text-muted);
  font-size: 12px;
  font-weight: 400;
}
.kb-list-card {
  height: 100%;
}
.kb-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.kb-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  border: 1px solid transparent;
  margin-bottom: 6px;
  &:hover { background: var(--dm-surface-2, #f7f7f7); }
  &.active {
    background: var(--dm-surface-2, #f4f6fb);
    border-color: var(--dm-primary, #2563eb);
  }
}
.kb-row-main { flex: 1; min-width: 0; }
.kb-row-name {
  font-weight: 600;
  color: var(--dm-text);
  font-size: 14px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-row-desc {
  margin-top: 4px;
  color: var(--dm-text-muted);
  font-size: 12px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.kb-row-meta {
  margin-top: 6px;
  display: inline-flex;
  gap: 6px;
  color: var(--dm-text-muted);
  font-size: 12px;
}
.row-del { opacity: 0.6; }
.row-del:hover { opacity: 1; }

.files-card { height: 100%; }
.upload-zone {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.upload-icon { color: var(--dm-text-muted); }
.upload-text { font-size: 14px; color: var(--dm-text); em { color: var(--dm-primary, #2563eb); font-style: normal; } }
.upload-tip { font-size: 12px; color: var(--dm-text-muted); margin-top: 4px; }
.upload-actions { display: flex; justify-content: flex-end; }
.files-table { margin-top: 8px; }

.query-zone {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--dm-border);
}
.query-zone-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--dm-text);
}
.query-input {
  display: flex;
  gap: 8px;
  align-items: center;
  .topk-input { width: 84px; }
}
.query-results {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hit-card {
  padding: 12px 14px;
  border: 1px solid var(--dm-border);
  border-radius: 8px;
  background: var(--dm-surface);
}
.hit-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--dm-text-muted);
  margin-bottom: 6px;
  .hit-rank { color: var(--dm-primary, #2563eb); font-weight: 600; }
  .hit-score { color: #16a34a; font-variant-numeric: tabular-nums; }
  .hit-file { color: var(--dm-text); font-weight: 500; }
  .hit-section {}
}
.hit-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--dm-text);
  word-break: break-word;
  white-space: pre-wrap;
  max-height: 7em;
  overflow: auto;
}
.query-empty { padding: 12px 0; }
</style>
