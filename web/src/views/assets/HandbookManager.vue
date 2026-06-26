<script setup lang="ts">
/**
 * 产品手册（Handbook Analysis）· 知识资产管理
 *
 * 业务定位：销冠对话最终要按 1/3/3/5/9/10 框架做归因分析，
 * 这里是上传产品 PPT/PDF/Word，解析为结构化文本的入口。
 * 挂在「知识与资产」组下，紧邻「产品知识库」——Handbook 是产品 KB
 * 之上的结构化话术骨架；分析报告位于「规模化测试」组下。
 *
 * Sprint 1 范围：上传 + 解析 + 结构预览（结构编辑器 / LLM 抽取在 Sprint 2 接入）
 */
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElTabPane,
  ElTabs,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTooltip,
  ElUpload,
  type FormInstance,
  type UploadFile,
  type UploadInstance,
  type UploadRawFile,
} from 'element-plus'
import {
  BookText,
  ChevronDown,
  ClipboardCheck,
  FileText,
  Plus,
  RefreshCcw,
  Save,
  Sparkles,
  Trash2,
  UploadCloud,
} from '@lucide/vue'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'
import {
  HANDBOOK_DOC_TYPE_LABEL,
  HANDBOOK_FILE_STATUS_LABEL,
  HANDBOOK_FILE_STATUS_TYPE,
  HANDBOOK_STATUS_LABEL,
  HANDBOOK_STATUS_TYPE,
  HANDBOOK_SUPPORTED_TYPES,
  handbookApi,
  type Handbook,
  type HandbookDocType,
  type HandbookFile,
} from '@/api/handbook'

// ============================================================
// State
// ============================================================
const handbooks = ref<Handbook[]>([])
const loadingList = ref(false)
const selectedId = ref<number | null>(null)

const detail = ref<Handbook | null>(null)
const files = ref<HandbookFile[]>([])
const loadingDetail = ref(false)
const loadingFiles = ref(false)

const selected = computed(() =>
  handbooks.value.find((h) => h.id === selectedId.value) || null,
)

const stats = computed(() => detail.value?.structure_stats || {
  intro_1: 0,
  selling_points: 0,
  competitor_points: 0,
  core_params: 0,
  faq: 0,
  demo_actions: 0,
})

/** playbook_v1 结构（按人设 + 4 章流程，变长）—— 结构内部带 doc_type 标记 */
const isPlaybook = computed(
  () => (detail.value?.structure as Record<string, unknown> | undefined)?.doc_type === 'playbook_v1',
)

const expectedTotals = { intro_1: 1, selling_points: 3, competitor_points: 3, core_params: 5, faq: 9, demo_actions: 10 }

const structureRows = computed(() => {
  if (isPlaybook.value) {
    // 变长结构：expect 取实际条数，不显示「缺 X 条」
    const s = (detail.value?.structure || {}) as any
    const openers = (s.open?.persona_openers || []).length
    const say = (s.say || []).length
    const compete = (s.compete || []).length
    const respond = (s.respond || []).length
    return [
      { key: 'open', label: '① 开场（按人设）', got: openers, expect: openers },
      { key: 'say', label: '② 核心卖点（按人设）', got: say, expect: say },
      { key: 'compete', label: '③ 竞品应对', got: compete, expect: compete },
      { key: 'respond', label: '④ 常见问答', got: respond, expect: respond },
    ]
  }
  return [
    { key: 'intro_1', label: '① 一句话定位', got: stats.value.intro_1, expect: 1 },
    { key: 'selling_points', label: '③ 核心卖点', got: stats.value.selling_points, expect: 3 },
    { key: 'competitor_points', label: '③ 竞品分析', got: stats.value.competitor_points, expect: 3 },
    { key: 'core_params', label: '⑤ 核心参数', got: stats.value.core_params, expect: 5 },
    { key: 'faq', label: '⑨ FAQ', got: stats.value.faq, expect: 9 },
    { key: 'demo_actions', label: '⑩ 演示动作', got: stats.value.demo_actions, expect: 10 },
  ]
})

const totalGot = computed(() =>
  structureRows.value.reduce((s, r) => s + (r.got || 0), 0),
)
const totalExpect = computed(() =>
  isPlaybook.value
    ? structureRows.value.reduce((s, r) => s + (r.expect || 0), 0)
    : Object.values(expectedTotals).reduce((s, n) => s + n, 0),
)

// ============================================================
// Load
// ============================================================
async function loadList() {
  loadingList.value = true
  try {
    const r = await handbookApi.list()
    handbooks.value = r.items
    if (handbooks.value.length > 0 && selectedId.value == null) {
      await select(handbooks.value[0].id)
    } else if (selectedId.value != null) {
      const stillExists = handbooks.value.some((h) => h.id === selectedId.value)
      if (!stillExists && handbooks.value.length > 0) {
        await select(handbooks.value[0].id)
      } else if (!stillExists) {
        selectedId.value = null
        detail.value = null
        files.value = []
      }
    }
  } finally {
    loadingList.value = false
  }
}

async function select(id: number) {
  selectedId.value = id
  await Promise.all([loadDetail(), loadFiles()])
}

async function loadDetail() {
  if (selectedId.value == null) return
  loadingDetail.value = true
  try {
    detail.value = await handbookApi.detail(selectedId.value)
  } finally {
    loadingDetail.value = false
  }
}

async function loadFiles() {
  if (selectedId.value == null) return
  loadingFiles.value = true
  try {
    const r = await handbookApi.listFiles(selectedId.value)
    files.value = r.items
  } finally {
    loadingFiles.value = false
  }
}

onMounted(loadList)

// ============================================================
// Create dialog · "上传即建" 一步到位
// ============================================================
const createVisible = ref(false)
const createLoading = ref(false)
const createForm = reactive({
  name: '',
  description: '',
  file: null as File | null,
})
const createFormRef = ref<FormInstance>()

function openCreate() {
  createForm.name = ''
  createForm.description = ''
  createForm.file = null
  createVisible.value = true
}

/** 拖拽 / 选择文件时触发：自动用文件名作为 Handbook 名称的初值。
 *
 * 注意：ElUpload 在 auto-upload=false 时 **不会** 触发 before-upload，
 * 必须用 on-change 钩子来捕获选中的文件（参数是 UploadFile，真实 File 在 .raw）。 */
