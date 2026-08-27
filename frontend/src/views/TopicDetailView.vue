<script setup lang="ts">
import { ArrowLeft, Bookmark, BookmarkCheck, Link2, Volume2 } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { extractErrorMessage } from '@/api/client'
import { addVocabWord } from '@/api/vocab'
import { fetchTopicDetail, speakText } from '@/api/topics'
import { usePracticeStore } from '@/stores/practice'
import type { ExpressionOut, TopicDetailOut } from '@/types'

const route = useRoute()
const router = useRouter()
const practice = usePracticeStore()

const topic = ref<TopicDetailOut | null>(null)
const loading = ref(false)
const savedExprIds = ref<Set<string>>(new Set())
const speakingKey = ref<string | null>(null)
let currentAudio: HTMLAudioElement | null = null

const tagMeta: Record<string, { label: string; tone: string }> = {
  must: { label: '必考题', tone: 'error' },
  retained: { label: '保留题', tone: 'warning' },
  new: { label: '新题', tone: 'info' },
}

const categoryLabel = computed(() => {
  const map: Record<string, string> = { person: '人物', event: '事件', object: '事物', place: '地点' }
  return topic.value?.category ? map[topic.value.category] ?? topic.value.category : ''
})

const part1Questions = computed(() => topic.value?.questions.filter((q) => q.part === 1) ?? [])
const cueQuestion = computed(() => topic.value?.questions.find((q) => q.part === 2) ?? null)
const part3Questions = computed(() => topic.value?.questions.filter((q) => q.part === 3) ?? [])
const mainAnswer = computed(
  () => topic.value?.sample_answers.find((a) => a.source === 'p2p3') ?? topic.value?.sample_answers[0] ?? null,
)
const linkedAnswers = computed(
  () => topic.value?.sample_answers.filter((a) => a.source === 'linked') ?? [],
)

async function load() {
  loading.value = true
  try {
    topic.value = await fetchTopicDetail(String(route.params.topicId))
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '话题加载失败'))
  } finally {
    loading.value = false
  }
}

async function toggleSpeak(key: string, text: string) {
  if (speakingKey.value === key) {
    currentAudio?.pause()
    speakingKey.value = null
    return
  }
  currentAudio?.pause()
  speakingKey.value = key
  try {
    const blob = await speakText(text)
    const url = URL.createObjectURL(blob)
    currentAudio = new Audio(url)
    currentAudio.onended = () => {
      speakingKey.value = null
      URL.revokeObjectURL(url)
    }
    await currentAudio.play()
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '朗读失败，请检查 TTS 配置'))
    speakingKey.value = null
  }
}

async function saveExpression(expr: ExpressionOut) {
  if (!topic.value || savedExprIds.value.has(expr.id)) return
  try {
    await addVocabWord({
      word: expr.text_en,
      context_en: expr.example_en,
      source_topic_id: topic.value.id,
    })
    savedExprIds.value.add(expr.id)
    ElMessage.success(`「${expr.text_en}」已加入词汇本`)
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '收藏失败'))
  }
}

function startPractice(part: number) {
  if (!topic.value) return
  practice.reset()
  router.push({ name: 'practice', query: { topic: topic.value.id, part: String(part) } })
}

onMounted(load)
onBeforeUnmount(() => currentAudio?.pause())
</script>

