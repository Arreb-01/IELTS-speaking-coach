import { client } from './client'
import type { TopicOut } from '@/types'

export interface PracticeCreateResult {
  session_id: string
  ws_ticket: string
  ws_path: string
}

export interface PracticeTurn {
  id: string
  seq: number
  question_text: string | null
  is_followup: boolean
  user_transcript: string | null
  has_audio: boolean
  started_at: string | null
  ended_at: string | null
}

export interface PracticeDetail {
  id: string
  mode: string
  part: number
  topic_id: string | null
  status: string
  accent: string
  speed: string
  started_at: string
  ended_at: string | null
  topic: TopicOut | null
  turns: PracticeTurn[]
}

export async function createPractice(payload: {
  topic_id: string
  part: number
  accent?: string
  speed?: string
}): Promise<PracticeCreateResult> {
  const { data } = await client.post<PracticeCreateResult>('/practices', payload)
  return data
}

export async function getReconnectTicket(sessionId: string): Promise<PracticeCreateResult> {
  const { data } = await client.get<PracticeCreateResult>(`/practices/${sessionId}/ticket`)
  return data
}

export async function fetchPracticeDetail(sessionId: string): Promise<PracticeDetail> {
  const { data } = await client.get<PracticeDetail>(`/practices/${sessionId}`)
  return data
}

export function turnAudioUrl(sessionId: string, turnId: string): string {
  return `/api/v1/practices/${sessionId}/turns/${turnId}/audio`
}
