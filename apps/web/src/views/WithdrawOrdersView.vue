<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { queryWithdrawOrders } from '../api/withdrawOrders'
import ChartPanel from '../components/ChartPanel.vue'
import type {
  SourceConfig,
  WithdrawOrder,
  WithdrawOrderQueryResponse,
  WithdrawOrderSummary,
  WithdrawStatusDictionaryEntry,
} from '../types'
import { formatDateTime } from '../ui'

const emptySummary: WithdrawOrderSummary = {
  orderCount: 0,
  amount: '0.00',
  realAmount: '0.00',
  averageAmount: '0.00',
  statusDistribution: [],
  timeSeries: [],
}

const loading = ref(false)
const sourcesLoading = ref(false)
const sources = ref<SourceConfig[]>([])
const response = ref<WithdrawOrderQueryResponse | null>(null)
const rows = ref<WithdrawOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const refreshSeconds = ref(60)
const knownStatuses = ref<string[]>([])
const filters = reactive({
  sourceId: '',
  dateRange: [] as string[],
  uid: '',
  status: '',
  auditAdmin: '',
})
let refreshTimer: number | undefined

const selectedSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const summary = computed(() => response.value?.summary || emptySummary)
const statusDictionary = computed(() => response.value?.statusDictionary || [])
const statusEntryByCode = computed(
  () => new Map(statusDictionary.value.map((entry) => [entry.code, entry])),
)
const currency = computed(() => response.value?.currency || selectedSource.value?.currency || 'INR')
const timezone = computed(
  () => response.value?.businessTimezone || selectedSource.value?.businessTimezone || 'Asia/Kolkata',
)
const lastUpdatedText = computed(() =>
  response.value ? formatDateTime(response.value.fetchedAt) : '尚未查询',
)
const refreshLabel = computed(() =>
  refreshSeconds.value ? `每 ${refreshSeconds.value < 60 ? `${refreshSeconds.value} 秒` : `${refreshSeconds.value / 60} 分钟`}刷新` : '自动刷新已关闭',
)

function businessDate(timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function setTodayRange(): void {
  const day = businessDate(selectedSource.value?.businessTimezone || 'Asia/Kolkata')
  filters.dateRange = [`${day} 00:00:00`, `${day} 23:59:59`]
}

function amountText(value: string | null | undefined): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currency.value,
      maximumFractionDigits: 2,
    }).format(amount)
  } catch {
    return `${amount.toLocaleString('en-IN', { maximumFractionDigits: 2 })} ${currency.value}`
  }
}

function statusLabel(status: string): string {
  const label = statusEntryByCode.value.get(status)?.label
  return label ? `${label}（${status}）` : `状态 ${status || '—'}`
}

function statusTagType(_status: string): 'info' {
  return 'info'
}

const statusOptions = computed(() => {
  const options = new Map<string, WithdrawStatusDictionaryEntry>()
  for (const entry of statusDictionary.value) {
    if (entry.active || entry.code === filters.status) options.set(entry.code, entry)
  }
  for (const status of knownStatuses.value) {
    if (!options.has(status)) options.set(status, { code: status, label: '', active: true })
  }
  if (filters.status && !options.has(filters.status)) {
    options.set(filters.status, { code: filters.status, label: '', active: false })
  }
  return [...options.values()].sort((left, right) =>
    left.code.localeCompare(right.code, undefined, { numeric: true }),
  )
})

function statusOptionLabel(entry: WithdrawStatusDictionaryEntry): string {
  return `${statusLabel(entry.code)}${entry.active ? '' : ' · 已停用'}`
}

function mergeKnownStatuses(values: string[]): void {
  knownStatuses.value = [...new Set([...knownStatuses.value, ...values])].sort((left, right) =>
    left.localeCompare(right, undefined, { numeric: true }),
  )
}

const trendOption = computed<EChartsOption>(() => ({
  color: ['#1d4e89', '#2a9d8f'],
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0, data: ['订单数', '提现金额'] },
  grid: { left: 54, right: 66, top: 30, bottom: 58 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: summary.value.timeSeries.map((item) => item.bucket),
    axisLabel: { color: '#829ab1', hideOverlap: true },
  },
  yAxis: [
    {
      type: 'value',
      name: '订单数',
      minInterval: 1,
      axisLabel: { color: '#829ab1' },
      splitLine: { lineStyle: { color: '#edf2f7' } },
    },
    {
      type: 'value',
      name: currency.value,
      axisLabel: { color: '#829ab1' },
      splitLine: { show: false },
    },
  ],
  series: [
    {
      name: '订单数',
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      areaStyle: { color: 'rgba(29, 78, 137, 0.08)' },
      data: summary.value.timeSeries.map((item) => item.count),
    },
    {
      name: '提现金额',
      type: 'line',
      smooth: true,
      yAxisIndex: 1,
      symbol: 'none',
      data: summary.value.timeSeries.map((item) => Number(item.amount)),
    },
  ],
}))

