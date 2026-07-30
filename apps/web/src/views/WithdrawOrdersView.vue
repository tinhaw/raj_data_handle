<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import {
  queryWithdrawOperatorSummary,
  queryWithdrawOrders,
  startWithdrawOrderRefresh,
} from '../api/withdrawOrders'
import ChartPanel from '../components/ChartPanel.vue'
import type {
  SourceConfig,
  WithdrawOperatorSummaryItem,
  WithdrawOperatorSummaryResponse,
  WithdrawOrder,
  WithdrawOrderQueryResponse,
  WithdrawOrderSummary,
  WithdrawStatusDictionaryEntry,
} from '../types'
import { formatDateTime } from '../ui'

type WithdrawTab = 'orders' | 'operators'

const emptySummary: WithdrawOrderSummary = {
  orderCount: 0,
  amount: '0.00',
  realAmount: '0.00',
  averageAmount: '0.00',
  statusDistribution: [],
  timeSeries: [],
}

const activeTab = ref<WithdrawTab>('orders')
const loading = ref(false)
const refreshStarting = ref(false)
const sourcesLoading = ref(false)
const sources = ref<SourceConfig[]>([])
const response = ref<WithdrawOrderQueryResponse | null>(null)
const rows = ref<WithdrawOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const queuedAt = ref<string | null>(null)
const knownStatuses = ref<string[]>([])
const filters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  uid: '',
  status: '',
  auditAdmin: '',
})

const operatorSummaryLoading = ref(false)
const operatorSummaryResponse = ref<WithdrawOperatorSummaryResponse | null>(null)
const operatorSummaryPage = ref(1)
const operatorSummaryPageSize = ref(50)
const operatorSummaryChartVisible = ref(false)
const selectedOperatorSummaryItem = ref<WithdrawOperatorSummaryItem | null>(null)
const operatorSummaryFilters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  statuses: [] as string[],
  auditAdmin: '',
})
let orderQueryRequestId = 0
let operatorSummaryRequestId = 0

const selectedOrderSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const selectedOperatorSummarySource = computed(() =>
  sources.value.find((source) => source.sourceId === operatorSummaryFilters.sourceId),
)
const summary = computed(() => response.value?.summary || emptySummary)
const statusDictionary = computed(() => response.value?.statusDictionary || [])
const statusEntryByCode = computed(
  () => new Map(statusDictionary.value.map((entry) => [entry.code, entry])),
)
const operatorSummaryDictionary = computed(() => {
  if (operatorSummaryResponse.value?.sourceId === operatorSummaryFilters.sourceId) {
    return operatorSummaryResponse.value.statusDictionary
  }
  if (response.value?.sourceId === operatorSummaryFilters.sourceId) {
    return response.value.statusDictionary
  }
  return []
})
const operatorSummaryStatusEntryByCode = computed(
  () => new Map(operatorSummaryDictionary.value.map((entry) => [entry.code, entry])),
)
const operatorSummaryStatusColumns = computed(
  () => operatorSummaryResponse.value?.statusColumns || [],
)
const currency = computed(
  () => response.value?.currency || selectedOrderSource.value?.currency || 'INR',
)
const localUpdatedText = computed(() =>
  response.value ? formatDateTime(response.value.localUpdatedAt) : '尚未查询',
)
const operatorSummaryLocalUpdatedText = computed(() =>
  operatorSummaryResponse.value
    ? formatDateTime(operatorSummaryResponse.value.localUpdatedAt)
    : '尚未查询',
)
const operatorSummarySourceName = computed(
  () =>
    operatorSummaryResponse.value?.sourceDisplayName ||
    selectedOperatorSummarySource.value?.displayName ||
    '所选盘口',
)
const operatorSummaryTimezone = computed(
  () =>
    operatorSummaryResponse.value?.businessTimezone ||
    selectedOperatorSummarySource.value?.businessTimezone ||
    '盘口业务时区',
)
const refreshIsIncomplete = computed(
  () => response.value?.refreshStatus === 'succeeded' && response.value.complete === false,
)
const syncTimingText = computed(() => {
  if (response.value?.lastRefreshedAt) {
    if (refreshIsIncomplete.value) {
      return (
        '上次同步 ' +
        formatDateTime(response.value.lastRefreshedAt) +
        ' · 结果不完整，已保留本地缓存'
      )
    }
    return '上次成功 ' + formatDateTime(response.value.lastRefreshedAt)
  }
  if (queuedAt.value) return '请求于 ' + formatDateTime(queuedAt.value)
  return '尚未成功同步'
})
const normalizedRefreshStatus = computed(() => {
  const responseStatus = response.value?.refreshStatus
  const status =
    queuedAt.value && (!responseStatus || responseStatus === 'not_started')
      ? 'queued'
      : responseStatus || 'not_started'
  return status.trim().toLowerCase()
})
const refreshStatusLabel = computed(() => {
  if (refreshIsIncomplete.value) return '同步不完整'
  const labels: Record<string, string> = {
    not_started: '暂无同步记录',
    idle: '等待下次同步',
    queued: '已排队',
    pending: '已排队',
    running: '同步中',
    refreshing: '同步中',
    completed: '同步完成',
    succeeded: '同步完成',
    success: '同步完成',
    failed: '同步失败',
  }
  return labels[normalizedRefreshStatus.value] || response.value?.refreshStatus || '暂无同步记录'
})
const refreshStatusTagType = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  if (refreshIsIncomplete.value) return 'warning'
  if (['failed', 'error'].includes(normalizedRefreshStatus.value)) return 'danger'
  if (['queued', 'pending', 'running', 'refreshing'].includes(normalizedRefreshStatus.value)) {
    return 'warning'
  }
  if (['completed', 'succeeded', 'success'].includes(normalizedRefreshStatus.value)) return 'success'
  return 'info'
})
const refreshInProgress = computed(() =>
  ['queued', 'pending', 'running', 'refreshing'].includes(normalizedRefreshStatus.value),
)
const operatorSummaryStatusOptions = computed(() => {
  const options = new Map<string, WithdrawStatusDictionaryEntry>()
  for (const entry of operatorSummaryDictionary.value) {
    options.set(entry.code, entry)
  }
  for (const status of operatorSummaryStatusColumns.value) {
    if (!options.has(status)) {
      options.set(status, { code: status, label: '', active: true })
    }
  }
  for (const status of operatorSummaryFilters.statuses) {
    if (!options.has(status)) {
      options.set(status, { code: status, label: '', active: false })
    }
  }
  return [...options.values()].sort((left, right) =>
    left.code.localeCompare(right.code, undefined, { numeric: true }),
  )
})

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
    return amount.toLocaleString('en-IN', { maximumFractionDigits: 2 }) + ' ' + currency.value
  }
}

