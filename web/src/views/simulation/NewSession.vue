<script setup lang="ts">
/**
 * 新建对话表单（Stage 6a）
 *
 * 一屏完成参数选择 + 开场白决策 + 启动跳转。
 *
 * 字段：
 *   persona_id          el-select 含搜索、按 tag 过滤
 *   product_kb_id       el-select（可选）
 *   enterprise_kb_id    el-select（可选）
 *   topic               el-input
 *   max_rounds          el-slider 8~50
 *   judge_interval      el-input-number
 *   memory_interval     el-input-number
 *   who_speaks_first    el-radio sales/persona
 *   opening (sales)     el-select 5 模板 + 「自定义」 → textarea
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElButton,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSlider,
  ElTag,
} from 'element-plus'
import { Play, Sparkles } from '@lucide/vue'

import { kbApi, type KnowledgeBase } from '@/api/kb'
import { handbookApi, type Handbook } from '@/api/handbook'
import { personasApi, type Persona } from '@/api/personas'
import { agentProfileApi } from '@/api/agent_profile'
import PersonaAvatar from '@/components/PersonaAvatar.vue'
import {
  sessionsApi,
  type CreateSessionPayload,
  type FirstSpeaker,
} from '@/api/sessions'

const router = useRouter()

const loading = ref(false)
const submitting = ref(false)

const personas = ref<Persona[]>([])
const productKbs = ref<KnowledgeBase[]>([])
const enterpriseKbs = ref<KnowledgeBase[]>([])
const handbooks = ref<Handbook[]>([])

const LANGUAGE_OPTIONS = [
  { value: 'zh-CN', label: '普通话（简体中文）', native: '中文' },
  { value: 'en-US', label: 'English (US)',         native: 'English' },
  { value: 'es-ES', label: 'Español',              native: 'Español' },
  { value: 'ar-SA', label: 'العربية',              native: 'العربية' },
  { value: 'id-ID', label: 'Bahasa Indonesia',     native: 'Bahasa' },
] as const

type LanguageCode = (typeof LANGUAGE_OPTIONS)[number]['value']

const form = ref({
  persona_id: null as number | null,
  // 留空即用默认话题（提交时由 onStart 兜底为「华为平板12X销售模拟」），
  // 这样打开表单时是空框 + placeholder 提示，无需先删再改。
  topic: '',
  product_kb_id: null as number | null,
  enterprise_kb_id: null as number | null,
  handbook_id: null as number | null,
  max_rounds: 30,
  judge_interval: 3,
  memory_interval: 3,
  who_speaks_first: 'sales' as FirstSpeaker,
  language: 'zh-CN' as LanguageCode,
})

const selectedPersona = computed(() =>
  personas.value.find((p) => p.id === form.value.persona_id) || null,
)

/** 是否被销冠的默认会话参数预填，用于 UI 提示。*/
const prefilledFromDefaults = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const [persRes, prodRes, entRes, hbRes, salesProfile] = await Promise.all([
      personasApi.list({ limit: 500 }),
      kbApi.list({ kb_type: 'product' }),
      kbApi.list({ kb_type: 'enterprise' }),
      handbookApi.list().catch(() => ({ items: [] as Handbook[], total: 0 })),
      agentProfileApi.get().catch(() => null),
    ])
    personas.value = persRes.items
    productKbs.value = prodRes
    enterpriseKbs.value = entRes
    handbooks.value = hbRes.items

    // —— 用销冠 default_session_params 预填（命中字段才覆盖）——
    const dsp = (salesProfile?.default_session_params || {}) as Record<string, any>
    const hits: string[] = []
    if (typeof dsp.max_rounds === 'number') {
      form.value.max_rounds = Math.min(50, Math.max(8, dsp.max_rounds))
      hits.push(`max_rounds=${form.value.max_rounds}`)
    }
    if (typeof dsp.product_kb_id === 'number') {
      form.value.product_kb_id = dsp.product_kb_id
      hits.push(`product_kb=#${dsp.product_kb_id}`)
    }
    if (typeof dsp.enterprise_kb_id === 'number') {
      form.value.enterprise_kb_id = dsp.enterprise_kb_id
      hits.push(`enterprise_kb=#${dsp.enterprise_kb_id}`)
    }
    prefilledFromDefaults.value = hits.length > 0

    // —— 默认值兜底（销冠没指定时才生效）——
    if (personas.value.length && form.value.persona_id === null) {
      form.value.persona_id = personas.value[0].id
    }
    if (productKbs.value.length && form.value.product_kb_id === null) {
      form.value.product_kb_id = productKbs.value[0].id
    }
    // Handbook：库里若只有一份 ready 的，默认选上（与后端 resolve_default_handbook_id 行为对齐）
    const readyHb = handbooks.value.filter((h) => h.status === 'ready')
    if (readyHb.length === 1 && form.value.handbook_id === null) {
      form.value.handbook_id = readyHb[0].id
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})