const statusOption = computed<EChartsOption>(() => ({
  color: ['#2a9d8f'],
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 50, right: 24, top: 26, bottom: 48 },
  xAxis: {
    type: 'category',
    data: summary.value.statusDistribution.map((item) => statusLabel(item.status)),
    axisLabel: { color: '#829ab1', interval: 0 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { color: '#829ab1' },
    splitLine: { lineStyle: { color: '#edf2f7' } },
  },
  series: [
    {
      name: '订单数',
      type: 'bar',
      barMaxWidth: 46,
      borderRadius: [6, 6, 0, 0],
      data: summary.value.statusDistribution.map((item) => item.count),
    },
  ],
}))

function validateFilters(): boolean {
  if (!filters.sourceId) {
    ElMessage.warning('请先选择盘口。')
    return false
  }
  if (filters.dateRange.length !== 2) {
    ElMessage.warning('请选择完整的创建时间范围。')
    return false
  }
  return true
}

async function load(resetPage = false, quiet = false): Promise<void> {
  if (!validateFilters() || loading.value) return
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const result = await queryWithdrawOrders({
      sourceId: filters.sourceId,
      createTimeStart: filters.dateRange[0]!,
      createTimeEnd: filters.dateRange[1]!,
      uid: filters.uid || undefined,
      status: filters.status || undefined,
      auditAdmin: filters.auditAdmin || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    response.value = result
    rows.value = result.items
    total.value = result.total
    mergeKnownStatuses(result.summary.statusDistribution.map((item) => item.status))
    if (!result.complete && !quiet) {
      ElMessage.warning('远端分页期间数据发生变化，本次汇总可能不完整，请稍后刷新。')
    }
  } catch (error) {
    if (!quiet) ElMessage.error(apiErrorMessage(error, '提现订单加载失败。'))
  } finally {
    loading.value = false
  }
}

function resetTimer(): void {
  if (refreshTimer) window.clearInterval(refreshTimer)
  refreshTimer = undefined
  if (refreshSeconds.value > 0) {
    refreshTimer = window.setInterval(() => {
      void load(false, true)
    }, refreshSeconds.value * 1_000)
  }
}

function handleSourceChange(): void {
  setTodayRange()
  page.value = 1
  response.value = null
  rows.value = []
  total.value = 0
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void load(false)
}

function handlePageSizeChange(nextPageSize: number): void {
  pageSize.value = nextPageSize
  void load(true)
}

watch(refreshSeconds, resetTimer)

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value.length) {
      filters.sourceId = sources.value[0]!.sourceId
      setTodayRange()
      await load(true)
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。'))
  } finally {
    sourcesLoading.value = false
  }
  resetTimer()
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="page-stack withdraw-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">WITHDRAWAL MONITOR</span>
        <h1>提现订单</h1>
        <p>按业务时间查询远端提现订单，自动刷新列表，并以相同筛选条件汇总订单量与金额。</p>
      </div>
      <div class="header-actions">
        <div class="refresh-state">
          <span class="refresh-state__dot" :class="{ 'is-live': refreshSeconds > 0 }" />
          <div>
            <strong>{{ refreshLabel }}</strong>
            <small>更新于 {{ lastUpdatedText }}</small>
          </div>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="load(false)">立即刷新</el-button>
      </div>
    </header>

    <section class="query-card surface-card">
      <div class="query-card__grid">
        <label class="query-field">
          <span>盘口</span>
          <el-select
            v-model="filters.sourceId"
            :loading="sourcesLoading"
            placeholder="选择已启用盘口"
            @change="handleSourceChange"
          >
            <el-option
              v-for="source in sources"
              :key="source.sourceId"
              :label="source.displayName"
              :value="source.sourceId"
            />
          </el-select>
        </label>
        <label class="query-field query-field--time">
          <span>创建时间（{{ timezone }}）</span>
          <el-date-picker
            v-model="filters.dateRange"
            type="datetimerange"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm:ss"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
          />
        </label>
        <label class="query-field">
          <span>用户 UID</span>
          <el-input v-model.trim="filters.uid" clearable placeholder="精确 UID" />
        </label>
        <label class="query-field">
          <span>状态</span>
          <el-select v-model="filters.status" clearable placeholder="全部状态">
            <el-option
              v-for="item in statusOptions"
              :key="item.code"
              :label="statusOptionLabel(item)"
              :value="item.code"
            />
          </el-select>
        </label>
        <label class="query-field">
          <span>操作人员</span>
          <el-input v-model.trim="filters.auditAdmin" clearable placeholder="包含匹配" />
        </label>
        <label class="query-field">
          <span>自动刷新</span>
          <el-select v-model="refreshSeconds">
            <el-option label="关闭" :value="0" />
            <el-option label="每 30 秒" :value="30" />
            <el-option label="每 1 分钟" :value="60" />
            <el-option label="每 5 分钟" :value="300" />
          </el-select>
        </label>
      </div>
      <div class="query-card__footer">
        <span>
          截止时间晚于当前时刻时，后端会自动截断到本次请求时间；单次查询最多 31 天。
        </span>
        <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">
          查询订单
        </el-button>
      </div>
    </section>

    <section class="metric-grid" aria-label="提现订单汇总">
      <article class="surface-card metric-card metric-card--orders">
        <span>订单总数</span>
        <strong>{{ summary.orderCount.toLocaleString() }}</strong>
        <small>当前筛选条件</small>
      </article>
      <article class="surface-card metric-card">
        <span>提现金额</span>
        <strong>{{ amountText(summary.amount) }}</strong>
        <small>amount 汇总</small>
      </article>
      <article class="surface-card metric-card">
        <span>实际到账</span>
        <strong>{{ amountText(summary.realAmount) }}</strong>
        <small>real_amount 汇总</small>
      </article>
      <article class="surface-card metric-card">
        <span>平均提现金额</span>
        <strong>{{ amountText(summary.averageAmount) }}</strong>
        <small>提现金额 / 订单数</small>
      </article>
    </section>

    <section class="chart-grid">
      <ChartPanel
        title="订单与金额趋势"
        :option="trendOption"
        :empty="summary.timeSeries.length === 0"
        :height="300"
      />
      <ChartPanel
        title="订单状态分布"
        :option="statusOption"
        :empty="summary.statusDistribution.length === 0"
        :height="300"
      />
    </section>

    <section class="surface-card table-card">
      <div class="section-heading">
        <div>
          <h2>提现订单列表</h2>
          <p>
            共 {{ total.toLocaleString() }} 条；已读取远端
            {{ response?.fetchedPages || 0 }} 页，统计截止
            {{ response?.effectiveCreateTimeEnd || '—' }}。
          </p>
        </div>
        <el-tag :type="response?.complete === false ? 'warning' : 'success'" effect="plain">
          {{ response?.complete === false ? '分页有变动' : '分页完整' }}
        </el-tag>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="当前条件下暂无提现订单">
        <el-table-column label="订单 ID" min-width="150" prop="id" fixed="left" />
        <el-table-column label="用户 UID" min-width="140" prop="uid" />
        <el-table-column label="提现金额" min-width="140" align="right">
          <template #default="{ row }">{{ amountText(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="实际到账" min-width="140" align="right">
          <template #default="{ row }">{{ amountText(row.realAmount) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="178">
          <template #default="{ row }">{{ row.createTime || '—' }}</template>
        </el-table-column>
        <el-table-column label="提交时间" min-width="178">
          <template #default="{ row }">{{ row.updateTime || '—' }}</template>
        </el-table-column>
        <el-table-column label="完成时间" min-width="178">
          <template #default="{ row }">{{ row.submitTime || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作人员" min-width="140">
          <template #default="{ row }">{{ row.auditAdmin || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="130" fixed="right">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="light">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-pagination">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          @update:current-page="handlePageChange"
          @update:page-size="handlePageSizeChange"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.withdraw-page {
  min-width: 0;
}

