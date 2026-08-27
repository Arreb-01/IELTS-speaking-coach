<script setup lang="ts">
import {
  BookOpenCheck,
  CalendarCheck,
  ChevronRight,
  Flame,
  Mic,
  PencilLine,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { updateProfile } from '@/api/auth'
import {
  fetchOverview,
  startPlacement,
  type DashboardOverview,
  type DailyTaskItem,
} from '@/api/dashboard'
import VChart from '@/plugins/echarts'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const auth = useAuthStore()
const router = useRouter()

const overview = ref<DashboardOverview | null>(null)
const loading = ref(true)
const startingPlacement = ref(false)

onMounted(async () => {
  try {
    overview.value = await fetchOverview()
    if (!overview.value.needs_placement) await auth.fetchUser()
  } finally {
    loading.value = false
  }
})

// ---- 初始能力测评入口 ----
async function beginPlacement() {
  startingPlacement.value = true
  try {
    await startPlacement() // 校验资格并创建会话（练习页直接复用）
    router.push({ name: 'practice', query: { placement: '1' } })
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '发起测评失败，请稍后重试')
  } finally {
    startingPlacement.value = false
  }
}

// ---- 四维雷达 ----
const DIM_META = [
  { key: 'fluency', label: '流利度' },
  { key: 'lexical', label: '词汇' },
  { key: 'grammar', label: '语法' },
  { key: 'pronunciation', label: '发音' },
] as const

const radarOption = computed(() => ({
  color: ['#0f766e'],
  radar: {
    indicator: DIM_META.map((d) => ({ name: d.label, max: 9 })),
    radius: '62%',
    axisName: { color: '#64748b', fontSize: 12 },
    axisLine: { lineStyle: { color: '#e2e8f0' } },
    splitLine: { lineStyle: { color: '#e2e8f0' } },
    splitArea: { areaStyle: { color: ['#ffffff', '#f8fafc'] } },
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          value: DIM_META.map((d) => overview.value?.radar?.[d.key] ?? 0),
          name: '近5次均值',
          areaStyle: { opacity: 0.14 },
          symbolSize: 5,
        },
      ],
    },
  ],
}))

// ---- 提分趋势折线 ----
const trendOption = computed(() => {
  const points = overview.value?.trend_points ?? []
  return {
    color: ['#0f766e'],
    grid: { left: 36, right: 16, top: 20, bottom: 26 },
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: points.map((p) => p.date.slice(5)),
      axisLabel: { color: '#64748b' },
    },
    yAxis: {
      type: 'value' as const,
      min: 3,
      max: 9,
      interval: 1,
      axisLabel: { color: '#64748b' },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [
      {
        name: '综合',
        type: 'line' as const,
        data: points.map((p) => p.overall_band),
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2.5 },
        areaStyle: { opacity: 0.08 },
        connectNulls: true,
      },
    ],
  }
})

// ---- 今日推荐卡路由 ----
function goTask(task: DailyTaskItem) {
  if (!task.topic_id) return
  if (task.payload?.action === 'practice') {
    router.push({
      name: 'practice',
      query: { topic: task.topic_id, part: String(task.part ?? 1) },
    })
    return
  }
  // 发音跟读 / 表达学习：进入话题详情页
  router.push({ name: 'topic-detail', params: { topicId: task.topic_id } })
}

const TASK_TYPE_META: Record<string, { label: string; icon: typeof Mic }> = {
  topic: { label: '话题练习', icon: Mic },
  special: { label: '发音专项', icon: Sparkles },
  corpus: { label: '表达学习', icon: BookOpenCheck },
}

