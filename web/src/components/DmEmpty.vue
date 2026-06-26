<script setup lang="ts">
import { Inbox } from '@lucide/vue'

withDefaults(
  defineProps<{
    title?: string
    description?: string
    iconSize?: number
  }>(),
  {
    title: '暂无内容',
    description: '',
    iconSize: 40,
  },
)
</script>

<template>
  <div class="dm-empty">
    <div class="icon-wrap">
      <Inbox :size="iconSize" :stroke-width="1.4" />
    </div>
    <div class="title">{{ title }}</div>
    <p v-if="description" class="desc">{{ description }}</p>
    <div v-if="$slots.action" class="action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.dm-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
  color: var(--dm-text-muted);
  text-align: center;
}
.icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  border-radius: var(--dm-radius-full);
  background: var(--dm-bg-muted);
  color: var(--dm-text-muted);
  margin-bottom: 16px;
}
.title {
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text-secondary);
}
.desc {
  margin: 8px 0 0;
  font-size: var(--dm-fs-caption);
  line-height: var(--dm-lh-caption);
  color: var(--dm-text-muted);
  max-width: 360px;
}
.action {
  margin-top: 20px;
}
</style>
