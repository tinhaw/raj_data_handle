<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import {
  querySpinChannelSummary,
  querySpinOrders,
  startSpinOrderRefresh,
} from '../api/spinOrders'
import ChartPanel from '../components/ChartPanel.vue'
import type {
  SourceConfig,
  SpinChannelSummaryResponse,
  SpinOrder,
  SpinOrderQueryResponse,
  SpinOrderRefreshRange,
  SpinOrderSummary,
} from '../types'
import { businessFullDayRange, formatDateTime } from '../ui'

type SpinTab = 'orders' | 'channels'

const SPIN_CONFIG_OPTIONS = [
  { value: '10001', label: '10001（200转盘）' },
  { value: '10002', label: '10002（500转盘）' },
]
const MANUAL_REFRESH_RANGE_OPTIONS: Array<{
  value: SpinOrderRefreshRange
  label: string
  description: string
}> = [
  {
    value: 'day_before_yesterday',
    label: '前天 00:00:00 至 23:59:59',
    description: '按所选盘口业务时区重新读取前天的转盘订单。',
  },
  {
    value: 'yesterday',
    label: '昨天 00:00:00 至 23:59:59',
    description: '按所选盘口业务时区重新读取昨天的转盘订单。',
  },
  {
    value: 'today',
    label: '今日 00:00:00 至当前时刻',
    description: '读取当日截至当前时刻的转盘订单。',
  },
]

const emptySummary: SpinOrderSummary = {
  orderCount: 0,
  passedOrderCount: 0,
  pendingOrderCount: 0,
  rejectedOrderCount: 0,
  suspendedOrderCount: 0,
  approvalRate: '—',
  winnerCount: 0,
  passedWinnerCount: 0,
  personApprovalRate: '—',
  statusDistribution: [],
}

const activeTab = ref<SpinTab>('orders')
const sources = ref<SourceConfig[]>([])
const sourcesLoading = ref(false)
const loading = ref(false)
const channelSummaryLoading = ref(false)
const refreshStarting = ref(false)
const manualRefreshDialogVisible = ref(false)
const manualRefreshQueryRange = ref<SpinOrderRefreshRange>('today')
const response = ref<SpinOrderQueryResponse | null>(null)
const channelSummaryResponse = ref<SpinChannelSummaryResponse | null>(null)
const rows = ref<SpinOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const channelSummaryPage = ref(1)
const channelSummaryPageSize = ref(50)
const queuedAt = ref<string | null>(null)
let ordersRequestId = 0
let channelSummaryRequestId = 0

const filters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  uid: '',
  status: '',
  spinConfigId: '',
  channelId: '',
})
const channelSummaryFilters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  spinConfigId: '',
  channelId: '',
})

const selectedSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const selectedChannelSummarySource = computed(() =>
  sources.value.find((source) => source.sourceId === channelSummaryFilters.sourceId),
)
const summary = computed(() => response.value?.summary || emptySummary)
const statusOptions = computed(() => response.value?.statusDictionary || [])
const channelOptions = computed(() => response.value?.channelDictionary || [])
const channelSummaryOptions = computed(
  () => channelSummaryResponse.value?.channelDictionary || channelOptions.value,
)
const localUpdatedText = computed(() => formatDateTime(response.value?.localUpdatedAt))
const refreshStatusLabel = computed(() => {
  const labels: Record<string, string> = {
    not_started: '等待首次刷新',
    idle: '等待刷新',
    queued: '已排队',
    running: '同步中',
    succeeded: '已完成',
    failed: '刷新失败',
  }
  return labels[response.value?.refreshStatus || 'not_started'] || '等待首次刷新'
})
const refreshStatusTagType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  if (response.value?.refreshStatus === 'succeeded') return 'success'
  if (response.value?.refreshStatus === 'failed') return 'danger'
  if (['queued', 'running'].includes(response.value?.refreshStatus || '')) return 'warning'
  return 'info'
})
const refreshInProgress = computed(() => ['queued', 'running'].includes(response.value?.refreshStatus || ''))
const channelSummaryRows = computed(() => channelSummaryResponse.value?.items || [])
const twoHourSeriesOption = computed<EChartsOption>(() => {
  const bySeries = new Map<string, Array<{ name: string; value: number }>>()
  for (const item of channelSummaryResponse.value?.timeSeries || []) {
    const name = `${item.spinConfigLabel} · ${item.channelName}`
    const point = `${item.date} ${item.bucket}`
    const current = bySeries.get(name) || []
    current.push({ name: point, value: item.applicantCount })
    bySeries.set(name, current)
  }
  const categories = [...new Set(
    [...bySeries.values()].flatMap((points) => points.map((point) => point.name)),
  )].sort()
  return {
    color: ['#2fa69d', '#4f8bc9', '#e9a23b', '#8a67d6', '#d76d80', '#6f849c'],
    tooltip: { trigger: 'axis', confine: true },
    legend: { type: 'scroll', bottom: 0, textStyle: { color: '#53657a' } },
    grid: { left: 52, right: 26, top: 28, bottom: 60, containLabel: true },
    xAxis: { type: 'category', data: categories, axisLabel: { color: '#66798f', rotate: 28 } },
    yAxis: { type: 'value', minInterval: 1, name: '申请人数', axisLabel: { color: '#66798f' } },
    series: [...bySeries.entries()].map(([name, points]) => {
      const values = new Map(points.map((point) => [point.name, point.value]))
      return {
        name,
        type: 'line',
        smooth: true,
        showSymbol: false,
        emphasis: { focus: 'series' },
        data: categories.map((category) => values.get(category) || 0),
      }
    }),
  }
})
const twoHourSeriesEmpty = computed(() => !(channelSummaryResponse.value?.timeSeries.length))

function percentage(value: string): string {
  return value === '—' ? value : `${value}%`
}

function statusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === '1' || status === '101') return 'success'
  if (status === '0' || status === '3') return 'warning'
  if (status === '2') return 'danger'
  return 'info'
}

function todayRange(source: SourceConfig | undefined): [string, string] {
  return businessFullDayRange(source?.businessTimezone || 'Asia/Kolkata', 0)
}

function queryPayload() {
  return {
    sourceId: filters.sourceId,
    createTimeStart: filters.createTimeRange?.[0],
    createTimeEnd: filters.createTimeRange?.[1],
    uid: filters.uid || undefined,
    status: filters.status || undefined,
    spinConfigId: filters.spinConfigId || undefined,
    channelId: filters.channelId || undefined,
    page: page.value,
    pageSize: pageSize.value,
  }
}

async function loadOrders(resetPage = false): Promise<void> {
  if (!filters.sourceId) return
  if (resetPage) page.value = 1
  const requestId = ++ordersRequestId
  loading.value = true
  try {
    const next = await querySpinOrders(queryPayload())
    if (requestId !== ordersRequestId) return
    response.value = next
    rows.value = next.items
    total.value = next.total
  } catch (error) {
    if (requestId === ordersRequestId) {
      ElMessage.error(apiErrorMessage(error, '本地转盘订单加载失败。'))
    }
  } finally {
    if (requestId === ordersRequestId) loading.value = false
  }
}

async function loadChannelSummary(resetPage = false): Promise<void> {
  if (!channelSummaryFilters.sourceId) return
  if (resetPage) channelSummaryPage.value = 1
  const requestId = ++channelSummaryRequestId
  channelSummaryLoading.value = true
  try {
    channelSummaryResponse.value = await querySpinChannelSummary({
      sourceId: channelSummaryFilters.sourceId,
      createTimeStart: channelSummaryFilters.createTimeRange?.[0],
      createTimeEnd: channelSummaryFilters.createTimeRange?.[1],
      spinConfigId: channelSummaryFilters.spinConfigId || undefined,
      channelId: channelSummaryFilters.channelId || undefined,
      page: channelSummaryPage.value,
      pageSize: channelSummaryPageSize.value,
    })
  } catch (error) {
    if (requestId === channelSummaryRequestId) {
      ElMessage.error(apiErrorMessage(error, '转盘渠道汇总加载失败。'))
    }
  } finally {
    if (requestId === channelSummaryRequestId) channelSummaryLoading.value = false
  }
}

