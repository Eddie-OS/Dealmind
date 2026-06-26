/**
 * 向量库管理 API（蓝图 §Stage 5）
 *
 * 后端：src/api/routes_vector_admin.py
 *   GET    /api/vector/collections
 *   POST   /api/vector/collections/{name}/rebuild
 *   POST   /api/vector/collections/{name}/clear
 *   GET    /api/vector/embedder
 */
import { http } from './http'
import type { EmbedderInfo, KBType } from './kb'

export interface CollectionKBSummary {
  id: number
  name: string
  file_count: number
  chunk_count: number
}

export interface CollectionInfo {
  name: string
  kb_type: KBType | null
  exists: boolean
  chunk_count: number
  db_chunk_count: number
  kb_file_count: number
  kb_count: number
  kbs: CollectionKBSummary[]
  estimated_vector_bytes: number
}

export interface CollectionListResponse {
  items: CollectionInfo[]
  total: number
  chroma_dir: string
  chroma_dir_bytes: number
  embedder: EmbedderInfo
}

export interface CollectionActionResponse {
  collection: string
  kb_type: KBType
  affected_kbs: number
  affected_files: number
  indexer_started?: boolean
  message: string
}

export const vectorApi = {
  listCollections: () =>
    http.get<CollectionListResponse>('/api/vector/collections').then((r) => r.data),

  rebuild: (name: string) =>
    http
      .post<CollectionActionResponse>(`/api/vector/collections/${name}/rebuild`)
      .then((r) => r.data),

  clear: (name: string) =>
    http
      .post<CollectionActionResponse>(`/api/vector/collections/${name}/clear`)
      .then((r) => r.data),

  embedder: () => http.get<EmbedderInfo>('/api/vector/embedder').then((r) => r.data),
}

// ===== 工具：友好格式 =====

export function fmtBytes(n: number | null | undefined): string {
  if (n == null || n < 0) return '-'
  if (n === 0) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export const COLLECTION_LABEL: Record<string, string> = {
  product_knowledge: '产品知识库',
  enterprise_knowledge: '企业知识库',
  experience_knowledge: '案例 / 经验库',
}
