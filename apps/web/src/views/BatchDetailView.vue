<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import {
  Back,
  Check,
  Download,
  RefreshRight,
  VideoPause,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  cancelBatch,
  confirmBatch,
  downloadBatchExport,
  fetchBatch,
  fetchBatchCharts,
  fetchBatchResults,
  fetchBatchSummary,
  rerunBatch,
} from '../api/batches'
import { apiErrorMessage } from '../api/client'
import ChartPanel from '../components/ChartPanel.vue'
import type {
  BatchCharts,
  BatchRecord,
  BatchSummary,
  OrderResult,
  OrderResultList,
} from '../types'
import { formatDateTime, resultStatusLabel, statusLabel, statusTagType } from '../ui'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const acting = ref(false)
const batch = ref<BatchRecord | null>(null)
const summary = ref<BatchSummary | null>(null)
const charts = ref<BatchCharts | null>(null)
const results = ref<OrderResultList>({ items: [], total: 0 })
const resultStatus = ref('')
const currentPage = ref(1)
const pageSize = 50
const batchId = computed(() => String(route.params.batchId))
let pollTimer: number | undefined

const activeStatuses = ['queued', 'validating', 'fetching_remote', 'comparing', 'rechecking']
const cancellable = computed(() => activeStatuses.includes(batch.value?.status || ''))
const rerunnable = computed(() =>
  ['completed', 'failed', 'comparison_incomplete', 'cancelled'].includes(
    batch.value?.status || '',
  ),
)
const awaitingConfirmation = computed(() => batch.value?.status === 'awaiting_confirmation')
const statusOptions = computed(() =>
  (charts.value?.resultStatusDistribution || []).map((item) => item.status),
)

const resultDistributionOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 28, right: 20, top: 24, bottom: 34, containLabel: true },
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: {
    type: 'category',
    data: (charts.value?.resultStatusDistribution || []).map((item) =>
      resultStatusLabel(item.status),
    ),
  },
  series: [{
    type: 'bar',
    data: (charts.value?.resultStatusDistribution || []).map((item) => item.count),
    itemStyle: { color: '#2a9d8f', borderRadius: [0, 6, 6, 0] },
  }],
}))

const matrixOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 28, right: 20, top: 24, bottom: 80, containLabel: true },
  xAxis: {
    type: 'category',
    axisLabel: { rotate: 35 },
    data: (charts.value?.paymentStatusResultMatrix || []).map(
      (item) =>
        `${String(item.paymentStatus)} / ${resultStatusLabel(String(item.resultStatus))}`,
    ),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'bar',
    data: (charts.value?.paymentStatusResultMatrix || []).map((item) => Number(item.count)),
    itemStyle: { color: '#457b9d' },
  }],
}))

const timeSeriesOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 28, right: 20, top: 24, bottom: 34, containLabel: true },
  xAxis: {
    type: 'category',
    data: (charts.value?.timeSeries || []).map((item) => String(item.date)),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'line',
    smooth: true,
    data: (charts.value?.timeSeries || []).map((item) => Number(item.count)),
    areaStyle: { opacity: 0.12 },
    itemStyle: { color: '#e76f51' },
  }],
}))

const channelOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 28, right: 20, top: 24, bottom: 54, containLabel: true },
  xAxis: {
    type: 'category',
    axisLabel: { rotate: 25 },
    data: (charts.value?.channelComparison || []).map((item) => String(item.channel)),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'bar',
    data: (charts.value?.channelComparison || []).map((item) => Number(item.count)),
    itemStyle: { color: '#f4a261' },
  }],
}))

function remoteValue(row: OrderResult, key: string): unknown {
  return row.payloadJson.remoteOrder?.[key] ?? '—'
}

async function loadResults(): Promise<void> {
  results.value = await fetchBatchResults(batchId.value, {
    result_status: resultStatus.value || undefined,
    limit: pageSize,
    offset: (currentPage.value - 1) * pageSize,
  })
}

