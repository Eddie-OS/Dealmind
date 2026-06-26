<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="dm-page-header">
    <div class="text">
      <h1 class="title">{{ title }}</h1>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped lang="scss">
.dm-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 0 0 24px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--dm-border);
}
.title {
  font-size: var(--dm-fs-h1);
  line-height: var(--dm-lh-h1);
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
  margin: 0;
  letter-spacing: -0.01em;
}
.subtitle {
  margin: 8px 0 0;
  font-size: var(--dm-fs-caption);
  line-height: var(--dm-lh-caption);
  color: var(--dm-text-muted);
}
.actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-shrink: 0;
}
</style>
