/**
 * Providers Pinia store
 * 负责拉取/缓存 providers 列表，并暴露 CRUD/set_default/test actions
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  providersApi,
  type Provider,
  type ProviderCreate,
  type ProviderTestRequest,
  type ProviderTestResponse,
  type ProviderUpdate,
} from '@/api/providers'

export const useProvidersStore = defineStore('providers', () => {
  const list = ref<Provider[]>([])
  const loading = ref(false)

  const defaultProvider = computed(() => list.value.find((p) => p.is_default) ?? null)

  async function fetchAll() {
    loading.value = true
    try {
      list.value = await providersApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(payload: ProviderCreate): Promise<Provider> {
    const created = await providersApi.create(payload)
    await fetchAll()
    return created
  }

  async function update(id: number, payload: ProviderUpdate): Promise<Provider> {
    const updated = await providersApi.update(id, payload)
    await fetchAll()
    return updated
  }

  async function remove(id: number): Promise<void> {
    await providersApi.remove(id)
    await fetchAll()
  }

  async function setDefault(id: number): Promise<void> {
    await providersApi.setDefault(id)
    await fetchAll()
  }

  async function test(payload: ProviderTestRequest): Promise<ProviderTestResponse> {
    return providersApi.test(payload)
  }

  return {
    list,
    loading,
    defaultProvider,
    fetchAll,
    create,
    update,
    remove,
    setDefault,
    test,
  }
})
