/**
 * Personas Pinia store
 * 负责拉取/缓存 personas 列表与单条详情，并暴露 CRUD/上传/抽参 actions。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  personasApi,
  type Persona,
  type PersonaCreatePayload,
  type PersonaListQuery,
  type PersonaUpdatePayload,
  type PersonaUploadResponse,
} from '@/api/personas'

export const usePersonasStore = defineStore('personas', () => {
  const list = ref<Persona[]>([])
  const loading = ref(false)
  const lastQuery = ref<PersonaListQuery>({})
  const current = ref<Persona | null>(null)

  const total = computed(() => list.value.length)
  const allTags = computed(() => {
    const set = new Set<string>()
    for (const p of list.value) for (const t of p.tags || []) set.add(t)
    return [...set].sort()
  })

  async function fetchAll(query: PersonaListQuery = {}) {
    loading.value = true
    try {
      const res = await personasApi.list(query)
      list.value = res.items
      lastQuery.value = query
    } finally {
      loading.value = false
    }
  }

  async function refresh() {
    return fetchAll(lastQuery.value)
  }

  async function fetchDetail(id: number): Promise<Persona> {
    const p = await personasApi.detail(id)
    current.value = p
    return p
  }

  async function create(payload: PersonaCreatePayload): Promise<Persona> {
    const created = await personasApi.create(payload)
    await refresh()
    return created
  }

  async function upload(file: File): Promise<PersonaUploadResponse> {
    const res = await personasApi.upload(file)
    await refresh()
    return res
  }

  async function update(id: number, payload: PersonaUpdatePayload): Promise<Persona> {
    const updated = await personasApi.update(id, payload)
    // 局部更新缓存，避免整列表重拉
    const idx = list.value.findIndex((p) => p.id === id)
    if (idx >= 0) list.value[idx] = updated
    if (current.value?.id === id) current.value = updated
    return updated
  }

  async function extractPressure(id: number): Promise<Persona> {
    const updated = await personasApi.extractPressure(id)
    const idx = list.value.findIndex((p) => p.id === id)
    if (idx >= 0) list.value[idx] = updated
    if (current.value?.id === id) current.value = updated
    return updated
  }

  async function remove(id: number): Promise<void> {
    await personasApi.remove(id)
    list.value = list.value.filter((p) => p.id !== id)
    if (current.value?.id === id) current.value = null
  }

  return {
    list,
    loading,
    current,
    total,
    allTags,
    fetchAll,
    refresh,
    fetchDetail,
    create,
    upload,
    update,
    extractPressure,
    remove,
  }
})
