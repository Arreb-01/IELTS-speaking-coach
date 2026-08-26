<script setup lang="ts">
import { BarChart3 } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'

import { fetchReports, fetchTrend, type ScoreReportListItem, type TrendPoint } from '@/api/reports'
import VChart from '@/plugins/echarts'

const reports = ref<ScoreReportListItem[]>([])
const trendPoints = ref<TrendPoint[]>([])
const loading = ref(true)
const trendMetric = ref<'overall_band' | 'fluency' | 'lexical' | 'grammar' | 'pronunciation'>(
  'overall_band',
)

const TREND_OPTIONS = [
  { value: 'overall_band', label: '综合' },
  { value: 'fluency', label: '流利度' },
  { value: 'lexical', label: '词汇' },
  { value: 'grammar', label: '语法' },
  { value: 'pronunciation', label: '发音' },
] as const

onMounted(async () => {
  try {
    const [list, trend] = await Promise.all([fetchReports(50), fetchTrend(60)])
    reports.value = list
    trendPoints.value = trend.points
  } finally {
    loading.value = false
  }
})

const trendOption = computed(() => {
  const metric = trendMetric.value
  const label = TREND_OPTIONS.find((o) => o.value === metric)?.label ?? ''
  return {
    color: ['#0f766e'],
    grid: { left: 36, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' as const },
    xAxis: {
      type: 'category' as const,
      data: trendPoints.value.map((p) => p.date.slice(5)),
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
        name: label,
        type: 'line' as const,
        data: trendPoints.value.map((p) => p[metric]),
        smooth: true,
        symbolSize: 7,
        lineStyle: { width: 2.5 },
        areaStyle: { opacity: 0.08 },
        connectNulls: true,
      },
    ],
  }
})

const statusMeta: Record<string, { label: string; tone: string }> = {
  completed: { label: '已完成', tone: 'success' },
  processing: { label: '评分中', tone: 'warning' },
  pending: { label: '排队中', tone: 'warning' },
  failed: { label: '失败', tone: 'error' },
}

const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
</script>

<template>
  <div class="reports" v-loading="loading">
    <!-- 趋势 -->
    <div class="ielts-card trend-card">
      <div class="trend-card__head">
        <h2 class="trend-card__title">提分趋势</h2>
        <div class="trend-switch">
          <button
            v-for="opt in TREND_OPTIONS"
            :key="opt.value"
            class="trend-switch__btn"
            :class="{ 'is-active': trendMetric === opt.value }"
            @click="trendMetric = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>
      <VChart v-if="trendPoints.length" :option="trendOption" class="trend-chart" autoresize />
      <div v-else class="trend-empty">
        完成第一次练习并生成评分后，这里将展示你的提分曲线
      </div>
    </div>

    <!-- 报告列表 -->
    <div class="ielts-card list-card">
      <h2 class="list-card__title">历史报告</h2>
      <div v-if="reports.length" class="table-wrap">
        <table class="report-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>话题</th>
              <th>Part</th>
              <th>综合</th>
              <th>流利度</th>
              <th>词汇</th>
              <th>语法</th>
              <th>发音</th>
              <th>状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in reports" :key="r.report_id">
              <td class="cell-date">{{ formatDate(r.created_at) }}</td>
              <td class="cell-topic">{{ r.topic_name_zh || r.topic_name_en || '--' }}</td>
              <td>Part {{ r.part }}</td>
              <td class="cell-band">
                {{ r.overall_band != null ? r.overall_band.toFixed(1) : '--' }}
              </td>
              <td>{{ r.fluency != null ? r.fluency.toFixed(1) : '--' }}</td>
              <td>{{ r.lexical != null ? r.lexical.toFixed(1) : '--' }}</td>
              <td>{{ r.grammar != null ? r.grammar.toFixed(1) : '--' }}</td>
              <td>{{ r.pronunciation != null ? r.pronunciation.toFixed(1) : '--' }}</td>
              <td>
                <span
                  class="status-badge"
                  :class="`status-badge--${statusMeta[r.status]?.tone || 'muted'}`"
                >
                  {{ statusMeta[r.status]?.label || r.status }}
                </span>
              </td>
              <td>
                <RouterLink
                  :to="{ name: 'report-detail', params: { sessionId: r.session_id } }"
                  class="view-link"
                >
                  查看
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="list-empty">
        <BarChart3 :size="32" class="list-empty__icon" />
        <p>还没有评分报告</p>
        <RouterLink :to="{ name: 'topics' }" class="list-empty__link">去练一轮 →</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reports {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: 300px;
}

.trend-card,
.list-card {
  padding: 20px;
}

.trend-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.trend-card__title,
.list-card__title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
  margin: 0;
}

.trend-switch {
  display: inline-flex;
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  overflow: hidden;
}

.trend-switch__btn {
  border: none;
  background: var(--ielts-card);
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-xs);
  padding: 5px 12px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.trend-switch__btn.is-active {
  background: var(--ielts-primary);
  color: var(--ielts-primary-foreground);
}

.trend-chart {
  width: 100%;
  height: 280px;
}

.trend-empty,
.list-empty {
  padding: 40px 16px;
  text-align: center;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.list-empty__icon {
  opacity: 0.5;
}

.list-empty__link {
  color: var(--ielts-primary);
  text-decoration: none;
  font-weight: 500;
}

.table-wrap {
  overflow-x: auto;
}

.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ielts-text-sm);
}

.report-table th {
  text-align: left;
  font-weight: 500;
  color: var(--ielts-muted-foreground);
  border-bottom: 1px solid var(--ielts-border);
  padding: 8px 10px;
  white-space: nowrap;
}

.report-table td {
  border-bottom: 1px solid color-mix(in srgb, var(--ielts-border) 50%, transparent);
  padding: 10px;
  white-space: nowrap;
}

.report-table tbody tr:hover {
  background: color-mix(in srgb, var(--ielts-muted) 50%, transparent);
}

.cell-topic {
  white-space: normal !important;
  min-width: 140px;
}

.cell-band {
  font-weight: 600;
}

.status-badge {
  font-size: var(--ielts-text-xs);
  border-radius: var(--ielts-radius-sm);
  padding: 2px 8px;
}

.status-badge--success {
  background: var(--state-success-bg);
  color: var(--state-success);
}

.status-badge--warning {
  background: var(--state-warning-bg);
  color: var(--state-warning);
}

.status-badge--error {
  background: var(--state-error-bg);
  color: var(--state-error);
}

.status-badge--muted {
  background: var(--ielts-muted);
  color: var(--ielts-muted-foreground);
}

.view-link {
  color: var(--ielts-primary);
  text-decoration: none;
  font-weight: 500;
}
</style>
