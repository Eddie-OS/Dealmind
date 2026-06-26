<script setup lang="ts">
/**
 * 通用占位视图（Stage 0）
 * 后续每个真实页面会用独立 *View.vue 替换此占位
 */
import { useRoute } from 'vue-router'
import DmPageHeader from '@/components/DmPageHeader.vue'
import DmEmpty from '@/components/DmEmpty.vue'

const route = useRoute()
</script>

<template>
  <div class="placeholder-view">
    <DmPageHeader
      :title="(route.meta.title as string) ?? '页面'"
      subtitle="此页面将在后续 Stage 实现，当前为占位。"
    />
    <div class="card">
      <DmEmpty
        title="正在路上"
        description="此模块尚未实现，先把整体骨架立起来。点击左侧菜单可在各占位页之间切换以验证路由与布局。"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.placeholder-view {
  width: 100%;
}
.card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-lg);
}
</style>