function formatPracticeDate(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

// ---- 目标分弹窗 ----
const targetDialogVisible = ref(false)
const targetDraft = ref<number | null>(null)
const savingTarget = ref(false)

const TARGET_OPTIONS = Array.from({ length: 11 }, (_, i) =>
  Number((4 + i * 0.5).toFixed(1)),
)

function openTargetDialog() {
  targetDraft.value = overview.value?.hero.target_band ?? null
  targetDialogVisible.value = true
}

async function saveTarget() {
  if (targetDraft.value == null) {
    ElMessage.warning('请选择目标分数')
    return
  }
  savingTarget.value = true
  try {
    await updateProfile({ target_band: targetDraft.value })
    await auth.fetchUser()
    overview.value = overview.value
      ? {
          ...overview.value,
          hero: { ...overview.value.hero, target_band: targetDraft.value },
        }
      : overview.value
    targetDialogVisible.value = false
    ElMessage.success('目标分数已更新')
  } catch {
    ElMessage.error('保存失败，请稍后重试')
  } finally {
    savingTarget.value = false
  }
}

function weekDeltaText(): string | null {
  const delta = overview.value?.hero.week_delta
  if (delta == null || overview.value?.hero.predicted.band == null) return null
  if (delta > 0) return `较上周 +${delta.toFixed(1)}`
  if (delta < 0) return `较上周 ${delta.toFixed(1)}`
  return '与上周持平'
}

// ---- 模板辅助 ----
const heroEtaText = computed(() => overview.value?.hero.eta_text ?? null)

const weakDim = computed(() => {
  for (const dim of overview.value?.radar_order ?? []) {
    return DIM_META.find((d) => d.key === dim) ?? null
  }
  return null
})

/** 今日推荐：pending 优先展示，最多 3 张卡 */
const recommendTasks = computed(() => {
  const tasks = [...(overview.value?.recommendations ?? [])]
  tasks.sort((a, b) => {
    const weight = (s: DailyTaskItem['status']) =>
      s === 'pending' ? 0 : s === 'skipped' ? 1 : 2
    return weight(a.status) - weight(b.status)
  })
  return tasks.slice(0, 3)
})
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- ========== 态一：未测评 → 测评引导卡 ========== -->
    <div v-if="overview?.needs_placement" class="placement-card ielts-card">
      <div class="placement-card__badge">
        <Sparkles :size="18" />
      </div>
      <h2 class="placement-card__title">完成能力测评，解锁专属学习计划</h2>
      <p class="placement-card__text">
        与 AI 考官进行 5 道简短问答（约 3 分钟），系统将据此生成你的四维能力画像，
        并定制每日练习路径与提分计划。
      </p>
      <ul class="placement-card__points">
        <li>AI 考官真人语速提问 · 自动录音识别</li>
        <li>流利度 / 词汇 / 语法 / 发音四维评分</li>
        <li>设定目标分数，获取预计达成时间</li>
      </ul>
      <button
        class="placement-card__cta"
        :disabled="startingPlacement"
        @click="beginPlacement"
      >
        {{ startingPlacement ? '正在准备…' : '开始能力测评（约 3 分钟）' }}
      </button>
    </div>

    <!-- ========== 态二：已测评但没有任何完整练习 ========== -->
    <div v-else-if="overview && !overview.has_any_practice" class="empty-card ielts-card">
      <div class="empty-card__icon"><Mic :size="28" /></div>
      <h2 class="empty-card__title">还没有完整的练习记录</h2>
      <p class="empty-card__text">从话题库挑一个熟悉的话题，和 AI 考官聊两句吧。</p>
      <RouterLink :to="{ name: 'topics' }" class="empty-card__cta">浏览话题练习库</RouterLink>
    </div>

    <!-- ========== 态三：正常 Dashboard ========== -->
    <template v-else-if="overview">
      <!-- Hero 统计 -->
      <div class="hero-grid">
        <div class="stat-card ielts-card is-clickable" @click="openTargetDialog">
          <div class="stat-card__label">
            <Target :size="14" /> 目标 Band
            <PencilLine :size="13" class="stat-card__edit" />
          </div>
          <div class="stat-card__value">
            {{ overview.hero.target_band ?? '--' }}
          </div>
          <div class="stat-card__hint">{{ heroEtaText ?? (overview.hero.target_band != null ? '点击修改目标分数' : '点击设置你的目标分数') }}</div>
        </div>

        <div class="stat-card ielts-card">
          <div class="stat-card__label"><TrendingUp :size="14" /> 当前预测 Band</div>
          <div class="stat-card__value">{{ overview.hero.predicted.band ?? '--' }}</div>
          <div class="stat-card__hint">
            {{
              weekDeltaText() ??
              (overview.hero.predicted.hint || '最近一次综合评分即为基线')
            }}
          </div>
        </div>

        <div class="stat-card ielts-card">
          <div class="stat-card__label"><CalendarCheck :size="14" /> 今日练习</div>
          <div class="stat-card__value">
            {{ overview.hero.today_done }}
            <span class="stat-card__unit">/ {{ Math.max(overview.hero.today_total, 1) }} 项任务</span>
          </div>
          <div class="today-bar">
            <div
              class="today-bar__fill"
              :style="{
                width:
                  (Math.min(
                    overview.hero.today_done,
                    Math.max(overview.hero.today_total, 1),
                  ) /
                    Math.max(overview.hero.today_total, 1)) *
                    100 +
                  '%',
              }"
            ></div>
          </div>
        </div>

        <div class="stat-card ielts-card">
          <div class="stat-card__label"><Flame :size="14" /> 连续打卡</div>
          <div class="stat-card__value">
            {{ overview.hero.streak_days }}<span class="stat-card__unit">天</span>
          </div>
          <div class="stat-card__hint">
            {{
              overview.hero.avg_session_minutes != null
                ? `单次平均 ${overview.hero.avg_session_minutes} 分钟`
                : '完成当日任意一次练习即打卡'
            }}
          </div>
        </div>
      </div>

      <!-- 主内容两列 -->
      <div class="main-grid">
        <div class="left-col">
          <!-- 四维雷达 -->
          <div class="ielts-card panel">
            <div class="panel__head">
              <h2 class="panel__title">四维能力画像</h2>
              <span class="panel__sub">近 5 次评分均值</span>
            </div>
            <VChart
              :option="radarOption"
              class="radar-chart"
              autoresize
            />
            <div class="dim-chips">
              <button
                v-for="d in DIM_META"
                :key="d.key"
                class="dim-chip"
                :class="{ 'is-weak': weakDim?.key === d.key }"
                :title="weakDim?.key === d.key ? '当前薄弱项' : `针对${d.label}推荐话题`"
                @click="router.push({ name: 'topics', query: { weak: d.key } })"
              >
                {{ d.label }}
                <span v-if="weakDim?.key === d.key" class="dim-chip__tag">弱项</span>
              </button>
            </div>
          </div>

          <!-- 提分趋势 -->
          <div class="ielts-card panel">
            <div class="panel__head">
              <h2 class="panel__title">提分趋势</h2>
              <RouterLink :to="{ name: 'reports' }" class="panel__link">
                全部报告 <ChevronRight :size="13" />
              </RouterLink>
            </div>
            <VChart
              v-if="overview.trend_points.length"
              :option="trendOption"
              class="trend-chart"
              autoresize
            />
            <div v-else class="chart-empty">完成第一次练习后这里会展示你的提分曲线</div>
          </div>
        </div>

        <div class="right-col">
          <!-- 今日推荐 -->
          <div class="ielts-card panel">
            <div class="panel__head">
              <h2 class="panel__title">今日推荐</h2>
              <RouterLink :to="{ name: 'plan' }" class="panel__link">
                学习路径 <ChevronRight :size="13" />
              </RouterLink>
            </div>
            <div v-if="recommendTasks.length" class="rec-list">
              <div
                v-for="task in recommendTasks"
                :key="task.id"
                class="rec-item"
                :class="{ 'is-done': task.status === 'done' }"
                role="button"
                tabindex="0"
                @click="goTask(task)"
                @keydown.enter="goTask(task)"
              >
                <div class="rec-item__icon">
                  <component :is="TASK_TYPE_META[task.task_type]?.icon ?? Mic" :size="15" />
                </div>
                <div class="rec-item__body">
                  <div class="rec-item__title">{{ task.title_zh }}</div>
                  <div class="rec-item__desc">{{ task.desc_zh }}</div>
                </div>
                <span class="rec-item__type">{{
                  TASK_TYPE_META[task.task_type]?.label ?? '任务'
                }}</span>
              </div>
            </div>
            <div v-else class="chart-empty">
              今天暂无推荐任务，去学习路径页看看本周安排吧
            </div>
          </div>

          <!-- 最近练习 -->
          <div class="ielts-card panel">
            <div class="panel__head">
              <h2 class="panel__title">最近练习</h2>
              <RouterLink :to="{ name: 'reports' }" class="panel__link">
                更多 <ChevronRight :size="13" />
              </RouterLink>
            </div>
            <div v-if="overview.recent_practices.length" class="recent-list">
              <div
                v-for="item in overview.recent_practices"
                :key="item.session_id"
                class="recent-item"
                role="button"
                tabindex="0"
                @click="router.push({ name: 'report-detail', params: { sessionId: item.session_id } })"
                @keydown.enter="
                  router.push({ name: 'report-detail', params: { sessionId: item.session_id } })
                "
              >
                <div class="recent-item__meta">
                  <span class="recent-item__part">Part {{ item.part }}</span>
                  <span class="recent-item__topic">{{
                    item.topic_name_zh || item.topic_name_en || '综合口语'
                  }}</span>
                </div>
                <div class="recent-item__side">
                  <span class="recent-item__date">{{ formatPracticeDate(item.started_at) }}</span>
                  <span
                    class="recent-item__band"
                    :class="{ 'is-none': item.overall_band == null }"
                  >
                    {{ item.overall_band != null ? item.overall_band.toFixed(1) : '待出分' }}
                  </span>
                </div>
              </div>
            </div>
            <div v-else class="chart-empty">还没有练习记录</div>
          </div>
        </div>
      </div>
    </template>

    <!-- 目标分数修改弹窗 -->
    <el-dialog v-model="targetDialogVisible" title="设定目标分数" width="360px">
      <p class="target-dialog__tip">
        目标分数用于计算你与目标的差距、预测达成时间，并指导每日任务的强度。
      </p>
      <el-select v-model="targetDraft" placeholder="选择目标 Band" style="width: 100%">
        <el-option v-for="opt in TARGET_OPTIONS" :key="opt" :label="`Band ${opt}`" :value="opt" />
      </el-select>
      <template #footer>
        <el-button @click="targetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingTarget" @click="saveTarget">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>


