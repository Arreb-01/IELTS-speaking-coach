<script setup lang="ts">
import { AudioWaveform, Brain, Mic, ShieldCheck, Volume2 } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { deleteApiKey, listApiKeys, saveApiKey, testApiKey } from '@/api/apiKeys'
import { extractErrorMessage } from '@/api/client'
import type { ApiKeyOut, ApiKeyStatus, ServiceType } from '@/types'

/** 四类服务的展示元信息（对齐设计稿 api-keys.html） */
const SERVICE_META: Record<
  ServiceType,
  { title: string; subtitle: string; icon: typeof Brain }
> = {
  llm: { title: '大语言模型 LLM', subtitle: '评分反馈与高分表达', icon: Brain },
  asr: { title: '语音识别 ASR', subtitle: '实时转写与流式识别', icon: Mic },
  tts: { title: '语音合成 TTS', subtitle: 'AI 考官语音播报', icon: Volume2 },
  evaluation: { title: '口语评测', subtitle: '发音与流利度评分', icon: AudioWaveform },
}

const SERVICE_ORDER: ServiceType[] = ['llm', 'asr', 'tts', 'evaluation']

const STATUS_META: Record<ApiKeyStatus, { label: string; tone: string }> = {
  valid: { label: '已连接', tone: 'success' },
  unverified: { label: '待验证', tone: 'warning' },
  invalid: { label: '验证失败', tone: 'error' },
  not_configured: { label: '未配置', tone: 'muted' },
}

const LLM_MODELS = [
  { value: 'doubao-1.5-pro-32k-250115', label: 'doubao-1.5-pro-32k（日常评分）' },
  { value: 'doubao-seed-2.1-turbo', label: 'doubao-seed-2.1-turbo（高质量反馈）' },
]

const TTS_VOICES = [
  { value: 'en_female_anna', label: '英音女声 · Anna（亲切）' },
  { value: 'en_female_ariana', label: '美音女声 · Ariana（活力）' },
  { value: 'en_male_jackson', label: '美音男声 · Jackson（活力）' },
]

const keys = reactive<Record<ServiceType, ApiKeyOut | null>>({
  llm: null,
  asr: null,
  tts: null,
  evaluation: null,
})

/** 每张卡片的表单状态：key 输入 + 服务配置 */
const forms = reactive({
  llm: { key: '', model: LLM_MODELS[0]!.value, region: 'cn-beijing' },
  asr: { key: '', appid: '', version: '2.0' },
  tts: { key: '', appid: '', voice: TTS_VOICES[0]!.value },
  evaluation: { key: '' },
})

const saving = reactive<Record<ServiceType, boolean>>({
  llm: false,
  asr: false,
  tts: false,
  evaluation: false,
})
const testing = reactive<Record<ServiceType, boolean>>({
  llm: false,
  asr: false,
  tts: false,
  evaluation: false,
})

const loaded = ref(false)

/** 从已保存的 config 回填表单 */
function backfillForms() {
  const llm = keys.llm
  if (llm?.config.model) forms.llm.model = String(llm.config.model)
  if (llm?.config.region) forms.llm.region = String(llm.config.region)
  const asr = keys.asr
  if (asr?.config.version) forms.asr.version = String(asr.config.version)
  if (asr?.config.appid) forms.asr.appid = String(asr.config.appid)
  const tts = keys.tts
  if (tts?.config.voice) forms.tts.voice = String(tts.config.voice)
  if (tts?.config.appid) forms.tts.appid = String(tts.config.appid)
}

async function refreshList() {
  const list = await listApiKeys()
  for (const item of list) {
    keys[item.service_type] = item
  }
  backfillForms()
}

function placeholder(service: ServiceType): string {
  const key = keys[service]
  const hint =
    service === 'llm' ? '请输入火山引擎方舟 API Key' : '请输入语音服务 Access Token'
  if (key?.configured && key.key_last4) {
    return `••••••••••••****${key.key_last4}（重新输入可更换）`
  }
  return hint
}

