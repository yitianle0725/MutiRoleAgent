// 后端 API 封装：SSE 流式聊天客户端
// 用 fetch + ReadableStream 手动解析 SSE（比 EventSource 灵活：支持 POST、可选诊断）

import type { StructuredPayload } from './features/StructuredCards'

export interface ChatPayload {
  query: string
  session_id?: string
  persona?: string
  user_id?: string
}

export interface ToolEventData {
  phase: 'start' | 'end'
  tool_name: string
  tool_args?: Record<string, unknown>
  result_preview?: string
}

export interface StreamHandlers {
  onChunk: (text: string) => void
  onTool?: (tool: ToolEventData) => void
  onStructured?: (data: StructuredPayload) => void
  onDone: () => void
  onError: (message: string) => void
}

/** 发起 SSE 流式聊天，逐事件回调。 */
export async function streamChat(
  payload: ChatPayload,
  handlers: StreamHandlers,
): Promise<void> {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* 非 JSON 错误 */
    }
    handlers.onError(detail)
    return
  }

  if (!resp.body) {
    handlers.onError('浏览器不支持流式响应')
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      // 剥离所有 \r：兼容 CRLF（Windows sse-starlette）与 LF 两种事件分隔
      // （SSE 的 data 中不应出现裸 CR，去掉是安全的）
      buf += decoder.decode(value, { stream: true }).replace(/\r/g, '')

      // SSE 块以空行分隔：每块可能含 event:xxx 与 data:xxx 行
      const blocks = buf.split('\n\n')
      buf = blocks.pop() ?? ''
      for (const block of blocks) {
        handleSseBlock(block, handlers)
      }
    }
    // 剩余残块
    if (buf.trim()) handleSseBlock(buf, handlers)
  } catch (err) {
    handlers.onError(err instanceof Error ? err.message : String(err))
  }
}

function handleSseBlock(block: string, handlers: StreamHandlers): void {
  let event = 'chunk'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5)
  }

  switch (event) {
    case 'chunk':
      // 空 chunk 无意义，跳过；但 done/error 即使 data 为空也必须处理
      if (data) handlers.onChunk(data)
      break
    case 'tool':
      try {
        handlers.onTool?.(JSON.parse(data) as ToolEventData)
      } catch {
        /* 忽略解析失败的工具事件 */
      }
      break
    case 'structured':
      try {
        const parsed = JSON.parse(data) as StructuredPayload
        handlers.onStructured?.(parsed)
      } catch {
        // 兜底：解析失败时把原文当 markdown 渲染
        handlers.onStructured?.({
          schema_type: 'unknown',
          raw_json: {},
          formatted: data,
        })
      }
      break
    case 'done':
      handlers.onDone()
      break
    case 'error':
      handlers.onError(data || '未知错误')
      break
    default:
      break
  }
}

// ==================== 会话 / 角色 / 配置 ====================

export interface SessionItem {
  session_id: string
  title: string
  user_id?: string
  message_count?: number
  updated_at?: string
}

export interface HistoryItem {
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}

export async function listSessions(): Promise<SessionItem[]> {
  const data = await requestJson<{ sessions?: SessionItem[] }>('/api/sessions')
  return data.sessions ?? []
}

export async function createSession(): Promise<string> {
  const data = await requestJson<{ session_id: string }>('/api/sessions', { method: 'POST' })
  return data.session_id
}

export async function getSessionHistory(sessionId: string): Promise<HistoryItem[]> {
  const data = await requestJson<{ history?: HistoryItem[] }>(
    `/api/sessions/${encodeURIComponent(sessionId)}/history`,
  )
  return data.history ?? []
}

export async function deleteSession(sessionId: string): Promise<void> {
  await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export async function listPersonas(): Promise<string[]> {
  const data = await requestJson<{ names?: string[] }>('/api/personas')
  return data.names ?? []
}

export interface AppConfig {
  llm?: { model?: string; base_url?: string }
  embedding?: { mode?: string }
  voice?: { enabled?: boolean; tts_model?: string; tts_voice?: string; asr_model?: string }
  store?: { session?: string; db?: string }
  agent?: { max_steps?: number | null; personas?: string[] }
}

export async function getConfig(): Promise<AppConfig> {
  return await requestJson<AppConfig>('/api/config')
}

/** 通用 JSON 请求（GET/POST/PATCH/DELETE），支持泛型返回值。 */
async function requestJson<T = Record<string, unknown>>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(url, options)
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return (await resp.json()) as T
}
