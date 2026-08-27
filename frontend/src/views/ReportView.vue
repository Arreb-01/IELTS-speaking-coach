<script setup lang="ts">
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  Loader2,
  RefreshCw,
  RotateCcw,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  fetchReport,
  rescorePractice,
  type ScoreReportDetail,
  type SentenceAnalysis,
} from '@/api/reports'
import { updateProfile } from '@/api/auth'
import { turnAudioUrl } from '@/api/practice'
import VChart from '@/plugins/echarts'
import TurnAudioPlayer from '@/components/TurnAudioPlayer.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId as string

const report = ref<ScoreReportDetail | null>(null)
const loading = ref(true)
const rescoring = ref(false)
const loadError = ref('')
let pollTimer: number | null = null
let pollCount = 0

const LOADING_STEPS = [
  '正在统计流利度指标…',
  '正在分析您的发音…',
  '考官正在逐句审阅…',
  '正在生成中文深度反馈…',
]
const loadingStep = computed(() =>
  LOADING_STEPS[Math.min(Math.floor(pollCount / 4), LOADING_STEPS.length - 1)],
)

async function load() {
  loading.value = !report.value
  try {
    report.value = await fetchReport(sessionId)
    loadError.value = ''
  } catch {
    loadError.value = '报告加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  maybeStartPolling()
})

onBeforeUnmount(stopPolling)

/** 需要继续轮询：评分进行中，或已完成但深度分析（逐句/反馈）还在后台生成 */
function needPoll(): boolean {
  const r = report.value
  if (!r) return false
  if (['pending', 'processing'].includes(r.status)) return true
  return r.status === 'completed' && !r.overall_comment_zh && pollCount < 130
}

function maybeStartPolling() {
  if (pollTimer !== null || !needPoll()) return
  pollTimer = window.setInterval(async () => {
    pollCount += 1
    await load()
    if (!needPoll()) stopPolling()
  }, 1500)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function handleRescore() {
  rescoring.value = true
  try {
    await rescorePractice(sessionId)
    ElMessage.success('已重新开始评分')
    pollCount = 0
    await load()
    maybeStartPolling()
  } catch {
    ElMessage.error('重新评分失败，请稍后重试')
  } finally {
    rescoring.value = false
  }
}

// ------------------------------------------------------------------
// 能力测评出分后：设定目标分数（users.target_band 为空才提示）
// ------------------------------------------------------------------

const auth = useAuthStore()
const targetDialogVisible = ref(false)
const targetDraft = ref<number | null>(null)
const savingTarget = ref(false)

const TARGET_OPTIONS = Array.from({ length: 11 }, (_, i) =>
  Number((4 + i * 0.5).toFixed(1)),
)

watch(
  () => report.value?.status,
  (status) => {
    if (
      status === 'completed' &&
      report.value?.session?.is_placement &&
      auth.user?.target_band == null
    ) {
      targetDialogVisible.value = true
    }
  },
)

async function saveTarget() {
  if (targetDraft.value == null) return
  savingTarget.value = true
  try {
    const user = await updateProfile({ target_band: targetDraft.value })
    auth.user = user
    targetDialogVisible.value = false
    ElMessage.success('目标分数已保存')
    router.push({ name: 'dashboard' })
  } catch {
    ElMessage.error('保存失败，请稍后重试')
  } finally {
    savingTarget.value = false
  }
}

// ------------------------------------------------------------------
// 展示推导
// ------------------------------------------------------------------

const isCompleted = computed(() => report.value?.status === 'completed')
const isFailed = computed(() => report.value?.status === 'failed')
const isProcessing = computed(
  () => loading.value || (report.value && ['pending', 'processing'].includes(report.value.status)),
)
const deepPending = computed(() => {
  const r = report.value
  return Boolean(
    r && r.status === 'completed' && !r.overall_comment_zh,
  )
})
const feedbackPending = deepPending

const dimensions = computed(() => [
  { key: 'fluency', label: '流利度', value: report.value?.fluency },
  { key: 'lexical', label: '词汇', value: report.value?.lexical },
  { key: 'grammar', label: '语法', value: report.value?.grammar },
  { key: 'pronunciation', label: '发音', value: report.value?.pronunciation },
])

const radarOption = computed(() => ({
  color: ['#0f766e'],
  radar: {
    indicator: [
      { name: '流利度', max: 9 },
      { name: '词汇', max: 9 },
      { name: '语法', max: 9 },
      { name: '发音', max: 9 },
    ],
    radius: '65%',
    splitNumber: 4,
    axisName: { color: '#64748b' },
    splitArea: {
      areaStyle: { color: ['#f8fafc', '#f1f5f9', '#e2e8f0', '#cbd5e1'] },
    },
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          value: dimensions.value.map((d) => d.value ?? 0),
          name: '本次评分',
          areaStyle: { opacity: 0.2 },
        },
      ],
    },
  ],
}))

