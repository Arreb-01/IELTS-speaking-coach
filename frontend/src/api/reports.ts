import { client } from './client'

/** 评分报告类型定义（对齐后端 schemas/report.py） */

export interface SentenceIssue {
  type: 'grammar' | 'vocab' | 'fluency' | 'pronunciation'
  severity: 'minor' | 'moderate' | 'major'
  explanation_zh: string
  suggestion: string
}

export interface SentenceAnalysis {
  text: string
  issues: SentenceIssue[]
}

export interface TurnAnalysisOut {
  id: string
  turn_id: string
  seq: number
  sentences: SentenceAnalysis[] | null
  pronunciation_detail: {
    score: number | null
    fluency: number | null
    integrity: number | null
    words: { word: string; score: number | null }[]
    mock?: boolean
  } | null
  filler_hits: { word: string; count: number }[] | null
}

export interface ExpressionUpgrade {
  original: string
  upgraded: string
  note_zh?: string
}

export interface ReportSessionBrief {
  session_id: string
  part: number
  mode: string
  topic_name_en: string | null
  topic_name_zh: string | null
  started_at: string | null
  ended_at: string | null
}

export interface ScoreReportDetail {
  id: string
  session_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  overall_band: number | null
  fluency: number | null
  lexical: number | null
  grammar: number | null
  pronunciation: number | null
  fluency_metrics: Record<string, unknown> | null
  overall_comment_zh: string | null
  strengths: string[] | null
  improvements: string[] | null
  expression_upgrades: ExpressionUpgrade[] | null
  low_confidence: string[] | null
  model_versions: Record<string, unknown> | null
  error: string | null
  created_at: string
  completed_at: string | null
  session: ReportSessionBrief | null
  turn_analyses: TurnAnalysisOut[]
}

export interface ScoreReportListItem {
  report_id: string
  session_id: string
  status: string
  overall_band: number | null
  fluency: number | null
  lexical: number | null
  grammar: number | null
  pronunciation: number | null
  part: number
  mode: string
  topic_name_en: string | null
  topic_name_zh: string | null
  created_at: string
}

export interface TrendPoint {
  date: string
  overall_band: number | null
  fluency: number | null
  lexical: number | null
  grammar: number | null
  pronunciation: number | null
}

export async function fetchReport(sessionId: string): Promise<ScoreReportDetail> {
  const { data } = await client.get<ScoreReportDetail>(`/practices/${sessionId}/report`)
  return data
}

export async function rescorePractice(sessionId: string): Promise<{ status: string }> {
  const { data } = await client.post<{ status: string }>(`/practices/${sessionId}/rescore`)
  return data
}

export async function fetchReports(limit = 20): Promise<ScoreReportListItem[]> {
  const { data } = await client.get<ScoreReportListItem[]>('/reports', { params: { limit } })
  return data
}

export async function fetchTrend(limit = 30): Promise<{ points: TrendPoint[] }> {
  const { data } = await client.get<{ points: TrendPoint[] }>('/reports/trend', {
    params: { limit },
  })
  return data
}