async function onStart() {
  if (!form.value.persona_id) {
    ElMessage.warning('请先选择 Persona 人设')
    return
  }
  submitting.value = true
  try {
    const payload: CreateSessionPayload = {
      persona_id: form.value.persona_id,
      topic: form.value.topic.trim() || '华为平板12X销售模拟',
      product_kb_id: form.value.product_kb_id ?? null,
      enterprise_kb_id: form.value.enterprise_kb_id ?? null,
      handbook_id: form.value.handbook_id ?? null,
      max_rounds: form.value.max_rounds,
      judge_interval: form.value.judge_interval,
      memory_interval: form.value.memory_interval,
      who_speaks_first: form.value.who_speaks_first,
      language: form.value.language,
    }
    // 开场白不再由前端指定：销售先开口时由 LLM 按会话语言现场生成。

    const created = await sessionsApi.create(payload)
    await sessionsApi.start(created.id)
    ElMessage.success('已创建并启动会话，跳转对话现场')
    router.push(`/simulation/live/${encodeURIComponent(created.id)}`)
  } catch (e) {
    console.error(e)
    // http interceptor 已弹 toast
  } finally {
    submitting.value = false
  }
}

function personaFilter(query: string, persona: Persona): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    persona.name.toLowerCase().includes(q)
    || (persona.tags || []).some((t) => t.toLowerCase().includes(q))
  )
}
</script>

<template>
  <div class="new-session">
    <div class="page-header">
      <h1 class="dm-text-h1">新建对话</h1>
      <p class="dm-text-body-muted">
        选择 persona 与产品 / 企业知识库，配置开场策略与节奏，启动一场实时博弈
      </p>
    </div>

    <div v-if="prefilledFromDefaults" class="prefill-banner">
      <span class="prefill-icon">✦</span>
      <span class="prefill-text">
        已根据「销冠 Agent · 默认会话参数」自动预填部分字段，可随时调整。
      </span>
      <router-link to="/kb/sales-agent" class="prefill-link">前往修改默认 →</router-link>
    </div>

    <ElForm
      label-position="top"
      class="form-grid"
      @submit.prevent="onStart"
    >
      <!-- 左列：核心要素 -->
      <section class="card">
        <h2 class="dm-text-h3">会话要素</h2>

        <ElFormItem label="Persona 人设" required>
          <ElSelect
            v-model="form.persona_id"
            placeholder="选择或搜索人设"
            filterable
            :filter-method="(q: string) => undefined /* 内置 filter */"
            :loading="loading"
            class="full"
          >
            <ElOption
              v-for="p in personas"
              :key="p.id"
              :value="p.id"
              :label="p.name"
            >
              <div class="opt-row">
                <PersonaAvatar
                  :avatar-key="p.avatar_key"
                  :name="p.name"
                  :size="26"
                />
                <span class="opt-name">{{ p.name }}</span>
                <span class="opt-meta">
                  <ElTag
                    v-for="t in (p.tags || []).slice(0, 3)"
                    :key="t"
                    size="small"
                    type="info"
                    effect="plain"
                  >{{ t }}</ElTag>
                </span>
              </div>
            </ElOption>
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="销售话题">
          <ElInput
            v-model="form.topic"
            placeholder="留空即用默认话题「华为平板12X销售模拟」"
            maxlength="200"
            clearable
            show-word-limit
          />
        </ElFormItem>

        <ElFormItem label="产品知识库">
          <ElSelect
            v-model="form.product_kb_id"
            placeholder="可选 — Stage 6b 会接入 RAG"
            clearable
            class="full"
          >
            <ElOption
              v-for="kb in productKbs"
              :key="kb.id"
              :value="kb.id"
              :label="kb.name"
            >
              <span>{{ kb.name }}</span>
              <span class="opt-side">{{ kb.file_count }} 文件 · {{ kb.chunk_count }} chunks</span>
            </ElOption>
          </ElSelect>
        </ElFormItem>

        <ElFormItem>
          <template #label>
            <span>产品手册</span>
            <span class="label-hint">销冠剧本 — 注入 prompt 强约束（1/3/3/5/9/10 或 Playbook 结构）</span>
          </template>
          <ElSelect
            v-model="form.handbook_id"
            placeholder="可选 — 不选则按通用销售经验作答"
            clearable
            class="full"
          >
            <ElOption
              v-for="hb in handbooks"
              :key="hb.id"
              :value="hb.id"
              :label="hb.name"
              :disabled="hb.status !== 'ready'"
            >
              <span>{{ hb.name }}</span>
              <span class="opt-side">
                v{{ hb.version_no }} · {{ hb.status }}
              </span>
            </ElOption>
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="企业知识库">
          <ElSelect
            v-model="form.enterprise_kb_id"
            placeholder="可选 — Stage 6b 会接入 RAG"
            clearable
            class="full"
          >
            <ElOption
              v-for="kb in enterpriseKbs"
              :key="kb.id"
              :value="kb.id"
              :label="kb.name"
            >
              <span>{{ kb.name }}</span>
              <span class="opt-side">{{ kb.file_count }} 文件 · {{ kb.chunk_count }} chunks</span>
            </ElOption>
          </ElSelect>
        </ElFormItem>

        <ElFormItem label="对话语言">
          <ElSelect v-model="form.language" class="full">
            <ElOption
              v-for="o in LANGUAGE_OPTIONS"
              :key="o.value"
              :value="o.value"
              :label="o.label"
            >
              <div class="opt-row">
                <span class="opt-name">{{ o.label }}</span>
                <span class="opt-meta">
                  <ElTag size="small" effect="plain">{{ o.value }}</ElTag>
                </span>
              </div>
            </ElOption>
          </ElSelect>
          <div class="dm-text-small dm-text-muted" style="margin-top: 6px">
            所有 Agent（人设 / 销冠 / Judge / Coach）的输出都会切到该语言；
            JSON 字段名保持英文不变。
          </div>
        </ElFormItem>
      </section>

      <!-- 右列：节奏 + 开场 -->
      <section class="card">
        <h2 class="dm-text-h3">节奏与开场</h2>

        <ElFormItem :label="`最大轮数：${form.max_rounds}`">
          <ElSlider
            v-model="form.max_rounds"
            :min="8"
            :max="50"
            :step="1"
            show-stops
            :marks="{ 8: '8', 20: '20', 30: '30', 50: '50' }"
          />
        </ElFormItem>

        <div class="row-2">
          <ElFormItem label="Judge 间隔（轮）">
            <ElInputNumber v-model="form.judge_interval" :min="1" :max="10" class="full" />
          </ElFormItem>
          <ElFormItem label="Memory 间隔（轮）">
            <ElInputNumber v-model="form.memory_interval" :min="1" :max="10" class="full" />
          </ElFormItem>
        </div>

        <ElFormItem label="谁先开口">
          <ElRadioGroup v-model="form.who_speaks_first">
            <ElRadioButton value="sales">销冠先开口（推荐）</ElRadioButton>
            <ElRadioButton value="persona">客户先开口</ElRadioButton>
          </ElRadioGroup>
        </ElFormItem>

        <div v-if="form.who_speaks_first === 'sales'" class="opening-preview">
          <Sparkles :size="14" :stroke-width="1.6" />
          <span class="opening-text">
            开场白由 AI 现场生成，并自动匹配上方所选「对话语言」——无需手动设置。
          </span>
        </div>
      </section>
    </ElForm>

    <!-- 底部操作 -->
    <div class="bottom-bar">
      <div class="bb-info dm-text-body-muted">
        <template v-if="selectedPersona">
          已选：<b>{{ selectedPersona.name }}</b>
          <span v-if="selectedPersona.tags?.length"> · {{ selectedPersona.tags.slice(0, 3).join(' / ') }}</span>
        </template>
        <template v-else>未选择 persona</template>
      </div>
      <div class="bb-actions">
        <ElButton :disabled="submitting" @click="router.push('/simulation/history')">
          查看历史会话
        </ElButton>
        <ElButton
          type="primary"
          :loading="submitting"
          :disabled="!form.persona_id"
          @click="onStart"
        >
          <template #icon><Play :size="16" :stroke-width="1.8" /></template>
          开始对话
        </ElButton>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.new-session {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header h1 { margin-bottom: 4px; }

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  align-items: start;
}
@media (max-width: 1100px) {
  .form-grid { grid-template-columns: 1fr; }
}

