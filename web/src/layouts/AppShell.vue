<script setup lang="ts">
/**
 * App 主框架
 * 严格对齐 design/DESIGN_SYSTEM.md §8.2
 * 左侧 220px 导航（4 大板块分组）+ 顶部 64px Header + 主内容区
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTooltip, ElDropdown, ElDropdownMenu, ElDropdownItem } from 'element-plus'
import {
  Brain,
  Home,
  MessageSquarePlus,
  MessageCircle,
  History,
  BarChart3,
  Layers,
  FileBarChart,
  Microscope,
  BookText,
  Users,
  Box,
  Building2,
  BookOpen,
  Sparkles,
  Settings,
  Database,
  Activity,
  Wrench,
  Bell,
  ChevronDown,
  Search,
  User,
  LogOut,
} from '@lucide/vue'
import { statusApi } from '@/api/status'
import { clearLogin } from '@/router'
import brandMark from '@/assets/dealmind-mark.png'

type NavItem = {
  to: string
  label: string
  icon: any
}
type NavGroup = {
  id: string
  title: string
  items: NavItem[]
}

const groups: NavGroup[] = [
  {
    id: 'simulation',
    title: '模拟运营',
    items: [
      { to: '/', label: '首页总览', icon: Home },
      { to: '/simulation/new', label: '新建对话', icon: MessageSquarePlus },
      { to: '/simulation/live', label: '对话现场', icon: MessageCircle },
      { to: '/simulation/history', label: '会话历史', icon: History },
      { to: '/simulation/review', label: '会话复盘', icon: BarChart3 },
    ],
  },
  {
    id: 'batch',
    title: '规模化测试',
    items: [
      { to: '/batch/run', label: '批量测试', icon: Layers },
      { to: '/batch/report', label: '批量报告', icon: FileBarChart },
      { to: '/batch/analysis', label: '分析报告', icon: Microscope },
    ],
  },
  {
    id: 'kb',
    title: '知识与资产',
    items: [
      { to: '/kb/sales-agent', label: '销冠 Agent', icon: Brain },
      { to: '/kb/personas', label: 'Persona 人设库', icon: Users },
      { to: '/kb/product', label: '产品知识库', icon: Box },
      { to: '/kb/handbooks', label: '产品手册', icon: BookText },
      { to: '/kb/enterprise', label: '企业知识库', icon: Building2 },
      { to: '/kb/cases', label: '销售案例集', icon: BookOpen },
      { to: '/kb/excellent-phrases', label: '优秀话术库', icon: Sparkles },
    ],
  },
  {
    id: 'settings',
    title: '系统设置',
    items: [
      { to: '/settings/model', label: '模型设置', icon: Settings },
      { to: '/settings/skills', label: '销冠技能', icon: Wrench },
      { to: '/settings/vector', label: '向量库管理', icon: Database },
      { to: '/settings/status', label: '运行状态', icon: Activity },
    ],
  },
]

const route = useRoute()
const router = useRouter()

const currentPath = computed(() => route.path)

function isActive(to: string) {
  if (to === '/') return currentPath.value === '/'
  return currentPath.value === to || currentPath.value.startsWith(to + '/')
}

// ============================================================
// Stage 12：右上角后端健康状态灯（10s 轮询 /health）
// ============================================================
type HealthState = 'unknown' | 'ok' | 'down'
const health = ref<HealthState>('unknown')
const healthTip = ref<string>('正在检查后端连接…')
const healthLastOkAt = ref<string>('')
let healthTimer: ReturnType<typeof setInterval> | null = null

async function checkHealth() {
  try {
    const r = await statusApi.health()
    health.value = 'ok'
    healthLastOkAt.value = r.time || new Date().toISOString()
    healthTip.value = `后端正常 · ${r.service} v${r.version}`
  } catch {
    health.value = 'down'
    healthTip.value = healthLastOkAt.value
      ? `后端连接失败 · 最近一次正常 ${healthLastOkAt.value.slice(11, 19)}`
      : '后端连接失败 · 请确认 uvicorn 已启动 (127.0.0.1:8000)'
  }
}

onMounted(() => {
  checkHealth()
  healthTimer = setInterval(checkHealth, 10_000)
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
})

function goStatusPage() {
  router.push('/settings/status')
}

function go(to: string) {
  if (to !== currentPath.value) router.push(to)
}

function handleUserCommand(command: string) {
  if (command === 'logout') {
    clearLogin()
    router.push('/login')
  }
  // 'profile' 暂占位，不做
}
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand" @click="go('/')">
        <img :src="brandMark" class="brand-icon" alt="DealMind" />
        <div class="brand-text">
          <div class="brand-name">DealMind</div>
          <div class="brand-sub">Sales Sim Engine</div>
        </div>
      </div>

      <nav class="nav">
        <div v-for="g in groups" :key="g.id" class="nav-group">
          <div class="group-title dm-text-overline">{{ g.title }}</div>
          <button
            v-for="item in g.items"
            :key="item.to"
            class="nav-item"
            :class="{ active: isActive(item.to) }"
            @click="go(item.to)"
          >
            <component :is="item.icon" :size="18" :stroke-width="1.6" class="nav-icon" />
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="logo-card">
          <img :src="brandMark" class="logo-card-mark" alt="DealMind" />
          <span>DealMind</span>
        </div>
        <div class="version">v 1.0.0</div>
      </div>
    </aside>

    <div class="main">
      <header class="header">
        <div class="header-left">
          <button class="workspace-switch">
            <span class="ws-name">默认工作区</span>
            <ChevronDown :size="16" :stroke-width="1.6" />
          </button>
        </div>
        <div class="header-right">
          <ElTooltip :content="healthTip" placement="bottom">
            <button
              class="health-btn"
              :class="{
                'is-ok': health === 'ok',
                'is-down': health === 'down',
                'is-unknown': health === 'unknown',
              }"
              aria-label="后端健康状态"
              @click="goStatusPage"
            >
              <span class="health-dot" />
              <span class="health-text">
                {{
                  health === 'ok'
                    ? '后端正常'
                    : health === 'down'
                    ? '后端不可用'
                    : '检测中'
                }}
              </span>
            </button>
          </ElTooltip>
          <button class="icon-btn" aria-label="搜索">
            <Search :size="18" :stroke-width="1.6" />
          </button>
          <button class="icon-btn" aria-label="通知">
            <Bell :size="18" :stroke-width="1.6" />
          </button>
          <ElDropdown trigger="click" @command="handleUserCommand">
            <button class="user">
              <span class="avatar">A</span>
              <span class="user-name">admin</span>
              <ChevronDown :size="14" :stroke-width="1.6" />
            </button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem command="profile">
                  <User :size="15" :stroke-width="1.6" class="menu-icon" />
                  个人中心
                </ElDropdownItem>
                <ElDropdownItem command="logout" divided>
                  <LogOut :size="15" :stroke-width="1.6" class="menu-icon" />
                  退出登录
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </header>

      <main class="content">
        <div class="content-inner">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped lang="scss">
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--dm-bg);
}

/* ===== Sidebar ===== */
.sidebar {
  flex: 0 0 var(--dm-sidebar-w);
  width: var(--dm-sidebar-w);
  background: var(--dm-bg-sidebar);
  display: flex;
  flex-direction: column;
  padding: 0;
  position: sticky;
  top: 0;
  height: 100vh;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: var(--dm-header-h);
  padding: 0 20px;
  cursor: pointer;
  user-select: none;
}
.brand-icon {
  height: 22px;
  width: auto;
  object-fit: contain;
  display: block;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.1;
}
.brand-name {
  font-size: 16px;
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
  letter-spacing: -0.01em;
}
.brand-sub {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  margin-top: 2px;
}

