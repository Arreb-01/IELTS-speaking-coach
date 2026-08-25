/** axios 实例：自动附带 Bearer token，401 时静默刷新并重放请求。 */

import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'

import { tokens } from './tokens'

export const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
})

client.interceptors.request.use((config) => {
  if (tokens.access) {
    config.headers.Authorization = `Bearer ${tokens.access}`
  }
  return config
})

/** 并发 401 时只发起一次刷新 */
let refreshing: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  refreshing ??= axios
    .post('/api/v1/auth/refresh', { refresh_token: tokens.refresh })
    .then((resp) => {
      const { access_token, refresh_token } = resp.data
      tokens.set(access_token, refresh_token)
      return access_token as string
    })
    .catch(() => {
      tokens.clear()
      return null
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const url = config?.url ?? ''
    const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/refresh')
    if (error.response?.status === 401 && config && !config._retried && !isAuthEndpoint) {
      config._retried = true
      const token = await refreshAccessToken()
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
        return client.request(config)
      }
      // 刷新失败：回到登录页（硬跳转，重置全部状态）
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
    }
    return Promise.reject(error)
  },
)

/** 提取后端错误信息（FastAPI 的 detail 字段） */
export function extractErrorMessage(error: unknown, fallback = '请求失败，请稍后重试'): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}