<style scoped>
/* 复用 script setup 的 computed：辅助文本 */
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* ---------- 测评引导 ---------- */
.placement-card {
  padding: 40px 32px;
  text-align: center;
  border-top: 3px solid var(--ielts-primary);
}

.placement-card__badge {
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  border-radius: var(--ielts-radius-lg);
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
}

.placement-card__title {
  font-size: var(--ielts-text-2xl);
  font-weight: 600;
  margin-bottom: 10px;
}

.placement-card__text {
  max-width: 520px;
  margin: 0 auto 18px;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-md);
  line-height: 1.7;
}

.placement-card__points {
  list-style: none;
  padding: 0;
  margin: 0 0 24px;
  display: flex;
  justify-content: center;
  gap: 22px;
  flex-wrap: wrap;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
}

.placement-card__points li::before {
  content: '✓';
  color: var(--ielts-primary);
  margin-right: 6px;
  font-weight: 600;
}

.placement-card__cta {
  border: none;
  background: var(--ielts-primary);
  color: var(--ielts-primary-foreground);
  font-size: var(--ielts-text-md);
  font-weight: 500;
  padding: 12px 30px;
  border-radius: var(--ielts-radius-full);
  cursor: pointer;
  transition: opacity 0.15s;
}

.placement-card__cta:hover {
  opacity: 0.9;
}