async function load(showLoading = true): Promise<void> {
  if (showLoading) loading.value = true
  try {
    const [detail, aggregate, chartData] = await Promise.all([
      fetchBatch(batchId.value),
      fetchBatchSummary(batchId.value),
      fetchBatchCharts(batchId.value),
    ])
    batch.value = detail
    summary.value = aggregate
    charts.value = chartData
    await loadResults()
    if (!activeStatuses.includes(detail.status) && pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = undefined
    }
  } catch (error) {
    if (showLoading) ElMessage.error(apiErrorMessage(error, '批次详情加载失败。'))
  } finally {
    loading.value = false
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = window.setInterval(() => void load(false), 3000)
}

async function confirmAndStart(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将按当前模板、渠道和时间口径启动只读比对。确认后参数不可修改。',
      '确认并启动',
      { type: 'warning', confirmButtonText: '启动比对' },
    )
    acting.value = true
    batch.value = await confirmBatch(batchId.value)
    ElMessage.success('批次已进入执行队列。')
    startPolling()
    await load(false)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '启动比对失败。'))
  } finally {
    acting.value = false
  }
}

async function rerun(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将使用当前盘口配置创建新的执行版本，启动前仍需再次确认。',
      '确认重新比对',
      { type: 'warning', confirmButtonText: '创建新版本' },
    )
    const created = await rerunBatch(batchId.value)
    ElMessage.success(`已创建执行版本 V${created.runVersion}`)
    await router.push(`/batches/${created.id}`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '重新比对失败。'))
  }
}