function statusText(
  status: string,
  entries: Map<string, WithdrawStatusDictionaryEntry>,
): string {
  const code = status.trim()
  const label = entries.get(code)?.label?.trim()
  return label || code || '未填写状态'
}

function statusLabel(status: string): string {
  return statusText(status, statusEntryByCode.value)
}

function operatorSummaryStatusLabel(status: string): string {
  return statusText(status, operatorSummaryStatusEntryByCode.value)
}

function statusOptionsLabel(entry: WithdrawStatusDictionaryEntry): string {
  return statusLabel(entry.code) + (entry.active ? '' : ' · 已停用')
}

function operatorSummaryStatusOptionLabel(entry: WithdrawStatusDictionaryEntry): string {
  return operatorSummaryStatusLabel(entry.code) + (entry.active ? '' : ' · 已停用')
}

function mergeKnownStatuses(values: string[]): void {
  knownStatuses.value = [
    ...new Set([...knownStatuses.value, ...values.map((value) => value.trim()).filter(Boolean)]),
  ].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }))
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

function validateFilters(): boolean {
  if (!filters.sourceId) {
    ElMessage.warning('请先选择盘口。')
    return false
  }
  return true
}

function validateOperatorSummaryFilters(): boolean {
  if (!operatorSummaryFilters.sourceId) {
    ElMessage.warning('请先选择需要汇总的盘口。')
    return false
  }
  return true
}

