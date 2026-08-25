<script setup lang="ts">
import { Pause, Play } from 'lucide-vue-next'
import { onBeforeUnmount, ref } from 'vue'

import { client } from '@/api/client'

const props = defineProps<{ url: string }>()

const playing = ref(false)
const loading = ref(false)
const failed = ref(false)
let objectUrl: string | null = null
let audio: HTMLAudioElement | null = null

async function toggle() {
  if (playing.value) {
    audio?.pause()
    playing.value = false
    return
  }
  if (failed.value) return
  loading.value = true
  try {
    if (!objectUrl) {
      const resp = await client.get(props.url, { responseType: 'blob' })
      objectUrl = URL.createObjectURL(resp.data as Blob)
      audio = new Audio(objectUrl)
      audio.onended = () => {
        playing.value = false
      }
    }
    await audio?.play()
    playing.value = true
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  audio?.pause()
  if (objectUrl) URL.revokeObjectURL(objectUrl)
})
</script>

<template>
  <button class="audio-btn" :class="{ 'is-failed': failed }" :disabled="loading || failed" @click="toggle">
    <Pause v-if="playing" :size="13" />
    <Play v-else :size="13" />
    <span>{{ failed ? '回放不可用' : playing ? '停止' : '回放' }}</span>
  </button>
</template>

<style scoped>
.audio-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--ielts-border);
  background: var(--ielts-card);
  color: var(--ielts-muted-foreground);
  border-radius: var(--ielts-radius-sm);
  padding: 3px 8px;
  font-size: var(--ielts-text-xs);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}

.audio-btn:hover:not(:disabled) {
  color: var(--ielts-primary);
  border-color: var(--ielts-primary);
}

.audio-btn.is-failed {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