/** 薄弱项分析卡：四维中最弱两项（error/warning）+ 最强一项（success） */
const weaknessCards = computed(() => {
  const dims = dimensions.value
    .filter((d) => d.value != null)
    .map((d) => ({ ...d, value: d.value as number }))
  if (dims.length < 3) return []
  const sorted = [...dims].sort((a, b) => a.value - b.value)
  const tone = (v: number) => (v < 5.5 ? 'error' : v < 6.5 ? 'warning' : 'success')
  return [
    { ...sorted[0], tone: tone(sorted[0].value) },
    { ...sorted[1], tone: tone(sorted[1].value) },
    { ...sorted[sorted.length - 1], tone: 'success' },
  ]
})

const ISSUE_META: Record<string, { label: string; tone: 'error' | 'warning' | 'info' }> = {
  grammar: { label: '语法', tone: 'error' },
  vocab: { label: '词汇', tone: 'warning' },
  fluency: { label: '流利度', tone: 'warning' },
  pronunciation: { label: '发音', tone: 'info' },
}
const SEVERITY_LABEL: Record<string, { label: string; tone: string }> = {
  minor: { label: '轻微', tone: 'muted' },
  moderate: { label: '中等', tone: 'warning' },
  major: { label: '较高', tone: 'error' },
}

interface AnalysisRow {
  seq: number
  sentence: SentenceAnalysis
  turnId: string
  hasAudio: boolean
}

/** 逐句表行：把 turn_analyses 拉平成一行一句（跳过无句子数据的轮次） */
const analysisRows = computed<AnalysisRow[]>(() => {
  const rows: AnalysisRow[] = []
  for (const ta of report.value?.turn_analyses ?? []) {
    for (const sentence of ta.sentences ?? []) {
      rows.push({ seq: ta.seq, sentence, turnId: ta.turn_id, hasAudio: true })
    }
  }
  return rows
})

const LOW_CONFIDENCE_LABEL: Record<string, string> = {
  answer_too_short: '作答偏短，分数置信度有限',
  audio_noisy: '录音环境有噪音',
  dimension_spread: '四维差距较大，建议复核',
  llm_score_unavailable: 'LLM 评分暂不可用，部分维度为保守估计',
  pronunciation_missing: '发音评测不可用，发音分为文本侧估计',
  pronunciation_mock: '发音评测使用模拟数据',
}

const lowConfidenceTexts = computed(() =>
  (report.value?.low_confidence ?? []).map((f) => LOW_CONFIDENCE_LABEL[f] ?? f),
)

const fluencyMetrics = computed(() => {
  const m = (report.value?.fluency_metrics ?? {}) as Record<string, number | boolean>
  const wpm = typeof m.wpm === 'number' ? Math.round(m.wpm) : '--'
  const words = typeof m.total_words === 'number' ? m.total_words : '--'
  const pauses = typeof m.long_pause_count === 'number' ? m.long_pause_count : '--'
  const fillers = typeof m.filler_total === 'number' ? m.filler_total : '--'
  const seconds = typeof m.speech_seconds === 'number' ? Math.round(m.speech_seconds) : '--'
  return { wpm, words, pauses, fillers, seconds }
})

const partLabel = computed(() => {
  const part = report.value?.session?.part
  return part ? `Part ${part}` : ''
})

const topicLabel = computed(
  () => report.value?.session?.topic_name_zh || report.value?.session?.topic_name_en || '',
)

function practiceAgain() {
  router.push({ name: 'topics' })
}
</script>

