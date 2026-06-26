import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const AUTH_KEY = 'dm_logged_in'

export function isLoggedIn(): boolean {
  return localStorage.getItem(AUTH_KEY) === '1'
}

export function setLoggedIn(): void {
  localStorage.setItem(AUTH_KEY, '1')
}

export function clearLogin(): void {
  localStorage.removeItem(AUTH_KEY)
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { layout: 'blank' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppShell.vue'),
    children: [
      {
        path: '',
        name: 'home',
        component: () => import('@/views/placeholder/HomeView.vue'),
        meta: { title: '首页总览', group: 'simulation' },
      },
      {
        path: 'simulation/new',
        name: 'simulation-new',
        component: () => import('@/views/simulation/NewSession.vue'),
        meta: { title: '新建对话', group: 'simulation' },
      },
      {
        path: 'simulation/live',
        name: 'simulation-live',
        redirect: '/simulation/new',
        meta: { title: '对话现场', group: 'simulation' },
      },
      {
        path: 'simulation/live/:id',
        name: 'simulation-live-detail',
        component: () => import('@/views/simulation/LiveSession.vue'),
        meta: { title: '对话现场', group: 'simulation' },
      },
      {
        path: 'simulation/history',
        name: 'simulation-history',
        component: () => import('@/views/simulation/SessionHistory.vue'),
        meta: { title: '会话历史', group: 'simulation' },
      },
      {
        path: 'simulation/detail/:id',
        name: 'simulation-detail',
        component: () => import('@/views/simulation/SessionDetail.vue'),
        meta: { title: '会话复盘', group: 'simulation' },
      },
      {
        // 会话复盘入口（无 id 时回到历史选一条）
        path: 'simulation/review',
        name: 'simulation-review',
        redirect: '/simulation/history',
        meta: { title: '会话复盘', group: 'simulation' },
      },
      {
        path: 'batch/run',
        name: 'batch-run',
        component: () => import('@/views/scale/BatchTest.vue'),
        meta: { title: '批量测试', group: 'batch' },
      },
      {
        path: 'batch/report',
        name: 'batch-report',
        component: () => import('@/views/scale/BatchReport.vue'),
        meta: { title: '批量报告', group: 'batch' },
      },
      {
        path: 'batch/analysis',
        name: 'batch-analysis',
        component: () => import('@/views/scale/AnalysisReport.vue'),
        meta: { title: '分析报告', group: 'batch' },
      },
      {
        path: 'kb/personas',
        name: 'kb-personas',
        component: () => import('@/views/assets/PersonaLibrary.vue'),
        meta: { title: 'Persona 人设库', group: 'kb' },
      },
      {
        path: 'kb/product',
        name: 'kb-product',
        component: () => import('@/views/assets/ProductKB.vue'),
        meta: { title: '产品知识库', group: 'kb' },
      },
      {
        path: 'kb/handbooks',
        name: 'kb-handbooks',
        component: () => import('@/views/assets/HandbookManager.vue'),
        meta: { title: '产品手册', group: 'kb' },
      },
      {
        path: 'kb/enterprise',
        name: 'kb-enterprise',
        component: () => import('@/views/assets/EnterpriseKB.vue'),
        meta: { title: '企业知识库', group: 'kb' },
      },
      {
        path: 'kb/cases',
        name: 'kb-cases',
        component: () => import('@/views/assets/SalesCases.vue'),
        meta: { title: '销售案例集', group: 'kb' },
      },
      {
        path: 'kb/excellent-phrases',
        name: 'kb-excellent-phrases',
        component: () => import('@/views/assets/ExcellentPhrases.vue'),
        meta: { title: '优秀话术库', group: 'kb' },
      },
      {
        path: 'kb/sales-agent',
        name: 'kb-sales-agent',
        component: () => import('@/views/assets/SalesAgent.vue'),
        meta: { title: '销冠 Agent', group: 'kb' },
      },
      {
        path: 'settings/model',
        name: 'settings-model',
        component: () => import('@/views/system/ModelSettings.vue'),
        meta: { title: '模型设置', group: 'settings' },
      },
      {
        path: 'settings/vector',
        name: 'settings-vector',
        component: () => import('@/views/system/VectorAdmin.vue'),
        meta: { title: '向量库管理', group: 'settings' },
      },
      {
        path: 'settings/status',
        name: 'settings-status',
        component: () => import('@/views/system/RunningStatus.vue'),
        meta: { title: '运行状态', group: 'settings' },
      },
      {
        path: 'settings/skills',
        name: 'settings-skills',
        component: () => import('@/views/system/AgentSkills.vue'),
        meta: { title: '销冠技能', group: 'settings' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (to.name === 'login') {
    // 已登录时访问 /login → 直接跳首页
    if (isLoggedIn()) return next({ name: 'home', replace: true })
    return next()
  }
  // 未登录访问任何其他页面 → 跳登录页
  if (!isLoggedIn()) return next({ name: 'login', replace: true })
  next()
})

export default router
