// 设置面板：只读展示当前配置快照（LLM / 语音 / 存储 / Agent）
import { useEffect, useState } from 'react'
import { getConfig, type AppConfig } from '../api'
import './SettingsPanel.css'

export function SettingsPanel() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    void getConfig().then(setConfig).catch(console.error)
  }, [])

  return (
    <div className="settings-panel">
      <button className="settings-toggle" onClick={() => setOpen((o) => !o)}>
        ⚙️ 设置 {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="settings-body">
          <Row label="LLM 模型" value={config?.llm?.model ?? '—'} />
          <Row label="LLM BaseURL" value={config?.llm?.base_url ?? '—'} />
          <Row label="Embedding" value={config?.embedding?.mode ?? '—'} />
          <Row
            label="语音对话"
            value={config?.voice?.enabled ? '✅ 已启用' : '⭕ 未启用'}
          />
          <Row label="TTS 模型" value={config?.voice?.tts_model ?? '—'} />
          <Row label="TTS 音色" value={config?.voice?.tts_voice ?? '—'} />
          <Row label="ASR 模型" value={config?.voice?.asr_model ?? '—'} />
          <Row label="会话存储" value={config?.store?.session ?? '—'} />
          <Row label="数据库" value={config?.store?.db ?? '—'} />
        </div>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="settings-row">
      <span className="settings-label">{label}</span>
      <span className="settings-value" title={value}>
        {value}
      </span>
    </div>
  )
}