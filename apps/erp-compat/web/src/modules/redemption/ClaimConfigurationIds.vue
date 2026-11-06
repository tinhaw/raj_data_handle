<script setup lang="ts">
defineProps<{ ids: string[]; context: string }>()
</script>

<template>
  <el-popover v-if="ids.length" trigger="click" placement="bottom" :width="280">
    <template #reference>
      <el-button link class="configuration-trigger" :aria-label="`${context}的远端配置 ID`">
        远端 ID：{{ ids[0] }}<span v-if="ids.length > 1"> · {{ ids.length }} 组</span>
      </el-button>
    </template>
    <div class="configuration-heading">远端配置 ID · {{ ids.length }} 组</div>
    <p class="configuration-context">{{ context }}</p>
    <div class="configuration-list" role="list" aria-label="远端配置 ID 列表">
      <span v-for="id in ids" :key="id" role="listitem">{{ id }}</span>
    </div>
    <p class="configuration-help">对应此格统计涉及的配置，包含待同步或更新失败的组。</p>
  </el-popover>
  <span v-else class="configuration-empty">远端 ID：—</span>
</template>

<style scoped>
.configuration-trigger.el-button,
.configuration-empty {
  height: auto;
  padding: 0;
  color: var(--theme-text-muted);
  font-size: 11px;
  line-height: 1.6;
}
.configuration-trigger.el-button { white-space: normal; text-align: right; }
.configuration-trigger.el-button:hover,
.configuration-trigger.el-button:focus-visible { color: var(--el-color-primary); }
.configuration-heading { color: var(--theme-text-strong); font-size: 13px; font-weight: 600; }
.configuration-context,
.configuration-help { margin: 8px 0; color: var(--theme-text-muted); font-size: 12px; line-height: 1.6; }
.configuration-help { margin-bottom: 0; }
.configuration-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  max-height: 180px;
  overflow: auto;
  color: var(--theme-text);
  font-family: ui-monospace, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
  user-select: text;
}
</style>
