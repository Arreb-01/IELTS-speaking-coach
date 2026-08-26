/** 练习会话前端状态：WS 消息处理、录音/播放编排、计时器。 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  createPractice,
  fetchPracticeDetail,
  type PracticeDetail,
} from '@/api/practice'
import { useAudioPlayer } from '@/composables/useAudioPlayer'
import { useRecorder } from '@/composables/useRecorder'
import { useWsClient, type ServerMessage } from '@/composables/useWsClient'
import type { CueCard, TopicOut } from '@/types'

export type Phase = 'idle' | 'connecting' | 'preparing' | 'examiner_asks' | 'user_answers' | 'finished'
export type TurnButtonState = 'waiting' | 'ready' | 'recording' | 'processing'

export interface TranscriptEntry {
  turnId: string
  question: string
  answer: string
  isFollowup: boolean
}

const ACCENT_OPTIONS = [
  { value: 'en_female_anna', label: '美音女声' },
  { value: 'en_female_ariana', label: '美音女声 2' },
  { value: 'en_male_jackson', label: '美音男声' },
]
const SPEED_OPTIONS = [
  { value: 'slow', label: '语速 慢' },
  { value: 'normal', label: '语速 正常' },
  { value: 'fast', label: '语速 快' },
]

export const usePracticeStore = defineStore('practice', () => {
  // ---- 会话状态 ----
  const phase = ref<Phase>('idle')
  const sessionId = ref('')
  const part = ref(1)
  const topic = ref<TopicOut | null>(null)
  const accent = ref('en_female_anna')
  const speed = ref('normal')
  const paused = ref(false)
  const fatalMessage = ref('')

  // ---- 当前题目 ----
  const currentQuestion = ref('')
  const questionIndex = ref(0)
  const questionTotal = ref(0)
  const isFollowup = ref(false)

  // ---- Part 2 ----
  const cueCard = ref<CueCard | null>(null)
  const prepCountdown = ref(0)
  const notes = ref('')

  // ---- 转写 ----
  const partialText = ref('')
  const transcripts = ref<TranscriptEntry[]>([])

  // ---- 计时 ----
  const turnElapsed = ref(0) // 当前轮已用时（秒）
  const turnMaxSeconds = ref(90)

  // ---- 基础设施 ----
  const player = useAudioPlayer()
  const recorder = useRecorder()
  const reportAvailable = ref(false)
  let turnTimer: number | null = null
  let turnStartedAt = 0
  let speechEvents: { type: string; t: number }[] = []
  let currentTurnQuestion = ''

  const buttonState = computed<TurnButtonState>(() => {
    if (phase.value !== 'user_answers') return 'waiting'
    if (recorder.recording.value) return 'recording'
    if (recorder.paused.value) return 'processing'
    return 'ready'
  })

  const ws = useWsClient({
    onMessage: handleMessage,
    onReconnecting: () => {
      recorder.pause()
    },
    onFatal: (reason) => {
      fatalMessage.value = reason
      phase.value = 'finished'
    },
  })

  // ------------------------------------------------------------------
  // 消息处理
  // ------------------------------------------------------------------

  function handleMessage(msg: ServerMessage): void {
    switch (msg.type) {
      case 'session_started':
        sessionId.value = msg.session_id as string
        part.value = msg.part as number
        topic.value = msg.topic as TopicOut | null
        phase.value = 'connecting'
        break
      case 'phase':
        handlePhase(msg.phase as string, msg)
        break
      case 'question':
        currentQuestion.value = msg.text as string
        currentTurnQuestion = msg.text as string
        questionIndex.value = (msg.index as number) + 1
        questionTotal.value = msg.total as number
        isFollowup.value = Boolean(msg.is_followup)
        break
      case 'cue_card':
        cueCard.value = msg.card as CueCard
        startPrepCountdown(msg.prep_seconds as number)
        break
      case 'prep_end':
        stopPrepCountdown()
        break
      case 'audio_start':
        // 新一段考官台词：清空播放队列从头排
        player.stopAll()
        break
      case 'audio_chunk': {
        const base64 = msg.data as string
        const binary = atob(base64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
        player.enqueuePcm(bytes.buffer)
        break
      }
      case 'turn_started':
        partialText.value = ''
        beginRecording()
        break
      case 'asr_partial':
        partialText.value = msg.text as string
        break
      case 'asr_final': {
        stopRecording()
        const text = (msg.text as string) || ''
        if (currentTurnQuestion || text) {
          transcripts.value.push({
            turnId: msg.turn_id as string,
            question: currentTurnQuestion,
            answer: text,
            isFollowup: isFollowup.value,
          })
        }
        partialText.value = ''
        break
      }
      case 'time_up':
        // 服务端强制作答结束；前端同步收尾（end_turn 幂等）
        if (recorder.recording.value) {
          endAnswer()
        }
        break
      case 'silence_prompt':
        break // 音频随 audio_chunk 流播放
      case 'paused':
        paused.value = true
        recorder.pause()
        player.stopAll()
        break
      case 'resumed':
        paused.value = false
        recorder.resume()
        break
      case 'turn_reset':
        stopRecording()
        partialText.value = ''
        break
      case 'settings_updated':
        accent.value = msg.accent as string
        speed.value = msg.speed as string
        break
      case 'finished':
        reportAvailable.value = Boolean(msg.report_available) && !msg.abandoned
        finishPractice()
        break
      case 'error': {
        const message = msg.message as string
        // 静默降级提示只在关键错误时弹
        import('element-plus').then(({ ElMessage }) => {
          ElMessage.warning(message)
        })
        break
      }
      default:
        break
    }
  }

  function handlePhase(next: string, msg: ServerMessage): void {
    phase.value = next as Phase
    if (next === 'user_answers') {
      turnMaxSeconds.value = (msg.max_seconds as number) ?? 90
      turnElapsed.value = 0
    }
  }

  // ------------------------------------------------------------------
  // 录音编排
  // ------------------------------------------------------------------

  function beginRecording(): void {
    speechEvents = []
    void recorder.start({
      onPcm: (chunk) => ws.sendPcm(chunk),
      onSilence: () => ws.send({ type: 'silence' }),
      onNoisy: () => {
        import('element-plus').then(({ ElMessage }) => {
          ElMessage.warning('检测到环境噪音较大，建议在安静环境练习')
        })
      },
      onSpeechEvent: (event) => speechEvents.push(event),
    })
    turnStartedAt = performance.now()
    if (turnTimer !== null) window.clearInterval(turnTimer)
    turnTimer = window.setInterval(() => {
      if (recorder.paused.value) return
      turnElapsed.value = Math.floor((performance.now() - turnStartedAt) / 1000)
      if (turnElapsed.value >= turnMaxSeconds.value) {
        // 前端兜底：到时自动结束（服务端 watchdog 也会触发）
        endAnswer()
      }
    }, 500)
  }

  function stopRecording(): void {
    if (turnTimer !== null) {
      window.clearInterval(turnTimer)
      turnTimer = null
    }
    if (recorder.recording.value) {
      const events = recorder.stop()
      speechEvents.push(...events)
    }
    turnElapsed.value = 0
  }

  // ------------------------------------------------------------------
  // 用户动作
  // ------------------------------------------------------------------

  async function start(payload: {
    topicId: string
    part: number
    accent?: string
    speed?: string
    topic?: TopicOut | null
  }): Promise<void> {
    reset()
    phase.value = 'connecting'
    accent.value = payload.accent ?? accent.value
    speed.value = payload.speed ?? speed.value
    topic.value = payload.topic ?? null
    part.value = payload.part

    const created = await createPractice({
      topic_id: payload.topicId,
      part: payload.part,
      accent: accent.value,
      speed: speed.value,
    })
    sessionId.value = created.session_id
    ws.connect(created.ws_path, created.session_id)
  }

  function beginAnswer(): void {
    if (phase.value !== 'user_answers' || recorder.recording.value) return
    ws.send({ type: 'begin_turn' })
    // turn_started 消息到达后正式开始录音
  }

  function endAnswer(): void {
    if (!recorder.recording.value) return
    const events = speechEvents
    stopRecording()
    ws.send({ type: 'end_turn', speech_events: events })
  }

  function togglePause(): void {
    ws.send({ type: paused.value ? 'resume' : 'pause' })
  }

  function retryTurn(): void {
    if (!recorder.recording.value) return
    ws.send({ type: 'retry' })
  }

  function endSession(): void {
    if (recorder.recording.value) {
      endAnswer()
    }
    ws.send({ type: 'end_session' })
  }

  function p2Ready(): void {
    ws.send({ type: 'p2_ready' })
  }

  function updateSettings(next: { accent?: string; speed?: string }): void {
    if (next.accent) accent.value = next.accent
    if (next.speed) speed.value = next.speed
    ws.send({ type: 'settings', accent: accent.value, speed: speed.value })
  }

  async function warmUpMic(): Promise<boolean> {
    return recorder.warmUp()
  }

  // ------------------------------------------------------------------
  // Part 2 备稿倒计时
  // ------------------------------------------------------------------

  let prepTimer: number | null = null

  function startPrepCountdown(seconds: number): void {
    prepCountdown.value = seconds
    if (prepTimer !== null) window.clearInterval(prepTimer)
    prepTimer = window.setInterval(() => {
      if (prepCountdown.value > 0) prepCountdown.value -= 1
      if (prepCountdown.value <= 0) stopPrepCountdown()
    }, 1000)
  }

  function stopPrepCountdown(): void {
    if (prepTimer !== null) {
      window.clearInterval(prepTimer)
      prepTimer = null
    }
    prepCountdown.value = 0
  }

  // ------------------------------------------------------------------
  // 结束与重置
  // ------------------------------------------------------------------

  const summary = ref<PracticeDetail | null>(null)

  async function finishPractice(): Promise<void> {
    stopRecording()
    stopPrepCountdown()
    phase.value = 'finished'
    ws.close()
    player.stopAll()
    try {
      summary.value = await fetchPracticeDetail(sessionId.value)
    } catch {
      summary.value = null
    }
  }

  function reset(): void {
    stopRecording()
    stopPrepCountdown()
    ws.close()
    player.stopAll()
    phase.value = 'idle'
    sessionId.value = ''
    topic.value = null
    cueCard.value = null
    notes.value = ''
    partialText.value = ''
    transcripts.value = []
    currentQuestion.value = ''
    questionIndex.value = 0
    questionTotal.value = 0
    paused.value = false
    fatalMessage.value = ''
    summary.value = null
    reportAvailable.value = false
  }

  return {
    // 状态
    phase, sessionId, part, topic, accent, speed, paused, fatalMessage,
    currentQuestion, questionIndex, questionTotal, isFollowup,
    cueCard, prepCountdown, notes,
    partialText, transcripts, turnElapsed, turnMaxSeconds,
    recorder, summary, buttonState, reportAvailable,
    accentOptions: ACCENT_OPTIONS, speedOptions: SPEED_OPTIONS,
    // 动作
    start, beginAnswer, endAnswer, togglePause, retryTurn, endSession,
    p2Ready, updateSettings, warmUpMic, reset,
  }
})