function buildConfig(service: ServiceType): Record<string, unknown> {
  switch (service) {
    case 'llm':
      return { model: forms.llm.model, region: forms.llm.region.trim() }
    case 'asr':
      return { appid: forms.asr.appid.trim(), version: forms.asr.version }
    case 'tts':
      return { appid: forms.tts.appid.trim(), voice: forms.tts.voice }
    default:
      return {}
  }
}

async function handleSave(service: ServiceType) {
  saving[service] = true
  try {
    const payload: { key?: string; config: Record<string, unknown> } = {
      config: buildConfig(service),
    }
    const trimmed = forms[service].key.trim()
    if (trimmed) payload.key = trimmed
    keys[service] = await saveApiKey(service, payload)
    forms[service].key = ''
    ElMessage.success(`${SERVICE_META[service].title} 配置已保存`)
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '保存失败，请稍后重试'))
  } finally {
    saving[service] = false
  }
}

async function handleTest(service: ServiceType) {
  testing[service] = true
  try {
    const result = await testApiKey(service)
    if (!result.testable) {
      ElMessage.info(result.message)
      return
    }
    if (result.success) {
      ElMessage.success(
        `${result.message}（${result.latency_ms}ms，${
          result.key_source === 'user' ? '你的 Key' : '平台默认 Key'
        }）`,
      )
    } else {
      ElMessage.warning(result.message)
    }
    await refreshList()
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '测试失败，请稍后重试'))
  } finally {
    testing[service] = false
  }
}