<template>
  <div v-loading="loading" class="topic-detail">
    <template v-if="topic">
      <div class="detail-head ielts-card">
        <button class="detail-head__back" @click="router.back()">
          <ArrowLeft :size="16" /> 返回话题库
        </button>
        <div class="detail-head__row">
          <div>
            <h2 class="detail-head__title">{{ topic.name_en }}</h2>
            <div class="detail-head__sub">
              {{ topic.name_zh }}
              <span v-if="categoryLabel" class="detail-head__sep">·</span>
              <span v-if="categoryLabel">{{ categoryLabel }}</span>
            </div>
          </div>
          <div class="detail-head__side">
            <span v-if="topic.tag" class="ielts-badge" :class="`ielts-badge--${tagMeta[topic.tag]?.tone ?? 'muted'}`">
              {{ tagMeta[topic.tag]?.label ?? topic.tag }}
            </span>
            <el-button type="primary" @click="startPractice(cueQuestion ? 2 : part1Questions.length ? 1 : 3)">
              开始练习
            </el-button>
          </div>
        </div>
      </div>

      <!-- Part 2 Cue Card + 主范文 -->
      <div v-if="cueQuestion" class="detail-section ielts-card">
        <h3 class="detail-section__title">Cue Card</h3>
        <div class="cue-card">
          <div class="cue-card__prompt">{{ cueQuestion.content_en }}</div>
          <ul v-if="cueQuestion.cue_card?.you_should_say?.length" class="cue-card__list">
            <li v-for="(point, i) in cueQuestion.cue_card.you_should_say" :key="i">{{ point }}</li>
          </ul>
          <div v-if="cueQuestion.cue_card?.summary_zh" class="cue-card__summary">
            {{ cueQuestion.cue_card.summary_zh }}
          </div>
        </div>
        <el-collapse v-if="mainAnswer" class="answer-collapse">
          <el-collapse-item name="main">
            <template #title>
              <span class="answer-collapse__title">参考范文（点击展开）</span>
              <button
                class="speak-btn"
                :class="{ 'is-speaking': speakingKey === 'main' }"
                @click.stop="toggleSpeak('main', mainAnswer.text_en)"
              >
                <Volume2 :size="14" />
                {{ speakingKey === 'main' ? '停止' : '跟读' }}
              </button>
            </template>
            <p class="answer-text">{{ mainAnswer.text_en }}</p>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- Part 1 题目与范文 -->
      <div v-if="part1Questions.length" class="detail-section ielts-card">
        <h3 class="detail-section__title">Part 1 题目与范文（{{ part1Questions.length }} 题）</h3>
        <el-collapse>
          <el-collapse-item v-for="q in part1Questions" :key="q.id" :name="q.id">
            <template #title>
              <span class="answer-collapse__q">{{ q.content_en }}</span>
            </template>
            <div class="q-answer">
              <p class="answer-text">{{ q.sample_answer?.text_en ?? '暂无范文' }}</p>
              <button
                v-if="q.sample_answer"
                class="speak-btn"
                :class="{ 'is-speaking': speakingKey === q.id }"
                @click="toggleSpeak(q.id, q.sample_answer.text_en)"
              >
                <Volume2 :size="14" />
                {{ speakingKey === q.id ? '停止' : '跟读' }}
              </button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- Part 3 讨论题与范文 -->
      <div v-if="part3Questions.length" class="detail-section ielts-card">
        <h3 class="detail-section__title">Part 3 讨论题与范文（{{ part3Questions.length }} 题）</h3>
        <el-collapse>
          <el-collapse-item v-for="q in part3Questions" :key="q.id" :name="q.id">
            <template #title>
              <span class="answer-collapse__q">{{ q.content_en }}</span>
            </template>
            <div class="q-answer">
              <p class="answer-text">{{ q.sample_answer?.text_en ?? '暂无范文' }}</p>
              <button
                v-if="q.sample_answer"
                class="speak-btn"
                :class="{ 'is-speaking': speakingKey === q.id }"
                @click="toggleSpeak(q.id, q.sample_answer.text_en)"
              >
                <Volume2 :size="14" />
                {{ speakingKey === q.id ? '停止' : '跟读' }}
              </button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 高分表达 -->
      <div v-if="topic.expressions.length" class="detail-section ielts-card">
        <h3 class="detail-section__title">高分表达（{{ topic.expressions.length }}）</h3>
        <div class="expr-list">
          <div v-for="expr in topic.expressions" :key="expr.id" class="expr-item">
            <div class="expr-item__main">
              <span class="expr-item__text">{{ expr.text_en }}</span>
              <span class="expr-item__meaning">{{ expr.meaning_zh }}</span>
            </div>
            <div v-if="expr.example_en" class="expr-item__example">{{ expr.example_en }}</div>
            <button
              class="expr-item__save"
              :class="{ 'is-saved': savedExprIds.has(expr.id) }"
              :disabled="savedExprIds.has(expr.id)"
              @click="saveExpression(expr)"
            >
              <BookmarkCheck v-if="savedExprIds.has(expr.id)" :size="14" />
              <Bookmark v-else :size="14" />
              {{ savedExprIds.has(expr.id) ? '已收藏' : '收藏' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 串联提示 -->
      <div v-for="(link, i) in topic.links" :key="i" class="detail-section ielts-card">
        <h3 class="detail-section__title">
          <Link2 :size="15" style="vertical-align: -2px" /> 串联提示
        </h3>
        <div class="link-tip">
          <div class="link-tip__desc">
            此范文同时适配 <strong>{{ link.linked_topic_names.length }}</strong> 个话题：
            <el-tag v-for="name in link.linked_topic_names" :key="name" size="small" class="link-tip__tag">
              {{ name }}
            </el-tag>
          </div>
          <div class="link-tip__group">{{ link.group_name }}</div>
          <el-collapse class="answer-collapse">
            <el-collapse-item name="linked">
              <template #title>
                <span class="answer-collapse__title">查看串联范文（点击展开）</span>
                <button
                  class="speak-btn"
                  :class="{ 'is-speaking': speakingKey === `linked-${i}` }"
                  @click.stop="toggleSpeak(`linked-${i}`, link.shared_answer.text_en)"
                >
                  <Volume2 :size="14" />
                  {{ speakingKey === `linked-${i}` ? '停止' : '跟读' }}
                </button>
              </template>
              <p v-if="link.shared_answer.summary_zh" class="link-tip__summary">
                {{ link.shared_answer.summary_zh }}
              </p>
              <p class="answer-text">{{ link.shared_answer.text_en }}</p>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>

      <el-empty
        v-if="linkedAnswers.length === 0 && !topic.expressions.length && !topic.questions.length"
        description="该话题暂无参考资料"
      />
    </template>
  </div>
</template>

<style scoped>
.topic-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 860px;
}

.detail-head {
  padding: 20px;
}

.detail-head__back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  cursor: pointer;
  padding: 0 0 12px;
}

