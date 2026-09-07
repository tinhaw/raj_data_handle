<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { queryWithdrawPendingMonitor } from '../api/withdrawOrders'
import type {
  WithdrawOrderQueryRange,
  WithdrawPendingMonitorResponse,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const monitor = ref<WithdrawPendingMonitorResponse | null>(null)
let refreshTimer: number | undefined

const rangeLabels: Record<WithdrawOrderQueryRange, string> = {
  today: '当天 00:00 至当前时刻',
  last_1_hour: '最近 1 小时',
  last_2_hours: '最近 2 小时',
  last_3_hours: '最近 3 小时',
  last_6_hours: '最近 6 小时',
  last_12_hours: '最近 12 小时',
  last_24_hours: '最近 24 小时',
  last_48_hours: '最近 48 小时',
}

function clearAutoRefresh(): void {
  if (refreshTimer) window.clearInterval(refreshTimer)
  refreshTimer = undefined
}

function scheduleAutoRefresh(intervalHours: number): void {
  clearAutoRefresh()
  refreshTimer = window.setInterval(() => {
    void load()
  }, intervalHours * 60 * 60 * 1_000)
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
    const nextMonitor = await queryWithdrawPendingMonitor()
    monitor.value = nextMonitor
    scheduleAutoRefresh(nextMonitor.refreshIntervalHours)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '待处理提现监控加载失败。'))
  } finally {
    loading.value = false
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
        <p>同页汇总所有已启用盘口中待审核与待审查的提现申请数量。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">立即刷新</el-button>
    </header>

    <el-alert
      title="远端只读汇总"
      description="本页仅向各盘口请求两个状态的汇总数量：待审核（0）和待审查（4）。不会下载、缓存或显示订单明细。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-if="monitor" class="surface-card monitor-policy">
      <div>
        <span>自动刷新</span>
        <strong>每 {{ monitor.refreshIntervalHours }} 小时</strong>
      </div>
      <div>
        <span>查询范围</span>
        <strong>{{ rangeLabels[monitor.queryRange] }}</strong>
      </div>
      <div>
        <span>上次汇总</span>
        <strong>{{ formatDateTime(monitor?.generatedAt) }}</strong>
      </div>
      <router-link class="policy-link" to="/settings/system">调整监控设置</router-link>
    </section>

    <section v-if="monitor" class="monitor-metrics">
      <article class="surface-card monitor-metric monitor-metric--warning">
        <span>待审核</span>
        <strong>{{ monitor.pendingAuditTotal }}</strong>
        <small>状态值 0</small>
      </article>
      <article class="surface-card monitor-metric monitor-metric--primary">
        <span>待审查</span>
        <strong>{{ monitor.pendingReviewTotal }}</strong>
        <small>状态值 4</small>
      </article>
      <article class="surface-card monitor-metric">
        <span>待处理合计</span>
        <strong>{{ monitor.pendingTotal }}</strong>
        <small>成功查询 {{ monitor.successfulSourceCount }} / {{ monitor.sourceCount }} 个盘口</small>
      </article>
    </section>

    <el-alert
      v-if="monitor?.partial"
      title="部分盘口未完成查询"
      description="合计只包含查询成功的盘口；请查看下表中的状态说明。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="surface-card monitor-table-card" v-loading="loading">
      <div class="section-heading">
        <div>
          <h2>盘口汇总</h2>
          <p>时间范围按每个盘口的业务时区计算。</p>
        </div>
        <el-tag v-if="monitor" type="info">{{ monitor.sources.length }} 个盘口</el-tag>
      </div>

      <el-empty
        v-if="monitor && !monitor.sources.length"
        description="暂无已启用且已配置后台地址的盘口。"
      />
      <el-table v-else-if="monitor" :data="monitor.sources" stripe>
        <el-table-column label="盘口" min-width="180">
          <template #default="{ row }">
            <strong>{{ row.sourceDisplayName }}</strong>
            <div class="source-id">{{ row.sourceId }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="businessTimezone" label="业务时区" min-width="150" />
        <el-table-column label="查询时间范围" min-width="330">
          <template #default="{ row }">
            {{ row.createTimeStart }} — {{ row.createTimeEnd }}
          </template>
        </el-table-column>
        <el-table-column prop="pendingAuditCount" label="待审核" min-width="105" align="right" />
        <el-table-column prop="pendingReviewCount" label="待审查" min-width="105" align="right" />
        <el-table-column label="合计" min-width="90" align="right">
          <template #default="{ row }">{{ row.pendingAuditCount + row.pendingReviewCount }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="140">
          <template #default="{ row }">
            <el-tag :type="monitorStatusType(row.status)">{{ monitorStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="240">
          <template #default="{ row }">{{ row.message || '—' }}</template>
        </el-table-column>
        <el-table-column label="查询时间" min-width="190">
          <template #default="{ row }">{{ formatDateTime(row.queriedAt) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.monitor-policy,
.monitor-metrics {
  display: grid;
  gap: 16px;
}

.monitor-policy {
  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;
  align-items: center;
  padding: 18px 22px;
}

.monitor-policy > div,
.monitor-metric {
  display: grid;
  gap: 5px;
}

.monitor-policy span,
.monitor-metric span,
.monitor-metric small,
.section-heading p,
.source-id {
  color: var(--ink-muted);
}

.monitor-policy span,
.monitor-metric span,
.monitor-metric small,
.source-id,
.section-heading p {
  font-size: 13px;
}

.policy-link {
  color: var(--el-color-primary);
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.monitor-metrics {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.monitor-metric {
  padding: 22px;
}

.monitor-metric strong {
  color: var(--ink);
  font-size: 32px;
  font-variant-numeric: tabular-nums;
}

.monitor-metric--warning {
  border-top: 3px solid var(--el-color-warning);
}

.monitor-metric--primary {
  border-top: 3px solid var(--el-color-primary);
}

.monitor-table-card {
  min-width: 0;
  overflow: hidden;
  padding: 22px;
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

.source-id {
  margin-top: 3px;
}

@media (max-width: 980px) {
  .monitor-policy,
  .monitor-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