async function handleDelete(service: ServiceType) {
  try {
    await ElMessageBox.confirm(
      `删除后将回退到平台默认 Key（如有），确定删除${SERVICE_META[service].title}的配置吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteApiKey(service)
    keys[service] = null
    forms[service].key = ''
    ElMessage.success('已删除，该服务将使用平台默认 Key')
  } catch (error) {
    ElMessage.error(extractErrorMessage(error, '删除失败，请稍后重试'))
  }
}

const verifiedAtText = (key: ApiKeyOut | null) => {
  if (!key?.last_verified_at) return ''
  return new Date(key.last_verified_at).toLocaleString('zh-CN', { hour12: false })
}

const cards = computed(() =>
  SERVICE_ORDER.map((service) => ({
    service,
    meta: SERVICE_META[service],
    key: keys[service],
    status: STATUS_META[keys[service]?.status ?? 'not_configured'],
  })),
)

onMounted(async () => {
  try {
    await refreshList()
  } finally {
    loaded.value = true
  }
})
</script>

<template>
  <div class="api-keys">
    <el-alert type="info" :closable="false" class="security-banner">
      <template #title>
        <span class="security-banner__title"><ShieldCheck :size="15" /> 安全提示</span>
      </template>
      API Key 经 AES-256 加密存储，任何人（包括你自己）都无法再次查看完整 Key，
      界面仅显示后四位。系统调用 AI 服务时优先使用你配置的 Key，未配置时回退平台默认 Key。
    </el-alert>

    <div v-loading="!loaded" class="cards-grid">
      <div v-for="card in cards" :key="card.service" class="service-card ielts-card">
        <div class="service-card__header">
          <div class="service-card__icon">
            <component :is="card.meta.icon" :size="20" />
          </div>
          <div class="service-card__meta">
            <div class="service-card__title">{{ card.meta.title }}</div>
            <div class="service-card__subtitle">{{ card.meta.subtitle }}</div>
          </div>
          <span class="ielts-badge" :class="`ielts-badge--${card.status.tone}`">
            <span class="ielts-dot"></span>{{ card.status.label }}
          </span>
        </div>

        <div class="service-card__form">
          <el-input
            v-model="forms[card.service].key"
            type="password"
            show-password
            :placeholder="placeholder(card.service)"
            autocomplete="new-password"
          />

          <!-- 服务专属配置 -->
          <div v-if="card.service === 'llm'" class="service-config two-cols">
            <div class="service-config__field">
              <label class="service-config__label">默认模型（可直接输入 ep- 接入点 ID）</label>
              <el-select
                v-model="forms.llm.model"
                filterable
                allow-create
                default-first-option
                placeholder="选择或粘贴模型 ID / ep-xxx"
              >
                <el-option
                  v-for="m in LLM_MODELS"
                  :key="m.value"
                  :value="m.value"
                  :label="m.label"
                />
              </el-select>
            </div>
            <div class="service-config__field">
              <label class="service-config__label">Region</label>
              <el-input v-model="forms.llm.region" placeholder="cn-beijing" />
            </div>
          </div>

          <div v-else-if="card.service === 'asr'" class="service-config">
            <div class="service-config__field">
              <label class="service-config__label">APPID（语音控制台 · 应用管理）</label>
              <el-input v-model="forms.asr.appid" placeholder="例如 4123456789" />
            </div>
            <div class="service-config__field">
              <label class="service-config__label">服务版本</label>
              <el-select v-model="forms.asr.version">
                <el-option value="2.0" label="豆包流式语音识别 2.0" />
                <el-option value="1.0" label="豆包流式语音识别 1.0" />
              </el-select>
            </div>
          </div>

          <div v-else-if="card.service === 'tts'" class="service-config">
            <div class="service-config__field">
              <label class="service-config__label">APPID（语音控制台 · 应用管理）</label>
              <el-input v-model="forms.tts.appid" placeholder="例如 4123456789" />
            </div>
            <div class="service-config__field">
              <label class="service-config__label">考官音色</label>
              <el-select v-model="forms.tts.voice">
                <el-option
                  v-for="v in TTS_VOICES"
                  :key="v.value"
                  :value="v.value"
                  :label="v.label"
                />
              </el-select>
            </div>
          </div>

          <div v-else-if="card.service === 'evaluation'" class="service-config">
            <div class="service-config__field">
              <label class="service-config__label">服务类型</label>
              <el-input model-value="service_type 81（英文口语评测）" disabled />
            </div>
          </div>

          <div v-if="card.key?.last_verified_at" class="verified-at">
        上次验证：{{ verifiedAtText(card.key) }}
          </div>

          <div class="service-card__actions">
            <el-button
              size="small"
              :disabled="!forms[card.service].key && !card.key?.configured"
              :loading="saving[card.service]"
              @click="handleSave(card.service)"
            >
              保存
            </el-button>
            <el-button
              size="small"
              type="primary"
              plain
              :loading="testing[card.service]"
              @click="handleTest(card.service)"
            >
              测试连接
            </el-button>
            <el-button
              v-if="card.key?.configured"
              size="small"
              type="danger"
              plain
              @click="handleDelete(card.service)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.api-keys {
  max-width: 1024px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.security-banner :deep(.security-banner__title) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  min-height: 200px;
}

@media (max-width: 900px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }
}

.service-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  transition: box-shadow 0.2s;
}

.service-card:hover {
  box-shadow: var(--ielts-shadow-md);
}

.service-card__header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.service-card__icon {
  width: 40px;
  height: 40px;
  border-radius: var(--ielts-radius-md);
  background: var(--ielts-accent);
  color: var(--ielts-accent-foreground);
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.service-card__meta {
  flex: 1;
  min-width: 0;
}

.service-card__title {
  font-size: var(--ielts-text-md);
  font-weight: 600;
}

.service-card__subtitle {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.service-card__form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.service-config {
  display: grid;
  gap: 10px;
}

.service-config.two-cols {
  grid-template-columns: 1fr 1fr;
}

@media (max-width: 480px) {
  .service-config.two-cols {
    grid-template-columns: 1fr;
  }
}

.service-config__label {
  display: block;
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
  margin-bottom: 4px;
}

.verified-at {
  font-size: var(--ielts-text-xs);
  color: var(--ielts-muted-foreground);
}

.service-card__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-left: -8px;
  padding-top: 2px;
  border-top: 1px solid var(--ielts-border);
  padding-top: 12px;
}
</style>