async function sourceChanged(): Promise<void> {
  filters.createTimeRange = todayRange(selectedSource.value)
  filters.uid = ''
  filters.status = ''
  filters.spinConfigId = ''
  filters.channelId = ''
  await loadOrders(true)
}

async function channelSummarySourceChanged(): Promise<void> {
  channelSummaryFilters.createTimeRange = todayRange(selectedChannelSummarySource.value)
  channelSummaryFilters.spinConfigId = ''
  channelSummaryFilters.channelId = ''
  await loadChannelSummary(true)
}

async function handleTabChange(tab: string | number): Promise<void> {
  if (tab === 'channels' && !channelSummaryResponse.value) await loadChannelSummary(true)
}

function openManualRefreshDialog(): void {
  manualRefreshQueryRange.value = 'today'
  manualRefreshDialogVisible.value = true
}

async function startManualRefresh(): Promise<void> {
  if (!filters.sourceId) return
  refreshStarting.value = true
  try {
    const result = await startSpinOrderRefresh({
      sourceId: filters.sourceId,
      queryRange: manualRefreshQueryRange.value,
    })
    queuedAt.value = result.requestedAt
    manualRefreshDialogVisible.value = false
    ElMessage.success(result.message)
    await loadOrders()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '转盘订单刷新任务提交失败。'))
  } finally {
    refreshStarting.value = false
  }
}

function handlePageChange(value: number): void {
  page.value = value
  void loadOrders()
}

function handlePageSizeChange(value: number): void {
  pageSize.value = value
  void loadOrders(true)
}

function handleChannelSummaryPageChange(value: number): void {
  channelSummaryPage.value = value
  void loadChannelSummary()
}

function handleChannelSummaryPageSizeChange(value: number): void {
  channelSummaryPageSize.value = value
  void loadChannelSummary(true)
}

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    const first = sources.value[0]
    if (!first) return
    filters.sourceId = first.sourceId
    filters.createTimeRange = todayRange(first)
    channelSummaryFilters.sourceId = first.sourceId
    channelSummaryFilters.createTimeRange = todayRange(first)
    await loadOrders(true)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。'))
  } finally {
    sourcesLoading.value = false
  }
})
</script>