.placement-card__cta:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* ---------- 空状态 ---------- */
.empty-card {
  padding: 56px 24px;
  text-align: center;
}

.empty-card__icon {
  width: 60px;
  height: 60px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
}

.empty-card__title {
  font-size: var(--ielts-text-xl);
  font-weight: 600;
  margin-bottom: 8px;
}

.empty-card__text {
  color: var(--ielts-muted-foreground);
  margin-bottom: 20px;
}

.empty-card__cta {
  display: inline-block;
  background: var(--ielts-primary);
  color: #fff;
  padding: 10px 24px;
  border-radius: var(--ielts-radius-full);
  font-size: var(--ielts-text-base);
}

/* ---------- Hero ---------- */
.hero-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 900px) {
  .hero-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.stat-card {
  padding: 18px;
}

.stat-card.is-clickable {
  cursor: pointer;
  transition: box-shadow 0.15s;
}

.stat-card.is-clickable:hover {
  box-shadow: var(--ielts-shadow-md);
}

.stat-card__label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.stat-card__edit {
  margin-left: auto;
  color: var(--ielts-muted-foreground);
}

.stat-card__value {
  font-size: var(--ielts-text-3xl);
  font-weight: 700;
  margin: 8px 0 4px;
  line-height: 1.1;
}

.stat-card__unit {
  font-size: var(--ielts-text-md);
  font-weight: 400;
  color: var(--ielts-muted-foreground);
  margin-left: 4px;
}

.stat-card__hint {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.today-bar {
  height: 6px;
  background: var(--ielts-muted);
  border-radius: var(--ielts-radius-full);
  overflow: hidden;
  margin-top: 10px;
}

.today-bar__fill {
  height: 100%;
  background: var(--ielts-primary);
  border-radius: var(--ielts-radius-full);
  transition: width 0.3s ease;
}

/* ---------- 两列主区 ---------- */
.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 1000px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

.left-col,
.right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel {
  padding: 20px;
}

.panel__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel__title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
}

.panel__sub {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.panel__link {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-primary);
  text-decoration: none;
}

.radar-chart {
  height: 240px;
}

.trend-chart {
  height: 220px;
}

.chart-empty {
  height: 120px;
  display: grid;
  place-items: center;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  background: var(--ielts-slate-50);
  border-radius: var(--ielts-radius-md);
}

.dim-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.dim-chip {
  position: relative;
  border: 1px solid var(--ielts-border);
  background: #fff;
  border-radius: var(--ielts-radius-full);
  padding: 5px 14px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-foreground);
  cursor: pointer;
  transition: border-color 0.15s, background-color 0.15s;
}

