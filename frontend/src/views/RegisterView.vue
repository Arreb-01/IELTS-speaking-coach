<script setup lang="ts">
import { Mic } from 'lucide-vue-next'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { extractErrorMessage } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const form = reactive({ email: '', password: '', confirm: '', nickname: '' })
const loading = ref(false)
const errorMessage = ref('')

const passwordRules = {
  validator: (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    if (!value) callback(new Error('请输入密码'))
    else if (value.length < 8) callback(new Error('密码至少 8 位'))
    else if (!/[a-zA-Z]/.test(value) || !/\d/.test(value)) {
      callback(new Error('密码需同时包含字母和数字'))
    } else callback()
  },
}

async function handleSubmit() {
  if (form.password !== form.confirm) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    await auth.register({
      email: form.email.trim(),
      password: form.password,
      nickname: form.nickname.trim() || undefined,
    })
    router.push('/')
  } catch (error) {
    errorMessage.value = extractErrorMessage(error, '注册失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card ielts-card">
      <div class="auth-brand">
        <div class="auth-brand__icon"><Mic :size="20" color="#fff" /></div>
        <div>
          <div class="auth-brand__name">雅思口语教练</div>
          <div class="auth-brand__slogan">中文深度反馈 · 自适应学习路径</div>
        </div>
      </div>

      <h2 class="auth-title">创建账号</h2>
      <p class="auth-subtitle">注册即可开始 AI 口语训练</p>

      <el-form label-position="top" size="large" @submit.prevent="handleSubmit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="you@example.com" autocomplete="email" />
        </el-form-item>
        <el-form-item label="昵称（可选）">
          <el-input v-model="form.nickname" placeholder="怎么称呼你？" maxlength="50" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="至少 8 位，包含字母和数字"
            show-password
            autocomplete="new-password"
            :rules="[passwordRules]"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="form.confirm"
            type="password"
            placeholder="再次输入密码"
            show-password
            autocomplete="new-password"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          show-icon
          :closable="false"
          class="auth-error"
        />

        <el-button
          type="primary"
          native-type="submit"
          class="auth-submit"
          :loading="loading"
          :disabled="!form.email || !form.password || !form.confirm"
        >
          注 册
        </el-button>
      </el-form>

      <div class="auth-switch">
        已有账号？
        <RouterLink :to="{ name: 'login' }">直接登录</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(60% 40% at 20% 0%, var(--ielts-teal-50) 0%, transparent 60%),
    radial-gradient(50% 35% at 90% 100%, var(--ielts-teal-50) 0%, transparent 55%),
    var(--ielts-background);
}

.auth-card {
  width: 100%;
  max-width: 400px;
  padding: 36px 32px 28px;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.auth-brand__icon {
  width: 40px;
  height: 40px;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-primary);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.auth-brand__name {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
}

.auth-brand__slogan {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.auth-title {
  font-size: var(--ielts-text-2xl);
  margin-bottom: 4px;
}

.auth-subtitle {
  margin: 0 0 20px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.auth-error {
  margin-bottom: 14px;
}

.auth-submit {
  width: 100%;
  margin-top: 4px;
}

.auth-switch {
  margin-top: 18px;
  text-align: center;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}
</style>
