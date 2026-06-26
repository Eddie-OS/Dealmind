<script setup lang="ts">
/**
 * 登录页（ref_01）
 * 严格对齐 design/DESIGN_SYSTEM.md §8.1
 * Stage 0：仅 UI，无鉴权。两个按钮都直接跳首页（D5 单人本地）
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Mail, Lock, Eye, EyeOff, FolderOpen } from '@lucide/vue'
import loginIllustration from '@/assets/login-illustration.png'
import brandMark from '@/assets/dealmind-mark.png'
import { setLoggedIn } from '@/router'

const router = useRouter()

const activeTab = ref<'login' | 'local'>('login')
const email = ref('')
const password = ref('')
const showPassword = ref(false)

function handleLogin() {
  if (!email.value || !password.value) {
    ElMessage.warning('请输入邮箱和密码')
    return
  }
  setLoggedIn()
  router.push('/')
}

function enterWorkspace() {
  setLoggedIn()
  router.push('/')
}
</script>

<template>
  <div class="login-page">
    <header class="login-header">
      <div class="brand">
        <img :src="brandMark" class="brand-icon" alt="DealMind" />
        <div class="brand-text">
          <div class="brand-name">DealMind</div>
          <div class="brand-sub">Sales Simulation Engine</div>
        </div>
      </div>
    </header>

    <main class="login-main">
      <section class="login-left">
        <h1 class="welcome-title">欢迎回来，多人设销冠压力测试引擎</h1>
        <p class="welcome-desc">
          登录并进入你的工作区，管理压力测试模拟，<br />
          沉淀销售知识与资产，驱动团队持续成长。
        </p>
        <div class="illustration-wrap">
          <img
            :src="loginIllustration"
            alt="DealMind 协作插画"
            class="illustration"
            draggable="false"
          />
        </div>
      </section>

      <section class="login-right">
        <div class="login-card">
          <div class="tabs">
            <button
              class="tab"
              :class="{ active: activeTab === 'login' }"
              @click="activeTab = 'login'"
            >
              登录
            </button>
            <button
              class="tab"
              :class="{ active: activeTab === 'local' }"
              @click="activeTab = 'local'"
            >
              本地模式
            </button>
          </div>

          <div v-if="activeTab === 'login'" class="form">
            <div class="field">
              <label>邮箱</label>
              <el-input
                v-model="email"
                placeholder="请输入邮箱..."
                size="large"
              >
                <template #prefix>
                  <Mail :size="16" :stroke-width="1.6" />
                </template>
              </el-input>
            </div>

            <div class="field">
              <label>密码</label>
              <el-input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                placeholder="请输入密码..."
                size="large"
                @keyup.enter="handleLogin"
              >
                <template #prefix>
                  <Lock :size="16" :stroke-width="1.6" />
                </template>
                <template #suffix>
                  <component
                    :is="showPassword ? EyeOff : Eye"
                    :size="16"
                    :stroke-width="1.6"
                    class="eye-toggle"
                    @click="showPassword = !showPassword"
                  />
                </template>
              </el-input>
              <div class="forgot">
                <a href="javascript:void(0)">忘记密码？</a>
              </div>
            </div>

            <el-button
              type="primary"
              size="large"
              class="login-btn"
              @click="handleLogin"
            >
              登录
            </el-button>
          </div>

          <div v-else class="form local-form">
            <p class="local-tip">
              本地模式：使用本机配置的 LLM 与本地数据，无需账号即可直接开始。
            </p>
          </div>

          <div class="divider">
            <span class="line" />
            <span class="or">或</span>
            <span class="line" />
          </div>

          <el-button
            size="large"
            class="workspace-btn"
            @click="enterWorkspace"
          >
            <FolderOpen :size="18" :stroke-width="1.6" class="btn-icon" />
            进入工作区
          </el-button>
        </div>
      </section>
    </main>

    <footer class="login-footer">
      <span>© 2024 DealMind. 保留所有权利.</span>
      <span>版本 1.0.0</span>
    </footer>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  min-height: 100vh;
  background: var(--dm-bg);
  display: flex;
  flex-direction: column;
  padding: 24px 48px;
}

/* ===== Header ===== */
.login-header {
  flex: 0 0 auto;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.brand-icon {
  height: 26px;
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
  font-size: 22px;
  font-weight: var(--dm-fw-bold);
  letter-spacing: -0.01em;
  color: var(--dm-text);
}
.brand-sub {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  margin-top: 2px;
}

/* ===== Main ===== */
.login-main {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 64px;
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 0;
}

.login-left {
  flex: 1 1 0;
  min-width: 0;
  max-width: 600px;
}
.welcome-title {
  font-size: 30px;
  line-height: 40px;
  font-weight: var(--dm-fw-bold);
  color: var(--dm-text);
  margin: 0 0 12px;
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.welcome-desc {
  font-size: var(--dm-fs-body);
  line-height: var(--dm-lh-body);
  color: var(--dm-text-muted);
  margin: 0 0 32px;
}
.illustration-wrap {
  width: 100%;
  max-width: 560px;
}
.illustration {
  width: 100%;
  height: auto;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
  /* 插画背景已透明（墨线稿），直接漂浮在页面背景上，无矩形边界 */
}

/* ===== Right card ===== */
.login-right {
  flex: 0 0 auto;
  width: var(--dm-login-card-w);
}
.login-card {
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border);
  border-radius: var(--dm-radius-xl);
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.tabs {
  display: inline-flex;
  background: var(--dm-bg-muted);
  border-radius: var(--dm-radius);
  padding: 4px;
  align-self: stretch;
}
.tab {
  flex: 1 1 0;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: 6px;
  font-size: var(--dm-fs-body);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text-muted);
  cursor: pointer;
  transition: all var(--dm-transition);
}
.tab.active {
  background: var(--dm-bg-card);
  color: var(--dm-text);
  box-shadow: var(--dm-shadow-xs);
}

.form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field label {
  font-size: var(--dm-fs-caption);
  font-weight: var(--dm-fw-medium);
  color: var(--dm-text);
}
.eye-toggle {
  cursor: pointer;
  color: var(--dm-text-muted);
}
.eye-toggle:hover { color: var(--dm-text); }

.forgot {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}
.forgot a {
  font-size: var(--dm-fs-caption);
  color: var(--dm-text-muted);
}
.forgot a:hover { color: var(--dm-text); }

.login-btn {
  width: 100%;
  height: 44px;
  font-size: var(--dm-fs-body);
}

.local-form {
  min-height: 152px;
  justify-content: center;
}
.local-tip {
  font-size: var(--dm-fs-caption);
  color: var(--dm-text-secondary);
  line-height: var(--dm-lh-caption);
  margin: 0;
}

.divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 4px 0;
}
.divider .line {
  flex: 1 1 0;
  height: 1px;
  background: var(--dm-border);
}
.divider .or {
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
}

.workspace-btn {
  width: 100%;
  height: 44px;
  background: var(--dm-bg-card);
  border: 1px solid var(--dm-border-strong);
  color: var(--dm-text);
  font-size: var(--dm-fs-body);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.workspace-btn:hover {
  background: var(--dm-bg-elevated);
}
.btn-icon { display: inline-flex; }

/* ===== Footer ===== */
.login-footer {
  flex: 0 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--dm-fs-small);
  color: var(--dm-text-muted);
  padding-top: 16px;
}

/* ===== 响应式：小屏堆叠 ===== */
@media (max-width: 960px) {
  .login-main {
    flex-direction: column;
    gap: 40px;
  }
  .login-right { width: 100%; max-width: 480px; }
}
</style>
