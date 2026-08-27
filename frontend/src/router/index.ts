import { createRouter, createWebHistory } from 'vue-router'

import { tokens } from '@/api/tokens'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录' },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { title: '注册' },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '首页', requiresAuth: true },
        },
        {
          path: 'plan',
          name: 'plan',
          component: () => import('@/views/PlanView.vue'),
          meta: { title: '学习路径', requiresAuth: true },
        },
        {
          path: 'topics',
          name: 'topics',
          component: () => import('@/views/TopicsView.vue'),
          meta: { title: '话题练习', requiresAuth: true },
        },
        {
          path: 'topics/:topicId',
          name: 'topic-detail',
          component: () => import('@/views/TopicDetailView.vue'),
          meta: { title: '话题详情', requiresAuth: true },
        },
        {
          path: 'vocab',
          name: 'vocab',
          component: () => import('@/views/VocabView.vue'),
          meta: { title: '我的词汇本', requiresAuth: true },
        },
        {
          path: 'mistakes',
          name: 'mistakes',
          component: () => import('@/views/MistakesView.vue'),
          meta: { title: '错题本', requiresAuth: true },
        },
        {
          path: 'practice',
          name: 'practice',
          component: () => import('@/views/PracticeView.vue'),
          meta: { title: 'AI 练习', requiresAuth: true },
        },
        {
          path: 'mock-exam',
          name: 'mock-exam',
          component: () => import('@/views/MockExamView.vue'),
          meta: { title: '模拟考试', requiresAuth: true },
        },
        {
          path: 'reports',
          name: 'reports',
          component: () => import('@/views/ReportsView.vue'),
          meta: { title: '评分报告', requiresAuth: true },
        },
        {
          path: 'reports/:sessionId',
          name: 'report-detail',
          component: () => import('@/views/ReportView.vue'),
          meta: { title: '评分报告详情', requiresAuth: true },
        },
        {
          path: 'settings/api-keys',
          name: 'api-keys',
          component: () => import('@/views/ApiKeysView.vue'),
          meta: { title: 'API Key 管理', requiresAuth: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const loggedIn = tokens.access !== null
  if (to.meta.requiresAuth && !loggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // 已登录用户访问登录/注册页时直接回首页
  if (loggedIn && (to.name === 'login' || to.name === 'register')) {
    return { name: 'dashboard' }
  }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 雅思口语教练` : '雅思口语教练'
})

export default router