function onCreatePickFile(uploadFile: UploadFile): void {
  const raw = uploadFile.raw
  if (!raw) return
  const ok = HANDBOOK_SUPPORTED_TYPES.some((s) =>
    raw.name.toLowerCase().endsWith(s),
  )
  if (!ok) {
    ElMessage.error(
      `不支持的格式：${raw.name}。支持：${HANDBOOK_SUPPORTED_TYPES.join(', ')}`,
    )
    return
  }
  if (raw.size > 50 * 1024 * 1024) {
    ElMessage.error('单文件不能超过 50MB')
    return
  }
  createForm.file = raw
  if (!createForm.name.trim()) {
    // 用去后缀的文件名作为默认 Handbook 名（用户可改）
    createForm.name = raw.name.replace(/\.[^.]+$/, '').slice(0, 100)
  }
}

function removeCreateFile() {
  createForm.file = null
}

async function submitCreate() {
  try {
    await createFormRef.value?.validate()
  } catch {
    // 校验失败（validate 会 reject）——表单项已高亮，无需额外提示
    return
  }
  if (!createForm.file) {
    ElMessage.warning('请先选择一个文件')
    return
  }
  createLoading.value = true
  let createdId: number | null = null
  try {
    // ── Step 1 · 建 Handbook 壳 ──
    const hb = await handbookApi.create({
      name: createForm.name.trim(),
      description: createForm.description.trim() || null,
    })
    createdId = hb.id

    // ── Step 2 · 立即上传文件 + 同步解析 ──
    const up = await handbookApi.uploadFiles(hb.id, [createForm.file])
    const failed = up.items.filter((f) => f.status === 'failed')

    if (failed.length > 0) {
      ElMessage.warning(
        `Handbook 已建，但文件解析失败：${failed[0].error_msg || '未知错误'}`,
      )
    } else {
      const chars = up.items[0]?.parsed_text_length ?? 0
      ElMessage.success(
        `已创建并解析：${hb.name}（${chars} 字）`,
      )
    }

    createVisible.value = false
    await loadList()
    await select(hb.id)
  } catch (e: any) {
    console.error('[HandbookManager] create+upload failed:', e)
    const detail = e?.response?.data?.detail
    let msg = '创建/上传失败'
    if (typeof detail === 'string') msg = detail
    else if (detail) msg = JSON.stringify(detail)
    else if (e?.message) msg = e.message

    // 若已建出 Handbook 但上传失败，提示用户进入详情手动重试
    if (createdId != null) {
      ElMessage.warning(`已创建 Handbook 但上传失败：${msg}（请选中后重试上传）`)
      createVisible.value = false
      await loadList()
      await select(createdId)
    } else {
      ElMessage.error({ message: msg, duration: 6000, showClose: true })
    }
  } finally {
    createLoading.value = false
  }
}

