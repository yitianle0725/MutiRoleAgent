// 左侧栏：会话列表 + 角色选择
// 会话来自后端 chat_db 持久化；角色来自 persona_loader
import { useEffect, useState } from 'react'
import {
  listSessions,
  createSession,
  deleteSession,
  listPersonas,
  type SessionItem,
} from '../api'
import './Sidebar.css'

interface SidebarProps {
  sessionId: string
  persona: string
  onSelectSession: (id: string) => void
  onSelectPersona: (name: string) => void
  onRefreshHistory: () => void
}

export function Sidebar(props: SidebarProps) {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [personas, setPersonas] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  const loadSessions = async () => {
    setLoading(true)
    try {
      setSessions(await listSessions())
    } catch (err) {
      console.error('[sessions]', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSessions()
    void listPersonas().then(setPersonas).catch(console.error)
  }, [])

  const handleNew = async () => {
    try {
      const id = await createSession()
      props.onSelectSession(id) // 切到新会话（空历史）
      await loadSessions()
    } catch (err) {
      console.error('[sessions] new', err)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm(`确定删除会话「${id.slice(0, 8)}…」？`)) return
    try {
      await deleteSession(id)
      if (id === props.sessionId) {
        // 删除的是当前会话：切到默认
        props.onSelectSession('default')
      }
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
          <span className="sidebar-title">会话</span>
          <button className="sidebar-new" onClick={() => void handleNew()} title="新建会话">
            +
          </button>
        </div>
        <div className="session-list">
          {sessions.length === 0 && !loading && (
            <div className="sidebar-empty">暂无历史会话</div>
          )}
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`session-item ${s.session_id === props.sessionId ? 'is-active' : ''}`}
            >
              <button
                className="session-item-main"
                onClick={() => props.onSelectSession(s.session_id)}
              >
                <span className="session-item-title">{s.title || s.session_id.slice(0, 8)}</span>
                <span className="session-item-meta">
                  {s.message_count ?? 0} 条 · {s.updated_at?.slice(5, 16) ?? ''}
                </span>
              </button>
              <button
                className="session-item-del"
                onClick={() => void handleDelete(s.session_id)}
                title="删除会话"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-header">
          <span className="sidebar-title">角色</span>
        </div>
        <div className="persona-list">
          {personas.map((p) => (
            <button
              key={p}
              className={`persona-item ${p === props.persona ? 'is-active' : ''}`}
              onClick={() => props.onSelectPersona(p)}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
    </aside>
  )
}
