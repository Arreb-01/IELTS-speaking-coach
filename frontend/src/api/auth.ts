import { client } from './client'
import type { TokenResponse, UserOut } from '@/types'

export async function register(payload: {
  email: string
  password: string
  nickname?: string
}): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>('/auth/register', payload)
  return data
}

export async function login(payload: { email: string; password: string }): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>('/auth/login', payload)
  return data
}

export async function fetchMe(): Promise<UserOut> {
  const { data } = await client.get<UserOut>('/auth/me')
  return data
}

export async function logout(refreshToken: string | null): Promise<void> {
  if (!refreshToken) return
  // 尽力通知服务端吊销 refresh token，失败不影响本地登出
  await client.post('/auth/logout', { refresh_token: refreshToken }).catch(() => undefined)
}

export async function updateProfile(payload: {
  nickname?: string
  target_band?: number
}): Promise<UserOut> {
  const { data } = await client.put<UserOut>('/users/me', payload)
  return data
}
