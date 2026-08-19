// 聊天主界面：SSE 流式对话 + 工具指示器 + TTS 语音播报 + ASR 语音输入
// + 会话/角色侧栏 + 设置面板
// 基于 @ant-design/x 的 Sender（输入框）+ Bubble（消息气泡）
import { useState, useRef } from 'react'
import { Bubble, Sender } from '@ant-design/x'
import {
  streamChat,
  getSessionHistory,
  type ToolEventData,
  type HistoryItem,
} from '../api'
import { getToolDisplayName } from './toolNames'
import { useSpeech } from './voice/speak'
import { useRecorder } from './voice/recorder'
import { Sidebar } from './Sidebar'
import { SettingsPanel } from './SettingsPanel'
import './Chat.css'

interface Msg {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface ToolEntry {
  id: string
  tool_name: string
  phase: 'start' | 'end'
}

const DEFAULT_SESSION = 'default'
const DEFAULT_PERSONA = 'Cyrene'

export function Chat() {
  const [sessionId, setSessionId] = useState(DEFAULT_SESSION)
  const [persona, setPersona] = useState(DEFAULT_PERSONA)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [tools, setTools] = useState<ToolEntry[]>([])
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [asrMsg, setAsrMsg] = useState('')
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

  const lastAssistantContent = [...msgs].reverse().find((m) => m.role === 'assistant')?.content ?? ''

  // 切换会话：重新加载历史回填消息列表
  const handleSelectSession = async (id: string) => {
    if (busy) return
    setSessionId(id)
    setMsgs([])
    setTools([])
    try {
      const history = await getSessionHistory(id)
      const loaded: Msg[] = history.map((h: HistoryItem) => ({
        id: crypto.randomUUID(),
        role: h.role === 'user' ? 'user' : 'assistant',
        content: h.content,
      }))
      setMsgs(loaded)
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
    setMsgs((m) => [...m, { id: crypto.randomUUID(), role: 'user', content: text }])

    // 准备一个空的 assistant 气泡，流式期间往里追加
    const assistantId = crypto.randomUUID()
    assistantIdRef.current = assistantId
    draftRef.current = ''
    setMsgs((m) => [...m, { id: assistantId, role: 'assistant', content: '' }])
    setBusy(true)

    void streamChat(
      { query: text, session_id: sessionId, persona },
      {
        onChunk: (c) => {
          draftRef.current += c
          setMsgs((prev) =>
            prev.map((m) =>
              m.id === assistantIdRef.current
                ? { ...m, content: draftRef.current }
                : m,
            ),
          )
        },
        onTool: (t: ToolEventData) => {
          setTools((prev) => [
            ...prev,
            { id: crypto.randomUUID(), tool_name: t.tool_name, phase: t.phase },
          ])
        },
        onStructured: () => {
          /* 结构化输出暂以纯文本展示 */
        },
        onDone: () => {
          const finalText = draftRef.current
          assistantIdRef.current = null
          draftRef.current = ''
          setBusy(false)
          setTools([])
          // 自动播报：对话完成后朗读最终回复
          if (autoSpeak && finalText) {
            void speak(finalText).catch((err) => console.error('[TTS]', err))
          }
        },
        onError: (msg) => {
          setMsgs((prev) =>
            prev.map((m) =>
              m.id === assistantIdRef.current
                ? { ...m, content: (m.content || '') + `\n\n⚠️ ${msg}` }
                : m,
            ),
          )
          assistantIdRef.current = null
          draftRef.current = ''
          setBusy(false)
          setTools([])
        },
      },
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
          {tools.length > 0 && (
            <div className="tool-indicators">
              {tools.map((t) => (
                <span key={t.id} className={`tool-chip ${t.phase === 'end' ? 'is-done' : ''}`}>
                  {t.phase === 'start' ? '🛠️' : '✅'} {getToolDisplayName(t.tool_name)}
                </span>
              ))}
            </div>
          )}

          {msgs.length === 0 ? (
            <div className="chat-empty">向 MutiRoleAgent 说点什么吧～</div>
          ) : (
            <Bubble.List
              items={msgs.map((m) => ({
                key: m.id,
                role: m.role === 'user' ? 'user' : 'assistant',
                placement: m.role === 'user' ? 'end' : 'start',
                content: m.content || (m.role === 'assistant' ? '…' : ''),
              }))}
              style={{ padding: '12px 16px' }}
            />
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