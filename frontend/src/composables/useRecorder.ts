/** 麦克风录音：16kHz PCM 流 + VAD（沉默/噪音/发言事件）。 */

import { ref } from 'vue'

import workletURL from '@/audio/pcm-worklet.js?url'

export interface SpeechEvent {
  type: 'speech_start' | 'speech_end' | 'silence_prompted' | 'noisy'
  t: number // 相对录音开始的毫秒
}

export interface RecorderCallbacks {
  /** 每批 16kHz/16bit/单声道 PCM（已应用暂停门控） */
  onPcm?: (chunk: ArrayBuffer) => void
  /** 连续 10 秒无有效语音（每轮最多触发一次） */
  onSilence?: (elapsedMs: number) => void
  /** 环境噪音过大提示 */
  onNoisy?: () => void
  onSpeechEvent?: (event: SpeechEvent) => void
}

const SPEECH_RMS_THRESHOLD = 0.012
const SILENCE_REPORT_MS = 10_000
const NOISY_RMS_THRESHOLD = 0.28
const NOISY_SUSTAIN_MS = 2500

export function useRecorder() {
  const recording = ref(false)
  const paused = ref(false)
  const micDenied = ref(false)
  const level = ref(0) // 当前音量（0-1），用于 UI 动画
  const noisy = ref(false)

  let stream: MediaStream | null = null
  let ctx: AudioContext | null = null
  let node: AudioWorkletNode | null = null

  let startedAt = 0
  let pausedTotalMs = 0
  let pausedAt = 0
  let silenceReported = false
  let noiseReported = false
  let lastSpeechAt = 0
  let speaking = false
  let noisySince = 0
  let silenceTimer: number | null = null
  let callbacks: RecorderCallbacks = {}

  function elapsedMs(): number {
    if (!startedAt) return 0
    return performance.now() - startedAt - pausedTotalMs
  }

  function handlePcm(buffer: ArrayBuffer): void {
    if (!recording.value) return
    // RMS 计算用于 VAD（无论是否暂停都更新电平显示）
    const view = new DataView(buffer)
    const frames = Math.floor(view.byteLength / 2)
    let sumSquares = 0
    for (let i = 0; i < frames; i++) {
      const v = view.getInt16(i * 2, true) / 32768
      sumSquares += v * v
    }
    const rms = Math.sqrt(sumSquares / Math.max(frames, 1))
    level.value = Math.min(1, rms * 4)

    if (paused.value) return

    callbacks.onPcm?.(buffer)
    const now = elapsedMs()

    if (rms >= SPEECH_RMS_THRESHOLD) {
      lastSpeechAt = now
      noisySince = 0
      if (!speaking) {
        speaking = true
        callbacks.onSpeechEvent?.({ type: 'speech_start', t: now })
      }
    } else if (speaking) {
      speaking = false
      callbacks.onSpeechEvent?.({ type: 'speech_end', t: now })
    }

    if (rms >= NOISY_RMS_THRESHOLD) {
      if (!noisySince) noisySince = now
      if (!noiseReported && now - noisySince >= NOISY_SUSTAIN_MS) {
        noiseReported = true
        noisy.value = true
        callbacks.onSpeechEvent?.({ type: 'noisy', t: now })
        callbacks.onNoisy?.()
      }
    } else {
      noisySince = 0
    }

    if (!silenceReported && lastSpeechAt > 0 && now - lastSpeechAt >= SILENCE_REPORT_MS) {
      silenceReported = true
      callbacks.onSpeechEvent?.({ type: 'silence_prompted', t: now })
      callbacks.onSilence?.(now - lastSpeechAt)
    }
  }

  /** 预热：提前请求麦克风权限，避免练习中途弹窗。 */
  async function warmUp(): Promise<boolean> {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach((t) => t.stop())
      micDenied.value = false
      return true
    } catch {
      micDenied.value = true
      return false
    }
  }

  async function start(cb: RecorderCallbacks): Promise<boolean> {
    if (recording.value) return true
    callbacks = cb
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
    } catch {
      micDenied.value = true
      return false
    }

    const Ctor: typeof AudioContext =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    ctx = new Ctor()
    await ctx.audioWorklet.addModule(workletURL)
    const source = ctx.createMediaStreamSource(stream)
    node = new AudioWorkletNode(ctx, 'pcm-recorder')
    node.port.onmessage = (event: MessageEvent) => {
      if (event.data?.type === 'pcm') handlePcm(event.data.buffer as ArrayBuffer)
    }
    source.connect(node)

    recording.value = true
    paused.value = false
    startedAt = performance.now()
    pausedTotalMs = 0
    silenceReported = false
    noiseReported = false
    speaking = false
    lastSpeechAt = 0
    noisySince = 0
    noisy.value = false

    silenceTimer = window.setInterval(() => {
      // 沉默检测兜底（从未说话的场景）
      if (
        !recording.value ||
        paused.value ||
        silenceReported ||
        lastSpeechAt > 0
      )
        return
      if (elapsedMs() >= SILENCE_REPORT_MS + 2000) {
        silenceReported = true
        callbacks.onSpeechEvent?.({ type: 'silence_prompted', t: elapsedMs() })
        callbacks.onSilence?.(elapsedMs())
      }
    }, 1000)

    return true
  }

  function pause(): void {
    if (!recording.value || paused.value) return
    paused.value = true
    pausedAt = performance.now()
  }

  function resume(): void {
    if (!paused.value) return
    pausedTotalMs += performance.now() - pausedAt
    paused.value = false
  }

  function stop(): SpeechEvent[] {
    const events: SpeechEvent[] = []
    if (speaking) {
      events.push({ type: 'speech_end', t: elapsedMs() })
    }
    recording.value = false
    paused.value = false
    if (silenceTimer !== null) {
      window.clearInterval(silenceTimer)
      silenceTimer = null
    }
    if (node) {
      node.port.onmessage = null
      node.disconnect()
      node = null
    }
    if (ctx) {
      void ctx.close()
      ctx = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    level.value = 0
    return events
  }

  return { recording, paused, micDenied, level, noisy, warmUp, start, stop, pause, resume }
}