async function load(resetPage = false, quiet = false): Promise<void> {
  if (!validateFilters()) return
  if (resetPage) page.value = 1
  const requestId = ++orderQueryRequestId
  loading.value = true
  try {
    const [createTimeStart, createTimeEnd] = filters.createTimeRange || []
    const hasCreateTimeRange = Boolean(createTimeStart && createTimeEnd)
    const result = await queryWithdrawOrders({
      sourceId: filters.sourceId,
      createTimeStart: hasCreateTimeRange ? createTimeStart : undefined,
      createTimeEnd: hasCreateTimeRange ? createTimeEnd : undefined,
      uid: filters.uid || undefined,
      status: filters.status || undefined,
      auditAdmin: filters.auditAdmin || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (requestId !== orderQueryRequestId) return
    response.value = result
    rows.value = result.items
    total.value = result.total
    mergeKnownStatuses(result.summary.statusDistribution.map((item) => item.status))
  } catch (error) {
    if (requestId === orderQueryRequestId && !quiet) {
      ElMessage.error(apiErrorMessage(error, '本地提现订单加载失败。'))
    }
  } finally {
    if (requestId === orderQueryRequestId) loading.value = false
  }
}

async function loadOperatorSummary(resetPage = false): Promise<void> {
  if (!validateOperatorSummaryFilters()) return
  if (resetPage) operatorSummaryPage.value = 1
  const requestId = ++operatorSummaryRequestId
  operatorSummaryLoading.value = true
  try {
    const [createTimeStart, createTimeEnd] = operatorSummaryFilters.createTimeRange || []
    const hasCreateTimeRange = Boolean(createTimeStart && createTimeEnd)
    const result = await queryWithdrawOperatorSummary({
      sourceId: operatorSummaryFilters.sourceId,
      createTimeStart: hasCreateTimeRange ? createTimeStart : undefined,
      createTimeEnd: hasCreateTimeRange ? createTimeEnd : undefined,
      statuses: operatorSummaryFilters.statuses.length
        ? [...operatorSummaryFilters.statuses]
        : undefined,
      auditAdmin: operatorSummaryFilters.auditAdmin || undefined,
      page: operatorSummaryPage.value,
      pageSize: operatorSummaryPageSize.value,
    })
    if (requestId !== operatorSummaryRequestId) return
    operatorSummaryResponse.value = result
  } catch (error) {
    if (requestId === operatorSummaryRequestId) {
      ElMessage.error(apiErrorMessage(error, '操作人员汇总加载失败。'))
    }
  } finally {
    if (requestId === operatorSummaryRequestId) operatorSummaryLoading.value = false
  }
}

async function startRefresh(): Promise<void> {
  if (!validateFilters() || refreshStarting.value) return
  refreshStarting.value = true
  try {
    const result = await startWithdrawOrderRefresh({ sourceId: filters.sourceId })
    queuedAt.value = result.requestedAt
    ElMessage.success(result.message || '已提交后台同步任务。')
    await load(false, true)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '提现订单后台同步启动失败。'))
  } finally {
    refreshStarting.value = false
  }
}

function resetLocalResult(): void {
  orderQueryRequestId += 1
  response.value = null
  rows.value = []
  total.value = 0
  knownStatuses.value = []
  queuedAt.value = null
}

function resetOperatorSummaryResult(): void {
  operatorSummaryRequestId += 1
  operatorSummaryResponse.value = null
  selectedOperatorSummaryItem.value = null
  operatorSummaryChartVisible.value = false
}

function handleSourceChange(): void {
  page.value = 1
  filters.createTimeRange = null
  filters.status = ''
  resetLocalResult()
  void load(true)
}

function handleOperatorSummarySourceChange(): void {
  operatorSummaryPage.value = 1
  operatorSummaryFilters.createTimeRange = null
  operatorSummaryFilters.statuses = []
  operatorSummaryFilters.auditAdmin = ''
  resetOperatorSummaryResult()
  void loadOperatorSummary(true)
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void load(false)
}

function handlePageSizeChange(nextPageSize: number): void {
  pageSize.value = nextPageSize
  void load(true)
}

function handleOperatorSummaryPageChange(nextPage: number): void {
  operatorSummaryPage.value = nextPage
  void loadOperatorSummary(false)
}

function handleOperatorSummaryPageSizeChange(nextPageSize: number): void {
  operatorSummaryPageSize.value = nextPageSize
  void loadOperatorSummary(true)
}

function handleTabChange(nextTab: string | number): void {
  if (
    nextTab === 'operators' &&
    operatorSummaryResponse.value?.sourceId !== operatorSummaryFilters.sourceId &&
    operatorSummaryFilters.sourceId
  ) {
    void loadOperatorSummary(true)
  }
}

function operatorDisplayName(item: WithdrawOperatorSummaryItem): string {
  return item.auditAdminMissing || !item.auditAdmin.trim()
    ? '未填写操作人员'
    : item.auditAdmin
}

function operatorStatusCount(item: WithdrawOperatorSummaryItem, status: string): number {
  return item.statusCounts.find((entry) => entry.status === status)?.count || 0
}