.detail-head__back:hover {
  color: var(--ielts-primary);
}

.detail-head__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.detail-head__title {
  font-size: var(--ielts-text-lg);
  font-weight: 600;
  margin: 0;
}

.detail-head__sub {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  margin-top: 4px;
}

.detail-head__sep {
  margin: 0 6px;
}

.detail-head__side {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-section {
  padding: 20px;
}

.detail-section__title {
  font-size: var(--ielts-text-md);
  font-weight: 600;
  margin: 0 0 12px;
}

.cue-card {
  border: 1px solid var(--ielts-border);
  border-radius: 8px;
  padding: 16px;
  background: var(--ielts-muted, #f8fafc);
  margin-bottom: 12px;
}

.cue-card__prompt {
  font-weight: 600;
  line-height: 1.5;
}

.cue-card__list {
  margin: 10px 0 0;
  padding-left: 18px;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  line-height: 1.8;
}

.cue-card__summary {
  margin-top: 10px;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  border-top: 1px dashed var(--ielts-border);
  padding-top: 8px;
}

.answer-collapse__title {
  font-weight: 500;
}

.answer-collapse__q {
  font-size: var(--ielts-text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.answer-text {
  white-space: pre-wrap;
  line-height: 1.8;
  font-size: var(--ielts-text-sm);
  margin: 0;
}

.q-answer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.speak-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--ielts-border);
  border-radius: 5px;
  background: var(--ielts-card);
  color: var(--ielts-primary);
  font-size: var(--ielts-text-xs);
  padding: 3px 8px;
  cursor: pointer;
}

.speak-btn.is-speaking {
  background: var(--ielts-primary);
  color: #fff;
  border-color: var(--ielts-primary);
}

.expr-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.expr-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 12px;
  padding: 12px;
  border: 1px solid var(--ielts-border);
  border-radius: 8px;
}

.expr-item__main {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
}

.expr-item__text {
  font-weight: 600;
  color: var(--ielts-primary);
}

.expr-item__meaning {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}

.expr-item__example {
  grid-column: 1 / -1;
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  font-style: italic;
  line-height: 1.6;
}

.expr-item__save {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--ielts-border);
  border-radius: 5px;
  background: none;
  font-size: var(--ielts-text-xs);
  padding: 3px 8px;
  cursor: pointer;
  color: var(--ielts-foreground);
  height: fit-content;
}

.expr-item__save.is-saved {
  color: var(--ielts-primary);
  border-color: var(--ielts-primary);
}

.expr-item__save:disabled {
  cursor: default;
  opacity: 0.8;
}

.link-tip__desc {
  font-size: var(--ielts-text-sm);
  line-height: 1.8;
}

.link-tip__tag {
  margin: 0 4px;
}

.link-tip__group {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin: 6px 0 10px;
}

.link-tip__summary {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
  margin: 0 0 10px;
}
</style>