<template>
  <div class="report">
    <!-- 顶部操作条 -->
    <div class="report__topbar">
      <button class="back-btn" @click="router.back()">
        <ChevronLeft :size="16" /> 返回
      </button>
      <div class="report__title">
        评分报告
        <span v-if="partLabel || topicLabel" class="report__subtitle">
          {{ [partLabel, topicLabel].filter(Boolean).join(' · ') }}
        </span>
      </div>
      <div class="report__actions">
        <button class="ghost-btn" :disabled="rescoring" @click="handleRescore">
          <RefreshCw :size="14" :class="{ 'is-spinning': rescoring }" />
          重新评分
        </button>
        <button class="primary-btn" @click="practiceAgain">
          <RotateCcw :size="14" /> 再练一次
        </button>
      </div>
    </div>

    <!-- 加载态 -->
    <div v-if="isProcessing" class="loading-card ielts-card">
      <Loader2 :size="28" class="loading-icon" />
      <div class="loading-title">正在生成你的评分报告</div>
      <div class="loading-step">{{ loadingStep }}</div>
      <div class="loading-bar"><div class="loading-bar__fill"></div></div>
      <p class="loading-hint">通常 10 秒内完成；完成后此页面会自动刷新</p>
    </div>

    <!-- 失败态 -->
    <div v-else-if="isFailed" class="failed-card ielts-card">
      <AlertCircle :size="28" class="failed-icon" />
      <div class="failed-title">评分未完成</div>
      <p class="failed-text">{{ report?.error || '生成评分时出现问题' }}</p>
      <div class="failed-actions">
        <button class="primary-btn" :disabled="rescoring" @click="handleRescore">
          <RefreshCw :size="14" :class="{ 'is-spinning': rescoring }" /> 重新评分
        </button>
      </div>
    </div>

    <!-- 报告主体 -->
    <template v-else-if="isCompleted && report">
      <!-- 低置信度提示 -->
      <div v-if="lowConfidenceTexts.length" class="low-confidence">
        <AlertCircle :size="14" />
        本报告存在以下标注：{{ lowConfidenceTexts.join('；') }}
      </div>

      <!-- Hero：综合 Band + 四维 -->
      <div class="hero ielts-card">
        <div class="hero__main">
          <div class="hero__band">
            <span class="hero__band-value">{{ report.overall_band?.toFixed(1) }}</span>
            <span class="hero__band-label">综合 Band</span>
          </div>
          <div class="hero__desc">
            <p class="hero__desc-label">本次练习表现</p>
            <p class="hero__desc-text">
              {{ report.overall_comment_zh || '反馈生成中，稍后将自动补充…' }}
            </p>
          </div>
        </div>
        <div class="hero__dims">
          <div v-for="d in dimensions" :key="d.key" class="dim-cell">
            <p class="dim-cell__label">{{ d.label }}</p>
            <p class="dim-cell__value">{{ d.value != null ? d.value.toFixed(1) : '--' }}</p>
          </div>
        </div>
      </div>

      <!-- 雷达 + 薄弱项 -->
      <div class="grid-2">
        <div class="ielts-card section">
          <h2 class="section__title">四维能力雷达</h2>
          <VChart :option="radarOption" class="radar-chart" autoresize />
          <div class="metrics-strip">
            <div class="metric">
              <span class="metric__value">{{ fluencyMetrics.wpm }}</span>
              <span class="metric__label">词/分钟</span>
            </div>
            <div class="metric">
              <span class="metric__value">{{ fluencyMetrics.words }}</span>
              <span class="metric__label">总词数</span>
            </div>
            <div class="metric">
              <span class="metric__value">{{ fluencyMetrics.pauses }}</span>
              <span class="metric__label">长停顿</span>
            </div>
            <div class="metric">
              <span class="metric__value">{{ fluencyMetrics.fillers }}</span>
              <span class="metric__label">填充词</span>
            </div>
            <div class="metric">
              <span class="metric__value">{{ fluencyMetrics.seconds }}s</span>
              <span class="metric__label">发言时长</span>
            </div>
          </div>
        </div>
        <div class="ielts-card section">
          <h2 class="section__title">薄弱项分析</h2>
          <div v-if="weaknessCards.length" class="weakness-list">
            <div
              v-for="w in weaknessCards"
              :key="w.key + w.tone"
              class="weakness"
              :class="`weakness--${w.tone}`"
            >
              <div class="weakness__head">
                <AlertCircle v-if="w.tone !== 'success'" :size="15" />
                <CheckCircle2 v-else :size="15" />
                <span class="weakness__title">
                  {{ w.label }}：{{ w.value.toFixed(1) }}
                  {{ w.tone === 'success' ? '（本次最优）' : w.value < 5.5 ? '（重点提升）' : '（可加强）' }}
                </span>
              </div>
            </div>
          </div>
          <div v-else class="weakness-empty">分数数据不足</div>
        </div>
      </div>

      <!-- 逐句分析 -->
      <div class="ielts-card section">
        <h2 class="section__title">逐句分析</h2>
        <div v-if="analysisRows.length" class="table-wrap">
          <table class="sentence-table">
            <thead>
              <tr>
                <th class="col-seq">轮次</th>
                <th>转写文本</th>
                <th class="col-issue">问题类型</th>
                <th class="col-severity">严重度</th>
                <th class="col-audio">回放</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in analysisRows" :key="i">
                <td class="col-seq">#{{ row.seq }}</td>
                <td>
                  <span
                    v-if="row.sentence.issues.length"
                    class="sentence-problem"
                  >{{ row.sentence.text }}</span>
                  <span v-else>{{ row.sentence.text }}</span>
                  <div
                    v-for="(issue, j) in row.sentence.issues"
                    :key="j"
                    class="issue-detail"
                  >
                    <span class="issue-detail__explain">{{ issue.explanation_zh }}</span>
                    <span v-if="issue.suggestion" class="issue-detail__suggest">
                      建议：{{ issue.suggestion }}
                    </span>
                  </div>
                </td>
                <td class="col-issue">
                  <template v-if="row.sentence.issues.length">
                    <span
                      v-for="(issue, j) in row.sentence.issues.slice(0, 2)"
                      :key="j"
                      class="issue-badge"
                      :class="`issue-badge--${ISSUE_META[issue.type]?.tone || 'warning'}`"
                    >
                      {{ ISSUE_META[issue.type]?.label || issue.type }}
                    </span>
                  </template>
                  <span v-else class="issue-badge issue-badge--success">无误</span>
                </td>
                <td class="col-severity">
                  <template v-if="row.sentence.issues.length">
                    <span
                      v-for="(issue, j) in row.sentence.issues.slice(0, 2)"
                      :key="j"
                      class="severity-text"
                      :class="`severity--${SEVERITY_LABEL[issue.severity]?.tone || 'warning'}`"
                    >
                      {{ SEVERITY_LABEL[issue.severity]?.label || issue.severity }}
                    </span>
                  </template>
                  <span v-else class="severity--muted">-</span>
                </td>
                <td class="col-audio">
                  <TurnAudioPlayer :url="turnAudioUrl(report.session_id, row.turnId)" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="weakness-empty">
          {{ deepPending ? '逐句分析生成中，完成后此处自动更新…' : '本次未生成逐句分析（可点击右上角重新评分重试）' }}
        </div>
      </div>

      <!-- 建议 + 高分表达 -->
      <div class="grid-2">
        <div class="ielts-card section">
          <h2 class="section__title">中文改进建议</h2>
          <div v-if="feedbackPending" class="weakness-empty">
            反馈生成中，页面稍后自动补充…
          </div>
          <ol v-else-if="report.improvements?.length" class="advice-list">
            <li v-for="(item, i) in report.improvements" :key="i">
              <span class="advice-list__num">{{ i + 1 }}</span>
              <span>{{ item }}</span>
            </li>
          </ol>
          <div v-else class="weakness-empty">暂无建议</div>

          <template v-if="report.strengths?.length">
            <h3 class="section__subtitle">做得好的地方</h3>
            <ul class="strength-list">
              <li v-for="(s, i) in report.strengths" :key="i">
                <CheckCircle2 :size="14" /> {{ s }}
              </li>
            </ul>
          </template>
        </div>

        <div class="ielts-card section">
          <h2 class="section__title">高分表达替换</h2>
          <div v-if="report.expression_upgrades?.length" class="upgrades">
            <div
              v-for="(u, i) in report.expression_upgrades"
              :key="i"
              class="upgrade"
            >
              <div class="upgrade__side">
                <p class="upgrade__label">你用了</p>
                <p class="upgrade__original">{{ u.original }}</p>
              </div>
              <ArrowRight :size="15" class="upgrade__arrow" />
              <div class="upgrade__side is-right">
                <p class="upgrade__label">可替换为</p>
                <p class="upgrade__target">{{ u.upgraded }}</p>
                <p v-if="u.note_zh" class="upgrade__note">{{ u.note_zh }}</p>
              </div>
            </div>
          </div>
          <div v-else class="weakness-empty">
            {{ feedbackPending ? '反馈生成中…' : '暂无替换建议' }}
          </div>
        </div>
      </div>
    </template>

    <!-- 加载失败且无报告 -->
    <div v-else-if="loadError" class="failed-card ielts-card">
      <AlertCircle :size="28" class="failed-icon" />
      <div class="failed-title">{{ loadError }}</div>
      <div class="failed-actions">
        <button class="primary-btn" @click="load">重试</button>
      </div>
    </div>

    <!-- 能力测评出分后：设定目标分数 -->
    <el-dialog
      v-model="targetDialogVisible"
      title="设定你的目标分数"
      width="400px"
      :close-on-click-modal="false"
    >
      <p class="target-dialog__tip">
        目标分数用于生成你的专属学习路径：计算目标差距、预测达成时间，
        并安排每日练习强度。之后也可以在首页修改。
      </p>
      <el-select v-model="targetDraft" placeholder="选择目标 Band" style="width: 100%">
        <el-option v-for="opt in TARGET_OPTIONS" :key="opt" :label="`Band ${opt}`" :value="opt" />
      </el-select>
      <template #footer>
        <el-button @click="targetDialogVisible = false">稍后再说</el-button>
        <el-button type="primary" :loading="savingTarget" @click="saveTarget">
          保存并查看学习路径
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.target-dialog__tip {
  margin: 0 0 14px;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  line-height: 1.6;
}