const operatorChartData = computed(() => {
  const item = selectedOperatorSummaryItem.value
  if (!item) return []
  return operatorSummaryStatusColumns.value
    .map((status) => {
      const label = operatorSummaryStatusLabel(status)
      const code = status.trim()
      return {
        name: label === code || !code ? label : label + '（' + code + '）',
        value: operatorStatusCount(item, status),
      }
    })
    .filter((item) => item.value > 0)
})
const operatorChartEmpty = computed(() => operatorChartData.value.length === 0)
const operatorChartTitle = computed(() => {
  const item = selectedOperatorSummaryItem.value
  return item ? operatorDisplayName(item) + ' · 状态订单占比' : '状态订单占比'
})
const operatorChartOption = computed<EChartsOption>(() => {
  const selectedTotal = selectedOperatorSummaryItem.value?.selectedTotal || 0
  return {
    color: ['#2f80ed', '#40b7b2', '#ffb020', '#78c043', '#ef5350', '#8b64d8', '#5d8fc5'],
    tooltip: {
      trigger: 'item',
      valueFormatter: (value) => String(value) + ' 单',
    },
    title: {
      text: '总订单数\n' + selectedTotal.toLocaleString(),
      subtext: '单',
      left: '31%',
      top: '40%',
      textAlign: 'center',
      textStyle: {
        color: '#17324d',
        fontSize: 24,
        fontWeight: 800,
        lineHeight: 30,
      },
      subtextStyle: {
        color: '#627c96',
        fontSize: 12,
      },
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 14,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      textStyle: { color: '#52677b', fontSize: 12 },
      formatter: (name: string) => {
        const item = operatorChartData.value.find((entry) => entry.name === name)
        const count = item?.value || 0
        const percentage = selectedTotal ? Math.round((count / selectedTotal) * 100) : 0
        return name + '  ' + count.toLocaleString() + '（' + percentage + '%）'
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['31%', '50%'],
        avoidLabelOverlap: true,
        label: {
          show: true,
          position: 'inside',
          formatter: '{d}%',
          color: '#ffffff',
          fontSize: 12,
          fontWeight: 700,
        },
        labelLine: { show: false },
        data: operatorChartData.value,
      },
    ],
  }
})

function openOperatorSummaryChart(item: WithdrawOperatorSummaryItem): void {
  selectedOperatorSummaryItem.value = item
  operatorSummaryChartVisible.value = true
}

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value.length) {
      const firstSourceId = sources.value[0]!.sourceId
      filters.sourceId = firstSourceId
      operatorSummaryFilters.sourceId = firstSourceId
      await load(true)
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。'))
  } finally {
    sourcesLoading.value = false
  }
})
</script>

