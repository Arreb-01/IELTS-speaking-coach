<script setup lang="ts">
import {
  BookOpenCheck,
  Check,
  ChevronLeft,
  ChevronRight,
  Mic,
  SkipForward,
  Sparkles,
} from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import type { DailyTaskItem } from '@/api/dashboard'
import {
  completeTask,
  fetchPlanWeek,
  skipTask,
  type PlanWeek,
} from '@/api/plan'
import { ElMessage } from 'element-plus'

const router = useRouter()

const plan = ref<PlanWeek | null>(null)
const loading = ref(true)
const actingId = ref<string | null>(null)

function todayIso(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`
}

async function load(date?: string) {
  loading.value = true
  try {
    plan.value = await fetchPlanWeek(date)
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

const dayNumber = (iso: string) => Number(iso.slice(8, 10))

async function shiftWeek(direction: -1 | 1) {
  if (!plan.value) return
  // 以当前视图任取一天平移一周
  const base = new Date(`${plan.value.week_start}T12:00:00`)
  base.setDate(base.getDate() + direction * 7)
  const iso = `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, '0')}-${String(
    base.getDate(),
  ).padStart(2, '0')}`
  await load(iso)
}

// ---- 任务操作 ----
async function markDone(task: DailyTaskItem) {
  actingId.value = task.id
  try {
    await completeTask(task.id)
    task.status = 'done'
    ElMessage.success('已完成打卡 🎉')
    await load(plan.value?.selected_date)
  } catch {
    ElMessage.error('操作失败，请稍后重试')
  } finally {
    actingId.value = null
  }
}

async function markSkipped(task: DailyTaskItem) {
  actingId.value = task.id
  try {
    await skipTask(task.id)
    ElMessage.info('已跳过，系统会安排替补任务')
    await load(plan.value?.selected_date)
  } catch {
    ElMessage.error('操作失败，请稍后重试')
  } finally {
    actingId.value = null
  }
}

function goPractice(task: DailyTaskItem) {
  if (!task.topic_id) return
  router.push({
    name: 'practice',
    query: { topic: task.topic_id, part: String(task.part ?? 1) },
  })
}

function goTopicDetail(task: DailyTaskItem) {
  if (!task.topic_id) return
  router.push({ name: 'topic-detail', params: { topicId: task.topic_id } })
}

const TASK_TYPE_META: Record<string, { label: string; icon: typeof Mic }> = {
  topic: { label: '话题练习', icon: Mic },
  special: { label: '发音专项', icon: Sparkles },
  corpus: { label: '表达学习', icon: BookOpenCheck },
}

const DIM_ZH: Record<string, string> = {
  fluency: '流利度',
  lexical: '词汇',
  grammar: '语法',
  pronunciation: '发音',
}

/** 该任务的主行动 */
function actionOf(task: DailyTaskItem): 'practice' | 'detail' | null {
  if (task.status !== 'pending' || !task.topic_id) return null
  // 发音跟读 / 表达学习去话题详情页；话题独白与 Part1 练习直进练习页
  if (task.task_type === 'corpus') return 'detail'
  if (task.payload?.action === 'topic-detail') return 'detail'
  return 'practice'
}

const completionTone = computed(() => (plan.value?.meta.weekly_completion ?? 0) >= 60)
</script>

<template>
  <div class="plan" v-loading="loading">
    <template v-if="plan">
      <!-- 顶部信息条 -->
      <div class="meta-bar ielts-card">
        <div class="meta-bar__item">
          <span class="meta-bar__label">当前预测</span>
          <span class="meta-bar__value">{{
            plan.meta.current_band != null ? `Band ${plan.meta.current_band}` : '--'
          }}</span>
        </div>
        <div class="meta-bar__divider"></div>
        <div class="meta-bar__item">
          <span class="meta-bar__label">目标分数</span>
          <span class="meta-bar__value">{{
            plan.meta.target_band != null ? `Band ${plan.meta.target_band}` : '未设置'
          }}</span>
        </div>
        <div class="meta-bar__divider"></div>
        <div class="meta-bar__item is-grow">
          <span class="meta-bar__label">预计达成</span>
          <span class="meta-bar__value meta-bar__value--small">{{ plan.meta.eta_text ?? '继续积累数据' }}</span>
        </div>
      </div>

      <!-- 周日历条 -->
      <div class="week-strip ielts-card">
        <button class="week-nav" aria-label="上一周" @click="shiftWeek(-1)">
          <ChevronLeft :size="16" />
        </button>
        <div class="week-days">
          <button
            v-for="(day, i) in plan.days"
            :key="day.date"
            class="day-cell"
            :class="{
              'is-today': day.is_today,
              'is-selected': day.date === plan.selected_date,
            }"
            @click="load(day.date)"
          >
            <span class="day-cell__weekday">{{ ['一','二','三','四','五','六','日'][i] }}</span>
            <span class="day-cell__num">{{ dayNumber(day.date) }}</span>
            <span
              v-if="day.total_count > 0"
              class="day-cell__badge"
              :class="{ 'is-full': day.done_count >= day.total_count && day.total_count > 0 }"
            >
              {{ day.done_count }}/{{ day.total_count }}
            </span>
          </button>
        </div>
        <button class="week-nav" aria-label="下一周" @click="shiftWeek(1)">
          <ChevronRight :size="16" />
        </button>
      </div>

      <!-- 当日任务 -->
      <h3 class="section-title">
        {{
          plan.selected_date === todayIso()
            ? '今日任务'
            : `${plan.selected_date} 的任务`
        }}
      </h3>

      <div v-if="plan.tasks.length" class="task-list">
        <div
          v-for="task in plan.tasks"
          :key="task.id"
          class="task-card ielts-card"
          :class="{ 'is-done': task.status === 'done', 'is-skipped': task.status === 'skipped' }"
        >
          <div class="task-card__icon">
            <component :is="TASK_TYPE_META[task.task_type]?.icon ?? Mic" :size="17" />
          </div>
          <div class="task-card__body">
            <div class="task-card__title-row">
              <span class="task-card__title">{{ task.title_zh }}</span>
              <span
                v-if="task.dimension"
                class="task-card__dim"
              >针对{{ DIM_ZH[task.dimension] ?? task.dimension }}</span>
            </div>
            <p class="task-card__desc">{{ task.desc_zh }}</p>
          </div>
          <div class="task-card__actions">
            <template v-if="actionOf(task) === 'practice'">
              <el-button size="small" type="primary" @click="goPractice(task)">开始练习</el-button>
            </template>
            <template v-else-if="actionOf(task) === 'detail'">
              <el-button size="small" type="primary" plain @click="goTopicDetail(task)">去学习</el-button>
            </template>
            <template v-if="task.status === 'done'">
              <span class="task-card__state is-done"><Check :size="14" /> 已完成</span>
            </template>
            <template v-else-if="task.status === 'skipped'">
              <span class="task-card__state">已跳过</span>
            </template>
            <template v-else-if="actingId !== task.id">
              <button
                v-if="task.topic_id || task.task_type === 'corpus'"
                class="mini-action"
                title="标记完成（无需进入练习）"
                @click="markDone(task)"
              >
                <Check :size="14" />
              </button>
              <button class="mini-action is-muted" title="跳过并安排替补" @click="markSkipped(task)">
                <SkipForward :size="14" />
              </button>
            </template>
          </div>
        </div>
      </div>
      <div v-else class="chart-empty ielts-card">
        当天暂无任务。完成能力测评或若干次练习后，这里会生成你的专属计划。
      </div>

      <!-- 本周完成率 -->
      <div class="completion-card ielts-card">
        <div class="completion-card__head">
          <span>本周完成率</span>
          <span class="completion-card__num">{{ plan.meta.weekly_completion }}%</span>
        </div>
        <div class="completion-card__bar">
          <div
            class="completion-card__fill"
            :style="{
              width: Math.min(plan.meta.weekly_completion, 100) + '%',
              background: completionTone ? 'var(--ielts-success)' : 'var(--ielts-primary)',
            }"
          ></div>
          <div class="completion-card__goal" style="left: 60%" title="目标 60%"></div>
        </div>
        <p class="completion-card__tip">
          每周目标：完成 60% 以上的每日任务。跳过的任务不计入完成率。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.plan {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ---------- meta ---------- */
.meta-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 14px 20px;
}

.meta-bar__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-bar__item.is-grow {
  flex: 1;
}

.meta-bar__label {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.meta-bar__value {
  font-size: var(--ielts-text-lg);
  font-weight: 700;
  color: var(--ielts-primary);
}

.meta-bar__value--small {
  font-size: var(--ielts-text-base);
  font-weight: 500;
  color: var(--ielts-foreground);
}

.meta-bar__divider {
  width: 1px;
  height: 30px;
  background: var(--ielts-border);
}

/* ---------- 周条 ---------- */
.week-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
}

.week-nav {
  border: none;
  background: none;
  color: var(--ielts-muted-foreground);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--ielts-radius-sm);
  display: grid;
  place-items: center;
}

.week-nav:hover {
  background: var(--ielts-muted);
  color: var(--ielts-foreground);
}

.week-days {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.day-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 4px 8px;
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, background-color 0.15s;
}

.day-cell:hover {
  border-color: var(--ielts-primary);
}

.day-cell.is-selected {
  border-color: var(--ielts-primary);
  background: var(--ielts-accent);
}

.day-cell.is-today .day-cell__num {
  color: var(--ielts-primary);
  font-weight: 700;
}

.day-cell__weekday {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.day-cell__num {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
}

.day-cell__badge {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  background: var(--ielts-muted);
  border-radius: var(--ielts-radius-full);
  padding: 1px 8px;
}

.day-cell__badge.is-full {
  background: var(--ielts-success-bg);
  color: var(--ielts-success);
}

/* ---------- 任务 ---------- */
.section-title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
  margin-top: 6px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
}

.task-card.is-done {
  opacity: 0.62;
}

.task-card.is-done .task-card__title {
  text-decoration: line-through;
}

.task-card.is-skipped .task-card__title {
  text-decoration: line-through;
}

.task-card.is-skipped {
  opacity: 0.55;
}

.task-card__icon {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
}

.task-card__body {
  flex: 1;
  min-width: 0;
}

.task-card__title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-card__title {
  font-size: var(--ielts-text-md);
  font-weight: 600;
}

.task-card__dim {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-warning);
  background: var(--ielts-warning-bg);
  padding: 2px 8px;
  border-radius: var(--ielts-radius-full);
}

.task-card__desc {
  margin: 4px 0 0;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.task-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.task-card__state.is-done {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ielts-success);
  font-size: var(--ielts-text-sm);
  font-weight: 500;
}

.mini-action {
  width: 30px;
  height: 30px;
  border: 1px solid var(--ielts-border);
  background: #fff;
  border-radius: var(--ielts-radius-md);
  color: var(--ielts-primary);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background-color 0.15s, border-color 0.15s;
}

.mini-action:hover {
  background: var(--ielts-accent);
  border-color: var(--ielts-primary);
}

.mini-action.is-muted {
  color: var(--ielts-muted-foreground);
}

.chart-empty {
  min-height: 120px;
  display: grid;
  place-items: center;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
}

/* ---------- 完成率 ---------- */
.completion-card {
  padding: 16px 20px;
}

.completion-card__head {
  display: flex;
  justify-content: space-between;
  font-size: var(--ielts-text-base);
  font-weight: 600;
  margin-bottom: 10px;
}

.completion-card__num {
  color: var(--ielts-primary);
}

.completion-card__bar {
  position: relative;
  height: 8px;
  background: var(--ielts-muted);
  border-radius: var(--ielts-radius-full);
  overflow: visible;
}

.completion-card__fill {
  height: 100%;
  border-radius: var(--ielts-radius-full);
  transition: width 0.3s ease;
}

.completion-card__goal {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 14px;
  background: var(--ielts-slate-400);
  border-radius: 1px;
}

.completion-card__tip {
  margin: 10px 0 0;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}
</style>