.report {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ---- 顶部操作条 ---- */
.report__topbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: none;
  background: none;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  cursor: pointer;
  padding: 6px 8px;
  border-radius: var(--ielts-radius-sm);
}

.back-btn:hover {
  color: var(--ielts-foreground);
  background: var(--ielts-muted);
}

.report__title {
  flex: 1;
  font-size: var(--ielts-text-xl);
  font-weight: 600;
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.report__subtitle {
  font-size: var(--ielts-text-sm);
  font-weight: 400;
  color: var(--ielts-muted-foreground);
}

.report__actions {
  display: flex;
  gap: 8px;
}

.ghost-btn,
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ielts-text-sm);
  border-radius: var(--ielts-radius-md);
  padding: 7px 14px;
  cursor: pointer;
  transition: opacity 0.15s, background 0.15s;
}

.ghost-btn {
  border: 1px solid var(--ielts-border);
  background: var(--ielts-card);
  color: var(--ielts-muted-foreground);
}

.ghost-btn:hover:not(:disabled) {
  color: var(--ielts-foreground);
}

.primary-btn {
  border: none;
  background: var(--ielts-primary);
  color: var(--ielts-primary-foreground);
  font-weight: 500;
}

.primary-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.ghost-btn:disabled,
.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.is-spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ---- 低置信度 ---- */
.low-confidence {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ielts-text-xs);
  color: var(--state-warning);
  background: var(--state-warning-bg);
  border: 1px solid var(--state-warning);
  border-radius: var(--ielts-radius-md);
  padding: 8px 12px;
}