.refresh-state {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 170px;
}

.refresh-state__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #a0aec0;
  box-shadow: 0 0 0 4px rgba(160, 174, 192, 0.12);
}

.refresh-state__dot.is-live {
  background: var(--teal);
  box-shadow: 0 0 0 4px rgba(42, 157, 143, 0.13);
}

.refresh-state > div {
  display: grid;
  gap: 2px;
}

.refresh-state strong {
  color: var(--ink);
  font-size: 13px;
}

.refresh-state small {
  color: var(--ink-muted);
  font-size: 11px;
}

.query-card {
  overflow: hidden;
}

.query-card__grid {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(360px, 1.8fr) repeat(4, minmax(150px, 0.8fr));
  gap: 14px;
  padding: 18px;
}

.query-field {
  min-width: 0;
  display: grid;
  gap: 7px;
}

.query-field > span {
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
}

.query-field :deep(.el-select),
.query-field :deep(.el-date-editor) {
  width: 100%;
}

.query-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 18px;
  border-top: 1px solid var(--border);
  background: #f9fbfd;
}

.query-card__footer span {
  color: var(--ink-muted);
  font-size: 12px;
}

.metric-card {
  position: relative;
  overflow: hidden;
}

.metric-card::before {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--teal), #76c7bd);
  content: '';
}

.metric-card--orders::before {
  background: linear-gradient(90deg, var(--primary), #5d8fc5);
}

.metric-card strong {
  overflow: hidden;
  font-size: clamp(22px, 2vw, 30px);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-card :deep(.el-table) {
  cursor: default;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px 10px;
  border-top: 1px solid var(--border);
}

@media (max-width: 1500px) {
  .query-card__grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .query-field--time {
    grid-column: span 2;
  }
}

@media (max-width: 900px) {
  .query-card__grid {
    grid-template-columns: 1fr 1fr;
  }

  .query-field--time {
    grid-column: 1 / -1;
  }

  .query-card__footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .query-card__footer .el-button {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .query-card__grid {
    grid-template-columns: 1fr;
  }

  .query-field--time {
    grid-column: auto;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
