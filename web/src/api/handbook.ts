/**
 * Handbook Analysis · Handbook 管理 API
 *
 * 后端：src/api/routes_handbook.py
 * 接口（Sprint 1）：
 *   GET    /api/handbooks
 *   POST   /api/handbooks
 *   GET    /api/handbooks/{id}
 *   PUT    /api/handbooks/{id}
 *   DELETE /api/handbooks/{id}
 *   GET    /api/handbooks/{id}/files
 *   POST   /api/handbooks/{id}/files
 *   GET    /api/handbooks/{id}/files/{fid}?include_text=true
 *   DELETE /api/handbooks/{id}/files/{fid}
 *   POST   /api/handbooks/{id}/extract           （Sprint 2 真正落地，目前 501）
 *   GET    /api/handbooks/{id}/extract_status
 */
import { http } from './http'

export type HandbookStatus = 'draft' | 'extracting' | 'ready' | 'failed'
export type HandbookFileStatus = 'pending' | 'parsing' | 'parsed' | 'failed'
/** 结构类型：旧 1/3/3/5/9/10 或新「按人设 + 4 章流程」playbook */
export type HandbookDocType = 'handbook_135910' | 'playbook_v1'
export const HANDBOOK_DOC_TYPE_LABEL: Record<HandbookDocType, string> = {
  handbook_135910: '1/3/3/5/9/10（旧框架）',
  playbook_v1: 'Playbook（按人设 + 4 章流程）',
}

export interface HandbookIntro {
  id: string
  label: string
  text: string
  source?: string
}

export interface HandbookSellingPoint extends HandbookIntro {}
export interface HandbookCoreParam extends HandbookIntro {}
export interface HandbookDemoAction extends HandbookIntro {}

export interface HandbookCompetitor extends HandbookIntro {
  vs?: string
}

export interface HandbookFaq {
  id: string
  label: string
  q: string
  a: string
  source?: string
}

export interface HandbookStructure {
  product_name?: string
  intro_1?: HandbookIntro
  selling_points?: HandbookSellingPoint[]
  competitor_points?: HandbookCompetitor[]
  core_params?: HandbookCoreParam[]
  faq?: HandbookFaq[]
  demo_actions?: HandbookDemoAction[]
}

export interface HandbookStructureStats {
  intro_1: number
  selling_points: number
  competitor_points: number
  core_params: number
  faq: number
  demo_actions: number
}

export interface Handbook {
  id: number
  name: string
  product_kb_id: number | null
  description: string | null
  status: HandbookStatus
  version_no: number
  extraction_log: string | null
  source_files_json: unknown[]
  created_at: string
  updated_at: string
  structure?: HandbookStructure
  structure_stats?: HandbookStructureStats
}

export interface HandbookFile {
  id: number
  handbook_id: number
  filename: string
  file_type: string | null
  file_size: number | null
  status: HandbookFileStatus
  error_msg: string | null
  parsed_text_length: number
  parsed_text?: string
  created_at: string
  updated_at: string
}

export interface HandbookListResponse {
  items: Handbook[]
  total: number
}

export interface HandbookFileListResponse {
  items: HandbookFile[]
  total: number
}

export interface HandbookUploadResponse {
  imported: number
  items: HandbookFile[]
}

export interface HandbookCreatePayload {
  name: string
  product_kb_id?: number | null
  description?: string | null
}

export interface HandbookUpdatePayload {
  name?: string
  product_kb_id?: number | null
  description?: string | null
  structure?: HandbookStructure
  bump_version?: boolean
}

export const HANDBOOK_FILE_STATUS_LABEL: Record<HandbookFileStatus, string> = {
  pending: '待解析',
  parsing: '解析中',
  parsed: '已解析',
  failed: '失败',
}

export const HANDBOOK_FILE_STATUS_TYPE: Record<
  HandbookFileStatus,
  'info' | 'warning' | 'success' | 'danger'
> = {
  pending: 'info',
  parsing: 'warning',
  parsed: 'success',
  failed: 'danger',
}

export const HANDBOOK_STATUS_LABEL: Record<HandbookStatus, string> = {
  draft: '草稿',
  extracting: '抽取中',
  ready: '可用',
  failed: '失败',
}

export const HANDBOOK_STATUS_TYPE: Record<
  HandbookStatus,
  'info' | 'warning' | 'success' | 'danger'
> = {
  draft: 'info',
  extracting: 'warning',
  ready: 'success',
  failed: 'danger',
}

export const HANDBOOK_SUPPORTED_TYPES = [
  '.txt',
  '.md',
  '.pdf',
  '.docx',
  '.pptx',
  '.xlsx',
] as const

export const handbookApi = {
  list: () =>
    http
      .get<HandbookListResponse>('/api/handbooks')
      .then((r) => r.data),

  detail: (id: number) =>
    http.get<Handbook>(`/api/handbooks/${id}`).then((r) => r.data),

  create: (payload: HandbookCreatePayload) =>
    http
      .post<Handbook>('/api/handbooks', payload)
      .then((r) => r.data),

  update: (id: number, payload: HandbookUpdatePayload) =>
    http
      .put<Handbook>(`/api/handbooks/${id}`, payload)
      .then((r) => r.data),

  remove: (id: number) =>
    http
      .delete<void>(`/api/handbooks/${id}`)
      .then(() => undefined),

  listFiles: (id: number) =>
    http
      .get<HandbookFileListResponse>(`/api/handbooks/${id}/files`)
      .then((r) => r.data),

  getFile: (id: number, fileId: number, includeText = false) =>
    http
      .get<HandbookFile>(
        `/api/handbooks/${id}/files/${fileId}`,
        { params: { include_text: includeText } },
      )
      .then((r) => r.data),

  uploadFiles: (id: number, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return http
      .post<HandbookUploadResponse>(`/api/handbooks/${id}/files`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  removeFile: (id: number, fileId: number) =>
    http
      .delete<void>(`/api/handbooks/${id}/files/${fileId}`)
      .then(() => undefined),

  triggerExtract: (id: number, docType: HandbookDocType = 'handbook_135910') =>
    http
      .post<unknown>(
        `/api/handbooks/${id}/extract`,
        {},
        { silent: true, params: { doc_type: docType } },
      )
      .then((r) => r.data),

  extractStatus: (id: number) =>
    http
      .get<{
        handbook_id: number
        status: HandbookStatus
        version_no: number
        extraction_log: string | null
      }>(`/api/handbooks/${id}/extract_status`)
      .then((r) => r.data),
}
