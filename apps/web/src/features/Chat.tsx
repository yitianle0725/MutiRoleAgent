// 聊天主界面：SSE 流式对话 + 结构化输出卡片 + 工具加载气泡 + TTS/ASR + 会话面板
import { useState, useRef, useEffect } from 'react'
import { Bubble, Sender } from '@ant-design/x'
import {
  streamChat,
  getSessionHistory,
  getSession,
  getSessionMonitor,
  listSessions,
  type SessionMonitor,
  type HarnessEvent,
  type HistoryItem,
  type SessionItem,
} from '../api'
import { getToolDisplayName } from './toolNames'
import { useSpeech } from './voice/speak'
import { useRecorder } from './voice/recorder'
import { Sidebar } from './Sidebar'
import { SettingsPanel } from './SettingsPanel'
import { AssistantAvatar, UserAvatar } from './avatars'
import { StructuredCards, type StructuredPayload } from './StructuredCards'
import './Chat.css'
import './StructuredCards.css'

/** 用户、过程、工具、结构化卡片和最终回答分别建模。 */
type ChatItem =
  | { kind: 'text'; id: string; role: 'user' | 'assistant'; content: string; time: string }
  | { kind: 'process'; id: string; content: string; run_id?: string; failed?: boolean }
  | { kind: 'tool'; id: string; run_id: string; tool_call_id: string; tool_name: string; phase: 'start' | 'end'; started_at: number; status?: 'completed' | 'failed'; duration_ms?: number }
  | { kind: 'structured'; id: string; data: StructuredPayload; time: string }

type RunActivityItem = Extract<ChatItem, { kind: 'process' } | { kind: 'tool' }>

const DEFAULT_SESSION = 'default'
const DEFAULT_SESSION_INFO: SessionItem = {
  session_id: DEFAULT_SESSION,
  title: '默认会话',
  user_id: 'local_user',
  persona_id: 'cyrene',
  persona_name: 'Cyrene',
  persona_display_name: '昔涟',
  mode: 'chat',
}

const EMPTY_MONITOR: SessionMonitor = {
  total_turns: 0,
  input_tokens: 0,
  output_tokens: 0,
  tool_calls: 0,
  execution_steps: 0,
  llm_duration_ms: 0,
  tool_duration_ms: 0,
  average_duration_ms: null,
  average_ttft_ms: null,
  output_tokens_per_second: null,
  cache_hit_rate: null,
}

