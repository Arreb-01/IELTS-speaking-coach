<script setup lang="ts">
import { NotebookPen } from 'lucide-vue-next'
</script>

<template>
  <div class="mistakes ielts-card">
    <el-empty :image-size="90">
      <template #image>
        <NotebookPen :size="64" color="var(--ielts-muted-foreground)" />
      </template>
      <template #description>
        <div class="mistakes__title">错题本即将上线</div>
        <div class="mistakes__sub">练习评分后，逐句分析发现的语法与用词问题会自动收录到这里</div>
      </template>
    </el-empty>
  </div>
</template>

<style scoped>
.mistakes {
  padding: 60px 20px;
  max-width: 860px;
}

.mistakes__title {
  font-size: var(--ielts-text-md);
  font-weight: 600;
  margin-bottom: 6px;
}

.mistakes__sub {
  font-size: var(--ielts-text-sm);
  color: var(--ielts-muted-foreground);
}
</style>
