<script setup lang="ts">
import { Library, Search } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { extractErrorMessage } from '@/api/client'
import { fetchTopicsPage } from '@/api/topics'
import { usePracticeStore } from '@/stores/practice'
import type { TopicOut } from '@/types'

const router = useRouter()
const practice = usePracticeStore()

const activePart = ref<1 | 2 | 3>(1)
const loading = ref(false)
const topics = ref<TopicOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const search = ref('')
const category = ref('')
const tag = ref('')

const partTabs = [
  { value: 1 as const, label: 'Part 1 · 问答' },
  { value: 2 as const, label: 'Part 2 · 独白' },
  { value: 3 as const, label: 'Part 3 · 讨论' },
]

// Part 2/3 的主题分类（人物/事件/事物/地点）
const categories = [
  { value: 'person', label: '人物' },
  { value: 'event', label: '事件' },
  { value: 'object', label: '事物' },
  { value: 'place', label: '地点' },
]

const tagOptions = [
  { value: '', label: '全部标签' },
  { value: 'must', label: '必考题' },
  { value: 'new', label: '新题' },
  { value: 'retained', label: '保留题' },
]

const tagMeta: Record<string, { label: string; tone: string }> = {
  must: { label: '必考题', tone: 'error' },
  retained: { label: '保留题', tone: 'warning' },
  new: { label: '新题', tone: 'info' },
}

let searchTimer: ReturnType<typeof setTimeout> | null = null

async function load() {
  loading.value = true
  try {
    const data = await fetchTopicsPage({
      part: activePart.value,
      category: category.value || undefined,
      tag: tag.value || undefined,
      search: search.value.trim() || undefined,
      page: page.value,
      page_size: pageSize,
    })
    topics.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '题库加载失败'))
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  void load()
}

function switchPart(part: 1 | 2 | 3) {
  activePart.value = part
  category.value = '' // Part1 无主题分类
  resetAndLoad()
}

watch(search, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(resetAndLoad, 350) // 防抖
})

function startPractice(topic: TopicOut) {
  practice.reset()
  router.push({ name: 'practice', query: { topic: topic.id, part: String(activePart.value) } })
}

function openDetail(topic: TopicOut) {
  router.push({ name: 'topic-detail', params: { topicId: topic.id } })
}

onMounted(load)
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

    <div class="topics__filters">
      <div class="topics__search">
        <Search :size="14" class="topics__search-icon" />
        <input
          v-model="search"
          type="text"
          placeholder="搜索话题（中英文均可）..."
          class="topics__search-input"
        />
      </div>
      <select v-if="activePart !== 1" v-model="category" class="topics__select" @change="resetAndLoad">
        <option value="">全部主题</option>
        <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
      </select>
      <select v-model="tag" class="topics__select" @change="resetAndLoad">
        <option v-for="t in tagOptions" :key="t.value" :value="t.value">{{ t.label }}</option>
      </select>
    </div>

    <div v-loading="loading" class="topics__grid">
      <div v-for="topic in topics" :key="topic.id" class="topic-card ielts-card">
        <div class="topic-card__head">
          <div class="topic-card__title" @click="openDetail(topic)">{{ topic.name_en }}</div>
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
        <div class="topic-card__actions">
          <el-button class="topic-card__ghost" @click="openDetail(topic)">查看详情</el-button>
          <el-button type="primary" class="topic-card__action" @click="startPractice(topic)">
            开始练习
          </el-button>
        </div>
      </div>
    </div>

    <el-empty
      v-if="!loading && topics.length === 0"
      description="没有符合条件的话题"
    />

    <div v-if="total > pageSize" class="topics__pagination">
      <el-pagination
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="(p: number) => { page = p; void load() }"
      />
    </div>
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

.topics__filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.topics__search {
  position: relative;
  flex: 1;
  min-width: 220px;
  max-width: 380px;
}

.topics__search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--ielts-muted-foreground);
}

.topics__search-input {
  width: 100%;
  padding: 8px 12px 8px 30px;
  border: 1px solid var(--ielts-border);
  border-radius: 6px;
  background: var(--ielts-card);
  font-size: var(--ielts-text-sm);
  color: var(--ielts-foreground);
}

.topics__search-input:focus {
  outline: none;
  border-color: var(--ielts-primary);
}

.topics__select {
  padding: 8px 10px;
  border: 1px solid var(--ielts-border);
  border-radius: 6px;
  background: var(--ielts-card);
  font-size: var(--ielts-text-sm);
  color: var(--ielts-foreground);
  cursor: pointer;
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

.topics__pagination {
  display: flex;
  justify-content: center;
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
  cursor: pointer;
}

.topic-card__title:hover {
  color: var(--ielts-primary);
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

.topic-card__actions {
  margin-top: auto;
  display: flex;
  gap: 8px;
}

.topic-card__ghost {
  flex: 1;
}

.topic-card__action {
  flex: 1;
}
</style>