<template>
  <div class="page-stack withdraw-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">WITHDRAWAL MONITOR</span>
        <h1>提现订单</h1>
        <p>查询本地已同步的提现订单，或按操作人员汇总各状态订单数量。</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="withdraw-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="提现订单查询" name="orders">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>提现订单查询</h2>
              <p>仅查询本地已同步的提现订单；远端同步由系统配置的后台任务执行。</p>
            </div>
            <div class="header-actions">
              <div class="refresh-state">
                <span class="refresh-state__dot" :class="{ 'is-live': refreshInProgress }" />
                <div>
                  <strong>后台同步：{{ refreshStatusLabel }}</strong>
                  <small>{{ syncTimingText }} · 本地更新 {{ localUpdatedText }}</small>
                </div>
              </div>
              <el-button
                :icon="Refresh"
                :loading="refreshStarting"
                :disabled="!filters.sourceId"
                @click="startRefresh"
              >
                启动一次刷新
              </el-button>
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
              <label class="query-field query-field--time-range">
                <span>创建时间（{{ selectedOrderSource?.businessTimezone || '盘口业务时区' }}）</span>
                <el-date-picker
                  v-model="filters.createTimeRange"
                  type="datetimerange"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!filters.sourceId"
                  style="width: 100%"
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
                    :label="statusOptionsLabel(item)"
                    :value="item.code"
                  />
                </el-select>
              </label>
              <label class="query-field">
                <span>操作人员</span>
                <el-input v-model.trim="filters.auditAdmin" clearable placeholder="包含匹配" />
              </label>
            </div>
            <div class="query-card__footer">
              <span>筛选只作用于本地缓存；时间范围按盘口业务时区解释，不影响后台同步的时间范围与间隔。</span>
              <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">
                查询本地订单
              </el-button>
            </div>
          </section>

          <section class="metric-grid" aria-label="提现订单汇总">
            <article class="surface-card metric-card metric-card--orders">
              <span>订单总数</span>
              <strong>{{ summary.orderCount.toLocaleString() }}</strong>
              <small>当前本地筛选条件</small>
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

          <section class="surface-card table-card">
            <div class="section-heading">
              <div>
                <h2>提现订单列表</h2>
                <p>共 {{ total.toLocaleString() }} 条；本地数据更新时间：{{ localUpdatedText }}。</p>
              </div>
              <el-tag :type="refreshStatusTagType" effect="plain">
                {{ refreshStatusLabel }}
              </el-tag>
            </div>
            <el-table v-loading="loading" :data="rows" empty-text="当前本地数据中暂无提现订单">
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
                  <el-tag type="info" effect="light">
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
      </el-tab-pane>

      <el-tab-pane label="操作人员汇总" name="operators">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>操作人员汇总</h2>
              <p>按盘口和创建时间统计操作人员在所选状态下的提现订单数量。</p>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field">
                <span>盘口</span>
                <el-select
                  v-model="operatorSummaryFilters.sourceId"
                  :loading="sourcesLoading"
                  placeholder="选择已启用盘口"
                  @change="handleOperatorSummarySourceChange"
                >
                  <el-option
                    v-for="source in sources"
                    :key="source.sourceId"
                    :label="source.displayName"
                    :value="source.sourceId"
                  />
                </el-select>
              </label>
              <label class="query-field query-field--time-range">
                <span>创建时间（{{ operatorSummaryTimezone }}）</span>
                <el-date-picker
                  v-model="operatorSummaryFilters.createTimeRange"
                  type="datetimerange"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!operatorSummaryFilters.sourceId"
                  style="width: 100%"
                />
              </label>
              <label class="query-field">
                <span>操作人员</span>
                <el-input
                  v-model.trim="operatorSummaryFilters.auditAdmin"
                  clearable
                  placeholder="包含匹配"
                />
              </label>
              <label class="query-field operator-summary-status-field">
                <span>参与统计的状态</span>
                <el-select
                  v-model="operatorSummaryFilters.statuses"
                  multiple
                  :multiple-limit="20"
                  collapse-tags
                  collapse-tags-tooltip
                  clearable
                  placeholder="默认统计全部状态（最多 20 项）"
                >
                  <el-option
                    v-for="item in operatorSummaryStatusOptions"
                    :key="item.code"
                    :label="operatorSummaryStatusOptionLabel(item)"
                    :value="item.code"
                  />
                </el-select>
              </label>
            </div>
            <div class="query-card__footer">
              <span>仅统计本地缓存；未选择状态时统计当前时间范围内的全部状态。空操作人员会单列为“未填写操作人员”。</span>
              <el-button
                type="primary"
                :icon="Search"
                :loading="operatorSummaryLoading"
                @click="loadOperatorSummary(true)"
              >
                查询汇总
              </el-button>
            </div>
          </section>

          <section class="surface-card table-card operator-summary-table-card">
            <div class="section-heading">
              <div>
                <h2>操作人员状态统计</h2>
                <p>
                  {{ operatorSummarySourceName }} · 共
                  {{ (operatorSummaryResponse?.total || 0).toLocaleString() }} 名操作人员 · 已选状态订单
                  {{ (operatorSummaryResponse?.selectedOrderTotal || 0).toLocaleString() }} 单 · 本地数据更新时间：
                  {{ operatorSummaryLocalUpdatedText }}。
                </p>
              </div>
              <el-tag type="info" effect="plain">
                {{ operatorSummaryStatusColumns.length }} 个统计状态
              </el-tag>
            </div>
            <el-table
              v-loading="operatorSummaryLoading"
              :data="operatorSummaryResponse?.items || []"
              empty-text="当前本地筛选条件下暂无操作人员统计"
            >
              <el-table-column label="操作人员" min-width="200" fixed="left">
                <template #default="{ row }">
                  <div class="operator-name-cell" :class="{ 'is-missing': row.auditAdminMissing }">
                    <strong>{{ operatorDisplayName(row) }}</strong>
                    <small v-if="row.auditAdminMissing">原始 audit_admin 为空</small>
                  </div>
                </template>
              </el-table-column>
              <el-table-column
                v-for="status in operatorSummaryStatusColumns"
                :key="status"
                :min-width="136"
                align="center"
              >
                <template #header>
                  <span class="status-column-heading">
                    <strong>{{ operatorSummaryStatusLabel(status) }}</strong>
                    <small v-if="status.trim() && operatorSummaryStatusLabel(status) !== status.trim()">
                      {{ status }}
                    </small>
                  </span>
                </template>
                <template #default="{ row }">
                  <span class="operator-status-count">
                    {{ operatorStatusCount(row, status).toLocaleString() }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="已选合计" min-width="112" align="right" fixed="right">
                <template #default="{ row }">
                  <strong class="operator-selected-total">{{ row.selectedTotal.toLocaleString() }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button
                    text
                    type="primary"
                    :disabled="row.selectedTotal === 0"
                    @click="openOperatorSummaryChart(row)"
                  >
                    图表
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="table-pagination">
              <el-pagination
                background
                layout="total, sizes, prev, pager, next, jumper"
                :total="operatorSummaryResponse?.total || 0"
                :current-page="operatorSummaryPage"
                :page-size="operatorSummaryPageSize"
                :page-sizes="[20, 50, 100]"
                @update:current-page="handleOperatorSummaryPageChange"
                @update:page-size="handleOperatorSummaryPageSizeChange"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="operatorSummaryChartVisible"
      :title="operatorChartTitle"
      width="min(640px, calc(100vw - 32px))"
      destroy-on-close
    >
      <p class="operator-chart-summary">
        已选状态合计
        <strong>{{ selectedOperatorSummaryItem?.selectedTotal.toLocaleString() || 0 }}</strong>
        单；占比仅按当前选中的状态计算。
      </p>
      <ChartPanel
        title="状态订单占比"
        :option="operatorChartOption"
        :empty="operatorChartEmpty"
        :height="300"
        :active="operatorSummaryChartVisible"
        plain
        :show-title="false"
      />
      <template #footer>
        <el-button @click="operatorSummaryChartVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.withdraw-page {
  min-width: 0;
}

.withdraw-tabs {
  min-width: 0;
}

.withdraw-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.withdraw-tabs :deep(.el-tabs__item) {
  height: 52px;
  padding: 0 18px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 800;
}

.withdraw-tabs :deep(.el-tabs__item.is-active) {
  color: var(--teal);
}

.withdraw-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: var(--teal);
}