/** 当前时间 → HH:MM。 */
function nowTime(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 从 SQLite 的 "YYYY-MM-DD HH:MM:SS" 中取 HH:MM。 */
function historyTime(createdAt?: string): string {
  return createdAt ? createdAt.slice(11, 16) : ''
}

/** AI 消息气泡的操作按钮：复制 + 重生成 */
function MessageActions(props: { content: string; onRegenerate: () => void }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(props.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch (err) {
      console.error('[copy] clipboard 不可用', err)
    }
  }
  return (
    <div className="msg-actions">
      <button className="msg-action-btn" onClick={handleCopy} title="复制">
        {copied ? '✓' : '📋'}
      </button>
      <button className="msg-action-btn" onClick={props.onRegenerate} title="重生成">
        🔄
      </button>
    </div>
  )
}

export function Chat() {
  const [sessionId, setSessionId] = useState(DEFAULT_SESSION)
  const [currentSession, setCurrentSession] = useState<SessionItem>(DEFAULT_SESSION_INFO)
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [asrMsg, setAsrMsg] = useState('')
  const [toolElapsed, setToolElapsed] = useState<Record<string, string>>({})
  const [monitor, setMonitor] = useState<SessionMonitor>(EMPTY_MONITOR)
  const [lastRunId, setLastRunId] = useState('')
  const { speaking, speak } = useSpeech()
  const assistantIdRef = useRef<string | null>(null)
  const draftRef = useRef('')
  const processIdRef = useRef<string | null>(null)
  const processDraftRef = useRef('')
  const { recording, begin, end, cancel } = useRecorder({
    onResult: (text) => {
      // 识别结果填入输入框（用户可确认后再发送）
      setInput(text)
      setAsrMsg(`识别到：${text}`)
    },
    onError: (msg) => setAsrMsg(msg),
  })

  const lastAssistantContent = items
    .filter((it): it is Extract<ChatItem, { kind: 'text' }> => it.kind === 'text')
    .reverse()
    .find((m) => m.role === 'assistant')?.content ?? ''
  const lastRunActivity = items.filter(
    (item): item is RunActivityItem =>
      (item.kind === 'process' || item.kind === 'tool') && item.run_id === lastRunId,
  )

  const refreshMonitor = async (id: string) => {
    try {
      setMonitor(await getSessionMonitor(id))
    } catch (err) {
      console.error('[monitor]', err)
      setMonitor(EMPTY_MONITOR)
    }
  }

  // 启动时自动恢复最近一个有消息的会话（避免每次打开页面从空白开始）
  useEffect(() => {
    void (async () => {
      try {
        const list = await listSessions()
        const recent = list.find((s) => (s.message_count ?? 0) > 0)
        if (recent) await handleSelectSession(recent)
      } catch (err) {
        console.error('[restore session]', err)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 工具调用进行中时，每秒刷新一次「耗时」文本
  useEffect(() => {
    const inflight = items.some(
      (it) => it.kind === 'tool' && it.phase === 'start',
    )
    if (!inflight) return
    const tick = () => {
      const now = Date.now()
      const next: Record<string, string> = {}
      for (const it of items) {
        if (it.kind === 'tool' && it.phase === 'start') {
          const elapsed = ((now - it.started_at) / 1000).toFixed(1)
          next[it.id] = `${elapsed}s`
        }
      }
      setToolElapsed(next)
    }
    tick()
    const handle = setInterval(tick, 200)
    return () => clearInterval(handle)
  }, [items])

  // 切换会话：重新加载历史回填
  const handleSelectSession = async (selected: SessionItem) => {
    if (busy) return
    const id = selected.session_id
    setSessionId(id)
    setCurrentSession(selected)
    setItems([])
    void refreshMonitor(id)
    try {
      const history = await getSessionHistory(id)
      const loaded: ChatItem[] = history.map((h: HistoryItem) => ({
        kind: 'text',
        id: crypto.randomUUID(),
        role: h.role === 'user' ? 'user' : 'assistant',
        content: h.content,
        time: historyTime(h.created_at),
      }))
      setItems(loaded)
    } catch (err) {
      console.error('[history]', err)
    }
  }

  const handleSend = (text: string) => {
    if (!text.trim() || busy) return
    setInput('')
    setAsrMsg('')

    // 追加用户消息
    setItems((prev) => [
      ...prev,
      {
        kind: 'text',
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        time: nowTime(),
      },
    ])

    // Final Answer 到达前不创建 Assistant 气泡，避免过程文本混入正文。
    assistantIdRef.current = null
    draftRef.current = ''
    processIdRef.current = null
    processDraftRef.current = ''
    setBusy(true)

    void streamChat(
      { message: text, session_id: sessionId },
      {
        onEvent: (event: HarnessEvent) => handleHarnessEvent(event),
        onTransportError: (message) => finishWithError(message),
      },
    )

    function handleHarnessEvent(event: HarnessEvent) {
      switch (event.type) {
        case 'run_start':
          setLastRunId(event.run_id)
          break
        case 'process_text': {
          processDraftRef.current = event.data.delta
            ? processDraftRef.current + event.data.text
            : event.data.text
          let id = processIdRef.current
          if (!id) {
            const newId = crypto.randomUUID()
            processIdRef.current = newId
            setItems((prev) => [...prev, { kind: 'process', id: newId, run_id: event.run_id, content: processDraftRef.current }])
          } else {
            setItems((prev) => prev.map((item) =>
              item.kind === 'process' && item.id === id
                ? { ...item, content: processDraftRef.current }
                : item,
            ))
          }
          break
        }
        case 'tool_start':
          setItems((prev) => [...prev, {
            kind: 'tool',
            id: `${event.run_id}:${event.data.tool_call_id}`,
            run_id: event.run_id,
            tool_call_id: event.data.tool_call_id,
            tool_name: event.data.tool_name,
            phase: 'start',
            started_at: Date.now(),
          }])
          break
        case 'tool_end':
          setItems((prev) => prev.map((item) =>
            item.kind === 'tool' && item.tool_call_id === event.data.tool_call_id
              ? {
                  ...item,
                  phase: 'end',
                  status: event.data.status,
                  duration_ms: event.data.duration_ms,
                }
              : item,
          ))
          break
        case 'structured_data':
          setItems((prev) => [...prev, {
            kind: 'structured',
            id: crypto.randomUUID(),
            data: event.data,
            time: nowTime(),
          }])
          break
        case 'final_text': {
          draftRef.current = event.data.delta
            ? draftRef.current + event.data.text
            : event.data.text
          let id = assistantIdRef.current
          if (!id) {
            const newId = crypto.randomUUID()
            assistantIdRef.current = newId
            setItems((prev) => [...prev, {
              kind: 'text', id: newId, role: 'assistant', content: draftRef.current, time: nowTime(),
            }])
          } else {
            setItems((prev) => prev.map((item) =>
              item.kind === 'text' && item.id === id
                ? { ...item, content: draftRef.current }
                : item,
            ))
          }
          break
        }
        case 'run_end':
          if (event.data.status === 'completed') finishRun()
          else finishWithError(event.data.error || '任务执行失败')
          break
        default:
          break
      }
    }

    function finishRun() {
      const finalText = draftRef.current
      assistantIdRef.current = null
      processIdRef.current = null
      setBusy(false)
      void refreshMonitor(sessionId)
      if (autoSpeak && finalText) {
        void speak(finalText).catch((err) => console.error('[TTS]', err))
      }
    }

    function finishWithError(message: string) {
      setItems((prev) => [...prev, {
        kind: 'process', id: crypto.randomUUID(), content: `⚠️ ${message}`, failed: true,
      }])
      assistantIdRef.current = null
      processIdRef.current = null
      setBusy(false)
      void refreshMonitor(sessionId)
    }
  }

  // 渲染单条 ChatItem
  // 重生成：从当前 assistant 往前找最近的 user 消息，重新发送
  const regenerateFrom = (currentItems: ChatItem[], currentIndex: number) => {
    if (busy) return
    for (let i = currentIndex - 1; i >= 0; i--) {
      const it = currentItems[i]
      if (it.kind === 'text' && it.role === 'user' && it.content) {
        // 移除当前 assistant 气泡及其后的所有条目（工具/结构化卡片），
        // 然后用相同 query 再发一次（让 server 重新生成）
        setItems((prev) => prev.slice(0, currentIndex))
        handleSend(it.content)
        return
      }
    }
  }

  // 渲染单条 ChatItem
  const renderItem = (item: ChatItem, index: number) => {
    if (item.kind === 'text') {
      const showActions = item.role === 'assistant' && item.content
      return (
        <Bubble
          key={item.id}
          placement={item.role === 'user' ? 'end' : 'start'}
          content={item.content || (item.role === 'assistant' ? '…' : '')}
          avatar={item.role === 'user' ? <UserAvatar /> : <AssistantAvatar />}
          footer={item.time ? <span className="msg-time">{item.time}</span> : undefined}
          footerPlacement="inner-end"
          styles={{ content: { maxWidth: '85%' } }}
          extra={
            showActions ? (
              <MessageActions
                content={item.content}
                onRegenerate={() => regenerateFrom(items, index)}
              />
            ) : undefined
          }
        />
      )
    }
    if (item.kind === 'process') {
      return (
        <div key={item.id} className="chat-item-row">
          <div className={`process-message ${item.failed ? 'is-failed' : ''}`}>
            {item.content}
          </div>
        </div>
      )
    }
    if (item.kind === 'tool') {
      const elapsed = toolElapsed[item.id] ?? ''
      const failed = item.phase === 'end' && item.status === 'failed'
      return (
        <div key={item.id} className="chat-item-row">
          <div className={`tool-bubble ${item.phase === 'end' ? 'is-done' : ''} ${failed ? 'is-failed' : ''}`}>
            <span className="tool-bubble-spinner" />
            <span className="tool-bubble-name">
              {item.phase === 'start' ? '🔍 正在执行' : failed ? '⚠️ 执行失败' : '✅ 已完成'} ·{' '}
              {getToolDisplayName(item.tool_name)}
            </span>
            {(item.duration_ms != null || elapsed) && (
              <span className="tool-bubble-elapsed">
                {item.phase === 'end'
                  ? (item.duration_ms != null ? `${(item.duration_ms / 1000).toFixed(1)}s` : '')
                  : `已用 ${elapsed}`}
              </span>
            )}
          </div>
        </div>
      )
    }
    // structured
    return (
      <div key={item.id} className="chat-item-row">
        <StructuredCards data={item.data} />
      </div>
    )
  }

  return (
    <div className="app-shell">
      <Sidebar
        sessionId={sessionId}
        onSelectSession={(session) => void handleSelectSession(session)}
        onRefreshHistory={() => void getSession(sessionId).then(handleSelectSession)}
      />

      <div className="chat-shell">
        <div className="chat-toolbar">
          <span className="chat-title">
            {currentSession.mode === 'chat' ? '💬' : '🛠️'} {currentSession.title || '会话'} · {currentSession.persona_display_name || currentSession.persona_name} · {currentSession.mode === 'chat' ? 'Chat' : 'Work'}
          </span>
          <div className="chat-toolbar-actions">
            {lastRunId && (
              <span className="run-id-badge" title={lastRunId}>
                Run {lastRunId.slice(0, 8)}
              </span>
            )}
            <label className="auto-speak-toggle">
              <input
                type="checkbox"
                checked={autoSpeak}
                onChange={(e) => setAutoSpeak(e.target.checked)}
              />
              自动播报回复
            </label>
            <SettingsPanel />
          </div>
        </div>

        {lastRunId && (
          <details className="run-details">
            <summary>执行详情 · Run {lastRunId.slice(0, 8)}</summary>
            <div className="run-details-id">完整 ID：{lastRunId}</div>
            {lastRunActivity.length === 0 ? (
              <div className="run-details-empty">本次运行尚未调用公开工具。</div>
            ) : (
              <div className="run-details-list">
                {lastRunActivity.map((item) => (
                  <div key={`trace-${item.id}`} className="run-details-entry">
                    {item.kind === 'process'
                      ? item.content
                      : `${item.phase === 'start' ? '执行中' : item.status === 'failed' ? '失败' : '完成'} · ${getToolDisplayName(item.tool_name)}${item.duration_ms != null ? ` · ${(item.duration_ms / 1000).toFixed(1)}s` : ''}`}
                  </div>
                ))}
              </div>
            )}
          </details>
        )}

        <div className="chat-body">
          {items.length === 0 ? (
            <div className="chat-empty">向 MutiRoleAgent 说点什么吧～</div>
          ) : (
            <div className="chat-items">
              {items.map((item, idx) => renderItem(item, idx))}
            </div>
          )}
        </div>

        <div className="chat-composer">
          <div className="composer-actions">
            <SessionMonitorPanel monitor={monitor} />
            {asrMsg && <span className="asr-status">{asrMsg}</span>}
            <button
              className={`speak-button ${recording ? 'is-recording' : ''}`}
              onPointerDown={() => void begin()}
              onPointerUp={() => void end()}
              onPointerCancel={() => cancel()}
              onPointerLeave={() => cancel()}
              disabled={busy}
              title="按住说话，松开识别"
            >
              {recording ? '⏺️ 录音中…松开结束' : '🎤 按住说话'}
            </button>
            <button
              className="speak-button"
              onClick={() => void speak(lastAssistantContent).catch((err) => console.error('[TTS]', err))}
              disabled={!lastAssistantContent || speaking || busy}
            >
              {speaking ? '🔊 播放中…' : '📢 朗读回复'}
            </button>
          </div>
          <Sender
            value={input}
            onChange={(v) => setInput(v as string)}
            onSubmit={handleSend}
            loading={busy}
            placeholder="输入消息，Enter 发送；或按住 🎤 用语音输入"
          />
        </div>
      </div>
    </div>
  )
}

function SessionMonitorPanel({ monitor }: { monitor: SessionMonitor }) {
  const ttft = monitor.average_ttft_ms === null
    ? '--'
    : `${(monitor.average_ttft_ms / 1000).toFixed(1)}s`
  const outputRate = monitor.output_tokens_per_second === null
    ? '--'
    : `${monitor.output_tokens_per_second.toFixed(1)} tok/s`
  const cacheHitRate = monitor.cache_hit_rate === null
    ? '--'
    : `${(monitor.cache_hit_rate * 100).toFixed(0)}%`
  return (
    <div className="session-monitor" aria-label="当前会话监控">
      <span title="当前会话已完成的 Agent 轮次">{monitor.total_turns} 轮</span>
      <span title="Agent 执行步骤数">{monitor.execution_steps} 步</span>
      <span title="累计 LLM 调用耗时">LLM {(monitor.llm_duration_ms / 1000).toFixed(1)}s</span>
      <span title="累计工具调用耗时">工具耗时 {(monitor.tool_duration_ms / 1000).toFixed(1)}s</span>
      <span title="平均首 Token 延迟">首字 {ttft}</span>
      <span title="输出 Token 速率">输出速率 {outputRate}</span>
      <span title="提示词缓存命中率">缓存 {cacheHitRate}</span>
      <span title="累计输入 Token">输入 {monitor.input_tokens.toLocaleString()}</span>
      <span title="累计输出 Token">输出 {monitor.output_tokens.toLocaleString()}</span>
    </div>
  )
}
