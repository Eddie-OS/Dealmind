/**
 * 全局 HTTP 客户端
 * 所有请求通过 Vite proxy 转发到后端（dev: 127.0.0.1:8000）
 * 统一处理：超时、错误提示、JSON 解析
 *
 * 自定义配置：
 *   silent: true   ─ 该请求出错时不弹 ElMessage（用于周期性轮询，如 /health）
 */
import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, clearLogin } from '@/router'

declare module 'axios' {
  // 让 TS 知道 config 上可以挂 silent 字段
  export interface AxiosRequestConfig {
    silent?: boolean
  }
  export interface InternalAxiosRequestConfig {
    silent?: boolean
  }
}

export const http: AxiosInstance = axios.create({
  baseURL: '/',
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
})

// 每个请求自动带上登录 token
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError<{ detail?: string | { msg: string }[] }>) => {
    const cfg = (error.config || {}) as InternalAxiosRequestConfig
    const silent = cfg.silent === true
    const status = error.response?.status
    let msg = '请求失败，请稍后重试'

    // 未授权 / 登录失效：清掉本地 token 并踢回登录页
    if (status === 401) {
      clearLogin()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login')
      }
      if (!silent) ElMessage.error('登录已失效，请重新登录')
      return Promise.reject(error)
    }

    if (error.code === 'ECONNABORTED') {
      msg = '请求超时，请检查网络或稍后重试'
    } else if (status === 0 || error.code === 'ERR_NETWORK') {
      msg = '无法连接后端服务，请确认 uvicorn 已启动（127.0.0.1:8000）'
    } else if (status && status >= 500) {
      msg = `服务端错误 (${status})`
    } else if (status && status >= 400) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') msg = detail
      else if (Array.isArray(detail) && detail[0]?.msg) msg = detail[0].msg
      else msg = `请求错误 (${status})`
    }

    if (!silent) ElMessage.error(msg)
    return Promise.reject(error)
  },
)
