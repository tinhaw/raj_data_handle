<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  fetchRetentionSettings,
  updateRetentionSettings,
} from '../api/systemSettings'
import { queryWithdrawPendingMonitor } from '../api/withdrawOrders'
import { isAdmin } from '../stores/auth'
import type {
  WithdrawPendingMonitorQueryRange,
  WithdrawPendingMonitorRefreshIntervalSeconds,
  WithdrawPendingMonitorResponse,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const savingSettings = ref(false)
const monitor = ref<WithdrawPendingMonitorResponse | null>(null)
const selectedInterval = ref<WithdrawPendingMonitorRefreshIntervalSeconds>(60)
const selectedRange = ref<WithdrawPendingMonitorQueryRange>('india_today')
let refreshTimer: number | undefined

const intervalOptions: WithdrawPendingMonitorRefreshIntervalSeconds[] = [
  5, 10, 15, 20, 25, 30, 60, 120, 300,
]

const settingsDirty = computed(
  () =>
    !!monitor.value &&
    (selectedInterval.value !== monitor.value.refreshIntervalSeconds ||
      selectedRange.value !== monitor.value.queryRange),
)

function clearAutoRefresh(): void {
  if (refreshTimer) window.clearInterval(refreshTimer)
  refreshTimer = undefined
}

function scheduleAutoRefresh(intervalSeconds: number): void {
  clearAutoRefresh()
  refreshTimer = window.setInterval(() => {
    void load()
  }, intervalSeconds * 1_000)
}

function monitorStatusType(status: string): 'success' | 'warning' | 'danger' {
  if (status === 'succeeded') return 'success'
  if (status === 'unavailable') return 'warning'
  return 'danger'
}

function monitorStatusLabel(status: string): string {
  if (status === 'succeeded') return '查询成功'
  if (status === 'unavailable') return '暂不可查询'
  return '查询失败'
}

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const hadUnsavedSettings = settingsDirty.value
    const nextMonitor = await queryWithdrawPendingMonitor()
    monitor.value = nextMonitor
    if (!hadUnsavedSettings) {
      selectedInterval.value = nextMonitor.refreshIntervalSeconds
      selectedRange.value = nextMonitor.queryRange
    }
    scheduleAutoRefresh(nextMonitor.refreshIntervalSeconds)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '待处理提现监控加载失败。'))
  } finally {
    loading.value = false
  }
}

