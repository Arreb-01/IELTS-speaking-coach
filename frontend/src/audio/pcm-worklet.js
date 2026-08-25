// AudioWorklet 处理器：浏览器采样率 → 16kHz 单声道 Int16 PCM
// 以 ?url 方式加载（见 useRecorder.ts），不参与 TS 编译
class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.targetRate = 16000
    this.step = sampleRate / this.targetRate // 例如 48000 → 3
    this.acc = 0
    this.sum = 0
    this.count = 0
    this.out = []
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const channel = input[0]

    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i]
      this.count++
      this.acc += 1
      if (this.acc >= this.step) {
        // 均值抽取，附带简单钳位
        const avg = this.sum / Math.max(this.count, 1)
        const clamped = Math.max(-1, Math.min(1, avg))
        this.out.push(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff)
        this.acc -= this.step
        this.sum = 0
        this.count = 0
        // 每积累约 64ms（1024 样本）上报一批
        if (this.out.length >= 1024) {
          this.postMessage(this.out)
          this.out = []
        }
      }
    }
    return true
  }

  postMessage(samples) {
    const buffer = new ArrayBuffer(samples.length * 2)
    const view = new DataView(buffer)
    for (let i = 0; i < samples.length; i++) {
      view.setInt16(i * 2, samples[i], true)
    }
    this.port.postMessage({ type: 'pcm', buffer }, [buffer])
  }
}

registerProcessor('pcm-recorder', PcmRecorderProcessor)
