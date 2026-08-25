<script setup lang="ts">
</script>

<template>
  <el-empty description="评分报告将随评分反馈系统（Part C）上线">
    <template #image>
      <div class="empty-icon">📊</div>
    </template>
    <p class="empty-hint">
      四维评分（流利度 / 词汇 / 语法 / 发音）+ 逐句分析 + 中文深度反馈 + 提分趋势。
    </p>
  </el-empty>
</template>

<style scoped>
.empty-icon {
  font-size: 48px;
  margin-bottom: 8px;
}

.empty-hint {
  margin: 0;
  color: var(--ielts-muted-foreground);
  font-size: var(--ielts-text-sm);
  max-width: 420px;
}
</style>
