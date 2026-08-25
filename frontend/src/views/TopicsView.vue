<script setup lang="ts">
import { Library } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { extractErrorMessage } from '@/api/client'
import { fetchTopics } from '@/api/practice'
import { usePracticeStore } from '@/stores/practice'
import type { TopicOut } from '@/types'

const router = useRouter()
const practice = usePracticeStore()

const activePart = ref<1 | 2 | 3>(1)
const loading = ref(false)
const topics = ref<Record<number, TopicOut[]>>({ 1: [], 2: [], 3: [] })

const partTabs = [
  { value: 1 as const, label: 'Part 1 · 问答' },
  { value: 2 as const, label: 'Part 2 · 独白' },
  { value: 3 as const, label: 'Part 3 · 讨论' },
]

const tagMeta: Record<string, { label: string; tone: string }> = {
  must: { label: '必考题', tone: 'error' },
  retained: { label: '保留题', tone: 'warning' },
  new: { label: '新题', tone: 'info' },
}

async function loadPart(part: number) {
  loading.value = true
  try {
    topics.value[part] = await fetchTopics(part)
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '题库加载失败'))
  } finally {
    loading.value = false
  }
}

async function switchPart(part: 1 | 2 | 3) {
  activePart.value = part
  await loadPart(part)
}

async function startPractice(topic: TopicOut) {
  // Part 3 练习挂靠在 Part 2 话题下（讨论基于同一话题）
  const part = activePart.value
  const topicId = part === 3 ? topics.value[2].find((t) => t.id === topic.id)?.id ?? topic.id : topic.id
  practice.reset()
  router.push({ name: 'practice', query: { topic: topicId, part: String(part) } })
}

onMounted(() => {
  void loadPart(1)
  void loadPart(2) // Part 3 tab 复用 Part 2 话题列表
})
</script>

<template>
  <div class="topics">
    <div class="topics__tabs">
      <button
        v-for="tab in partTabs"
        :key="tab.value"
        class="topics__tab"
        :class="{ 'is-active': activePart === tab.value }"
        @click="switchPart(tab.value)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div v-loading="loading" class="topics__grid">
      <div
        v-for="topic in activePart === 3 ? topics[2] : topics[activePart]"
        :key="topic.id"
        class="topic-card ielts-card"
      >
        <div class="topic-card__head">
          <div class="topic-card__title">{{ topic.name_en }}</div>
          <span v-if="topic.tag" class="ielts-badge" :class="`ielts-badge--${tagMeta[topic.tag]?.tone ?? 'muted'}`">
            {{ tagMeta[topic.tag]?.label ?? topic.tag }}
          </span>
        </div>
        <div class="topic-card__sub">{{ topic.name_zh }}</div>
        <div class="topic-card__meta">
          <Library :size="13" />
          <span>{{ activePart === 3 ? `${topic.question_count}+ 道讨论题` : `${topic.question_count} 道题` }}</span>
          <span v-if="activePart === 3" class="topic-card__hint">基于 Part 2 话题深入讨论</span>
        </div>
        <el-button type="primary" class="topic-card__action" @click="startPractice(topic)">
          开始练习
        </el-button>
      </div>
    </div>

    <el-empty
      v-if="!loading && (activePart === 3 ? topics[2] : topics[activePart]).length === 0"
      description="该 Part 暂无话题"
    />
  </div>
</template>

<style scoped>
.topics {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.topics__tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--ielts-border);
  padding: 0 4px;
}

.topics__tab {
  border: none;
  background: none;
  cursor: pointer;
  padding: 10px 2px;
  font-size: var(--ielts-text-md);
  color: var(--ielts-muted-foreground);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.15s;
}

.topics__tab:hover {
  color: var(--ielts-foreground);
}

.topics__tab.is-active {
  color: var(--ielts-primary);
  font-weight: 500;
  border-bottom-color: var(--ielts-primary);
}

.topics__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  min-height: 200px;
}

@media (max-width: 1000px) {
  .topics__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .topics__grid {
    grid-template-columns: 1fr;
  }
}

.topic-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  transition: box-shadow 0.2s;
}

.topic-card:hover {
  box-shadow: var(--ielts-shadow-md);
}

.topic-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.topic-card__title {
  font-size: var(--ielts-text-md);
  font-weight: 600;
  line-height: 1.4;
}

.topic-card__sub {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.topic-card__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.topic-card__hint {
  margin-left: auto;
}

.topic-card__action {
  margin-top: auto;
  width: 100%;
}
</style>
