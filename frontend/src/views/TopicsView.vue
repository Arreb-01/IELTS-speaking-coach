<script setup lang="ts">
</script>

<template>
  <el-empty description="话题练习库将随题库模块（Part D）上线">
    <template #image>
      <div class="empty-icon">📚</div>
    </template>
    <p class="empty-hint">
      将收录 2026 年 5-8 月口语真题：40+ Part 1 话题、50+ Part 2&amp;3 话题，
      支持按薄弱项筛选推荐。
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
