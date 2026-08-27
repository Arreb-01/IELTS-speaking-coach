import { client } from './client'

import type { DailyTaskItem } from './dashboard'

/** 学习路径接口类型（对齐后端 schemas/progress.py PlanWeekOut） */

export interface PlanDay {
  date: string
  done_count: number
  total_count: number
  is_today: boolean
}

export interface TaskActionMeta {
  current_band: number | null
  target_band: number | null
  predicted_band: number | null
  eta_text: string | null
  weekly_completion: number
}

export interface PlanWeek {
  week_start: string
  days: PlanDay[]
  selected_date: string
  tasks: DailyTaskItem[]
  meta: TaskActionMeta
}

export async function fetchPlanWeek(date?: string): Promise<PlanWeek> {
  const { data } = await client.get<PlanWeek>('/plan/week', {
    params: date ? { date } : {},
  })
  return data
}

export async function completeTask(taskId: string): Promise<{ id: string; status: string }> {
  const { data } = await client.post(`/plan/tasks/${taskId}/complete`)
  return data
}

export async function skipTask(taskId: string): Promise<{ id: string; status: string }> {
  const { data } = await client.post(`/plan/tasks/${taskId}/skip`)
  return data
}
