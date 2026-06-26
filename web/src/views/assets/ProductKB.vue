<script setup lang="ts">
/**
 * 产品知识库（蓝图 §Stage 4）
 * 销冠 Agent 用于 RAG 调用的产品资料、规格、FAQ。
 */
import KBManager from '@/components/KBManager.vue'
</script>

<template>
  <KBManager
    type="product"
    title="产品知识库"
    subtitle="销冠 Agent 检索的产品资料、规格说明、销售话术与常见问题（FAQ）"
  />
</template>
