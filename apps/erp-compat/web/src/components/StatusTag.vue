<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status?: string | null }>()

const status = computed(() => {
  const map: Record<string, { label: string; type: 'success' | 'warning' | 'info' | 'danger' }> = {
    ACTIVE: { label: '启用', type: 'success' },
    INACTIVE: { label: '已停用', type: 'info' },
    DRAFT: { label: '草稿', type: 'warning' },
    CONFIRMED: { label: '已确认', type: 'success' },
    VOIDED: { label: '已作废', type: 'info' },
    LOCKED: { label: '已锁定', type: 'danger' },
    UNLOCKED: { label: '未锁定', type: 'info' },
    SUCCESS: { label: '成功', type: 'success' },
    OK: { label: '通过', type: 'success' },
    WARNING: { label: '警告', type: 'warning' },
    ERROR: { label: '错误', type: 'danger' },
    PREVIEW_READY: { label: '待提交', type: 'warning' },
    SUCCEEDED: { label: '已完成', type: 'success' },
    FAILED: { label: '失败', type: 'danger' },
    REJECTED: { label: '已拒绝', type: 'danger' },
    CREATE: { label: '新增', type: 'success' },
    UPDATE: { label: '更新草稿', type: 'warning' },
    SKIP: { label: '跳过', type: 'info' },
    CREATED: { label: '已新增', type: 'success' },
    UPDATED: { label: '已更新', type: 'warning' },
    SKIPPED: { label: '已跳过', type: 'info' },
  }
  return map[props.status || ''] || { label: props.status || '—', type: 'info' as const }
})
</script>

<template>
  <el-tag size="small" effect="light" :type="status.type">{{ status.label }}</el-tag>
</template>
