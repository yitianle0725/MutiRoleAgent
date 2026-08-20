// 聊天主界面：SSE 流式对话 + 结构化输出卡片 + 工具加载气泡 + TTS/ASR + 会话面板
import { useState, useRef, useEffect } from 'react'
import { Bubble, Sender } from '@ant-design/x'
import {
  streamChat,
  getSessionHistory,
  listSessions,
  type ToolEventData,
  type HistoryItem,
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

/** 统一条目：文本气泡 / 工具调用 / 结构化卡片 */
type ChatItem =
  | { kind: 'text'; id: string; role: 'user' | 'assistant'; content: string; time: string }
  | { kind: 'tool'; id: string; tool_name: string; phase: 'start' | 'end'; started_at: number }
  | { kind: 'structured'; id: string; data: StructuredPayload; time: string }

const DEFAULT_SESSION = 'default'
const DEFAULT_PERSONA = 'Cyrene'

/** 当前时间 → HH:MM。 */
function nowTime(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 从 SQLite 的 "YYYY-MM-DD HH:MM:SS" 中取 HH:MM。 */
function historyTime(createdAt?: string): string {
  return createdAt ? createdAt.slice(11, 16) : ''
}

/** 移除文本里的 ```json ... ``` 代码块（结构化输出会单独渲染卡片，避免重复展示） */
function stripJsonCodeBlocks(text: string): string {
  return text
    .replace(/```json\s*\n[\s\S]*?\n```/g, '')
    .replace(/```\s*\n[\s\S]*?\n```/g, '')
    .trim()
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
  const [persona, setPersona] = useState(DEFAULT_PERSONA)
  const [items, setItems] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [asrMsg, setAsrMsg] = useState('')
  const [toolElapsed, setToolElapsed] = useState<Record<string, string>>({})
  const { speaking, speak } = useSpeech()
  const assistantIdRef = useRef<string | null>(null)
  const draftRef = useRef('')
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

  // 启动时自动恢复最近一个有消息的会话（避免每次打开页面从空白开始）
  useEffect(() => {
    void (async () => {
      try {
        const list = await listSessions()
        const recent = list.find((s) => (s.message_count ?? 0) > 0)
        if (recent) await handleSelectSession(recent.session_id)
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
  const handleSelectSession = async (id: string) => {
    if (busy) return
    setSessionId(id)
    setItems([])
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

  const handleSelectPersona = (name: string) => {
    setPersona(name)
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

    // 准备一个空的 assistant 气泡，流式期间往里追加
    const assistantId = crypto.randomUUID()
    assistantIdRef.current = assistantId
    draftRef.current = ''
    setItems((prev) => [
      ...prev,
      { kind: 'text', id: assistantId, role: 'assistant', content: '', time: nowTime() },
    ])
    setBusy(true)

    void streamChat(
      { query: text, session_id: sessionId, persona },
      {
        onChunk: (c) => {
          draftRef.current += c
          const id = assistantIdRef.current
          setItems((prev) =>
            prev.map((it) =>
              it.kind === 'text' && it.id === id
                ? { ...it, content: draftRef.current }
                : it,
            ),
          )
        },
        onTool: (t: ToolEventData) => {
          setItems((prev) => {
            if (t.phase === 'start') {
              return [
                ...prev,
                {
                  kind: 'tool',
                  id: crypto.randomUUID(),
                  tool_name: t.tool_name,
                  phase: 'start',
                  started_at: Date.now(),
                },
              ]
            }
            // end：把同名工具中最后一条仍处于 start 的标记为 end
            for (let i = prev.length - 1; i >= 0; i--) {
              const it = prev[i]
              if (it.kind === 'tool' && it.tool_name === t.tool_name && it.phase === 'start') {
                const copy = [...prev]
                copy[i] = { ...it, phase: 'end' }
                return copy
              }
            }
            return prev
          })
        },
        onStructured: (data) => {
          const id = assistantIdRef.current
          setItems((prev) => {
            const next = prev.map((it) =>
              it.kind === 'text' && it.id === id
                ? { ...it, content: stripJsonCodeBlocks(it.content) }
                : it,
            )
            // 紧随 assistant 文本追加结构化卡片
            next.push({
              kind: 'structured',
              id: crypto.randomUUID(),
              data,
              time: nowTime(),
            })
            return next
          })
        },
        onDone: () => {
          const finalText = draftRef.current
          assistantIdRef.current = null
          draftRef.current = ''
          setBusy(false)
          if (autoSpeak && finalText) {
            void speak(finalText).catch((err) => console.error('[TTS]', err))
          }
        },
        onError: (msg) => {
          const id = assistantIdRef.current
          setItems((prev) =>
            prev.map((it) =>
              it.kind === 'text' && it.id === id
                ? { ...it, content: (it.content || '') + `\n\n⚠️ ${msg}` }
                : it,
            ),
          )
          assistantIdRef.current = null
          draftRef.current = ''
          setBusy(false)
        },
      },
    )
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
    if (item.kind === 'tool') {
      const elapsed = toolElapsed[item.id] ?? ''
      return (
        <div key={item.id} className="chat-item-row">
          <div className={`tool-bubble ${item.phase === 'end' ? 'is-done' : ''}`}>
            <span className="tool-bubble-spinner" />
            <span className="tool-bubble-name">
              {item.phase === 'start' ? '🔍 正在查询' : '✅ 已完成'} ·{' '}
              {getToolDisplayName(item.tool_name)}
            </span>
            {elapsed && (
              <span className="tool-bubble-elapsed">
                {item.phase === 'end' ? '' : '已用 '}
                {elapsed}
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
        persona={persona}
        onSelectSession={(id) => void handleSelectSession(id)}
        onSelectPersona={handleSelectPersona}
        onRefreshHistory={() => void handleSelectSession(sessionId)}
      />

      <div className="chat-shell">
        <div className="chat-toolbar">
          <span className="chat-title">
            💬 {sessionId === DEFAULT_SESSION ? '默认会话' : '会话'} · 角色：{persona}
          </span>
          <div className="chat-toolbar-actions">
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