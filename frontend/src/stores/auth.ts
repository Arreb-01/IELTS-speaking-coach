import { defineStore } from 'pinia'
import { ref } from 'vue'

import * as authApi from '@/api/auth'
import { tokens } from '@/api/tokens'
import type { UserOut } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserOut | null>(null)

  const isLoggedIn = () => tokens.access !== null

  async function applyTokens(accessToken: string, refreshToken: string, nextUser: UserOut) {
    tokens.set(accessToken, refreshToken)
    user.value = nextUser
  }

  async function register(payload: { email: string; password: string; nickname?: string }) {
    const data = await authApi.register(payload)
    await applyTokens(data.access_token, data.refresh_token, data.user)
  }

  async function login(payload: { email: string; password: string }) {
    const data = await authApi.login(payload)
    await applyTokens(data.access_token, data.refresh_token, data.user)
  }

  /** 应用启动/进入主布局时拉取用户信息；令牌无效时由拦截器统一处理 */
  async function fetchUser() {
    if (!isLoggedIn() || user.value) return
    try {
      user.value = await authApi.fetchMe()
    } catch {
      // 拉取失败（非 401 场景）保持现状，由页面按需重试
    }
  }

  async function logout() {
    await authApi.logout(tokens.refresh)
    tokens.clear()
    user.value = null
  }

  return { user, isLoggedIn, register, login, fetchUser, logout }
})