/* ---- 加载/失败 ---- */
.loading-card,
.failed-card {
  padding: 56px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}

.loading-icon {
  color: var(--ielts-primary);
  animation: spin 1.2s linear infinite;
}

.loading-title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
}

.loading-step {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.loading-bar {
  width: 240px;
  height: 4px;
  border-radius: 999px;
  background: var(--ielts-muted);
  overflow: hidden;
  margin-top: 8px;
}

.loading-bar__fill {
  height: 100%;
  width: 40%;
  border-radius: 999px;
  background: var(--ielts-primary);
  animation: slide 1.4s ease-in-out infinite;
}

@keyframes slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(340%);
  }
}

.loading-hint {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.failed-icon {
  color: var(--state-error);
}

.failed-title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
}

.failed-text {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  max-width: 480px;
}

/* ---- Hero ---- */
.hero {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

@media (min-width: 900px) {
  .hero {
    flex-direction: row;
    align-items: center;
  }
}

.hero__main {
  display: flex;
  align-items: center;
  gap: 20px;
  min-width: 0;
}

.hero__band {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--ielts-primary) 10%, transparent);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.hero__band-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--ielts-primary);
  line-height: 1.1;
}

.hero__band-label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.hero__desc {
  min-width: 0;
}

.hero__desc-label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin: 0 0 4px;
}

.hero__desc-text {
  font-size: var(--ielts-text-md);
  margin: 0;
}

.hero__dims {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

@media (min-width: 720px) {
  .hero__dims {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.dim-cell {
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  padding: 12px 8px;
  text-align: center;
}

.dim-cell__label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin: 0 0 4px;
}

.dim-cell__value {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
}

/* ---- 通用分区 ---- */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
}

@media (min-width: 900px) {
  .grid-2 {
    grid-template-columns: 1fr 1fr;
  }
}

.section {
  padding: 20px;
}

.section__title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
  margin: 0 0 16px;
}