.nav {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 4px 8px 16px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.group-title {
  padding: 8px 12px 6px;
  color: var(--dm-text-muted);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  padding: 0 12px;
  border: none;
  background: transparent;
  border-radius: var(--dm-radius);
  font-size: var(--dm-fs-body);
  color: var(--dm-text);
  cursor: pointer;
  transition: background var(--dm-transition);
  text-align: left;
  font-family: inherit;
}
.nav-item:hover { background: rgba(0, 0, 0, 0.04); }
.nav-item.active {
  background: var(--dm-bg-selected);
  font-weight: var(--dm-fw-medium);
}
.nav-icon { flex-shrink: 0; color: var(--dm-text-secondary); }
.nav-item.active .nav-icon { color: var(--dm-text); }
.nav-label { flex: 1 1 auto; }

.sidebar-footer {
  flex: 0 0 auto;
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.logo-card {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--dm-radius);
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  font-size: var(--dm-fs-caption);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
  width: fit-content;
}
.logo-card-mark {
  height: 14px;
  width: auto;
  object-fit: contain;
  display: block;
}
.version {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  padding-left: 4px;
}

/* ===== Main ===== */
.main {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.header {
  flex: 0 0 var(--dm-header-h);
  height: var(--dm-header-h);
  background: var(--dm-bg-card);
  border-bottom: 1px solid var(--dm-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workspace-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  font-family: inherit;
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
  cursor: pointer;
  padding: 6px 10px;
  border-radius: var(--dm-radius);
}
.workspace-switch:hover { background: var(--dm-bg-muted); }

.icon-btn {
  position: relative;
  width: 32px;
  height: 32px;
  border-radius: var(--dm-radius);
  border: none;
  background: transparent;
  color: var(--dm-text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background var(--dm-transition);
}
.icon-btn:hover { background: var(--dm-bg-muted); color: var(--dm-text); }
.has-dot .dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  background: var(--dm-danger);
  border-radius: var(--dm-radius-full);
}

/* Stage 12：后端健康状态灯 */
.health-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--dm-border);
  background: var(--dm-bg);
  border-radius: 999px;
  font-size: 12px;
  color: var(--dm-text-secondary);
  cursor: pointer;
  transition: background var(--dm-transition), border-color var(--dm-transition);
}
.health-btn:hover { background: var(--dm-bg-muted); }
.health-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--dm-radius-full);
  background: #94a3b8;
  box-shadow: 0 0 0 0 rgba(0,0,0,0);
}
.health-btn.is-ok .health-dot {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.15);
}
.health-btn.is-down .health-dot {
  background: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18);
  animation: dm-blink 1.4s ease-in-out infinite;
}
.health-btn.is-down {
  border-color: rgba(239, 68, 68, 0.4);
  color: #b91c1c;
}
.health-btn.is-ok { color: #047857; }
.health-text {
  font-variant-numeric: tabular-nums;
}
@keyframes dm-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  font-family: inherit;
  padding: 4px 8px 4px 4px;
  border-radius: var(--dm-radius);
  cursor: pointer;
  color: var(--dm-text);
}
.user:hover { background: var(--dm-bg-muted); }
.avatar {
  width: 28px;
  height: 28px;
  border-radius: var(--dm-radius-full);
  background: var(--dm-bg-inverse);
  color: var(--dm-text-inverse);
  font-size: var(--dm-fs-caption);
  font-weight: var(--dm-fw-semibold);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.user-name {
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
}
.menu-icon {
  margin-right: 8px;
  vertical-align: -2px;
}

/* ===== Content ===== */
.content {
  flex: 1 1 auto;
  overflow-y: auto;
}
.content-inner {
  max-width: var(--dm-content-max);
  margin: 0 auto;
  padding: 32px;
}
</style>