.dim-chip:hover {
  border-color: var(--ielts-primary);
  background: var(--ielts-accent);
}

.dim-chip.is-weak {
  border-color: var(--ielts-warning);
  background: var(--ielts-warning-bg);
}

.dim-chip__tag {
  margin-left: 4px;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-warning);
  font-weight: 600;
}

/* ---------- 推荐与最近练习 ---------- */
.rec-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rec-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.rec-item:hover {
  border-color: var(--ielts-primary);
  box-shadow: var(--ielts-shadow-sm);
}

.rec-item.is-done {
  opacity: 0.55;
}

.rec-item__icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
}

.rec-item__body {
  flex: 1;
  min-width: 0;
}

.rec-item__title {
  font-weight: 500;
  font-size: var(--ielts-text-base);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-item__desc {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-item__type {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-primary);
  background: var(--ielts-accent);
  border-radius: var(--ielts-radius-full);
  padding: 3px 10px;
  flex-shrink: 0;
}

.recent-list {
  display: flex;
  flex-direction: column;
}

.recent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--ielts-border);
  cursor: pointer;
  border-radius: var(--ielts-radius-sm);
  transition: background-color 0.12s;
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-item:hover {
  background: var(--ielts-slate-50);
}

.recent-item__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.recent-item__part {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-primary);
  background: var(--ielts-accent);
  padding: 2px 8px;
  border-radius: var(--ielts-radius-sm);
  flex-shrink: 0;
}

.recent-item__topic {
  font-size: var(--ielts-text-base);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-item__side {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.recent-item__date {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.recent-item__band {
  font-size: var(--ielts-text-md);
  font-weight: 700;
  color: var(--ielts-primary);
  min-width: 34px;
  text-align: right;
}

.recent-item__band.is-none {
  color: var(--ielts-warning);
  font-weight: 400;
  font-size: var(--ielts-text-xs);
}

.target-dialog__tip {
  margin: 0 0 14px;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  line-height: 1.6;
}
</style>
