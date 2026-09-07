<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { queryWithdrawPendingMonitor } from '../api/withdrawOrders'
import type {
  WithdrawPendingMonitorQueryRange,
  WithdrawPendingMonitorResponse,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const monitor = ref<WithdrawPendingMonitorResponse | null>(null)
let refreshTimer: number | undefined

const rangeLabels: Record<WithdrawPendingMonitorQueryRange, string> = {
  india_today: '印度时间今天全天',
  india_yesterday_today: '印度时间昨天全天＋今天全天',
}

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
    const nextMonitor = await queryWithdrawPendingMonitor()
    monitor.value = nextMonitor
    scheduleAutoRefresh(nextMonitor.refreshIntervalSeconds)
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
        <strong>每 {{ monitor.refreshIntervalSeconds }} 秒</strong>
      </div>
      <div>
        <span>查询范围</span>
        <strong>{{ rangeLabels[monitor.queryRange] }}</strong>
      </div>
      <div>
        <span>查询时区</span>
        <strong>印度时间（Asia/Kolkata）</strong>
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
      description="合计只包含查询成功的盘口；请查看下方卡片中的状态说明。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="surface-card monitor-sources-card" v-loading="loading">
      <div class="section-heading">
        <div>
          <h2>盘口汇总卡片</h2>
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
.monitor-policy,
.monitor-metrics {
  display: grid;
  gap: 16px;
}

.monitor-policy {
  grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
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
.source-card__header span,
.source-card__footer,
.source-card__metrics span,
.source-card__metrics small,
.source-card__range span {
  color: var(--ink-muted);
}

.monitor-policy span,
.monitor-metric span,
.monitor-metric small,
.section-heading p,
.source-card__header span,
.source-card__footer,
.source-card__metrics span,
.source-card__metrics small,
.source-card__range span {
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
  .monitor-policy,
  .monitor-metrics {
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