.withdraw-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border);
}

.withdraw-tabs :deep(.el-tabs__content) {
  padding-top: 20px;
}

.tab-stack {
  display: grid;
  min-width: 0;
  gap: 20px;
}

.tab-pane-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}

.tab-pane-header h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 20px;
}

.tab-pane-header p {
  margin: 6px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
}

.refresh-state {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 240px;
}

.refresh-state__dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
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
  grid-template-columns: repeat(4, minmax(150px, 1fr));
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

.query-field :deep(.el-select) {
  width: 100%;
}

.query-field--time-range {
  grid-column: span 2;
}

.operator-summary-status-field {
  grid-column: 1 / -1;
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

.operator-summary-table-card {
  min-width: 0;
}

.operator-name-cell,
.status-column-heading {
  display: grid;
  gap: 3px;
}

.operator-name-cell strong,
.status-column-heading strong,
.operator-selected-total {
  color: var(--ink-strong);
}

.operator-name-cell small,
.status-column-heading small {
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 500;
}

.operator-name-cell.is-missing strong {
  color: #8b5a19;
}

.operator-status-count {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.operator-selected-total {
  font-variant-numeric: tabular-nums;
}

.operator-chart-summary {
  margin: 0 0 16px;
  color: var(--ink-muted);
  font-size: 13px;
}

.operator-chart-summary strong {
  margin: 0 3px;
  color: var(--ink-strong);
}

@media (max-width: 1100px) {
  .query-card__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .operator-summary-status-field {
    grid-column: span 2;
  }
}

@media (max-width: 900px) {
  .tab-pane-header,
  .header-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-actions {
    width: 100%;
  }

  .refresh-state,
  .header-actions .el-button {
    width: 100%;
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
  .withdraw-tabs :deep(.el-tabs__item) {
    padding: 0 12px;
  }

  .query-card__grid {
    grid-template-columns: 1fr;
  }

  .query-field--time-range,
  .operator-summary-status-field {
    grid-column: span 1;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