// ============================================================
// Delete handbook
// ============================================================
async function confirmDeleteHandbook(hb: Handbook) {
  await ElMessageBox.confirm(
    `删除 Handbook「${hb.name}」会同时清除所有来源文件、结构数据与历史分析结果，确定继续？`,
    '删除 Handbook',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  try {
    await handbookApi.remove(hb.id)
    ElMessage.success('已删除')
    selectedId.value = null
    detail.value = null
    files.value = []
    await loadList()
  } catch (e: any) {
    ElMessage.error(String(e?.message || '删除失败'))
  }
}

// ============================================================
// Upload
// ============================================================
const uploadRef = ref<UploadInstance>()
const uploading = ref(false)

function validateFile(rawFile: UploadRawFile): boolean {
  const name = rawFile.name.toLowerCase()
  const ok = HANDBOOK_SUPPORTED_TYPES.some((s) => name.endsWith(s))
  if (!ok) {
    ElMessage.error(
      `不支持的格式 ${name}。支持：${HANDBOOK_SUPPORTED_TYPES.join(', ')}`,
    )
    return false
  }
  if (rawFile.size > 50 * 1024 * 1024) {
    ElMessage.error('单文件不能超过 50MB')
    return false
  }
  return true
}

async function customUpload(opts: { file: File }) {
  if (selectedId.value == null) {
    ElMessage.warning('请先在左侧选择一个 Handbook（或点击「新建」创建一个）')
    return
  }
  uploading.value = true
  try {
    const r = await handbookApi.uploadFiles(selectedId.value, [opts.file])
    if (r.imported > 0) {
      const failed = r.items.filter((f) => f.status === 'failed')
      if (failed.length === 0) {
        ElMessage.success(
          `已上传并解析：${opts.file.name}（${r.items[0].parsed_text_length} 字）`,
        )
      } else {
        ElMessage.warning(
          `上传完成，但 ${failed.length} 个文件解析失败：${failed[0].error_msg || ''}`,
        )
      }
    }
    await loadFiles()
  } catch (e: any) {
    // 把后端 detail / 服务器异常 / 网络异常等都显式打到控制台与 toast，
    // 便于排查 "上传无响应" 类问题
    console.error('[HandbookManager] upload failed:', e)
    const detail = e?.response?.data?.detail
    let msg = '上传失败'
    if (typeof detail === 'string') msg = detail
    else if (detail && typeof detail === 'object') msg = JSON.stringify(detail)
    else if (e?.message) msg = e.message
    ElMessage.error({
      message: `上传失败：${msg}`,
      duration: 6000,
      showClose: true,
    })
  } finally {
    uploading.value = false
    uploadRef.value?.clearFiles()
  }
}

async function removeFile(file: HandbookFile) {
  await ElMessageBox.confirm(
    `删除文件「${file.filename}」？`,
    '确认删除',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await handbookApi.removeFile(file.handbook_id, file.id)
  ElMessage.success('已删除')
  await loadFiles()
}

// ============================================================
// Extract（B2 已上线 — 触发 + 轮询 extract_status）
// ============================================================
const extracting = ref(false)
let extractPollTimer: number | null = null

function stopExtractPoll() {
  if (extractPollTimer != null) {
    window.clearInterval(extractPollTimer)
    extractPollTimer = null
  }
}

function onExtractCommand(cmd: HandbookDocType) {
  void triggerExtract(cmd)
}

async function triggerExtract(docType: HandbookDocType = 'handbook_135910') {
  if (selectedId.value == null) return
  const docLabel = HANDBOOK_DOC_TYPE_LABEL[docType]
  // 二次确认
  try {
    await ElMessageBox.confirm(
      `将调用 LLM 从已解析文件抽取「${docLabel}」结构（约 30s ~ 1 分钟）。覆盖式更新当前结构并 +1 版本号。`,
      '抽取产品手册结构',
      { type: 'info', confirmButtonText: '开始抽取', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  extracting.value = true
  try {
    await handbookApi.triggerExtract(selectedId.value, docType)
    ElMessage.success('已触发抽取，后台运行中…')
    await loadDetail()
    pollExtractStatus(selectedId.value)
  } catch (e: any) {
    const status = e?.response?.status
    const detailObj = e?.response?.data?.detail
    const msg =
      typeof detailObj === 'string'
        ? detailObj
        : detailObj?.message || e?.message || '抽取失败'
    if (status === 409) {
      ElMessage.warning(String(msg))
      pollExtractStatus(selectedId.value)
    } else {
      ElMessage.error(String(msg))
      extracting.value = false
    }
  }
}

function pollExtractStatus(handbookId: number) {
  stopExtractPoll()
  extractPollTimer = window.setInterval(async () => {
    if (selectedId.value !== handbookId) {
      stopExtractPoll()
      extracting.value = false
      return
    }
    try {
      const st = await handbookApi.extractStatus(handbookId)
      if (st.status === 'ready') {
        stopExtractPoll()
        extracting.value = false
        ElMessage.success(`抽取完成（已更新到 v${st.version_no}）`)
        await loadDetail()
      } else if (st.status === 'failed') {
        stopExtractPoll()
        extracting.value = false
        ElMessage.error(
          `抽取失败：${(st.extraction_log || '').split('\n').pop() || '未知原因'}`,
        )
        await loadDetail()
      }
    } catch (e: any) {
      console.warn('poll extract failed', e)
    }
  }, 2000)
}

// ============================================================
// 结构校对抽屉（B3）—— 预览 / 编辑 / 保存
// ============================================================
const reviewOpen = ref(false)
const reviewTab = ref<string>('intro')
const reviewSaving = ref(false)

// playbook_v1 校对草稿（变长，可增删）
interface PbOpener { persona: string; persona_label: string; text: string }
interface PbPoint { label: string; text: string; demo: string }
interface PbSayBlock { persona: string; persona_label: string; points: PbPoint[] }
interface PbPair { customer: string; response: string }
interface PbCompete { vs: string; note: string; pairs: PbPair[] }
interface PbFaq { q: string; a: string; demo: string }
const playbookDraft = ref<{
  open: { opener: string; timing_cue: string; persona_openers: PbOpener[] }
  say: PbSayBlock[]
  compete: PbCompete[]
  respond: PbFaq[]
} | null>(null)

// —— 变长增删 helpers ——
function pbAddOpener() {
  playbookDraft.value?.open.persona_openers.push({ persona: '', persona_label: '', text: '' })
}
function pbRemoveOpener(i: number) {
  playbookDraft.value?.open.persona_openers.splice(i, 1)
}
function pbAddSayBlock() {
  playbookDraft.value?.say.push({ persona: '', persona_label: '', points: [{ label: '', text: '', demo: '' }] })
}
function pbRemoveSayBlock(i: number) {
  playbookDraft.value?.say.splice(i, 1)
}
function pbAddPoint(blk: PbSayBlock) {
  blk.points.push({ label: '', text: '', demo: '' })
}
function pbRemovePoint(blk: PbSayBlock, i: number) {
  blk.points.splice(i, 1)
}
function pbAddCompete() {
  playbookDraft.value?.compete.push({ vs: '', note: '', pairs: [{ customer: '', response: '' }] })
}
function pbRemoveCompete(i: number) {
  playbookDraft.value?.compete.splice(i, 1)
}
function pbAddPair(c: PbCompete) {
  c.pairs.push({ customer: '', response: '' })
}
function pbRemovePair(c: PbCompete, i: number) {
  c.pairs.splice(i, 1)
}
function pbAddFaq() {
  playbookDraft.value?.respond.push({ q: '', a: '', demo: '' })
}
function pbRemoveFaq(i: number) {
  playbookDraft.value?.respond.splice(i, 1)
}
const reviewDraft = ref<{
  intro_1: { id: string; label: string; text: string }
  selling_points: Array<{ id: string; label: string; text: string }>
  competitor_points: Array<{ id: string; label: string; vs: string; text: string }>
  core_params: Array<{ id: string; label: string; text: string }>
  faq: Array<{ id: string; label: string; q: string; a: string }>
  demo_actions: Array<{ id: string; label: string; text: string }>
} | null>(null)

function openReviewDrawer() {
  if (!detail.value) return
  const s = detail.value.structure || {}

  // playbook_v1：变长结构，单独构造草稿
  if (isPlaybook.value) {
    const sp = s as any
    playbookDraft.value = {
      open: {
        opener: sp.open?.opener || '',
        timing_cue: sp.open?.timing_cue || '',
        persona_openers: (sp.open?.persona_openers || []).map((po: any) => ({
          persona: po.persona || '', persona_label: po.persona_label || '', text: po.text || '',
        })),
      },
      say: (sp.say || []).map((b: any) => ({
        persona: b.persona || '', persona_label: b.persona_label || '',
        points: (b.points || []).map((p: any) => ({
          label: p.label || '', text: p.text || '', demo: p.demo || '',
        })),
      })),
      compete: (sp.compete || []).map((c: any) => ({
        vs: c.vs || '', note: c.note || '',
        pairs: (c.pairs || []).map((pr: any) => ({
          customer: pr.customer || '', response: pr.response || '',
        })),
      })),
      respond: (sp.respond || []).map((r: any) => ({
        q: r.q || '', a: r.a || '', demo: r.demo || '',
      })),
    }
    reviewDraft.value = null
    reviewTab.value = 'pb_open'
    reviewOpen.value = true
    return
  }
  playbookDraft.value = null

  const fill = <T,>(arr: T[] | undefined, expect: number, factory: (i: number) => T): T[] => {
    const r = (arr || []).slice(0, expect)
    while (r.length < expect) r.push(factory(r.length + 1))
    return r
  }
  reviewDraft.value = {
    intro_1: {
      id: 'intro_1',
      label: (s.intro_1?.label || '一句话定位') as string,
      text: (s.intro_1?.text || '') as string,
    },
    selling_points: fill(
      (s.selling_points || []) as Array<{ id?: string; label?: string; text?: string }>,
      3,
      (i) => ({ id: `sell_${i}`, label: '', text: '' }),
    ).map((it: any, i) => ({
      id: it.id || `sell_${i + 1}`,
      label: it.label || '',
      text: it.text || '',
    })),
    competitor_points: fill(
      (s.competitor_points || []) as Array<{ id?: string; label?: string; vs?: string; text?: string }>,
      3,
      (i) => ({ id: `comp_${i}`, label: '', vs: '', text: '' }),
    ).map((it: any, i) => ({
      id: it.id || `comp_${i + 1}`,
      label: it.label || '',
      vs: it.vs || '',
      text: it.text || '',
    })),
    core_params: fill(
      (s.core_params || []) as Array<{ id?: string; label?: string; text?: string }>,
      5,
      (i) => ({ id: `param_${i}`, label: '', text: '' }),
    ).map((it: any, i) => ({
      id: it.id || `param_${i + 1}`,
      label: it.label || '',
      text: it.text || '',
    })),
    faq: fill(
      (s.faq || []) as Array<{ id?: string; label?: string; q?: string; a?: string }>,
      9,
      (i) => ({ id: `faq_${i}`, label: '', q: '', a: '' }),
    ).map((it: any, i) => ({
      id: it.id || `faq_${i + 1}`,
      label: it.label || '',
      q: it.q || '',
      a: it.a || '',
    })),
    demo_actions: fill(
      (s.demo_actions || []) as Array<{ id?: string; label?: string; text?: string }>,
      10,
      (i) => ({ id: `demo_${i}`, label: '', text: '' }),
    ).map((it: any, i) => ({
      id: it.id || `demo_${i + 1}`,
      label: it.label || '',
      text: it.text || '',
    })),
  }
  reviewTab.value = 'intro'
  reviewOpen.value = true
}

async function saveReview(opts: { bump: boolean }) {
  if (selectedId.value == null) return

  // playbook_v1：把变长草稿序列化回结构（保留 doc_type，重算 id）
  if (isPlaybook.value && playbookDraft.value) {
    const d = playbookDraft.value
    const struct = {
      doc_type: 'playbook_v1',
      open: {
        opener: d.open.opener,
        timing_cue: d.open.timing_cue,
        persona_openers: d.open.persona_openers
          .filter((po) => po.text.trim() || po.persona.trim())
          .map((po) => ({ persona: po.persona, persona_label: po.persona_label, text: po.text })),
      },
      say: d.say
        .filter((b) => b.persona.trim() || b.points.some((p) => p.text.trim()))
        .map((b) => ({
          persona: b.persona,
          persona_label: b.persona_label,
          points: b.points
            .filter((p) => p.text.trim() || p.label.trim())
            .map((p, pi) => ({
              id: `say_${b.persona || 'X'}_${pi + 1}`,
              label: p.label, text: p.text, demo: p.demo,
            })),
        })),
      compete: d.compete
        .filter((c) => c.vs.trim() || c.pairs.some((pr) => pr.response.trim()))
        .map((c, ci) => ({
          id: `comp_${ci + 1}`,
          vs: c.vs, note: c.note,
          pairs: c.pairs
            .filter((pr) => pr.customer.trim() || pr.response.trim())
            .map((pr) => ({ customer: pr.customer, response: pr.response })),
        })),
      respond: d.respond
        .filter((r) => r.q.trim() || r.a.trim())
        .map((r, ri) => ({ id: `faq_${ri + 1}`, q: r.q, a: r.a, demo: r.demo })),
    }
    reviewSaving.value = true
    try {
      await handbookApi.update(selectedId.value, { structure: struct as any, bump_version: opts.bump })
      ElMessage.success(opts.bump ? '已保存并发布新版本' : '草稿已保存')
      reviewOpen.value = false
      await loadDetail()
      await loadList()
    } catch (e: any) {
      ElMessage.error(`保存失败：${e?.response?.data?.detail || e?.message || e}`)
    } finally {
      reviewSaving.value = false
    }
    return
  }

  if (!reviewDraft.value) return
  reviewSaving.value = true
  try {
    await handbookApi.update(selectedId.value, {
      structure: reviewDraft.value as any,
      bump_version: opts.bump,
    })
    ElMessage.success(opts.bump ? `已保存并发布新版本` : `草稿已保存`)
    reviewOpen.value = false
    await loadDetail()
    await loadList()
  } catch (e: any) {
    ElMessage.error(
      `保存失败：${e?.response?.data?.detail || e?.message || e}`,
    )
  } finally {
    reviewSaving.value = false
  }
}

// ============================================================
// Helpers
// ============================================================
function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(s: string | null | undefined): string {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 19)
}
</script>

<template>
  <div class="handbook-manager">
    <DmPageHeader
      title="产品手册（Handbook）"
      subtitle="结构化组织产品话术（1/3/3/5/9/10 或按人设+4章流程的 Playbook）。上传 PPT/PDF/Word 后，可在分析报告里对销冠对话做归因分析。"
    >
      <template #actions>
        <ElButton :icon="RefreshCcw" plain @click="loadList">刷新</ElButton>
        <ElButton type="primary" :icon="UploadCloud" @click="openCreate">
          上传 Handbook
        </ElButton>
      </template>
    </DmPageHeader>

    <div class="layout">
      <!-- 左：Handbook 列表 -->
      <ElCard class="card list-card" shadow="never">
        <template #header>
          <div class="card-head">
            <BookText :size="16" />
            <span>Handbook 列表</span>
            <span class="muted">{{ handbooks.length }}</span>
          </div>
        </template>

        <DmEmpty v-if="!loadingList && handbooks.length === 0" description="还没有 Handbook，点右上「上传 Handbook」开始" />

        <ul v-else class="hb-list">
          <li
            v-for="hb in handbooks"
            :key="hb.id"
            class="hb-item"
            :class="{ active: hb.id === selectedId }"
            @click="select(hb.id)"
          >
            <div class="hb-name">{{ hb.name }}</div>
            <div class="hb-meta">
              <ElTag size="small" :type="HANDBOOK_STATUS_TYPE[hb.status]" effect="light">
                {{ HANDBOOK_STATUS_LABEL[hb.status] }}
              </ElTag>
              <span class="hb-version">v{{ hb.version_no }}</span>
            </div>
            <div v-if="hb.description" class="hb-desc">{{ hb.description }}</div>
          </li>
        </ul>
      </ElCard>

      <!-- 右：详情 -->
      <div class="detail-area">
        <div v-if="!selected" class="empty-detail">
          <DmEmpty
            :description="
              handbooks.length === 0
                ? '还没有任何 Handbook，点右上「上传 Handbook」直接上传文件即可'
                : '请点击左侧某个 Handbook 进入详情，文件管理在选中后显示'
            "
          />
          <div v-if="handbooks.length === 0" class="empty-cta">
            <ElButton type="primary" :icon="UploadCloud" @click="openCreate">
              上传 Handbook
            </ElButton>
          </div>
        </div>

        <template v-else>
          <!-- 顶部信息条 -->
          <ElCard class="card" shadow="never">
            <div class="info-bar">
              <div class="info-main">
                <h2>{{ selected.name }}</h2>
                <div class="info-meta">
                  <ElTag :type="HANDBOOK_STATUS_TYPE[selected.status]" effect="light">
                    {{ HANDBOOK_STATUS_LABEL[selected.status] }}
                  </ElTag>
                  <span class="muted">v{{ selected.version_no }}</span>
                  <span class="muted">·</span>
                  <span class="muted">更新于 {{ formatTime(selected.updated_at) }}</span>
                </div>
                <p v-if="selected.description" class="info-desc">
                  {{ selected.description }}
                </p>
              </div>
              <div class="info-actions">
                <ElButton
                  :icon="ClipboardCheck"
                  :disabled="!detail"
                  @click="openReviewDrawer"
                >
                  校对结构
                </ElButton>
                <ElDropdown
                  trigger="click"
                  :disabled="files.length === 0 || extracting"
                  @command="onExtractCommand"
                >
                  <ElButton
                    type="primary"
                    :icon="Sparkles"
                    :loading="extracting"
                    :disabled="files.length === 0"
                  >
                    从文件抽取结构
                    <ChevronDown :size="14" style="margin-left: 4px" />
                  </ElButton>
                  <template #dropdown>
                    <ElDropdownMenu>
                      <ElDropdownItem command="handbook_135910">
                        {{ HANDBOOK_DOC_TYPE_LABEL.handbook_135910 }}
                      </ElDropdownItem>
                      <ElDropdownItem command="playbook_v1">
                        {{ HANDBOOK_DOC_TYPE_LABEL.playbook_v1 }}
                      </ElDropdownItem>
                    </ElDropdownMenu>
                  </template>
                </ElDropdown>
                <ElTooltip content="删除整份 Handbook" placement="top">
                  <ElButton type="danger" plain :icon="Trash2" @click="confirmDeleteHandbook(selected)" />
                </ElTooltip>
              </div>
            </div>
          </ElCard>

          <!-- 结构覆盖摘要 -->
          <ElCard class="card" shadow="never">
            <template #header>
              <div class="card-head">
                <span class="dot dot-primary" />
                <span>{{ isPlaybook ? '结构条目' : '结构完整度' }}</span>
                <span class="muted">
                  {{ isPlaybook ? `${totalGot} 条` : `${totalGot} / ${totalExpect} 条` }}
                </span>
              </div>
            </template>

            <div v-if="loadingDetail" class="muted">加载中…</div>
            <div v-else class="struct-grid">
              <div
                v-for="row in structureRows"
                :key="row.key"
                class="struct-cell"
                :class="{
                  miss: !isPlaybook && row.got < row.expect,
                  ok: isPlaybook ? row.got > 0 : row.got >= row.expect,
                }"
              >
                <div class="struct-label">{{ row.label }}</div>
                <div class="struct-count">
                  <strong>{{ row.got }}</strong>
                  <span v-if="!isPlaybook" class="muted">/ {{ row.expect }}</span>
                  <span v-else class="muted">条</span>
                </div>
                <template v-if="isPlaybook">
                  <div :class="row.got > 0 ? 'struct-ok' : 'struct-miss'">
                    {{ row.got > 0 ? '已抽取' : '空' }}
                  </div>
                </template>
                <template v-else>
                  <div v-if="row.got < row.expect" class="struct-miss">
                    缺 {{ row.expect - row.got }} 条
                  </div>
                  <div v-else class="struct-ok">完整</div>
                </template>
              </div>
            </div>
          </ElCard>

          <!-- 上传区 -->
          <ElCard class="card" shadow="never">
            <template #header>
              <div class="card-head">
                <UploadCloud :size="16" />
                <span>来源文件</span>
                <span class="muted">{{ files.length }}</span>
                <div class="card-head-actions">
                  <ElButton size="small" :icon="RefreshCcw" plain @click="loadFiles">刷新</ElButton>
                </div>
              </div>
            </template>

            <ElUpload
              ref="uploadRef"
              drag
              multiple
              :auto-upload="true"
              :show-file-list="false"
              :http-request="customUpload"
              :before-upload="validateFile"
              :accept="HANDBOOK_SUPPORTED_TYPES.join(',')"
            >
              <div class="upload-hint">
                <UploadCloud :size="36" />
                <p class="upload-title">拖拽或点击上传产品手册</p>
                <p class="upload-sub">
                  支持 PPT / PDF / Word / Excel / Markdown / TXT，单文件 ≤ 50MB
                </p>
                <p v-if="uploading" class="muted">上传并解析中…</p>
              </div>
            </ElUpload>

            <div class="files-table-wrap">
              <ElEmpty v-if="!loadingFiles && files.length === 0" description="还没有文件" :image-size="80" />
              <ElTable v-else :data="files" stripe size="default" v-loading="loadingFiles">
                <ElTableColumn label="文件名" prop="filename" min-width="240">
                  <template #default="{ row }">
                    <div class="file-cell">
                      <FileText :size="14" />
                      <span class="file-name">{{ row.filename }}</span>
                    </div>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="类型" prop="file_type" width="90">
                  <template #default="{ row }">
                    <ElTag size="small" effect="plain">{{ (row.file_type || '?').toUpperCase() }}</ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="大小" width="100">
                  <template #default="{ row }">
                    <span class="muted">{{ formatSize(row.file_size) }}</span>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="解析状态" width="130">
                  <template #default="{ row }">
                    <ElTag :type="HANDBOOK_FILE_STATUS_TYPE[row.status as 'pending'|'parsing'|'parsed'|'failed']" size="small" effect="light">
                      {{ HANDBOOK_FILE_STATUS_LABEL[row.status as 'pending'|'parsing'|'parsed'|'failed'] }}
                    </ElTag>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="解析文本量" width="120">
                  <template #default="{ row }">
                    <span v-if="row.status === 'parsed'" class="muted">{{ row.parsed_text_length }} 字</span>
                    <span v-else-if="row.status === 'failed'" class="text-danger" :title="row.error_msg || ''">
                      {{ (row.error_msg || '失败').slice(0, 24) }}
                    </span>
                    <span v-else class="muted">-</span>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="上传时间" width="170">
                  <template #default="{ row }">
                    <span class="muted">{{ formatTime(row.created_at) }}</span>
                  </template>
                </ElTableColumn>
                <ElTableColumn label="操作" width="80" align="right">
                  <template #default="{ row }">
                    <ElButton size="small" link type="danger" :icon="Trash2" @click="removeFile(row)" />
                  </template>
                </ElTableColumn>
              </ElTable>
            </div>
          </ElCard>
        </template>
      </div>
    </div>

    <!-- 上传新建对话框：一步到位 创建 Handbook + 上传文件 + 同步解析 -->
    <ElDialog
      v-model="createVisible"
      title="上传产品手册"
      width="520px"
      :close-on-click-modal="false"
    >
      <ElForm ref="createFormRef" :model="createForm" label-width="80px" @submit.prevent>
        <ElFormItem label="文件" required>
          <ElUpload
            drag
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onCreatePickFile"
            :accept="HANDBOOK_SUPPORTED_TYPES.join(',')"
            style="width: 100%"
          >
            <div class="upload-hint">
              <UploadCloud :size="32" />
              <p class="upload-title">
                {{ createForm.file ? '点击或拖入更换文件' : '拖拽或点击选择文件' }}
              </p>
              <p class="upload-sub">
                支持 PPT / PDF / Word / Excel / Markdown / TXT，单文件 ≤ 50MB
              </p>
            </div>
          </ElUpload>
          <div v-if="createForm.file" class="picked-file">
            <FileText :size="14" />
            <span class="file-name">{{ createForm.file.name }}</span>
            <span class="muted">
              （{{ (createForm.file.size / 1024).toFixed(1) }} KB）
            </span>
            <ElButton link type="danger" size="small" @click="removeCreateFile">
              移除
            </ElButton>
          </div>
        </ElFormItem>

        <ElFormItem
          label="名称"
          prop="name"
          :rules="[{ required: true, message: '请输入 Handbook 名称', trigger: 'blur' }]"
        >
          <ElInput
            v-model="createForm.name"
            placeholder="选择文件后会自动用文件名填充"
            maxlength="128"
          />
        </ElFormItem>
        <ElFormItem label="说明">
          <ElInput
            v-model="createForm.description"
            type="textarea"
            :rows="2"
            placeholder="可选。一两句话描述产品/版本/用途"
            maxlength="512"
            show-word-limit
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="createVisible = false">取消</ElButton>
        <ElButton
          type="primary"
          :loading="createLoading"
          :disabled="!createForm.file || !createForm.name.trim()"
          @click="submitCreate"
        >
          {{ createLoading ? '解析中…' : '上传并解析' }}
        </ElButton>
      </template>
    </ElDialog>

    <!-- ============================================================
         B3 · 结构校对抽屉
         ============================================================ -->
    <ElDrawer
      v-model="reviewOpen"
      :title="isPlaybook ? '校对 Handbook 结构（Playbook · 按人设 + 4 章流程）' : '校对 Handbook 结构（1/3/3/5/9/10）'"
      direction="rtl"
      size="780px"
    >
      <!-- playbook_v1 变长编辑器 -->
      <div v-if="playbookDraft" class="review-drawer">
        <div class="review-hint">
          抽屉里改的是<strong>当前 Playbook 的话术结构</strong>。每个板块条目数量不固定，可
          <strong>增删</strong>。"保存草稿"只更新内容；"保存并发布"会把版本号 +1。
        </div>
        <ElTabs v-model="reviewTab" class="review-tabs">
          <!-- ① 开场 -->
          <ElTabPane label="① 开场" name="pb_open">
            <ElForm label-position="top" size="default">
              <ElFormItem label="通用开场白（opener）">
                <ElInput v-model="playbookDraft.open.opener" type="textarea" :rows="2" maxlength="1000" show-word-limit />
              </ElFormItem>
              <ElFormItem label="时机/触发提示（timing_cue，可选）">
                <ElInput v-model="playbookDraft.open.timing_cue" type="textarea" :rows="2" maxlength="1000" show-word-limit />
              </ElFormItem>
            </ElForm>
            <div class="review-sub">按人设开场白</div>
            <div v-for="(po, i) in playbookDraft.open.persona_openers" :key="i" class="review-card">
              <div class="review-card-head">
                开场 #{{ i + 1 }}
                <ElButton text type="danger" size="small" @click="pbRemoveOpener(i)">删除</ElButton>
              </div>
              <ElForm label-position="top" size="default">
                <div class="review-row2">
                  <ElFormItem label="人设代号（A/B/C/D）">
                    <ElInput v-model="po.persona" placeholder="A" />
                  </ElFormItem>
                  <ElFormItem label="人设名称">
                    <ElInput v-model="po.persona_label" placeholder="如：商务人士" />
                  </ElFormItem>
                </div>
                <ElFormItem label="开场话术">
                  <ElInput v-model="po.text" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
            <ElButton plain :icon="Plus" @click="pbAddOpener">新增人设开场</ElButton>
          </ElTabPane>

          <!-- ② 卖点 by 人设 -->
          <ElTabPane label="② 卖点（按人设）" name="pb_say">
            <div v-for="(b, bi) in playbookDraft.say" :key="bi" class="review-block">
              <div class="review-block-head">
                <span>人设 #{{ bi + 1 }}</span>
                <ElButton text type="danger" size="small" @click="pbRemoveSayBlock(bi)">删除人设</ElButton>
              </div>
              <div class="review-row2">
                <ElFormItem label="人设代号（A/B/C/D）">
                  <ElInput v-model="b.persona" placeholder="A" />
                </ElFormItem>
                <ElFormItem label="人设名称">
                  <ElInput v-model="b.persona_label" placeholder="如：内容创作者" />
                </ElFormItem>
              </div>
              <div v-for="(p, pi) in b.points" :key="pi" class="review-card">
                <div class="review-card-head">
                  卖点 #{{ pi + 1 }}
                  <ElButton text type="danger" size="small" @click="pbRemovePoint(b, pi)">删除</ElButton>
                </div>
                <ElForm label-position="top" size="default">
                  <ElFormItem label="卖点标签">
                    <ElInput v-model="p.label" />
                  </ElFormItem>
                  <ElFormItem label="卖点内容">
                    <ElInput v-model="p.text" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                  </ElFormItem>
                  <ElFormItem label="演示动作（demo，可选）">
                    <ElInput v-model="p.demo" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                  </ElFormItem>
                </ElForm>
              </div>
              <ElButton plain :icon="Plus" size="small" @click="pbAddPoint(b)">新增卖点</ElButton>
            </div>
            <ElButton plain :icon="Plus" @click="pbAddSayBlock">新增人设</ElButton>
          </ElTabPane>

          <!-- ③ 竞品攻防 -->
          <ElTabPane label="③ 竞品攻防" name="pb_compete">
            <div v-for="(c, ci) in playbookDraft.compete" :key="ci" class="review-block">
              <div class="review-block-head">
                <span>竞品 #{{ ci + 1 }}</span>
                <ElButton text type="danger" size="small" @click="pbRemoveCompete(ci)">删除竞品</ElButton>
              </div>
              <div class="review-row2">
                <ElFormItem label="竞品（vs）">
                  <ElInput v-model="c.vs" placeholder="如：iPad Air / 三星 Tab S9" />
                </ElFormItem>
                <ElFormItem label="备注（note，可选）">
                  <ElInput v-model="c.note" />
                </ElFormItem>
              </div>
              <div v-for="(pr, pri) in c.pairs" :key="pri" class="review-card">
                <div class="review-card-head">
                  攻防 #{{ pri + 1 }}
                  <ElButton text type="danger" size="small" @click="pbRemovePair(c, pri)">删除</ElButton>
                </div>
                <ElForm label-position="top" size="default">
                  <ElFormItem label="客户说（customer）">
                    <ElInput v-model="pr.customer" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                  </ElFormItem>
                  <ElFormItem label="应答话术（response）">
                    <ElInput v-model="pr.response" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                  </ElFormItem>
                </ElForm>
              </div>
              <ElButton plain :icon="Plus" size="small" @click="pbAddPair(c)">新增攻防话术</ElButton>
            </div>
            <ElButton plain :icon="Plus" @click="pbAddCompete">新增竞品</ElButton>
          </ElTabPane>

          <!-- ④ FAQ -->
          <ElTabPane label="④ FAQ" name="pb_respond">
            <div v-for="(r, ri) in playbookDraft.respond" :key="ri" class="review-card">
              <div class="review-card-head">
                FAQ #{{ ri + 1 }}
                <ElButton text type="danger" size="small" @click="pbRemoveFaq(ri)">删除</ElButton>
              </div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="客户提问（Q）">
                  <ElInput v-model="r.q" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                </ElFormItem>
                <ElFormItem label="标准答案（A）">
                  <ElInput v-model="r.a" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
                <ElFormItem label="演示动作（demo，可选）">
                  <ElInput v-model="r.demo" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
            <ElButton plain :icon="Plus" @click="pbAddFaq">新增 FAQ</ElButton>
          </ElTabPane>
        </ElTabs>
      </div>

      <div v-else-if="reviewDraft" class="review-drawer">
        <div class="review-hint">
          抽屉里改的是<strong>当前 Handbook 的话术结构</strong>。"保存草稿"只更新内容；
          "保存并发布"会把版本号 +1。所有字段允许留空。
        </div>
        <ElTabs v-model="reviewTab" class="review-tabs">
          <!-- ① -->
          <ElTabPane label="① 一句话定位" name="intro">
            <ElForm label-position="top" size="default">
              <ElFormItem label="标签（label）">
                <ElInput v-model="reviewDraft.intro_1.label" maxlength="1000" show-word-limit />
              </ElFormItem>
              <ElFormItem label="一句话定位（text）">
                <ElInput
                  v-model="reviewDraft.intro_1.text"
                  type="textarea"
                  :rows="3"
                  maxlength="1000"
                  show-word-limit
                  placeholder="一句话讲清产品定位"
                />
              </ElFormItem>
            </ElForm>
          </ElTabPane>

          <!-- ③ 卖点 -->
          <ElTabPane label="③ 卖点" name="sell">
            <div v-for="(it, i) in reviewDraft.selling_points" :key="it.id" class="review-card">
              <div class="review-card-head">卖点 #{{ i + 1 }} <span class="mono muted">{{ it.id }}</span></div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="标签">
                  <ElInput v-model="it.label" />
                </ElFormItem>
                <ElFormItem label="内容">
                  <ElInput v-model="it.text" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
          </ElTabPane>

          <!-- ③ 竞品 -->
          <ElTabPane label="③ 竞品对比" name="comp">
            <div v-for="(it, i) in reviewDraft.competitor_points" :key="it.id" class="review-card">
              <div class="review-card-head">竞品对比 #{{ i + 1 }} <span class="mono muted">{{ it.id }}</span></div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="标签">
                  <ElInput v-model="it.label" />
                </ElFormItem>
                <ElFormItem label="对比对象（vs）">
                  <ElInput v-model="it.vs" placeholder="例如：iPad Air / 三星 Tab S9" />
                </ElFormItem>
                <ElFormItem label="差异点">
                  <ElInput v-model="it.text" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
          </ElTabPane>

          <!-- ⑤ 参数 -->
          <ElTabPane label="⑤ 核心参数" name="param">
            <div v-for="(it, i) in reviewDraft.core_params" :key="it.id" class="review-card">
              <div class="review-card-head">核心参数 #{{ i + 1 }} <span class="mono muted">{{ it.id }}</span></div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="标签（如：屏幕 / 音质 / 重量 / 续航 / 系统）">
                  <ElInput v-model="it.label" />
                </ElFormItem>
                <ElFormItem label="参数值（含具体数字）">
                  <ElInput v-model="it.text" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
          </ElTabPane>

          <!-- ⑨ FAQ -->
          <ElTabPane label="⑨ FAQ" name="faq">
            <div v-for="(it, i) in reviewDraft.faq" :key="it.id" class="review-card">
              <div class="review-card-head">FAQ #{{ i + 1 }} <span class="mono muted">{{ it.id }}</span></div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="主题（label）">
                  <ElInput v-model="it.label" />
                </ElFormItem>
                <ElFormItem label="客户提问（Q）">
                  <ElInput v-model="it.q" type="textarea" :rows="2" maxlength="1000" show-word-limit />
                </ElFormItem>
                <ElFormItem label="标准答案（A）">
                  <ElInput v-model="it.a" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
          </ElTabPane>

          <!-- ⑩ 演示动作 -->
          <ElTabPane label="⑩ 演示动作" name="demo">
            <div v-for="(it, i) in reviewDraft.demo_actions" :key="it.id" class="review-card">
              <div class="review-card-head">演示动作 #{{ i + 1 }} <span class="mono muted">{{ it.id }}</span></div>
              <ElForm label-position="top" size="default">
                <ElFormItem label="动作名">
                  <ElInput v-model="it.label" />
                </ElFormItem>
                <ElFormItem label="如何引导客户体验（动作 + 话术）">
                  <ElInput v-model="it.text" type="textarea" :rows="3" maxlength="1000" show-word-limit />
                </ElFormItem>
              </ElForm>
            </div>
          </ElTabPane>
        </ElTabs>
      </div>

      <template #footer>
        <div class="review-footer">
          <ElButton @click="reviewOpen = false">取消</ElButton>
          <ElButton :loading="reviewSaving" @click="saveReview({ bump: false })">
            保存草稿
          </ElButton>
          <ElButton type="primary" :icon="Save" :loading="reviewSaving" @click="saveReview({ bump: true })">
            保存并发布新版本
          </ElButton>
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<style scoped lang="scss">
.handbook-manager { display: flex; flex-direction: column; }

.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
}

.card { background: var(--dm-bg-card); }

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: var(--dm-fw-medium);
}
.card-head-actions { margin-left: auto; }

.muted { color: var(--dm-text-muted); font-size: var(--dm-fs-small); }
.mono { font-family: var(--dm-font-mono, ui-monospace, SFMono-Regular, monospace); }

/* B3 · 校对抽屉 */
.review-drawer { padding-bottom: 8px; }
.review-hint {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: var(--dm-bg-soft);
  border-radius: 6px;
  font-size: 12px;
  color: var(--dm-text-muted);
  line-height: 1.6;
}
.review-tabs { margin-top: 4px; }
.review-card {
  margin-bottom: 16px;
  padding: 12px 14px;
  background: var(--dm-bg, #fff);
  border: 1px solid var(--dm-border);
  border-radius: 8px;
}
.review-card-head {
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--dm-text-primary);
}
.review-card-head .mono { margin-left: 6px; font-size: 12px; }
.review-card-head .el-button { float: right; padding: 0; }
.review-block {
  margin-bottom: 20px;
  padding: 14px;
  border: 1px solid var(--dm-border);
  border-radius: 10px;
  background: var(--dm-bg-subtle, #fafafa);
}
.review-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 700;
  margin-bottom: 10px;
  color: var(--dm-text-primary);
}
.review-sub {
  font-weight: 600;
  margin: 14px 0 8px;
  color: var(--dm-text-secondary, #555);
}
.review-row2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.review-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.text-danger { color: var(--dm-danger); font-size: var(--dm-fs-small); }

/* ---------- 左侧列表 ---------- */
.list-card :deep(.el-card__body) { padding: 8px; }

.hb-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.hb-item {
  padding: 10px 12px;
  border-radius: var(--dm-radius);
  cursor: pointer;
  transition: background var(--dm-transition);
  border: 1px solid transparent;
}
.hb-item:hover { background: var(--dm-bg-muted); }
.hb-item.active {
  background: var(--dm-bg-selected);
  border-color: var(--dm-border);
}
.hb-name {
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
  margin-bottom: 6px;
  line-height: 1.4;
}
.hb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hb-version {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  font-variant-numeric: tabular-nums;
}
.hb-desc {
  margin-top: 6px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 右侧详情 ---------- */
.detail-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.info-bar {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}
.info-main h2 {
  margin: 0 0 8px;
  font-size: var(--dm-fs-h3);
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
}
.info-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.info-desc {
  margin: 8px 0 0;
  color: var(--dm-text-secondary);
  font-size: var(--dm-fs-body);
}
.info-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot-primary { background: var(--dm-primary, #3b82f6); }

/* 结构完整度网格 */
.struct-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}
@media (max-width: 1280px) {
  .struct-grid { grid-template-columns: repeat(3, 1fr); }
}

.struct-cell {
  padding: 14px 12px;
  border-radius: var(--dm-radius);
  background: var(--dm-bg);
  border: 1px solid var(--dm-border);
}
.struct-cell.ok {
  border-color: rgba(16, 185, 129, 0.35);
  background: rgba(16, 185, 129, 0.05);
}
.struct-cell.miss {
  border-color: rgba(245, 158, 11, 0.45);
  background: rgba(245, 158, 11, 0.06);
}
.struct-label {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-secondary);
  margin-bottom: 4px;
}
.struct-count {
  font-size: 22px;
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
  font-variant-numeric: tabular-nums;
}
.struct-count .muted { font-size: var(--dm-fs-small); font-weight: normal; margin-left: 4px; }
.struct-miss {
  font-size: var(--dm-fs-small);
  color: #b45309;
  margin-top: 2px;
}
.struct-ok {
  font-size: var(--dm-fs-small);
  color: #047857;
  margin-top: 2px;
}

/* 空状态详情区 */
.empty-detail {
  padding: 48px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.empty-cta {
  display: flex;
  justify-content: center;
}

/* 上传对话框选中文件预览 */
.picked-file {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--dm-bg-soft);
  font-size: var(--dm-fs-small);
}
.picked-file .file-name { font-weight: var(--dm-fw-medium); }

/* 上传区 */
.upload-hint {
  padding: 16px 0;
  color: var(--dm-text-secondary);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.upload-title {
  margin: 4px 0 0;
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
}
.upload-sub {
  margin: 0;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}

.files-table-wrap { margin-top: 16px; }

.file-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.file-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
