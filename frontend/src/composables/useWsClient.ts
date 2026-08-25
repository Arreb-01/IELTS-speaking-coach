/** 练习 WebSocket 客户端：JSON 控制帧 + 二进制音频帧，自动重连。 */

import { ref } from 'vue'

import { getReconnectTicket } from '@/api/practice'

export type ServerMessage = Record<string, unknown> & { type: string }

export interface WsClientOptions {
  onMessage: (msg: ServerMessage) => void
  onReconnecting?: () => void
  onFatal?: (reason: string) => void
}

function wsBaseUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
}

export function useWsClient(options: WsClientOptions) {
  const connected = ref(false)
  const reconnecting = ref(false)

  let ws: WebSocket | null = null
  let sessionId = ''
  let manuallyClosed = false
  let attempts = 0
  let reconnectTimer: number | null = null

  function connect(path: string, sid: string): void {
    sessionId = sid
    manuallyClosed = false
    open(`${wsBaseUrl()}${path}`)
  }

  function open(url: string): void {
    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    ws.onopen = () => {
      connected.value = true
      reconnecting.value = false
      attempts = 0
    }
    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return
      try {
        options.onMessage(JSON.parse(event.data) as ServerMessage)
      } catch {
        /* 忽略非法帧 */
      }
    }
    ws.onclose = () => {
      connected.value = false
      if (!manuallyClosed) {
        void scheduleReconnect()
      }
    }
    ws.onerror = () => {
      /* onclose 会跟进 */
    }
  }

  async function scheduleReconnect(): Promise<void> {
    if (attempts >= 3) {
      options.onFatal?.('连接已断开，请返回重新开始练习')
      return
    }
    attempts += 1
    reconnecting.value = true
    options.onReconnecting?.()
    const delay = Math.min(1000 * 2 ** (attempts - 1), 5000)
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = window.setTimeout(async () => {
      try {
        const ticket = await getReconnectTicket(sessionId)
        open(`${wsBaseUrl()}${ticket.ws_path}`)
      } catch {
        await scheduleReconnect()
      }
    }, delay)
  }

  function send(payload: Record<string, unknown>): void {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
    }
  }

  function sendPcm(buffer: ArrayBuffer): void {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(buffer)
    }
  }

  function close(): void {
    manuallyClosed = true
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    reconnecting.value = false
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    connected.value = false
  }

  return { connected, reconnecting, connect, send, sendPcm, close }
}
