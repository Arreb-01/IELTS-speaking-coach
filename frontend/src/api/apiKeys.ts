import { client } from './client'
import type { ApiKeyOut, ApiKeyTestResult, ServiceType } from '@/types'

export async function listApiKeys(): Promise<ApiKeyOut[]> {
  const { data } = await client.get<ApiKeyOut[]>('/api-keys')
  return data
}

export async function saveApiKey(
  serviceType: ServiceType,
  payload: { key?: string; config?: Record<string, unknown> },
): Promise<ApiKeyOut> {
  const { data } = await client.put<ApiKeyOut>(`/api-keys/${serviceType}`, payload)
  return data
}

export async function deleteApiKey(serviceType: ServiceType): Promise<void> {
  await client.delete(`/api-keys/${serviceType}`)
}

export async function testApiKey(serviceType: ServiceType): Promise<ApiKeyTestResult> {
  const { data } = await client.post<ApiKeyTestResult>(`/api-keys/${serviceType}/test`)
  return data
}
