<script setup lang="ts">
import {
  ChevronRight,
  Mic,
  MicOff,
  Pause,
  Play,
  Redo,
  Square,
} from 'lucide-vue-next'
import { ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import TurnAudioPlayer from '@/components/TurnAudioPlayer.vue'
import { turnAudioUrl } from '@/api/practice'
import { usePracticeStore } from '@/stores/practice'

const route = useRoute()
const router = useRouter()
const practice = usePracticeStore()

const examinerSpeaking = computed(() => practice.phase === 'examiner_asks')
const isPreparing = computed(() => practice.phase === 'preparing')
const canAnswer = computed(() => practice.phase === 'user_answers' && !practice.paused)
const isFinished = computed(() => practice.phase === 'finished')

const recordButtonIcon = computed(() => {
  if (practice.buttonState === 'recording') return Square
  return Mic
})

const part2Stage = computed(() => (isPreparing.value ? 1 : 2))

const transcriptSegments = computed(() =>
  practice.transcripts.map((t, i) => ({
    id: t.turnId || `seg-${i}`,
    ...t,
  })),
)

const tips = computed(() => {
  if (practice.part === 2) {
    return [
      '利用准备时间在草稿区记下关键词',
      '覆盖 Cue Card 中的每个要点',
      '尽量说满 1-2 分钟，注意时态和连接词',
    ]
  }
  if (practice.part === 3) {
    return [
      '回答要具体，给出理由或例子',
      '可以使用 In my opinion / Generally speaking 等表达',
      '考官可能针对你的观点进一步追问',
    ]
  }
  return [
    '直接回答问题，再给 1-2 句展开',
    '不必使用很难的词汇，准确更重要',
    '每题回答 30 秒到 1 分钟为宜',
  ]
})

async function confirmEnd() {
  try {
    await ElMessageBox.confirm('结束本次练习？将生成练习总结。', '结束练习', {
      type: 'warning',
      confirmButtonText: '结束练习',
      cancelButtonText: '继续练习',
    })
  } catch {
    return
  }
  practice.endSession()
}

async function confirmRetry() {
  if (practice.buttonState !== 'recording') return
  try {
    await ElMessageBox.confirm('重来将清除当前回答，重新开始本题。', '重来本题', {
      type: 'warning',
      confirmButtonText: '重来',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  practice.retryTurn()
}

function fmt(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

onMounted(async () => {
  const topicId = route.query.topic as string
  const part = Number(route.query.part ?? 1) as 1 | 2 | 3
  if (!topicId) {
    router.replace({ name: 'topics' })
    return
  }
  const micReady = await practice.warmUpMic()
  if (!micReady) return // 视图显示麦克风引导
  await practice.start({ topicId, part })
})

onBeforeUnmount(() => {
  if (practice.phase !== 'finished') {
    practice.endSession()
  }
  practice.reset()
})
</script>

<template>
  <div class="practice">
    <!-- 顶栏：音色与语速 -->
    <div class="practice__bar">
      <div class="practice__topic">
        {{ practice.topic?.name_en ?? '口语练习' }}
        <span class="practice__part-tag">Part {{ practice.part }}</span>
      </div>
      <div class="practice__settings">
        <el-select
          :model-value="practice.accent"
          size="small"
          style="width: 170px"
          @update:model-value="(v: string) => practice.updateSettings({ accent: v })"
        >
          <el-option
            v-for="o in practice.accentOptions"
            :key="o.value"
            :value="o.value"
            :label="o.label"
          />
        </el-select>
        <el-select
          :model-value="practice.speed"
          size="small"
          style="width: 120px"
          @update:model-value="(v: string) => practice.updateSettings({ speed: v })"
        >
          <el-option
            v-for="o in practice.speedOptions"
            :key="o.value"
            :value="o.value"
            :label="o.label"
          />
        </el-select>
      </div>
    </div>

    <!-- 麦克风权限引导 -->
      <div v-if="practice.recorder.micDenied" class="practice__overlay">
      <div class="ielts-card mic-guide">
        <MicOff :size="36" color="var(--ielts-error)" />
        <h3>需要麦克风权限</h3>
        <p>请在浏览器地址栏的权限设置中允许麦克风访问，然后刷新页面。</p>
        <p class="mic-guide__tip">推荐使用最新版 Chrome 或 Edge 浏览器。</p>
        <el-button type="primary" @click="router.back()">返回</el-button>
      </div>
    </div>

    <!-- 重连提示 -->
    <div v-else-if="practice.fatalMessage" class="practice__overlay">
      <div class="ielts-card mic-guide">
        <h3>连接中断</h3>
        <p>{{ practice.fatalMessage }}</p>
        <el-button type="primary" @click="router.push({ name: 'topics' })">返回话题列表</el-button>
      </div>
    </div>

    <!-- 练习总结 -->
    <div v-else-if="isFinished" class="summary">
      <div class="summary__head ielts-card">
        <div>
          <h2 class="summary__title">练习完成 🎉</h2>
          <p class="summary__sub">
            {{ practice.topic?.name_en }} · Part {{ practice.part }} ·
            共 {{ practice.transcripts.length }} 轮作答
          </p>
        </div>
        <div class="summary__actions">
          <el-button @click="router.push({ name: 'topics' })">再选话题</el-button>
          <el-button
            type="primary"
            @click="router.push({ name: 'practice', query: { topic: route.query.topic, part: route.query.part } })"
          >
            再练一次
          </el-button>
        </div>
      </div>

      <div
        v-for="(seg, i) in transcriptSegments"
        :key="seg.id"
        class="summary__turn ielts-card"
      >
        <div class="summary__turn-head">
          <span class="summary__seq">{{ i + 1 }}</span>
          <span v-if="seg.isFollowup" class="ielts-badge ielts-badge--info">追问</span>
          <TurnAudioPlayer v-if="seg.turnId" :url="turnAudioUrl(practice.sessionId, seg.turnId)" />
        </div>
        <div class="summary__question">{{ seg.question }}</div>
        <div class="summary__answer" :class="{ 'is-empty': !seg.answer }">
          {{ seg.answer || '（未作答）' }}
        </div>
      </div>
      <el-empty v-if="transcriptSegments.length === 0" description="本次练习没有有效作答" />

      <p class="summary__note">完整四维评分与中文深度反馈将在评分模块上线后提供。</p>
    </div>

    <!-- 练习进行中 -->
    <template v-else>
      <!-- 进度 -->
      <div v-if="practice.part !== 2" class="practice__progress ielts-card">
        <el-progress
          :percentage="practice.questionTotal ? (practice.questionIndex / practice.questionTotal) * 100 : 0"
          :show-text="false"
          :stroke-width="6"
        />
        <span class="practice__progress-label mono">
          {{ practice.questionIndex }}/{{ practice.questionTotal }} 题
        </span>
      </div>

      <div v-else class="p2-stages">
        <div class="p2-stage" :class="{ 'is-active': part2Stage === 1, 'is-done': part2Stage > 1 }">
          <span class="p2-stage__num">1</span> 准备时间
        </div>
        <div class="p2-stage__line" :class="{ 'is-done': part2Stage > 1 }"></div>
        <div class="p2-stage" :class="{ 'is-active': part2Stage === 2 }">
          <span class="p2-stage__num">2</span> 独白录音
        </div>
      </div>

      <div class="practice__grid" :class="{ 'is-p2': practice.part === 2 }">
        <!-- 左：考官 / Cue Card -->
        <div v-if="practice.part === 2" class="cue-card ielts-card">
          <template v-if="isPreparing || practice.cueCard">
            <div class="cue-card__head">
              <span class="ielts-badge ielts-badge--warning">Cue Card</span>
              <span v-if="isPreparing" class="cue-card__countdown mono">
                {{ fmt(practice.prepCountdown) }}
              </span>
            </div>
            <div class="cue-card__prompt">{{ practice.cueCard?.prompt }}</div>
            <ul v-if="practice.cueCard?.you_should_say?.length" class="cue-card__points">
              <li v-for="(point, i) in practice.cueCard?.you_should_say" :key="i">
                {{ point }}
              </li>
            </ul>
            <div v-if="practice.cueCard?.summary_zh" class="cue-card__summary">
              {{ practice.cueCard.summary_zh }}
            </div>
          </template>
        </div>

        <div v-else class="examiner-card ielts-card">
          <div class="examiner-card__head">
            <div class="examiner-card__avatar">
              <Mic :size="18" color="#fff" />
              <span class="examiner-card__online"></span>
            </div>
            <div>
              <div class="examiner-card__name">AI 考官</div>
              <div class="examiner-card__status">
                {{ examinerSpeaking ? '正在提问…' : isPreparing ? '请准备' : '等待你作答' }}
              </div>
            </div>
          </div>
          <div class="examiner-card__question" :class="{ 'is-speaking': examinerSpeaking }">
            {{ practice.currentQuestion || '…' }}
          </div>
          <ul class="examiner-card__tips">
            <li v-for="(tip, i) in tips" :key="i">
              <ChevronRight :size="12" />{{ tip }}
            </li>
          </ul>
        </div>

        <!-- 右：转写 / 笔记 -->
        <div v-if="practice.part === 2 && isPreparing" class="notes-card ielts-card">
          <div class="notes-card__title">关键词笔记</div>
          <el-input
            v-model="practice.notes"
            type="textarea"
            :rows="8"
            placeholder="在准备时间记下要点，例如：who / when / what happened / why memorable…"
            resize="none"
          />
          <el-button type="primary" class="notes-card__start" @click="practice.p2Ready()">
            准备好了，开始作答
          </el-button>
        </div>

        <div v-else class="transcript-card ielts-card">
          <div class="transcript-card__head">
            <span class="transcript-card__title">实时转写</span>
            <span
              v-if="practice.buttonState === 'recording'"
              class="ielts-badge ielts-badge--success"
            >
              <span class="ielts-dot"></span>录音中
            </span>
            <span v-else-if="practice.paused" class="ielts-badge ielts-badge--warning">已暂停</span>
            <span v-else class="ielts-badge ielts-badge--muted">待作答</span>
          </div>
          <div class="transcript-card__body">
            <div v-for="seg in transcriptSegments" :key="seg.id" class="transcript-seg">
              <span class="transcript-seg__text">{{ seg.answer }}</span>
            </div>
            <div v-if="practice.partialText" class="transcript-seg is-live">
              <span class="transcript-seg__text">{{ practice.partialText }}</span>
            </div>
            <div v-if="!practice.partialText && practice.buttonState !== 'recording'" class="transcript-empty">
              {{ practice.part === 2 ? '准备时间结束后自动进入录音' : '点击下方按钮开始作答，说出你的回答' }}
            </div>
          </div>
          <div class="transcript-card__foot">
            <span class="mono">{{ fmt(practice.turnElapsed) }} / {{ fmt(practice.turnMaxSeconds) }}</span>
            <span v-if="practice.recorder.noisy" class="transcript-card__noise">
              ⚠ 环境噪音较大
            </span>
            <!-- 音量指示 -->
            <span class="level-meter">
              <span
                class="level-meter__bar"
                :style="{ transform: `scaleY(${Math.max(0.08, practice.recorder.level)})` }"
              ></span>
            </span>
          </div>
        </div>
      </div>

      <!-- 底部控制条 -->
      <div class="controls">
        <div class="controls__left">
          <el-button size="small" :disabled="!canAnswer" @click="practice.togglePause()">
            <component :is="practice.paused ? Play : Pause" :size="14" style="margin-right:4px" />
            {{ practice.paused ? '继续' : '暂停' }}
          </el-button>
          <el-button size="small" :disabled="practice.buttonState !== 'recording'" @click="confirmRetry">
            <Redo :size="14" style="margin-right:4px" />重来
          </el-button>
        </div>

        <button
          class="controls__record"
          :class="{
            'is-recording': practice.buttonState === 'recording',
            'is-disabled': !canAnswer,
          }"
          :disabled="!canAnswer"
          @click="practice.buttonState === 'recording' ? practice.endAnswer() : practice.beginAnswer()"
        >
          <component :is="recordButtonIcon" :size="24" color="#fff" />
        </button>

        <div class="controls__right">
          <el-button size="small" type="danger" plain @click="confirmEnd">结束练习</el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.practice {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - var(--ielts-topbar-height) - 48px);
}

.practice__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.practice__topic {
  font-size: var(--ielts-text-md);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.practice__part-tag {
  font-size: var(--ielts-text-xs);
  font-weight: 500;
  color: var(--ielts-accent-foreground);
  background: var(--ielts-accent);
  padding: 2px 8px;
  border-radius: var(--ielts-radius-full);
}

.practice__settings {
  display: flex;
  gap: 8px;
}

.practice__overlay {
  display: grid;
  place-items: center;
  flex: 1;
}

.mic-guide {
  padding: 40px 48px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  max-width: 420px;
}

.mic-guide h3 {
  font-size: var(--ielts-text-lg);
}

.mic-guide p {
  margin: 0;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
}

.mic-guide__tip {
  font-size: var(--ielts-text-xs) !important;
}

.practice__progress {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
}

.practice__progress :deep(.el-progress) {
  flex: 1;
}

.practice__progress-label {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

/* Part 2 阶段指示器 */
.p2-stages {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  background: var(--ielts-card);
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
}

.p2-stage {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.p2-stage__num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid var(--ielts-border);
  display: grid;
  place-items: center;
  font-size: var(--ielts-text-xs);
}

.p2-stage.is-active {
  color: var(--ielts-primary);
  font-weight: 500;
}

.p2-stage.is-active .p2-stage__num {
  background: var(--ielts-primary);
  border-color: var(--ielts-primary);
  color: #fff;
}

.p2-stage.is-done {
  color: var(--ielts-accent-foreground);
}

.p2-stage__line {
  flex: 1;
  height: 1px;
  background: var(--ielts-border);
}

.p2-stage__line.is-done {
  background: var(--ielts-primary);
}

/* 主网格 */
.practice__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  flex: 1;
}

@media (max-width: 900px) {
  .practice__grid {
    grid-template-columns: 1fr;
  }
}

/* 考官卡 */
.examiner-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.examiner-card__head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.examiner-card__avatar {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--ielts-primary);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.examiner-card__online {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ielts-success);
  border: 2px solid var(--ielts-card);
}

.examiner-card__name {
  font-size: var(--ielts-text-md);
  font-weight: 600;
}

.examiner-card__status {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.examiner-card__question {
  background: var(--ielts-muted);
  border-radius: var(--ielts-radius-md);
  padding: 18px;
  font-size: var(--ielts-text-lg);
  line-height: 1.6;
  min-height: 90px;
  transition: box-shadow 0.2s;
}

.examiner-card__question.is-speaking {
  box-shadow: inset 0 0 0 1px var(--ielts-ring);
}

.examiner-card__tips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.examiner-card__tips li {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

/* Cue Card */
.cue-card {
  padding: 20px;
  border-color: color-mix(in srgb, var(--ielts-primary) 25%, var(--ielts-border));
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cue-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cue-card__countdown {
  font-size: var(--ielts-text-xl);
  font-weight: 600;
  color: var(--ielts-warning);
}

.cue-card__prompt {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
  line-height: 1.5;
}

.cue-card__points {
  list-style: none;
  margin: 0;
  padding: 0 0 0 4px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cue-card__points li {
  padding-left: 14px;
  position: relative;
  font-size: var(--ielts-text-base);
  color: var(--ielts-slate-700);
}

.cue-card__points li::before {
  content: '–';
  position: absolute;
  left: 0;
  color: var(--ielts-primary);
}

.cue-card__summary {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  border-top: 1px dashed var(--ielts-border);
  padding-top: 10px;
}

/* 笔记卡 */
.notes-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notes-card__title {
  font-size: var(--ielts-text-base);
  font-weight: 500;
}

.notes-card__start {
  margin-top: auto;
}

/* 转写卡 */
.transcript-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.transcript-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.transcript-card__title {
  font-size: var(--ielts-text-base);
  font-weight: 500;
}

.transcript-card__body {
  flex: 1;
  min-height: 220px;
  max-height: 360px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--ielts-slate-50);
  border-radius: var(--ielts-radius-md);
  padding: 14px;
}

.transcript-seg__text {
  font-size: var(--ielts-text-base);
  line-height: 1.6;
}

.transcript-seg.is-live .transcript-seg__text {
  color: var(--ielts-muted-foreground);
}

.transcript-empty {
  margin: auto;
  color: var(--ielts-slate-400);
  font-size: var(--ielts-text-sm);
  text-align: center;
}

.transcript-card__foot {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.transcript-card__noise {
  color: var(--ielts-warning);
  font-size: var(--ielts-text-xs);
}

.level-meter {
  margin-left: auto;
  width: 4px;
  height: 16px;
  background: var(--ielts-muted);
  border-radius: 2px;
  overflow: hidden;
  display: grid;
  align-items: end;
}

.level-meter__bar {
  display: block;
  width: 100%;
  height: 100%;
  background: var(--ielts-success);
  transform-origin: bottom;
  transition: transform 0.1s;
}

/* 控制条 */
.controls {
  position: sticky;
  bottom: 16px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 12px 20px;
  background: var(--ielts-card);
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-lg);
  box-shadow: var(--ielts-shadow-float);
}

.controls__left {
  display: flex;
  gap: 8px;
  justify-self: start;
}

.controls__right {
  justify-self: end;
}

.controls__record {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  border: none;
  background: var(--ielts-primary);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: pointer;
  box-shadow: 0 6px 16px -6px color-mix(in srgb, var(--ielts-primary) 60%, transparent);
  transition: transform 0.15s, background 0.15s;
}

.controls__record:hover:not(:disabled) {
  transform: scale(1.05);
}

.controls__record.is-recording {
  background: var(--ielts-error);
  animation: pulse 1.6s infinite;
}

.controls__record.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--ielts-error) 40%, transparent);
  }
  70% {
    box-shadow: 0 0 0 16px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

/* 总结 */
.summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px;
  gap: 16px;
  flex-wrap: wrap;
}

.summary__title {
  font-size: var(--ielts-text-xl);
}

.summary__sub {
  margin: 4px 0 0;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
}

.summary__turn {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary__turn-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.summary__seq {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
  font-size: var(--ielts-text-xs);
  font-weight: 600;
}

.summary__question {
  font-size: var(--ielts-text-base);
  font-weight: 500;
}

.summary__answer {
  font-size: var(--ielts-text-base);
  line-height: 1.7;
  color: var(--ielts-slate-700);
  background: var(--ielts-slate-50);
  padding: 12px 14px;
  border-radius: var(--ielts-radius-md);
  white-space: pre-wrap;
}

.summary__answer.is-empty {
  color: var(--ielts-slate-400);
}

.summary__note {
  text-align: center;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-xs);
}
</style>
