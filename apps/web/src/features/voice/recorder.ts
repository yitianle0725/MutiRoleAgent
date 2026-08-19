// 浏览器录音：捕获麦克风 → 重采样到 16kHz 单声道 → 封装为 16bit PCM WAV
// 输出的 WAV 满足后端 tools/voice/decode_wav_to_pcm16 的要求（16kHz/单声道/16bit）
import { useRef, useState } from 'react'

/**
 * 线性重采样：把任意采样率的一段音频缩放到目标采样率。
 * @param buffer    源 Float32Array（-1..1）
 * @param fromRate  源采样率
 * @param toRate    目标采样率
 */
function resample(buffer: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return buffer
  const ratio = fromRate / toRate
  const newLength = Math.round(buffer.length / ratio)
  const result = new Float32Array(newLength)
  for (let i = 0; i < newLength; i++) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, buffer.length - 1)
    const frac = pos - i0
    // 线性插值（对 44.1k→16k 足够好）
    result[i] = buffer[i0] * (1 - frac) + buffer[i1] * frac
  }
  return result
}

/** 把 16bit PCM 样本封装成标准 WAV 容器（PCM 无压缩）。 */
function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const pcm = new DataView(new ArrayBuffer(samples.length * 2))
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    pcm.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }

  const buffer = new ArrayBuffer(44 + pcm.byteLength)
  const view = new DataView(buffer)
  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }

  // RIFF 头
  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + pcm.byteLength, true)
  writeStr(8, 'WAVE')
  // fmt 块
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true)          // fmt 块大小
  view.setUint16(20, 1, true)           // PCM 编码
  view.setUint16(22, 1, true)           // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 字节率
  view.setUint16(32, 2, true)           // 块对齐
  view.setUint16(34, 16, true)          // 位深
  // data 块
  writeStr(36, 'data')
  view.setUint32(40, pcm.byteLength, true)
  new Uint8Array(buffer, 44).set(new Uint8Array(pcm.buffer))

  return new Blob([buffer], { type: 'audio/wav' })
}

/** 录音控制器：start() 开始，stop() 结束并返回 16kHz WAV Blob。 */
export interface Recorder {
  start: () => Promise<void>
  stop: () => Promise<Blob>
  cancel: () => void
}

/** 开始录音，返回控制器。 */
export async function startRecorder(): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const ctx = new AudioContext()
  const src = ctx.createMediaStreamSource(stream)

  // 用 ScriptProcessor 采集原始 Float32 块（保留原始采样率，结束时统一重采样）
  const chunks: Float32Array[] = []
  const processor = ctx.createScriptProcessor(4096, 1, 1)
  processor.onaudioprocess = (e) => {
    chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)))
  }
  src.connect(processor)
  processor.connect(ctx.destination)

  let stopped = false

  return {
    async start() {
      // 已在构造时开始采集
    },
    async stop() {
      if (stopped) throw new Error('录音已停止')
      stopped = true
      // 断开并释放麦克风
      processor.disconnect()
      src.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      await ctx.close()

      // 拼接 → 重采样到 16kHz → 封装 WAV
      const raw = new Float32Array(chunks.reduce((n, c) => n + c.length, 0))
      let offset = 0
      for (const c of chunks) {
        raw.set(c, offset)
        offset += c.length
      }
      const targetRate = 16000
      const resampled = resample(raw, ctx.sampleRate, targetRate)
      return encodeWav(resampled, targetRate)
    },
    cancel() {
      if (stopped) return
      stopped = true
      processor.disconnect()
      src.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      void ctx.close()
    },
  }
}

/** React hook：管理「录音中 / 识别中」状态与录音动作。 */
export function useRecorder(options: {
  onResult: (text: string) => void
  onError: (msg: string) => void
}) {
  const [recording, setRecording] = useState(false)
  const recorderRef = useRef<Recorder | null>(null)

  const begin = async () => {
    setRecording(true)
    recorderRef.current = await startRecorder()
  }

  const end = async () => {
    setRecording(false)
    const r = recorderRef.current
    recorderRef.current = null
    if (!r) return
    const wav = await r.stop()
    await transcribe(wav, options.onResult, options.onError)
  }

  const cancel = () => {
    setRecording(false)
    recorderRef.current?.cancel()
    recorderRef.current = null
  }

  return { recording, begin, end, cancel }
}

/** 把 WAV 上传后端识别。 */
async function transcribe(
  wav: Blob,
  onResult: (text: string) => void,
  onError: (msg: string) => void,
): Promise<void> {
  const fd = new FormData()
  fd.append('file', wav, 'recording.wav')
  const resp = await fetch('/api/voice/asr', { method: 'POST', body: fd })
  if (!resp.ok) {
    let detail = `语音识别失败 (HTTP ${resp.status})`
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    onError(detail)
    return
  }
  const data = await resp.json()
  if (data.text) onResult(data.text)
  else onError('未识别到有效语音')
}
