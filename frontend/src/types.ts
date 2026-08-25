/** 与后端 Pydantic 模型对应的类型定义 */

export interface UserOut {
  id: string
  email: string
  nickname: string | null
  target_band: number | null
  is_active: boolean
  created_at: string
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserOut
}

export type ServiceType = 'llm' | 'asr' | 'tts' | 'evaluation'

/** not_configured 为前端虚拟状态（后端无对应行时返回） */
export type ApiKeyStatus = 'not_configured' | 'unverified' | 'valid' | 'invalid'

export interface ApiKeyOut {
  service_type: ServiceType
  configured: boolean
  status: ApiKeyStatus
  key_last4: string | null
  config: Record<string, unknown>
  last_verified_at: string | null
}

export interface ApiKeyTestResult {
  service_type: ServiceType
  testable: boolean
  success: boolean
  message: string
  key_source: 'user' | 'platform' | 'none'
  latency_ms: number | null
}

export interface TopicOut {
  id: string
  name_en: string
  name_zh: string | null
  category: string | null
  tag: string | null
  question_count: number
}

export interface CueCard {
  prompt: string
  summary_zh?: string
  you_should_say?: string[]
}
