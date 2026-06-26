/**
 * 知识库 (KB) Pinia store
 *
 * 设计要点：
 *   - 按 kb_type 分桶（'product' / 'enterprise'），两个组件共用一个 store
 *   - selectedId(byType) 记忆当前激活 KB
 *   - 文件列表带 polling：上传后定时 refresh，直到没有 pending/indexing
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  kbApi,
  type EmbedderInfo,
  type KBCreatePayload,
  type KBFile,
  type KBQueryHit,
  type KBQueryResponse,
  type KBType,
  type KnowledgeBase,
} from '@/api/kb'

interface BucketState {
  list: KnowledgeBase[]
  selectedId: number | null
  files: KBFile[]
  filesLoading: boolean
  pollingTimer: ReturnType<typeof setInterval> | null
}

function emptyBucket(): BucketState {
  return {
    list: [],
    selectedId: null,
    files: [],
    filesLoading: false,
    pollingTimer: null,
  }
}

export const useKBStore = defineStore('kb', () => {
  const buckets = ref<Record<KBType, BucketState>>({
    product: emptyBucket(),
    enterprise: emptyBucket(),
    experience: emptyBucket(),
  })
  const loading = ref(false)
  const embedder = ref<EmbedderInfo | null>(null)
  const lastQueryResult = ref<KBQueryResponse | null>(null)
  const querying = ref(false)

  const productList = computed(() => buckets.value.product.list)
  const enterpriseList = computed(() => buckets.value.enterprise.list)

  function bucket(type: KBType): BucketState {
    return buckets.value[type]
  }

  async function fetchKBs(type: KBType): Promise<KnowledgeBase[]> {
    loading.value = true
    try {
      const res = await kbApi.list(type)
      buckets.value[type].list = res.items
      // 若未选中或选中已被删，默认选第一个
      const b = buckets.value[type]
      if (!b.selectedId || !res.items.some((k) => k.id === b.selectedId)) {
        b.selectedId = res.items.length ? res.items[0].id : null
      }
      return res.items
    } finally {
      loading.value = false
    }
  }

  async function selectKB(type: KBType, kbId: number | null) {
    const b = bucket(type)
    b.selectedId = kbId
    stopPolling(type)
    if (kbId == null) {
      b.files = []
      return
    }
    await fetchFiles(type)
  }

  async function fetchFiles(type: KBType): Promise<KBFile[]> {
    const b = bucket(type)
    if (!b.selectedId) return []
    b.filesLoading = true
    try {
      const res = await kbApi.listFiles(b.selectedId)
      b.files = res.items
      // 索引中 → 持续 polling
      if (b.files.some((f) => f.status === 'pending' || f.status === 'indexing')) {
        startPolling(type)
      } else {
        stopPolling(type)
        // 索引结束后刷新 KB 列表，更新 file_count/chunk_count
        await fetchKBs(type)
      }
      return res.items
    } finally {
      b.filesLoading = false
    }
  }

  function startPolling(type: KBType, intervalMs = 2000) {
    const b = bucket(type)
    if (b.pollingTimer) return
    b.pollingTimer = setInterval(() => {
      fetchFiles(type).catch(() => undefined)
    }, intervalMs)
  }

  function stopPolling(type: KBType) {
    const b = bucket(type)
    if (b.pollingTimer) {
      clearInterval(b.pollingTimer)
      b.pollingTimer = null
    }
  }

  async function createKB(payload: KBCreatePayload): Promise<KnowledgeBase> {
    const kb = await kbApi.create(payload)
    await fetchKBs(payload.kb_type)
    buckets.value[payload.kb_type].selectedId = kb.id
    await fetchFiles(payload.kb_type)
    return kb
  }

  async function deleteKB(type: KBType, kbId: number): Promise<void> {
    await kbApi.remove(kbId)
    const b = bucket(type)
    if (b.selectedId === kbId) {
      stopPolling(type)
      b.selectedId = null
      b.files = []
    }
    await fetchKBs(type)
    if (b.list.length && b.selectedId == null) {
      await selectKB(type, b.list[0].id)
    }
  }

  async function uploadFiles(type: KBType, files: File[]) {
    const b = bucket(type)
    if (!b.selectedId) throw new Error('未选中知识库')
    const res = await kbApi.uploadFiles(b.selectedId, files)
    await fetchFiles(type)
    return res
  }

  async function removeFile(type: KBType, fileId: number): Promise<void> {
    const b = bucket(type)
    if (!b.selectedId) return
    await kbApi.removeFile(b.selectedId, fileId)
    await fetchFiles(type)
  }

  async function runQuery(type: KBType, text: string, top_k = 3): Promise<KBQueryHit[]> {
    const b = bucket(type)
    if (!b.selectedId) return []
    querying.value = true
    try {
      const res = await kbApi.query(b.selectedId, text, top_k)
      lastQueryResult.value = res
      embedder.value = res.embedder
      return res.hits
    } finally {
      querying.value = false
    }
  }

  async function fetchEmbedder(): Promise<EmbedderInfo> {
    const info = await kbApi.embedderInfo()
    embedder.value = info
    return info
  }

  return {
    buckets,
    loading,
    querying,
    embedder,
    lastQueryResult,
    productList,
    enterpriseList,
    bucket,
    fetchKBs,
    selectKB,
    fetchFiles,
    startPolling,
    stopPolling,
    createKB,
    deleteKB,
    uploadFiles,
    removeFile,
    runQuery,
    fetchEmbedder,
  }
})
