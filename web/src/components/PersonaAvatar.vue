<script setup lang="ts">
/**
 * Notion 风格人设头像。
 *
 * - 若 `avatarKey` 形如 `pNN`（NN=01..44）→ 渲染 `/avatars/<key>.png`
 * - 否则按 name 取首字符渲染圆形占位（线性 hash 决定背景色）
 * - 加载失败 → 自动降级到首字符占位，不会出现碎图
 *
 * 注：图片实际放在 `web/public/avatars/p01.png` … `p44.png`，
 *     Vite 把 `public/` 直接当成根目录，所以 `/avatars/p01.png` 在 dev/prod 都可直访。
 */
import { computed, ref, watch } from 'vue'

interface Props {
  avatarKey?: string | null
  name?: string
  size?: number | string
  /** 是否在右下角显示圆形小指示点，例如选中态。默认 false。*/
  selected?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  avatarKey: null,
  name: '',
  size: 40,
  selected: false,
})

const failed = ref(false)
watch(() => props.avatarKey, () => { failed.value = false })

const isPresetKey = computed(() =>
  typeof props.avatarKey === 'string' && /^p\d{2}$/.test(props.avatarKey)
)

const avatarUrl = computed(() =>
  isPresetKey.value ? `/avatars/${props.avatarKey}.png` : ''
)

const sizePx = computed(() =>
  typeof props.size === 'number' ? `${props.size}px` : String(props.size)
)

const initials = computed(() => {
  const s = (props.name || '').trim()
  if (!s) return '?'
  // 中文：取首字；英文：取首字母大写
  const ch = s.charAt(0)
  return /[a-zA-Z]/.test(ch) ? ch.toUpperCase() : ch
})

// 8 色调色板：根据 name 长度 + char code hash 稳定挑色
const palette = [
  '#fde68a', '#fecaca', '#bbf7d0', '#bfdbfe',
  '#ddd6fe', '#fbcfe8', '#fed7aa', '#e2e8f0',
]
const fallbackBg = computed(() => {
  const s = props.name || ''
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return palette[Math.abs(h) % palette.length]
})

function onImgError() {
  failed.value = true
}
</script>

<template>
  <span
    class="persona-avatar"
    :style="{ width: sizePx, height: sizePx }"
    :class="{ selected }"
  >
    <img
      v-if="avatarUrl && !failed"
      :src="avatarUrl"
      :alt="name || avatarKey || 'avatar'"
      class="avatar-img"
      @error="onImgError"
    />
    <span
      v-else
      class="avatar-initials"
      :style="{ background: fallbackBg, fontSize: `calc(${sizePx} * 0.42)` }"
    >
      {{ initials }}
    </span>
    <span v-if="selected" class="dot" />
  </span>
</template>

<style scoped lang="scss">
.persona-avatar {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: visible;
  background: #f5f5f4;
  flex-shrink: 0;
  border: 1px solid rgba(0, 0, 0, 0.06);
  box-sizing: border-box;
  user-select: none;

  &.selected {
    border-color: #4f46e5;
    box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.15);
  }
}

.avatar-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  display: block;
}

.avatar-initials {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #2c2b29;
  font-weight: 600;
  letter-spacing: 0;
  line-height: 1;
}

.dot {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #4f46e5;
  border: 2px solid #fff;
}
</style>
