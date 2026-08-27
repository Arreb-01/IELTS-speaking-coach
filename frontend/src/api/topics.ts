import { client } from './client'
import type { ExpressionOut, TopicDetailOut, TopicListOut, TopicOut } from '@/types'

export interface TopicQuery {
  part: number
  category?: string
  tag?: string
  search?: string
  page?: number
  page_size?: number
}

export async function fetchTopicsPage(query: TopicQuery): Promise<TopicListOut> {
  const { data } = await client.get<TopicListOut>('/topics', { params: query })
  return data
}

export async function fetchTopicDetail(topicId: string): Promise<TopicDetailOut> {
  const { data } = await client.get<TopicDetailOut>(`/topics/${topicId}`)
  return data
}

export async function fetchExpressions(topicId?: string): Promise<ExpressionOut[]> {
  const { data } = await client.get<ExpressionOut[]>('/topics/expressions', {
    params: topicId ? { topic_id: topicId, page_size: 100 } : { page_size: 100 },
  })
  return data
}

/** 范文跟读：文本 → WAV 音频 Blob（VOLC_MOCK 时为静音块） */
export async function speakText(text: string): Promise<Blob> {
  const { data } = await client.post<Blob>(
    '/topics/speak',
    { text: text.slice(0, 1200) },
    { responseType: 'blob' },
  )
  return data
}

/** 兼容旧调用：一次性取全量话题（练习页选话题等场景） */
export async function fetchTopics(part: number): Promise<TopicOut[]> {
  const data = await fetchTopicsPage({ part, page_size: 100 })
  return data.items
}
