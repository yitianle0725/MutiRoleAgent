// 后端 API 封装：SSE 流式聊天客户端
// 用 fetch + ReadableStream 手动解析 SSE（比 EventSource 灵活：支持 POST、可选诊断）

import type { StructuredPayload } from './features/StructuredCards'

export interface ChatPayload {
  message: string
  session_id: string
}

interface HarnessEnvelope<T extends string, D> {
  version: 1
  type: T
  run_id: string
  sequence: number
  data: D
}

export type HarnessEvent =
  | HarnessEnvelope<'run_start', { session_id: string }>
  | HarnessEnvelope<'process_text', { text: string; delta: boolean }>
  | HarnessEnvelope<'tool_start', {
      tool_call_id: string
      tool_name: string
      tool_args: Record<string, unknown>
    }>
  | HarnessEnvelope<'tool_end', {
      tool_call_id: string
      tool_name: string
      status: 'completed' | 'failed'
      result_preview: string
      duration_ms?: number
    }>
  | HarnessEnvelope<'structured_data', StructuredPayload>
  | HarnessEnvelope<'final_text', { text: string; delta: boolean }>
  | HarnessEnvelope<'run_end', {
      status: 'completed' | 'failed' | 'cancelled' | 'timeout'
      error?: string
    }>

export interface StreamHandlers {
  onEvent: (event: HarnessEvent) => void
  onTransportError: (message: string) => void
}

/** 发起 SSE 流式聊天，逐事件回调。 */
export async function streamChat(
  payload: ChatPayload,
  handlers: StreamHandlers,
): Promise<void> {
  const resp = await fetch('/api/v1/chat/stream', {
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
    handlers.onTransportError(detail)
    return
  }

  if (!resp.body) {
    handlers.onTransportError('浏览器不支持流式响应')
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
    handlers.onTransportError(err instanceof Error ? err.message : String(err))
  }
}

function handleSseBlock(block: string, handlers: StreamHandlers): void {
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('data:')) data += line.slice(5)
  }

  const parsed = parseSseJson<HarnessEvent>(data)
  if (!parsed?.type || parsed.version !== 1) {
    handlers.onTransportError('收到无法识别的 HarnessEvent')
    return
  }
  handlers.onEvent(parsed)
}

// ==================== 会话 / 角色 / 配置 ====================

function parseSseJson<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch {
    return null
  }
}

export interface SessionItem {
  session_id: string
  title: string
  user_id: string
  persona_id: string
  persona_name: string
  persona_display_name: string
  mode: 'chat' | 'work'
  message_count?: number
  updated_at?: string
}

export interface HistoryItem {
  role: 'user' | 'assistant'
  content: string
  created_at?: string
}

export async function listSessions(): Promise<SessionItem[]> {
  return await requestJson<SessionItem[]>('/api/v1/sessions')
}

export async function createSession(input: {
  user_id: string
  persona_id: string
  mode: 'chat' | 'work'
}): Promise<SessionItem> {
  return await requestJson<SessionItem>('/api/v1/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function getSessionHistory(sessionId: string): Promise<HistoryItem[]> {
  const data = await requestJson<{ messages?: HistoryItem[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
  )
  return data.messages ?? []
}

export async function getSession(sessionId: string): Promise<SessionItem & { messages: HistoryItem[] }> {
  return await requestJson<SessionItem & { messages: HistoryItem[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
  )
}

export async function deleteSession(sessionId: string): Promise<void> {
  await requestJson(`/api/v1/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export interface PersonaItem {
  persona_id: string
  name: string
  display_name: string
}

export async function listPersonas(): Promise<PersonaItem[]> {
  const data = await requestJson<{ personas?: PersonaItem[] }>('/api/v1/personas')
  return data.personas ?? []
}

export interface SessionMonitor {
  total_turns: number
  input_tokens: number
  output_tokens: number
  tool_calls: number
  execution_steps: number
  llm_duration_ms: number
  tool_duration_ms: number
  average_duration_ms: number | null
  average_ttft_ms: number | null
  output_tokens_per_second: number | null
  cache_hit_rate: number | null
}

export async function getSessionMonitor(sessionId: string): Promise<SessionMonitor> {
  return await requestJson<SessionMonitor>(
    `/api/v1/monitor/sessions/${encodeURIComponent(sessionId)}`,
  )
}

export interface AppConfig {
  llm?: { model?: string; base_url?: string }
  embedding?: { mode?: string }
  voice?: { enabled?: boolean; tts_model?: string; tts_voice?: string; asr_model?: string; realtime_model?: string }
  store?: { session?: string; db?: string }
  agent?: { max_steps?: number | null; personas?: string[] }
}

export async function getConfig(): Promise<AppConfig> {
  return await requestJson<AppConfig>('/api/v1/config')
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
