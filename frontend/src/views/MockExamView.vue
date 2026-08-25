<script setup lang="ts">
</script>

<template>
  <el-empty description="模拟考试模式将随语音与评分模块（Part B + C + D）上线">
    <template #image>
      <div class="empty-icon">🎯</div>
    </template>
    <p class="empty-hint">
      完整还原 Part 1 → 2 → 3 考试流程，严格计时，结束后生成综合评分报告。
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
