import { client } from './client'
import type { VocabListOut, VocabWordOut } from '@/types'

export async function fetchVocabWords(params: {
  favorite?: boolean
  search?: string
  page?: number
  page_size?: number
}): Promise<VocabListOut> {
  const { data } = await client.get<VocabListOut>('/vocab-words', { params })
  return data
}

export async function addVocabWord(payload: {
  word: string
  context_en?: string | null
  source_topic_id?: string | null
}): Promise<VocabWordOut> {
  const { data } = await client.post<VocabWordOut>('/vocab-words', payload)
  return data
}

export async function toggleVocabFavorite(wordId: string): Promise<VocabWordOut> {
  const { data } = await client.patch<VocabWordOut>(`/vocab-words/${wordId}/favorite`)
  return data
}

export async function deleteVocabWord(wordId: string): Promise<void> {
  await client.delete(`/vocab-words/${wordId}`)
}
