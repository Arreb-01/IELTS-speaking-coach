/** 考官语音播放器：PCM 分块无缝排队播放。 */

export interface AudioPlayerOptions {
  sampleRate?: number // 默认 24000，与后端 TTS 输出一致
}

export function useAudioPlayer(options: AudioPlayerOptions = {}) {
  const sampleRate = options.sampleRate ?? 24000
  let ctx: AudioContext | null = null
  let sources: AudioBufferSourceNode[] = []
  let nextStartTime = 0

  function ensureContext(): AudioContext {
    if (!ctx) {
      const Ctor: typeof AudioContext =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      ctx = new Ctor({ sampleRate })
    }
    if (ctx.state === 'suspended') {
      void ctx.resume()
    }
    return ctx
  }

  /** Int16 PCM 小端字节 → AudioBuffer */
  function pcmToAudioBuffer(bytes: ArrayBuffer): AudioBuffer {
    const view = new DataView(bytes)
    const frames = Math.floor(view.byteLength / 2)
    const buffer = ensureContext().createBuffer(1, frames, sampleRate)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < frames; i++) {
      channel[i] = view.getInt16(i * 2, true) / 32768
    }
    return buffer
  }

  /** 入队一块 PCM 音频，立即调度播放（无缝衔接）。 */
  function enqueuePcm(bytes: ArrayBuffer): void {
    if (bytes.byteLength < 2) return
    const context = ensureContext()
    const buffer = pcmToAudioBuffer(bytes)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    const now = context.currentTime
    if (nextStartTime < now) {
      nextStartTime = now + 0.02
    }
    source.start(nextStartTime)
    nextStartTime += buffer.duration
    sources.push(source)
    source.onended = () => {
      sources = sources.filter((s) => s !== source)
    }
  }

  /** 停止当前全部播放并清空队列（暂停/打断时用）。 */
  function stopAll(): void {
    for (const source of sources) {
      try {
        source.stop()
      } catch {
        /* 已结束 */
      }
    }
    sources = []
    nextStartTime = 0
  }

  function close(): void {
    stopAll()
    if (ctx) {
      void ctx.close()
      ctx = null
    }
  }

  return { enqueuePcm, stopAll, close }
}