.section__subtitle {
  font-size: var(--ielts-text-md);
  font-weight: 600;
  margin: 20px 0 10px;
}

.radar-chart {
  width: 100%;
  height: 260px;
}

.metrics-strip {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid var(--ielts-border);
  padding-top: 12px;
  margin-top: 8px;
}

.metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.metric__value {
  font-size: var(--ielts-text-md);
  font-weight: 600;
}

.metric__label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

/* ---- 薄弱项 ---- */
.weakness-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.weakness {
  border-radius: var(--ielts-radius-md);
  padding: 14px;
  border: 1px solid transparent;
}

.weakness--error {
  background: var(--state-error-bg);
  border-color: color-mix(in srgb, var(--state-error) 25%, transparent);
  color: var(--state-error);
}

.weakness--warning {
  background: var(--state-warning-bg);
  border-color: color-mix(in srgb, var(--state-warning) 25%, transparent);
  color: var(--state-warning);
}

.weakness--success {
  background: var(--state-success-bg);
  border-color: color-mix(in srgb, var(--state-success) 25%, transparent);
  color: var(--state-success);
}

.weakness__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.weakness__title {
  font-size: var(--ielts-text-sm);
  font-weight: 600;
  color: var(--ielts-foreground);
}

.weakness-empty {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  padding: 20px 0;
  text-align: center;
}

/* ---- 逐句分析表 ---- */
.table-wrap {
  overflow-x: auto;
}

.sentence-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ielts-text-sm);
}

.sentence-table th {
  text-align: left;
  font-weight: 500;
  color: var(--ielts-muted-foreground);
  border-bottom: 1px solid var(--ielts-border);
  padding: 8px 10px;
  white-space: nowrap;
}

.sentence-table td {
  border-bottom: 1px solid color-mix(in srgb, var(--ielts-border) 50%, transparent);
  padding: 12px 10px;
  vertical-align: top;
}

.sentence-table tr:hover td {
  background: color-mix(in srgb, var(--ielts-muted) 50%, transparent);
}

.col-seq,
.col-severity,
.col-audio {
  white-space: nowrap;
}

.sentence-problem {
  text-decoration-color: var(--state-error);
}

.issue-detail {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.issue-detail__explain,
.issue-detail__suggest {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.issue-detail__suggest {
  color: var(--ielts-primary);
}

.issue-badge {
  display: inline-block;
  font-size: var(--ielts-text-xs);
  border-radius: var(--ielts-radius-sm);
  padding: 2px 8px;
  margin: 2px 4px 2px 0;
}

.issue-badge--error {
  background: var(--state-error-bg);
  color: var(--state-error);
}

.issue-badge--warning {
  background: var(--state-warning-bg);
  color: var(--state-warning);
}

.issue-badge--info {
  background: var(--state-info-bg, var(--ielts-accent));
  color: var(--ielts-primary);
}

.issue-badge--success {
  background: var(--state-success-bg);
  color: var(--state-success);
}

.severity-text {
  display: block;
  font-size: var(--ielts-text-xs);
}

.severity--error {
  color: var(--state-error);
}

.severity--warning {
  color: var(--state-warning);
}

.severity--muted {
  color: var(--ielts-muted-foreground);
}

/* ---- 建议 / 高分表达 ---- */
.advice-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.advice-list li {
  display: flex;
  gap: 10px;
  font-size: var(--ielts-text-sm);
  line-height: 1.6;
}

.advice-list__num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--ielts-primary);
  color: var(--ielts-primary-foreground);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 3px;
}

.strength-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.strength-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--ielts-text-sm);
  line-height: 1.6;
  color: var(--ielts-muted-foreground);
}

.strength-list svg {
  color: var(--state-success);
  flex-shrink: 0;
  margin-top: 4px;
}

.upgrades {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.upgrade {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  padding: 12px 14px;
}

.upgrade__side {
  min-width: 0;
  flex: 1;
}

.upgrade__side.is-right {
  text-align: right;
}

.upgrade__label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin: 0 0 2px;
}

.upgrade__original {
  font-size: var(--ielts-text-sm);
  color: var(--state-error);
  text-decoration: line-through;
  margin: 0;
  word-break: break-word;
}

.upgrade__target {
  font-size: var(--ielts-text-sm);
  font-weight: 500;
  color: var(--state-success);
  margin: 0;
  word-break: break-word;
}

.upgrade__note {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin: 4px 0 0;
}

.upgrade__arrow {
  color: var(--ielts-muted-foreground);
  flex-shrink: 0;
}
</style>
