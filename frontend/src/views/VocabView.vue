<script setup lang="ts">
import { Search, Star, Trash2 } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { extractErrorMessage } from '@/api/client'
import { deleteVocabWord, fetchVocabWords, toggleVocabFavorite } from '@/api/vocab'
import type { VocabWordOut } from '@/types'

const router = useRouter()
const loading = ref(false)
const words = ref<VocabWordOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const search = ref('')
const favoriteOnly = ref(false)

let searchTimer: ReturnType<typeof setTimeout> | null = null

async function load() {
  loading.value = true
  try {
    const data = await fetchVocabWords({
      favorite: favoriteOnly.value || undefined,
      search: search.value.trim() || undefined,
      page: page.value,
      page_size: pageSize,
    })
    words.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '词汇本加载失败'))
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  void load()
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(resetAndLoad, 350)
}

async function toggleFavorite(word: VocabWordOut) {
  try {
    const updated = await toggleVocabFavorite(word.id)
    Object.assign(word, updated)
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '操作失败'))
  }
}

async function removeWord(word: VocabWordOut) {
  try {
    await ElMessageBox.confirm(`确定删除「${word.word}」吗？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteVocabWord(word.id)
    words.value = words.value.filter((w) => w.id !== word.id)
    total.value -= 1
    ElMessage.success('已删除')
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '删除失败'))
  }
}

function goTopic(word: VocabWordOut) {
  if (word.source_topic_id) {
    router.push({ name: 'topic-detail', params: { topicId: word.source_topic_id } })
  }
}

onMounted(load)
</script>

<template>
  <div class="vocab">
    <div class="vocab__filters">
      <div class="vocab__search">
        <Search :size="14" class="vocab__search-icon" />
        <input
          v-model="search"
          type="text"
          placeholder="搜索单词..."
          class="vocab__search-input"
          @input="onSearchInput"
        />
      </div>
      <el-checkbox v-model="favoriteOnly" @change="resetAndLoad">只看收藏</el-checkbox>
      <span class="vocab__count">共 {{ total }} 个词条</span>
    </div>

    <div v-loading="loading" class="vocab__list">
      <div v-for="word in words" :key="word.id" class="vocab-item ielts-card">
        <div class="vocab-item__main">
          <div class="vocab-item__word">{{ word.word }}</div>
          <div v-if="word.context_en" class="vocab-item__context">{{ word.context_en }}</div>
          <button
            v-if="word.source_topic_name"
            class="vocab-item__source"
            @click="goTopic(word)"
          >
            来自：{{ word.source_topic_name }}
          </button>
        </div>
        <div class="vocab-item__actions">
          <button
            class="vocab-item__icon-btn"
            :class="{ 'is-fav': word.is_favorite }"
            :title="word.is_favorite ? '取消收藏' : '收藏'"
            @click="toggleFavorite(word)"
          >
            <Star :size="16" :fill="word.is_favorite ? 'currentColor' : 'none'" />
          </button>
          <button class="vocab-item__icon-btn is-danger" title="删除" @click="removeWord(word)">
            <Trash2 :size="16" />
          </button>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && words.length === 0" description="词汇本还是空的，去话题详情页收藏高分表达吧">
      <el-button type="primary" @click="router.push({ name: 'topics' })">浏览话题库</el-button>
    </el-empty>

    <div v-if="total > pageSize" class="vocab__pagination">
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
.vocab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 860px;
}

.vocab__filters {
  display: flex;
  align-items: center;
  gap: 14px;
}

.vocab__search {
  position: relative;
  flex: 1;
  max-width: 320px;
}

.vocab__search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--ielts-muted-foreground);
}

.vocab__search-input {
  width: 100%;
  padding: 8px 12px 8px 30px;
  border: 1px solid var(--ielts-border);
  border-radius: 6px;
  background: var(--ielts-card);
  font-size: var(--ielts-text-sm);
}

.vocab__search-input:focus {
  outline: none;
  border-color: var(--ielts-primary);
}

.vocab__count {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  margin-left: auto;
}

.vocab__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 120px;
}

.vocab-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
}

.vocab-item__word {
  font-weight: 600;
  color: var(--ielts-primary);
}

.vocab-item__context {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  font-style: italic;
  margin-top: 4px;
  line-height: 1.6;
}

.vocab-item__source {
  border: none;
  background: none;
  padding: 0;
  margin-top: 6px;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  cursor: pointer;
  text-decoration: underline dotted;
}

.vocab-item__source:hover {
  color: var(--ielts-primary);
}

.vocab-item__actions {
  display: flex;
  gap: 6px;
}

.vocab-item__icon-btn {
  border: 1px solid var(--ielts-border);
  border-radius: 6px;
  background: none;
  padding: 6px;
  cursor: pointer;
  color: var(--ielts-muted-foreground);
  display: inline-flex;
}

.vocab-item__icon-btn:hover {
  color: var(--ielts-primary);
  border-color: var(--ielts-primary);
}

.vocab-item__icon-btn.is-fav {
  color: #f5a623;
  border-color: #f5a623;
}

.vocab-item__icon-btn.is-danger:hover {
  color: var(--ielts-danger, #e5484d);
  border-color: var(--ielts-danger, #e5484d);
}

.vocab__pagination {
  display: flex;
  justify-content: center;
}
</style>