.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-lg);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.card h2 { margin: 0 0 8px; }

.full { width: 100%; }

.row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.opt-row {
  display: flex; align-items: center; gap: 10px;
}
.opt-name { font-weight: var(--dm-fw-medium); flex: 1; min-width: 0; }
.opt-meta { display: inline-flex; gap: 4px; }

.prefill-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
  background: linear-gradient(180deg, #fffbeb 0%, #fffefa 100%);
  border: 1px solid #fde68a;
  border-radius: 8px;
  font-size: 13px;
  color: #78350f;
}
.prefill-icon {
  font-size: 16px;
  color: #d97706;
  line-height: 1;
}
.prefill-text { flex: 1; min-width: 0; }
.prefill-link {
  color: #92400e;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;

  &:hover { color: #4f46e5; }
}
.opt-side {
  margin-left: 8px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}

.label-hint {
  margin-left: 8px;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  font-weight: 400;
}

.opening-preview {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: var(--dm-radius);
  background: var(--dm-bg-muted);
  border: 1px dashed var(--dm-border);
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--dm-text-muted);
}
.opening-text {
  color: var(--dm-text);
  font-weight: var(--dm-fw-medium);
  flex: 1 1 100%;
  margin-top: 4px;
  white-space: pre-wrap;
}

.bottom-bar {
  position: sticky;
  bottom: 0;
  margin: 0 -32px -32px;
  padding: 14px 32px;
  background: var(--dm-bg-card);
  border-top: 1px solid var(--dm-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.bb-actions { display: flex; gap: 8px; }
</style>
