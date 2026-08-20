// TTS 语音播放：拉取后端合成音频并播放，带「停止」能力
import { useState } from 'react'

let _current: HTMLAudioElement | null = null

/** 把一段文本合成语音并播放（自动替换正在播放的上一段）。 */
export async function speak(text: string): Promise<void> {
  const resp = await fetch('/api/v1/voice/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)

  // 打断上一段（停止播放）
  stopSpeech()
  _current = audio
  audio.onended = () => {
    _current = null
    URL.revokeObjectURL(url)
  }
  await audio.play()
}

/** 停止当前播放的语音。 */
export function stopSpeech(): void {
  if (_current) {
    _current.pause()
    _current = null
  }
}

/** React hook：管理「朗读中」状态，供按钮显示 loading。 */
export function useSpeech(): { speaking: boolean; speak: (t: string) => Promise<void>; stop: () => void } {
  const [speaking, setSpeaking] = useState(false)
  return {
    speaking,
    speak: async (t: string) => {
      setSpeaking(true)
      try {
        await speak(t)
      } finally {
        setSpeaking(false)
      }
    },
    stop: () => {
      stopSpeech()
      setSpeaking(false)
    },
  }
}
