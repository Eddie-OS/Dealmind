/**
 * 知识库 (Knowledge Base) API
 *
 * 后端：src/api/routes_kb.py
 * 接口（7 业务 + 1 元数据）：
 *   GET    /api/kbs?kb_type=
 *   POST   /api/kbs
 *   DELETE /api/kbs/{id}
 *   GET    /api/kbs/{id}/files
 *   POST   /api/kbs/{id}/files
 *   DELETE /api/kbs/{id}/files/{fid}
 *   POST   /api/kbs/{id}/query
 *   GET    /api/kbs/meta/embedder
 */
import { http } from './http'

export type KBType = 'product' | 'enterprise' | 'experience'

export type KBFileStatus = 'pending' | 'indexing' | 'indexed' | 'failed'

export interface KnowledgeBase {
  id: number
  name: string
  kb_type: KBType
  description: string | null
  file_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface KBFile {
  id: number
  kb_id: number
  filename: string
  file_type: string | null
  file_size: number | null
  chunk_count: number
  status: KBFileStatus
  error_msg: string | null
  created_at: string
  updated_at: string
}

export interface KBQueryHit {
  id: string | null
  text: string
  metadata: {
    kb_id?: number
    kb_type?: string
    file_id?: number
    filename?: string
    section?: string
    chunk_idx?: number
    sheet?: string
    row?: number
    column_names?: string
    [extra: string]: unknown
  }
  distance: number | null
  score: number | null
}

export interface KBQueryResponse {
  kb_id: number
  kb_name: string
  kb_type: KBType
  query: string
  top_k: number
  hits: KBQueryHit[]
  embedder: EmbedderInfo
}

export interface EmbedderInfo {
  backend: string
  model: string
  dim: number | null
  hf_endpoint: string | null
  error: string | null
}

export interface KBListResponse {
  items: KnowledgeBase[]
  total: number
}

export interface KBFileListResponse {
  items: KBFile[]
  total: number
}

export interface KBCreatePayload {
  name: string
  kb_type: KBType
  description?: string | null
}

export interface KBUploadResponse {
  imported: number
  items: KBFile[]
}

export const SUPPORTED_FILE_TYPES = ['.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx'] as const

export const STATUS_TAG_TYPE: Record<KBFileStatus, 'info' | 'warning' | 'success' | 'danger'> = {
  pending: 'info',
  indexing: 'warning',
  indexed: 'success',
  failed: 'danger',
}

export const STATUS_LABEL: Record<KBFileStatus, string> = {
  pending: '待索引',
  indexing: '索引中',
  indexed: '已索引',
  failed: '失败',
}

export const kbApi = {
  list: (kb_type?: KBType) =>
    http.get<KBListResponse>('/api/kbs', { params: kb_type ? { kb_type } : undefined }).then((r) => r.data),

  create: (payload: KBCreatePayload) =>
    http.post<KnowledgeBase>('/api/kbs', payload).then((r) => r.data),

  remove: (id: number) =>
    http.delete<void>(`/api/kbs/${id}`).then(() => undefined),

  listFiles: (id: number) =>
    http.get<KBFileListResponse>(`/api/kbs/${id}/files`).then((r) => r.data),

  uploadFiles: (id: number, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return http
      .post<KBUploadResponse>(`/api/kbs/${id}/files`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  removeFile: (kbId: number, fileId: number) =>
    http.delete<void>(`/api/kbs/${kbId}/files/${fileId}`).then(() => undefined),

  query: (kbId: number, text: string, top_k = 3) =>
    http
      .post<KBQueryResponse>(`/api/kbs/${kbId}/query`, { text, top_k })
      .then((r) => r.data),

  embedderInfo: () =>
    http.get<EmbedderInfo>('/api/kbs/meta/embedder').then((r) => r.data),
}
