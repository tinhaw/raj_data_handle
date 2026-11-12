<script setup lang="ts">
import { Moon, Sunny } from '@element-plus/icons-vue'

import { isDark } from '../stores/theme'
</script>

<template>
  <div class="theme-toggle">
    <span class="theme-toggle__label" aria-hidden="true">{{ isDark ? '深色' : '浅色' }}</span>
    <el-switch
      v-model="isDark"
      :active-action-icon="Moon"
      :inactive-action-icon="Sunny"
      aria-label="深色主题"
      :title="isDark ? '切换为浅色主题' : '切换为深色主题'"
      :width="44"
    />
  </div>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 3px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
}

.theme-toggle__label {
  color: var(--ink);
  font-size: 12px;
  font-weight: 600;
}

.theme-toggle :deep(.el-switch) {
  --el-switch-on-color: #3878c4;
  --el-switch-off-color: #8b9eb4;
}

.theme-toggle :deep(.el-switch__action) {
  color: #42658d;
}

.theme-toggle :deep(.el-switch.is-checked .el-switch__action) {
  color: #275b9a;
}
</style>
