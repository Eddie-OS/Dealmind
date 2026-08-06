/**
 * WebSocket 封装（Stage 6a）
 *
 * 设计：
 *   - 自动通过 Vite proxy 转发到后端（/ws/... → ws://127.0.0.1:8000/ws/...）
 *   - 简单事件分发：按 event.type 注册 handler
 *   - 重连策略：仅在异常关闭时自动重连（最多 3 次，指数退避）；正常关闭（session_end → 后端关）不重连
 *   - 支持发送下行消息（cancel / ping）
 *
 * 事件协议与后端 src/session.py 的 EVENT_* 严格对齐。
 */

export type WsEvent = {
  type: string
  data: Record<string, any>
}

export type WsHandler = (evt: WsEvent) => void

export interface WsClientOptions {
  /** 当 close code 在该集合中时不重连（正常完成）。默认 [1000, 1008] */
  noReconnectCodes?: number[]
  /** 最大重连次数。默认 3 */
  maxReconnect?: number
  /** 是否打 console.log。默认 false */
  debug?: boolean
}

export class WsClient {
  private ws: WebSocket | null = null
  private url: string
  private handlers = new Set<WsHandler>()
  private reconnectAttempts = 0
  private maxReconnect: number
  private noReconnectCodes: Set<number>
  private debug: boolean
  private manualClose = false

  constructor(path: string, opts: WsClientOptions = {}) {
    this.url = this.buildUrl(path)
    this.maxReconnect = opts.maxReconnect ?? 3
    this.noReconnectCodes = new Set(opts.noReconnectCodes ?? [1000, 1008])
    this.debug = opts.debug ?? false
  }

  /** 把 /ws/... 路径转完整 ws/wss URL，走 location 同源（vite proxy 兜底）*/
  private buildUrl(path: string): string {
    if (path.startsWith('ws://') || path.startsWith('wss://')) return path
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host // 含 port，例如 127.0.0.1:5173
    const p = path.startsWith('/') ? path : `/${path}`
    // WebSocket 无法设置 header，登录 token 通过查询参数传给后端鉴权中间件
    const token = sessionStorage.getItem('dm_token')
    const auth = token
      ? `${p.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : ''
    return `${proto}//${host}${p}${auth}`
  }

  on(handler: WsHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING
                   || this.ws.readyState === WebSocket.OPEN)) {
      return
    }
    this.log('connecting', this.url)
    this.ws = new WebSocket(this.url)
    this.ws.onopen = () => {
      this.log('open')
      this.reconnectAttempts = 0
    }
    this.ws.onmessage = (e) => {
      let evt: WsEvent
      try {
        evt = JSON.parse(e.data) as WsEvent
      } catch (err) {
        this.log('parse error', err, e.data)
        return
      }
      for (const h of this.handlers) {
        try { h(evt) } catch (err) { this.log('handler error', err) }
      }
    }
    this.ws.onerror = (e) => this.log('error', e)
    this.ws.onclose = (e) => {
      this.log(`close code=${e.code} reason=${JSON.stringify(e.reason)} clean=${e.wasClean}`)
      this.ws = null
      if (this.manualClose) return
      if (this.noReconnectCodes.has(e.code)) return
      if (this.reconnectAttempts >= this.maxReconnect) return
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 8000)
      this.reconnectAttempts += 1
      this.log(`reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnect})`)
      setTimeout(() => this.connect(), delay)
    }
  }

  send(msg: Record<string, any>): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false
    this.ws.send(JSON.stringify(msg))
    return true
  }

  /** 主动关闭，不再重连。 */
  close(): void {
    this.manualClose = true
    try { this.ws?.close(1000, 'client_close') } catch { /* ignore */ }
    this.ws = null
  }

  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED
  }

  private log(...args: any[]): void {
    if (this.debug) console.log('[ws]', ...args)
  }
}