async function applyMonitorSettings(): Promise<void> {
  if (!isAdmin.value || !settingsDirty.value) return
  savingSettings.value = true
  try {
    const current = await fetchRetentionSettings()
    const updated = await updateRetentionSettings({
      uploadedFileRetentionDays: current.uploadedFileRetentionDays,
      resultRetentionDays: current.resultRetentionDays,
      remoteCacheRetentionDays: current.remoteCacheRetentionDays,
      sessionTtlDays: current.sessionTtlDays,
      withdrawPendingMonitorRefreshIntervalSeconds: selectedInterval.value,
      withdrawPendingMonitorQueryRange: selectedRange.value,
    })
    selectedInterval.value = updated.withdrawPendingMonitorRefreshIntervalSeconds
    selectedRange.value = updated.withdrawPendingMonitorQueryRange
    scheduleAutoRefresh(updated.withdrawPendingMonitorRefreshIntervalSeconds)
    await load()
    ElMessage.success('监控参数已更新并生效。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '监控参数保存失败。'))
  } finally {
    savingSettings.value = false
  }
}

onMounted(() => {
  void load()
})

onBeforeUnmount(clearAutoRefresh)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Withdrawal monitor</span>
        <h1>待处理提现监控</h1>
        <p>分别查看各已启用盘口中待审核与待审查的提现申请数量。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">立即刷新</el-button>
    </header>

    <el-alert
      title="远端只读查询"
      description="本页仅向各盘口分别请求两个状态的数量：待审核（0）和待审查（4）。不会下载、缓存或显示订单明细。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-if="monitor" class="surface-card monitor-policy">
      <div class="policy-control">
        <span>刷新时间间隔</span>
        <el-select
          v-model="selectedInterval"
          aria-label="刷新时间间隔"
          :disabled="!isAdmin || savingSettings"
        >
          <el-option
            v-for="seconds in intervalOptions"
            :key="seconds"
            :label="`每 ${seconds} 秒`"
            :value="seconds"
          />
        </el-select>
      </div>
      <div class="policy-control">
        <span>查询范围</span>
        <el-select
          v-model="selectedRange"
          aria-label="查询时间范围"
          :disabled="!isAdmin || savingSettings"
        >
          <el-option label="印度时间今天全天" value="india_today" />
          <el-option label="印度时间昨天全天＋今天全天" value="india_yesterday_today" />
        </el-select>
      </div>
      <div>
        <span>查询时区</span>
        <strong>印度时间（Asia/Kolkata）</strong>
      </div>
      <div>
        <span>上次查询</span>
        <strong>{{ formatDateTime(monitor?.generatedAt) }}</strong>
      </div>
      <el-button
        v-if="isAdmin"
        type="primary"
        :disabled="!settingsDirty"
        :loading="savingSettings"
        @click="applyMonitorSettings"
      >
        应用参数
      </el-button>
    </section>

    <el-alert
      v-if="monitor?.partial"
      title="部分盘口未完成查询"
      description="请查看下方对应盘口卡片中的状态说明，其他盘口不受影响。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="surface-card monitor-sources-card" v-loading="loading">
      <div class="section-heading">
        <div>
          <h2>盘口数据</h2>
          <p>每个盘口独立展示待审核、待审查与合计，异常不会影响其他盘口。</p>
        </div>
        <el-tag v-if="monitor" type="info">{{ monitor.sources.length }} 个盘口</el-tag>
      </div>

      <el-empty
        v-if="monitor && !monitor.sources.length"
        description="暂无已启用且已配置后台地址的盘口。"
      />
      <div v-else-if="monitor" class="source-card-grid">
        <article
          v-for="row in monitor.sources"
          :key="row.sourceId"
          class="source-card"
          :class="`source-card--${row.status}`"
        >
          <header class="source-card__header">
            <div>
              <h3>{{ row.sourceDisplayName }}</h3>
              <span>{{ row.sourceId }}</span>
            </div>
            <el-tag :type="monitorStatusType(row.status)">
              {{ monitorStatusLabel(row.status) }}
            </el-tag>
          </header>

          <div class="source-card__metrics">
            <div>
              <span>待审核</span>
              <strong>{{ row.status === 'succeeded' ? row.pendingAuditCount : '—' }}</strong>
              <small>状态值 0</small>
            </div>
            <div>
              <span>待审查</span>
              <strong>{{ row.status === 'succeeded' ? row.pendingReviewCount : '—' }}</strong>
              <small>状态值 4</small>
            </div>
            <div>
              <span>合计</span>
              <strong>
                {{
                  row.status === 'succeeded'
                    ? row.pendingAuditCount + row.pendingReviewCount
                    : '—'
                }}
              </strong>
              <small>待处理申请</small>
            </div>
          </div>

          <div class="source-card__range">
            <span>印度时间查询范围</span>
            <strong>{{ row.createTimeStart }} — {{ row.createTimeEnd }}</strong>
          </div>
          <footer class="source-card__footer">
            <span>查询时间 {{ formatDateTime(row.queriedAt) }}</span>
            <span v-if="row.message" class="source-card__message">{{ row.message }}</span>
          </footer>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.monitor-policy {
  display: grid;
  gap: 16px;
  grid-template-columns:
    minmax(180px, 0.8fr) minmax(260px, 1.3fr) repeat(2, minmax(0, 1fr)) auto;
  align-items: end;
  padding: 18px 22px;
}

.monitor-policy > div {
  display: grid;
  gap: 5px;
}

.monitor-policy span,
.section-heading p,
.source-card__header span,
.source-card__footer,
.source-card__metrics span,
.source-card__metrics small,
.source-card__range span {
  color: var(--ink-muted);
}

.monitor-policy span,
.section-heading p,
.source-card__header span,
.source-card__footer,
.source-card__metrics span,
.source-card__metrics small,
.source-card__range span {
  font-size: 13px;
}

.policy-control {
  min-width: 0;
}

.monitor-sources-card {
  min-width: 0;
  overflow: hidden;
  padding: 22px;
}

.source-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.source-card {
  display: grid;
  gap: 18px;
  padding: 20px;
  border: 1px solid var(--border);
  border-top: 3px solid var(--el-color-info);
  border-radius: 14px;
  background: #fbfdff;
}

.source-card--succeeded {
  border-top-color: var(--el-color-success);
}

.source-card--failed {
  border-top-color: var(--el-color-danger);
}

.source-card--unavailable {
  border-top-color: var(--el-color-warning);
}

.source-card__header,
.source-card__footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.source-card__header h3 {
  margin: 0 0 4px;
  color: var(--ink-strong);
  font-size: 19px;
}

.source-card__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.source-card__metrics > div {
  display: grid;
  gap: 4px;
  padding: 12px;
  border-radius: 10px;
  background: #f3f7fa;
}

.source-card__metrics strong {
  color: var(--ink-strong);
  font-size: 27px;
  font-variant-numeric: tabular-nums;
}

.source-card__range {
  display: grid;
  gap: 5px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.source-card__range strong {
  color: var(--ink);
  font-size: 14px;
  line-height: 1.5;
}

.source-card__footer {
  align-items: center;
  flex-wrap: wrap;
}

.source-card__message {
  color: var(--el-color-danger);
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.section-heading h2,
.section-heading p {
  margin: 0;
}

.section-heading p {
  margin-top: 5px;
}

@media (max-width: 980px) {
  .monitor-policy {
    grid-template-columns: 1fr;
  }

  .source-card-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .source-card__metrics {
    grid-template-columns: 1fr;
  }
}
</style>
