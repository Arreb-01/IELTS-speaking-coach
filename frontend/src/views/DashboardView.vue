<script setup lang="ts">
import { KeyRound, Mic } from 'lucide-vue-next'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <div class="dashboard">
    <div class="welcome-card ielts-card">
      <div class="welcome-card__title">
        你好，{{ auth.user?.nickname || '备考考生' }} 👋
      </div>
      <p class="welcome-card__text">
        欢迎使用 AI 雅思口语教练。语音对话练习、四维评分与中文深度反馈将随后续模块逐步上线，
        现在可以先完成下面的准备工作。
      </p>
      <div class="welcome-card__actions">
        <RouterLink :to="{ name: 'api-keys' }" class="welcome-action">
          <span class="welcome-action__icon"><KeyRound :size="16" /></span>
          <span class="welcome-action__body">
            <span class="welcome-action__title">配置火山引擎 API Key</span>
            <span class="welcome-action__desc">自带 Key 优先使用，突破免费额度限制</span>
          </span>
        </RouterLink>
        <div class="welcome-action is-disabled">
          <span class="welcome-action__icon"><Mic :size="16" /></span>
          <span class="welcome-action__body">
            <span class="welcome-action__title">语音对话练习</span>
            <span class="welcome-action__desc">Part 1/2/3 实时对话 · Part B 上线</span>
          </span>
        </div>
      </div>
    </div>

    <div class="dashboard-grid">
      <div class="stat-card ielts-card">
        <div class="stat-card__label">预测 Band</div>
        <div class="stat-card__value">--<span class="stat-card__unit">分</span></div>
        <div class="stat-card__hint">完成 5 次练习后开始预测</div>
      </div>
      <div class="stat-card ielts-card">
        <div class="stat-card__label">连续打卡</div>
        <div class="stat-card__value">0<span class="stat-card__unit">天</span></div>
        <div class="stat-card__hint">完成第一次练习开始累计</div>
      </div>
      <div class="stat-card ielts-card">
        <div class="stat-card__label">本周练习</div>
        <div class="stat-card__value">0<span class="stat-card__unit">次</span></div>
        <div class="stat-card__hint">话题练习库 · Part D 上线</div>
      </div>
      <div class="stat-card ielts-card">
        <div class="stat-card__label">综合能力</div>
        <div class="stat-card__value">--</div>
        <div class="stat-card__hint">四维雷达图 · 首次评分后展示</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.welcome-card {
  padding: 28px;
}

.welcome-card__title {
  font-size: var(--ielts-text-2xl);
  font-weight: 600;
  margin-bottom: 8px;
}

.welcome-card__text {
  margin: 0 0 20px;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-md);
}

.welcome-card__actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 720px) {
  .welcome-card__actions {
    grid-template-columns: 1fr;
  }
}

.welcome-action {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--ielts-border);
  border-radius: var(--ielts-radius-md);
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}

a.welcome-action:hover {
  border-color: var(--ielts-primary);
  box-shadow: var(--ielts-shadow-sm);
}

.welcome-action.is-disabled {
  opacity: 0.6;
}

.welcome-action__icon {
  width: 34px;
  height: 34px;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.welcome-action__title {
  display: block;
  font-weight: 500;
  font-size: var(--ielts-text-base);
}

.welcome-action__desc {
  display: block;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 900px) {
  .dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.stat-card {
  padding: 18px;
}

.stat-card__label {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.stat-card__value {
  font-size: var(--ielts-text-3xl);
  font-weight: 700;
  margin: 6px 0 2px;
}

.stat-card__unit {
  font-size: var(--ielts-text-md);
  font-weight: 400;
  color: var(--ielts-muted-foreground);
  margin-left: 4px;
}

.stat-card__hint {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}
</style>
