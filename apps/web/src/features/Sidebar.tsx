// 左侧栏：会话列表 + 创建时锁定角色和模式
import { useEffect, useState } from 'react'
import {
  listSessions,
  createSession,
  deleteSession,
  listPersonas,
  type PersonaItem,
  type SessionItem,
} from '../api'
import './Sidebar.css'

interface SidebarProps {
  sessionId: string
  onSelectSession: (session: SessionItem) => void
  onRefreshHistory: () => void
}

export function Sidebar(props: SidebarProps) {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [personas, setPersonas] = useState<PersonaItem[]>([])
  const [newPersonaId, setNewPersonaId] = useState('cyrene')
  const [newMode, setNewMode] = useState<'chat' | 'work'>('chat')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  const loadSessions = async () => {
    setLoading(true)
    setLoadError('')
    try {
      setSessions(await listSessions())
    } catch (err) {
      console.error('[sessions]', err)
      setLoadError('会话列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSessions()
    void listPersonas().then((items) => {
      setPersonas(items)
      if (items.length > 0) setNewPersonaId(items[0].persona_id)
    }).catch(console.error)
  }, [props.sessionId])

  const handleNew = async () => {
    try {
      const session = await createSession({
        user_id: 'local_user',
        persona_id: newPersonaId,
        mode: newMode,
      })
      props.onSelectSession(session)
      await loadSessions()
    } catch (err) {
      console.error('[sessions] new', err)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm(`确定删除会话「${id.slice(0, 8)}…」？`)) return
    try {
      await deleteSession(id)
      const remaining = sessions.filter((session) => session.session_id !== id)
      if (id === props.sessionId && remaining[0]) props.onSelectSession(remaining[0])
      await loadSessions()
      props.onRefreshHistory()
    } catch (err) {
      console.error('[sessions] delete', err)
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-header">
          <span className="sidebar-title">新会话</span>
        </div>
        <label className="session-create-field">
          <span>角色</span>
          <select value={newPersonaId} onChange={(event) => setNewPersonaId(event.target.value)}>
            {personas.map((persona) => (
              <option key={persona.persona_id} value={persona.persona_id}>
                {persona.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="session-create-field">
          <span>模式</span>
          <select value={newMode} onChange={(event) => setNewMode(event.target.value as 'chat' | 'work')}>
            <option value="chat">Chat · 陪伴聊天</option>
            <option value="work">Work · 工具任务</option>
          </select>
        </label>
        <button className="sidebar-create" onClick={() => void handleNew()}>
          创建会话
        </button>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-header"><span className="sidebar-title">会话</span></div>
        <div className="session-list">
          {loadError && <button className="sidebar-retry" onClick={() => void loadSessions()}>{loadError}，重试</button>}
          {sessions.length === 0 && !loading && !loadError && <div className="sidebar-empty">暂无历史会话</div>}
          {sessions.map((session) => (
            <div key={session.session_id} className={`session-item ${session.session_id === props.sessionId ? 'is-active' : ''}`}>
              <button className="session-item-main" onClick={() => props.onSelectSession(session)}>
                <span className="session-item-title">{session.title || session.session_id.slice(0, 8)}</span>
                <span className="session-item-meta">
                  {session.persona_display_name || session.persona_name} · {session.mode === 'chat' ? 'Chat' : 'Work'}
                </span>
                <span className="session-item-meta">{session.message_count ?? 0} 条 · {session.updated_at?.slice(5, 16) ?? ''}</span>
              </button>
              <button className="session-item-del" onClick={() => void handleDelete(session.session_id)} title="删除会话">×</button>
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}