<template>
  <div class="page-stack spin-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">SPIN ORDER MONITOR</span>
        <h1>转盘订单</h1>
        <p>按转盘配置、审核状态和用户渠道来源分析本地缓存的转盘申请订单。</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="spin-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="转盘订单明细" name="orders">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>转盘订单明细</h2>
              <p>只查询本地缓存；远端读取由后台工作进程每两小时执行，也可手动发起一次指定日期刷新。</p>
            </div>
            <div class="header-actions">
              <div class="refresh-state">
                <span class="refresh-state__dot" :class="{ 'is-live': refreshInProgress }" />
                <div>
                  <strong>后台刷新：{{ refreshStatusLabel }}</strong>
                  <small>最近完成 {{ formatDateTime(response?.lastRefreshedAt) }} · 本地更新 {{ localUpdatedText }}</small>
                </div>
              </div>
              <el-button :icon="Refresh" :loading="refreshStarting" :disabled="!filters.sourceId" @click="openManualRefreshDialog">启动一次刷新</el-button>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field"><span>盘口</span><el-select v-model="filters.sourceId" :loading="sourcesLoading" placeholder="选择已启用盘口" @change="sourceChanged"><el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" /></el-select></label>
              <label class="query-field query-field--time-range"><span>申请时间（{{ selectedSource?.businessTimezone || '盘口业务时区' }}）</span><el-date-picker v-model="filters.createTimeRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" format="YYYY-MM-DD HH:mm:ss" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable style="width: 100%" /></label>
              <label class="query-field"><span>用户 UID</span><el-input v-model.trim="filters.uid" clearable placeholder="精确 UID" /></label>
              <label class="query-field"><span>转盘配置</span><el-select v-model="filters.spinConfigId" clearable placeholder="全部转盘"><el-option v-for="item in SPIN_CONFIG_OPTIONS" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
              <label class="query-field"><span>审核状态</span><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option v-for="item in statusOptions" :key="item.code" :label="`${item.label}（${item.code}）`" :value="item.code" /></el-select></label>
              <label class="query-field"><span>渠道来源</span><el-select v-model="filters.channelId" clearable filterable placeholder="全部渠道"><el-option v-for="item in channelOptions" :key="item.code" :label="item.label" :value="item.code" /></el-select></label>
            </div>
            <div class="query-card__footer"><span>渠道来源来自 UID 对应的用户详情 channel_id；待解析或未登记渠道会在结果中明确标识。</span><el-button type="primary" :icon="Search" :loading="loading" @click="loadOrders(true)">查询本地订单</el-button></div>
          </section>

          <section class="metric-grid" aria-label="转盘订单汇总">
            <article class="surface-card metric-card metric-card--orders"><span>申请总订单数</span><strong>{{ summary.orderCount.toLocaleString() }}</strong><small>当前筛选条件</small></article>
            <article class="surface-card metric-card"><span>审核通过订单数</span><strong>{{ summary.passedOrderCount.toLocaleString() }}</strong><small>审核通过 + 自动审核通过</small></article>
            <article class="surface-card metric-card"><span>审核通过率</span><strong>{{ percentage(summary.approvalRate) }}</strong><small>通过订单 / 申请总订单</small></article>
            <article class="surface-card metric-card"><span>中奖人数</span><strong>{{ summary.winnerCount.toLocaleString() }}</strong><small>按 UID 去重</small></article>
            <article class="surface-card metric-card"><span>审核通过人数</span><strong>{{ summary.passedWinnerCount.toLocaleString() }}</strong><small>通过订单的 UID 去重</small></article>
            <article class="surface-card metric-card"><span>人数通过率</span><strong>{{ percentage(summary.personApprovalRate) }}</strong><small>通过人数 / 中奖人数</small></article>
          </section>

          <section class="surface-card table-card">
            <div class="section-heading"><div><h2>转盘订单列表</h2><p>共 {{ total.toLocaleString() }} 条；远端本次累计读取 {{ response?.remoteTotal || 0 }} 条，已解析渠道 UID {{ response?.resolvedUidCount || 0 }} 个，待重试 {{ response?.unresolvedUidCount || 0 }} 个。</p></div><el-tag :type="refreshStatusTagType" effect="plain">{{ refreshStatusLabel }}</el-tag></div>
            <el-table v-loading="loading" :data="rows" empty-text="当前本地数据中暂无转盘订单">
              <el-table-column label="订单 ID" prop="id" min-width="150" fixed="left" />
              <el-table-column label="用户 UID" prop="uid" min-width="130" />
              <el-table-column label="转盘配置" min-width="155"><template #default="{ row }"><strong>{{ row.spinConfigLabel }}</strong><small class="code-note">{{ row.spinConfigId }}</small></template></el-table-column>
              <el-table-column label="渠道来源" min-width="170" prop="channelName" show-overflow-tooltip><template #default="{ row }">{{ row.channelName }}<small v-if="row.channelId" class="code-note">{{ row.channelId }}</small></template></el-table-column>
              <el-table-column label="参与轮次" prop="roundNumber" min-width="100" align="right" />
              <el-table-column label="邀请人数" prop="inviteCount" min-width="110" align="right" />
              <el-table-column label="代理总人数" prop="agentTotalCount" min-width="120" align="right" />
              <el-table-column label="提现金额（分）" prop="amount" min-width="130" align="right" />
              <el-table-column label="申请时间" prop="createTime" min-width="178" />
              <el-table-column label="审核时间" prop="auditTime" min-width="178" />
              <el-table-column label="审核状态" min-width="140" fixed="right"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" effect="light">{{ row.statusLabel }}</el-tag></template></el-table-column>
            </el-table>
            <div class="table-pagination"><el-pagination background layout="total, sizes, prev, pager, next, jumper" :total="total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @update:current-page="handlePageChange" @update:page-size="handlePageSizeChange" /></div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="转盘渠道汇总" name="channels">
        <div class="tab-stack">
          <header class="tab-pane-header"><div><h2>转盘渠道汇总</h2><p>按业务日期、转盘配置和渠道来源统计订单及去重人数；通过状态包括审核通过和自动审核通过。</p></div></header>
          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field"><span>盘口</span><el-select v-model="channelSummaryFilters.sourceId" :loading="sourcesLoading" placeholder="选择已启用盘口" @change="channelSummarySourceChanged"><el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" /></el-select></label>
              <label class="query-field query-field--time-range"><span>申请时间（{{ selectedChannelSummarySource?.businessTimezone || '盘口业务时区' }}）</span><el-date-picker v-model="channelSummaryFilters.createTimeRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" format="YYYY-MM-DD HH:mm:ss" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" clearable style="width: 100%" /></label>
              <label class="query-field"><span>转盘配置</span><el-select v-model="channelSummaryFilters.spinConfigId" clearable placeholder="全部转盘"><el-option v-for="item in SPIN_CONFIG_OPTIONS" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
              <label class="query-field"><span>渠道来源</span><el-select v-model="channelSummaryFilters.channelId" clearable filterable placeholder="全部渠道"><el-option v-for="item in channelSummaryOptions" :key="item.code" :label="item.label" :value="item.code" /></el-select></label>
            </div>
            <div class="query-card__footer"><span>每两小时申请人数按“转盘配置 × 渠道来源”分别去重，图中不会跨组相加。</span><el-button type="primary" :icon="Search" :loading="channelSummaryLoading" @click="loadChannelSummary(true)">查询汇总</el-button></div>
          </section>
          <section class="surface-card spin-chart-card"><div class="section-heading"><div><h2>每 2 小时申请人数</h2><p>折线中每个点均是对应转盘配置和渠道来源组合下的 UID 去重人数。</p></div><el-tag effect="plain">{{ channelSummaryResponse?.businessTimezone || '盘口业务时区' }}</el-tag></div><ChartPanel title="每 2 小时申请人数" :option="twoHourSeriesOption" :empty="twoHourSeriesEmpty" :height="360" plain :show-title="false" /></section>
          <section class="surface-card table-card"><div class="section-heading"><div><h2>渠道来源统计</h2><p>共 {{ channelSummaryResponse?.total || 0 }} 个分组；本地数据更新时间：{{ formatDateTime(channelSummaryResponse?.localUpdatedAt) }}。</p></div><el-tag effect="plain">{{ channelSummaryResponse?.sourceDisplayName || '未选择盘口' }}</el-tag></div><el-table v-loading="channelSummaryLoading" :data="channelSummaryRows" empty-text="当前本地筛选条件下暂无转盘渠道汇总"><el-table-column label="日期" prop="date" min-width="120" fixed="left" /><el-table-column label="转盘配置" min-width="155"><template #default="{ row }">{{ row.spinConfigLabel }}</template></el-table-column><el-table-column label="渠道来源" prop="channelName" min-width="180" /><el-table-column label="申请总订单数" prop="applicationOrderCount" min-width="135" align="right" /><el-table-column label="审核通过订单数" prop="passedOrderCount" min-width="150" align="right" /><el-table-column label="待审核订单数" prop="pendingOrderCount" min-width="135" align="right" /><el-table-column label="已拒绝订单数" prop="rejectedOrderCount" min-width="135" align="right" /><el-table-column label="已挂起订单数" prop="suspendedOrderCount" min-width="135" align="right" /><el-table-column label="订单通过率" min-width="120" align="right"><template #default="{ row }">{{ percentage(row.approvalRate) }}</template></el-table-column><el-table-column label="中奖人数" prop="winnerCount" min-width="110" align="right" /><el-table-column label="审核通过人数" prop="passedWinnerCount" min-width="135" align="right" /><el-table-column label="人数通过率" min-width="120" align="right"><template #default="{ row }">{{ percentage(row.personApprovalRate) }}</template></el-table-column></el-table><div class="table-pagination"><el-pagination background layout="total, sizes, prev, pager, next" :total="channelSummaryResponse?.total || 0" :current-page="channelSummaryPage" :page-size="channelSummaryPageSize" :page-sizes="[20, 50, 100]" @update:current-page="handleChannelSummaryPageChange" @update:page-size="handleChannelSummaryPageSizeChange" /></div></section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="manualRefreshDialogVisible" title="选择本次转盘订单刷新范围" width="min(560px, calc(100vw - 32px))">
      <p class="dialog-copy">将对 {{ selectedSource?.displayName || '所选盘口' }} 发起只读远端刷新；刷新会分别读取全部审核状态并更新本地缓存，不会修改远端订单。</p>
      <el-radio-group v-model="manualRefreshQueryRange" class="refresh-range-list">
        <el-radio v-for="item in MANUAL_REFRESH_RANGE_OPTIONS" :key="item.value" :value="item.value"><strong>{{ item.label }}</strong><small>{{ item.description }}</small></el-radio>
      </el-radio-group>
      <template #footer><el-button :disabled="refreshStarting" @click="manualRefreshDialogVisible = false">取消</el-button><el-button type="primary" :loading="refreshStarting" @click="startManualRefresh">确认刷新</el-button></template>
    </el-dialog>
    <p v-if="queuedAt" class="queued-note">最近一次手动刷新已于 {{ formatDateTime(queuedAt) }} 提交，页面将在后台同步完成后显示新数据。</p>
  </div>