async function cancel(): Promise<void> {
  try {
    const result = await ElMessageBox.prompt(
      '取消后不会发布确认遗漏结论。原因可选。',
      '取消执行',
      { type: 'warning', confirmButtonText: '确认取消', inputPlaceholder: '取消原因（可选）' },
    )
    await cancelBatch(batchId.value, result.value)
    ElMessage.success('批次已取消。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '取消批次失败。'))
  }
}

async function download(format: 'csv' | 'xlsx'): Promise<void> {
  try {
    await downloadBatchExport(batchId.value, format)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导出失败。'))
  }
}

async function changeResultFilter(): Promise<void> {
  currentPage.value = 1
  await loadResults()
}

onMounted(async () => {
  await load()
  if (activeStatuses.includes(batch.value?.status || '')) startPolling()
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div v-loading="loading" class="page-stack">
    <header class="page-header">
      <div>
        <el-button text :icon="Back" @click="router.push('/batches')">返回批次中心</el-button>
        <span class="page-eyebrow">Batch detail</span>
        <h1>{{ batch?.sourceDisplayName || '批次详情' }} · V{{ batch?.runVersion || 1 }}</h1>
        <p>{{ batch?.uploadedFileName || '—' }}</p>
      </div>
      <div class="header-actions">
        <el-button
          v-if="awaitingConfirmation"
          type="primary"
          :icon="Check"
          :loading="acting"
          @click="confirmAndStart"
        >
          确认并启动
        </el-button>
        <el-button v-if="rerunnable" :icon="RefreshRight" @click="rerun">重新比对</el-button>
        <el-button v-if="cancellable" type="danger" plain :icon="VideoPause" @click="cancel">
          取消执行
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="batch && !batch.isFinal"
      :type="batch.status === 'awaiting_confirmation' ? 'info' : 'warning'"
      :closable="false"
      show-icon
      title="当前结果不是最终业务结论"
      :description="
        batch.status === 'awaiting_confirmation'
          ? '请核对支付模板、渠道、时间口径与币种后启动。'
          : batch.status === 'comparison_incomplete'
            ? batch.errorMessage || '远端数据未完整读取，没有发布确认遗漏结论。'
            : '批次正在执行或已终止；只有完成状态可以导出最终结果。'
      "
    />

    <section v-if="batch" class="surface-card meta-card">
      <div><span>状态</span><el-tag :type="statusTagType(batch.status)">{{ statusLabel(batch.status) }}</el-tag></div>
      <div><span>业务</span><strong>{{ batch.businessType === 'payin' ? '充值 / 代收' : '提现 / 代付' }}</strong></div>
      <div><span>时区</span><strong>{{ batch.sourceBusinessTimezone }}</strong></div>
      <div><span>币种</span><strong>{{ batch.sourceCurrency }}</strong></div>
      <div><span>创建时间</span><strong>{{ formatDateTime(batch.createdAt) }}</strong></div>
      <div><span>结果到期</span><strong>{{ formatDateTime(batch.resultExpiresAt) }}</strong></div>
    </section>

    <div class="metric-grid">
      <article class="metric-card surface-card">
        <span>确认遗漏</span><strong>{{ summary?.counts.confirmed_missing_success || 0 }}</strong>
        <small>仅支付成功状态进入主指标</small>
      </article>
      <article class="metric-card surface-card">
        <span>远端状态异常</span><strong>{{ summary?.counts.remote_status_not_success || 0 }}</strong>
        <small>支付成功、远端非成功</small>
      </article>
      <article class="metric-card surface-card">
        <span>待复查</span><strong>{{ summary?.counts.recheck_inconclusive || 0 }}</strong>
        <small>复查失败或结果不确定</small>
      </article>
      <article class="metric-card surface-card">
        <span>重复冲突</span><strong>{{ summary?.counts.duplicate_payment_conflict || 0 }}</strong>
        <small>不自动判定遗漏</small>
      </article>
    </div>

    <div class="chart-grid">
      <ChartPanel title="结果状态分布" :option="resultDistributionOption" :empty="!charts?.resultStatusDistribution.length" />
      <ChartPanel title="支付状态 × 比对结果" :option="matrixOption" :empty="!charts?.paymentStatusResultMatrix.length" />
      <ChartPanel title="订单与异常趋势" :option="timeSeriesOption" :empty="!charts?.timeSeries.length" />
      <ChartPanel title="渠道对比" :option="channelOption" :empty="!charts?.channelComparison.length" />
    </div>

    <section class="surface-card table-card">
      <div class="section-heading">
        <div>
          <h2>订单明细</h2>
          <p>支付平台状态和远端状态均保留展示；订单号按文本处理。</p>
        </div>
        <div class="header-actions">
          <el-select
            v-model="resultStatus"
            clearable
            placeholder="全部结果状态"
            style="width: 190px"
            @change="changeResultFilter"
          >
            <el-option v-for="item in statusOptions" :key="item" :label="resultStatusLabel(item)" :value="item" />
          </el-select>
          <el-button :disabled="!batch?.isFinal" :icon="Download" @click="download('xlsx')">完整 Excel</el-button>
          <el-button :disabled="!batch?.isFinal" @click="download('csv')">完整 CSV</el-button>
        </div>
      </div>
      <el-table :data="results.items" empty-text="当前筛选条件下没有结果">
        <el-table-column label="比对结果" min-width="190">
          <template #default="{ row }">{{ resultStatusLabel(row.resultStatus) }}</template>
        </el-table-column>
        <el-table-column label="支付状态" min-width="130" prop="paymentStatusRaw" />
        <el-table-column label="商户订单号" min-width="190" prop="merchantOrderNo" show-overflow-tooltip />
        <el-table-column label="支付平台订单号" min-width="190" prop="platformOrderNo" show-overflow-tooltip />
        <el-table-column label="金额 / 币种" min-width="130">
          <template #default="{ row }">{{ row.payloadJson.amount || '—' }} {{ row.payloadJson.currency || '' }}</template>
        </el-table-column>
        <el-table-column label="远端状态" min-width="110">
          <template #default="{ row }">{{ remoteValue(row, 'status') }}</template>
        </el-table-column>
        <el-table-column label="远端渠道" min-width="160">
          <template #default="{ row }">{{ remoteValue(row, '_remote_channel_label') }}</template>
        </el-table-column>
        <el-table-column label="来源行" min-width="120">
          <template #default="{ row }">{{ row.payloadJson.sourceRowNumbers?.join(', ') || '—' }}</template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="results.total > pageSize"
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="results.total"
        layout="prev, pager, next, total"
        @current-change="loadResults"
      />
    </section>
  </div>
</template>

<style scoped>
.meta-card {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  padding: 0;
  background: var(--border);
}

.meta-card > div {
  min-width: 0;
  display: grid;
  gap: 8px;
  padding: 17px;
  background: #fff;
}

.meta-card span {
  color: var(--ink-muted);
  font-size: 12px;
}

.meta-card strong {
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1100px) {
  .meta-card {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
