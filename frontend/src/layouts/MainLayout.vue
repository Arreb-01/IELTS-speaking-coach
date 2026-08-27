<script setup lang="ts">
import {
  BookMarked,
  CalendarCheck,
  ChartLine,
  KeyRound,
  LayoutDashboard,
  Library,
  LogOut,
  Mic,
  NotebookPen,
} from 'lucide-vue-next'
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const navItems = [
  { name: 'dashboard', label: '首页', icon: LayoutDashboard },
  { name: 'plan', label: '学习路径', icon: CalendarCheck },
  { name: 'topics', label: '话题练习', icon: Library },
  { name: 'mock-exam', label: '模拟考试', icon: Mic },
  { name: 'reports', label: '评分报告', icon: ChartLine },
  { name: 'vocab', label: '词汇本', icon: BookMarked },
  { name: 'mistakes', label: '错题本', icon: NotebookPen },
  { name: 'api-keys', label: 'API 设置', icon: KeyRound },
]

const activeNav = computed(() => route.name)
const pageTitle = computed(() => (route.meta.title as string) ?? '')

const avatarText = computed(() => {
  const name = auth.user?.nickname || auth.user?.email || '?'
  return name.slice(0, 1).toUpperCase()
})

const targetBandText = computed(() => {
  const band = auth.user?.target_band
  return band ? `目标 Band ${band.toFixed(1)}` : '未设置目标分数'
})

async function handleLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}

onMounted(() => {
  auth.fetchUser()
})
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="sidebar__logo">
        <div class="sidebar__logo-icon">
          <Mic :size="18" color="#fff" />
        </div>
        <span class="sidebar__logo-text">雅思口语教练</span>
      </div>

      <nav class="sidebar__nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.name"
          :to="{ name: item.name }"
          class="sidebar__nav-item"
          :class="{ 'is-active': activeNav === item.name }"
        >
          <component :is="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar__footer">
        <div class="sidebar__avatar">{{ avatarText }}</div>
        <div class="sidebar__user-meta">
          <div class="sidebar__user-name">{{ auth.user?.nickname || '备考考生' }}</div>
          <div class="sidebar__user-sub">{{ targetBandText }}</div>
        </div>
        <button class="sidebar__logout" title="退出登录" @click="handleLogout">
          <LogOut :size="15" />
        </button>
      </div>
    </aside>

    <div class="shell__main">
      <header class="topbar">
        <h1 class="topbar__title">{{ pageTitle }}</h1>
      </header>
      <main class="content">
        <div class="page-content">
          <RouterView />
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  position: fixed;
  inset-block: 0;
  left: 0;
  width: var(--ielts-sidebar-width);
  display: flex;
  flex-direction: column;
  background: var(--ielts-card);
  border-right: 1px solid var(--ielts-border);
  z-index: 20;
}

.sidebar__logo {
  height: var(--ielts-topbar-height);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid var(--ielts-border);
}

.sidebar__logo-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-primary);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.sidebar__logo-text {
  font-size: var(--ielts-text-md);
  font-weight: 600;
}

.sidebar__nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 16px 12px;
  overflow-y: auto;
}

.sidebar__nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--ielts-radius-md);
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-base);
  transition: background-color 0.15s, color 0.15s;
}

.sidebar__nav-item:hover {
  background: var(--ielts-muted);
  color: var(--ielts-foreground);
}

.sidebar__nav-item.is-active {
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  font-weight: 500;
}

.sidebar__footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-top: 1px solid var(--ielts-border);
}

.sidebar__avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--ielts-secondary);
  color: var(--ielts-secondary-foreground);
  display: grid;
  place-items: center;
  font-size: var(--ielts-text-sm);
  font-weight: 600;
  flex-shrink: 0;
}

.sidebar__user-meta {
  flex: 1;
  min-width: 0;
}

.sidebar__user-name {
  font-size: var(--ielts-text-sm);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__user-sub {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.sidebar__logout {
  border: none;
  background: none;
  color: var(--ielts-muted-foreground);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--ielts-radius-sm);
  display: grid;
  place-items: center;
}

.sidebar__logout:hover {
  color: var(--ielts-error);
  background: var(--ielts-error-bg);
}

/* ---------- 主区域 ---------- */
.shell__main {
  margin-left: var(--ielts-sidebar-width);
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--ielts-topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--ielts-card);
  border-bottom: 1px solid var(--ielts-border);
}

.topbar__title {
  font-size: var(--ielts-text-xl);
}

.content {
  flex: 1;
  padding: 24px;
  overflow-x: hidden;
}
</style>