</template>

<style scoped>
.spin-page { min-width: 0; }
.spin-tabs :deep(.el-tabs__content) { overflow: visible; }
.tab-stack { display: grid; gap: 20px; }
.tab-pane-header, .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.tab-pane-header h2, .section-heading h2 { margin: 0; color: var(--ink-strong); font-size: 20px; }
.tab-pane-header p, .section-heading p, .dialog-copy, .queued-note { margin: 6px 0 0; color: var(--ink-muted); font-size: 13px; line-height: 1.6; }
.header-actions, .refresh-state { display: flex; align-items: center; gap: 12px; }
.refresh-state { min-width: 230px; align-items: flex-start; }.refresh-state div { display: grid; gap: 2px; }.refresh-state small { color: var(--ink-muted); font-size: 12px; }.refresh-state__dot { width: 9px; height: 9px; margin-top: 5px; border-radius: 99px; background: #9aaabc; }.refresh-state__dot.is-live { background: #2fa69d; box-shadow: 0 0 0 4px rgba(47, 166, 157, 0.15); }
.query-card { padding: 18px; }.query-card__grid { display: grid; grid-template-columns: minmax(170px, 0.8fr) minmax(300px, 2fr) repeat(3, minmax(160px, 0.8fr)); gap: 14px; }.query-field { display: grid; gap: 7px; color: var(--ink); font-size: 12px; font-weight: 800; }.query-field :deep(.el-select) { width: 100%; }.query-field--time-range { grid-column: span 2; }.query-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; color: var(--ink-muted); font-size: 12px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }.metric-card { min-width: 0; display: grid; gap: 7px; padding: 16px; }.metric-card span, .metric-card small { color: var(--ink-muted); font-size: 12px; }.metric-card strong { overflow: hidden; color: var(--ink-strong); font-size: 22px; text-overflow: ellipsis; white-space: nowrap; }.metric-card--orders { border-top: 3px solid var(--teal); }
.table-card, .spin-chart-card { overflow: hidden; }.section-heading { padding: 18px 20px; }.table-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }.code-note { display: block; margin-top: 3px; color: var(--ink-muted); font-size: 11px; font-weight: 500; }.spin-chart-card { padding-bottom: 10px; background: linear-gradient(180deg, #fff 0%, #f8fcfc 100%); }.refresh-range-list { display: grid; gap: 12px; margin-top: 18px; }.refresh-range-list :deep(.el-radio) { height: auto; align-items: flex-start; margin-right: 0; }.refresh-range-list strong, .refresh-range-list small { display: block; }.refresh-range-list small { margin-top: 4px; color: var(--ink-muted); line-height: 1.5; }.queued-note { text-align: right; }
@media (max-width: 1260px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.query-card__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.query-field--time-range { grid-column: span 2; } }
@media (max-width: 820px) { .tab-pane-header, .header-actions, .section-heading, .query-card__footer { align-items: stretch; flex-direction: column; }.header-actions { width: 100%; }.query-card__grid, .metric-grid { grid-template-columns: 1fr; }.query-field--time-range { grid-column: auto; }.table-pagination { justify-content: flex-start; overflow-x: auto; } }
</style>
