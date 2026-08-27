import { client } from './client'

/** Dashboard 聚合接口类型（对齐后端 schemas/progress.py） */

export interface PredictedBand {
  band: number | null
  hint: string
}

export interface DashboardRadar {
  fluency: number | null
  lexical: number | null
  grammar: number | null
  pronunciation: number | null
}

export interface TrendPoint {
  date: string
  overall_band: number | null
  fluency: number | null
  lexical: number | null
  grammar: number | null
  pronunciation: number | null
}

export type TaskStatus = 'pending' | 'done' | 'skipped'
export type TaskType = 'topic' | 'special' | 'corpus'

export interface DailyTaskItem {
  id: string
  plan_date: string
  task_type: TaskType
  dimension: string | null
  topic_id: string | null
  part: number | null
  title_zh: string
  desc_zh: string
  payload: { action?: string } | null
  status: TaskStatus
  sort: number
}

export interface RecentPractice {
  session_id: string
  part: number
  mode: string
  topic_name_en: string | null
  topic_name_zh: string | null
  overall_band: number | null
  report_status: string | null
  started_at: string
}

export interface HeroStats {
  target_band: number | null
  predicted: PredictedBand
  streak_days: number
  today_done: number
  today_total: number
  avg_session_minutes: number | null
  week_delta: number | null
  eta_text: string | null
}

export interface DashboardOverview {
  needs_placement: boolean
  has_any_practice: boolean
  hero: HeroStats
  radar: DashboardRadar | null
  radar_order: string[]
  trend_points: TrendPoint[]
  recommendations: DailyTaskItem[]
  recent_practices: RecentPractice[]
}

export interface WeaknessSuggestion {
  topic_id: string
  name_en: string
  name_zh: string | null
  category: string | null
  tag: string | null
  reason_zh: string
}

export interface WeaknessInfo {
  dim_values: Record<string, number[]>
  averages: Record<string, number>
  primary_dimension: string | null
  primary_avg: number | null
  stable_dims: string[]
  suggestions: WeaknessSuggestion[]
}

export async function fetchOverview(): Promise<DashboardOverview> {
  const { data } = await client.get<DashboardOverview>('/dashboard/overview')
  return data
}

export async function fetchWeakness(dimension?: string): Promise<WeaknessInfo> {
  const { data } = await client.get<WeaknessInfo>('/dashboard/weakness', {
    params: dimension ? { dimension } : {},
  })
  return data
}

/** 初始能力测评：创建 5 题会话 */
export async function startPlacement(): Promise<{
  session_id: string
  ws_ticket: string
  ws_path: string
  total_questions: number
}> {
  const { data } = await client.post('/placement/start')
  return data
}
