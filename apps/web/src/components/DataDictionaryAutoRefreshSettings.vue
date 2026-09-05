<script setup lang="ts">
import { Clock, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref, watch } from 'vue'

import {
  fetchDataDictionaryRefreshConfig,
  updateDataDictionaryRefreshConfig,
} from '../api/dataDictionaries'
import { apiErrorMessage } from '../api/client'
import type {
  DataDictionaryRefreshConfig,
  RemoteDataDictionaryType,
} from '../types'
import { formatDateTime } from '../ui'

const props = defineProps<{
  sourceId: string
  dictionaryType: RemoteDataDictionaryType
}>()

const intervalOptions: Array<{
  label: string
  value: DataDictionaryRefreshConfig['intervalMinutes']
}> = [
  { label: '每 15 分钟', value: 15 },
  { label: '每 30 分钟', value: 30 },
  { label: '每 1 小时', value: 60 },
  { label: '每 3 小时', value: 180 },
  { label: '每 6 小时', value: 360 },
  { label: '每 12 小时', value: 720 },
  { label: '每 24 小时', value: 1440 },
]

const loading = ref(false)
const saving = ref(false)
const config = ref<DataDictionaryRefreshConfig | null>(null)
const enabled = ref(false)
const intervalMinutes = ref<DataDictionaryRefreshConfig['intervalMinutes']>(360)
let requestSequence = 0

function applyConfig(value: DataDictionaryRefreshConfig): void {
  config.value = value
  enabled.value = value.enabled
  intervalMinutes.value = value.intervalMinutes
}

async function loadConfig(): Promise<void> {
  const sourceId = props.sourceId
  const sequence = ++requestSequence
  if (!sourceId) {
    config.value = null
    enabled.value = false
    intervalMinutes.value = 360
    return
  }
  loading.value = true
  try {
    const result = await fetchDataDictionaryRefreshConfig(props.dictionaryType, sourceId)
    if (sequence === requestSequence) applyConfig(result)
  } catch (error) {
    if (sequence === requestSequence) {
      config.value = null
      ElMessage.error(apiErrorMessage(error, '自动刷新配置加载失败。'))
    }
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function saveConfig(): Promise<void> {
  if (!props.sourceId) {
    ElMessage.warning('请先选择盘口。')
    return
  }
  saving.value = true
  try {
    const result = await updateDataDictionaryRefreshConfig(props.dictionaryType, {
      sourceId: props.sourceId,
      enabled: enabled.value,
      intervalMinutes: intervalMinutes.value,
    })
    applyConfig(result)
    ElMessage.success(result.enabled ? '自动刷新配置已启用。' : '自动刷新已关闭。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '自动刷新配置保存失败。'))
  } finally {
    saving.value = false
  }
}

watch(() => [props.sourceId, props.dictionaryType], loadConfig, { immediate: true })
</script>

<template>
  <section v-loading="loading" class="auto-refresh-settings">
    <div class="auto-refresh-title">
      <div>
        <strong><el-icon><RefreshRight /></el-icon> 自动刷新</strong>
        <span v-if="config">当前盘口：{{ config.sourceDisplayName }}</span>
        <span v-else>选择盘口后可配置</span>
      </div>
      <el-tag v-if="config?.status === 'running'" type="warning">刷新中</el-tag>
      <el-tag v-else-if="config?.status === 'failed'" type="danger">上次失败</el-tag>
      <el-tag v-else-if="config?.lastSucceededAt" type="success">运行正常</el-tag>
      <el-tag v-else type="info">尚未运行</el-tag>
    </div>

    <div class="auto-refresh-controls">
      <el-switch
        v-model="enabled"
        :disabled="!sourceId || saving"
        active-text="开启"
        inactive-text="关闭"
      />
      <el-select
        v-model="intervalMinutes"
        :disabled="!sourceId || !enabled || saving"
        aria-label="自动刷新时间间隔"
      >
        <el-option
          v-for="option in intervalOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-button type="primary" :disabled="!sourceId" :loading="saving" @click="saveConfig">
        保存配置
      </el-button>
    </div>

    <div class="auto-refresh-state">
      <span><el-icon><Clock /></el-icon> 保存配置不会立即读取远端</span>
      <span v-if="config?.nextRefreshAt">下次刷新：{{ formatDateTime(config.nextRefreshAt) }}</span>
      <span v-if="config?.lastSucceededAt">
        最近成功：{{ formatDateTime(config.lastSucceededAt) }}
      </span>
      <span v-if="config?.lastFailedAt" class="failure-state">
        最近失败：{{ formatDateTime(config.lastFailedAt) }} · {{ config.lastError }}
      </span>
    </div>
  </section>
</template>

<style scoped>
.auto-refresh-settings {
  display: grid;
  gap: 12px;
  margin-top: 16px;
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #f8fbfd;
}

.auto-refresh-title,
.auto-refresh-controls,
.auto-refresh-state,
.auto-refresh-title > div,
.auto-refresh-title strong {
  display: flex;
  align-items: center;
}

.auto-refresh-title {
  justify-content: space-between;
  gap: 12px;
}

.auto-refresh-title > div {
  gap: 12px;
}

.auto-refresh-title strong {
  gap: 6px;
  color: var(--ink-strong);
  font-size: 15px;
}

.auto-refresh-title span,
.auto-refresh-state {
  color: var(--ink-muted);
  font-size: 12px;
}

.auto-refresh-controls {
  gap: 12px;
}

.auto-refresh-controls :deep(.el-select) {
  width: 180px;
}

.auto-refresh-state {
  flex-wrap: wrap;
  gap: 8px 18px;
}

.auto-refresh-state span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.failure-state {
  color: var(--el-color-danger) !important;
}

@media (max-width: 700px) {
  .auto-refresh-title,
  .auto-refresh-controls {
    align-items: flex-start;
    flex-direction: column;
  }

  .auto-refresh-controls :deep(.el-select) {
    width: 100%;
  }
}
</style>
