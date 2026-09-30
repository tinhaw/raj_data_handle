<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElButton, ElMessage, ElTag, TableV2FixedDir } from 'element-plus'
import type { Column } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, h, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { fetchSyncLogDetail, querySyncLogs } from '../api/syncLogs'
import ChartPanel from '../components/ChartPanel.vue'
import type {
  SourceConfig,
  SyncLogQueryResponse,
  SyncRunBusinessType,
  SyncRunDetailResponse,
  SyncRunRecord,
  SyncRunStatus,
  SyncRunTriggerType,
} from '../types'

const LOCAL_LOG_POLL_INTERVAL_MS = 15_000

const businessTypeOptions: Array<{ value: SyncRunBusinessType; label: string }> = [
  { value: 'charge_orders', label: '充值订单' },
  { value: 'withdraw_orders', label: '提现订单' },
  { value: 'withdraw_scoring_import', label: '评分审核订单' },
  { value: 'spin_orders', label: '转盘订单' },
]

const triggerTypeOptions: Array<{ value: SyncRunTriggerType; label: string }> = [
  { value: 'automatic', label: '自动同步' },
  { value: 'manual', label: '手动同步' },
  { value: 'upload', label: 'Excel 导入' },
]

const statusOptions: Array<{ value: SyncRunStatus; label: string }> = [
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '同步中' },
  { value: 'succeeded', label: '成功' },
  { value: 'partial', label: '部分完成' },
  { value: 'failed', label: '失败' },
  { value: 'superseded', label: '已替代' },
  { value: 'cancelled', label: '已取消' },
]

const sources = ref<SourceConfig[]>([])
const sourcesLoading = ref(false)
const loading = ref(false)
const detailLoading = ref(false)
const response = ref<SyncLogQueryResponse | null>(null)
const detail = ref<SyncRunDetailResponse | null>(null)
const detailVisible = ref(false)
const page = ref(1)
const pageSize = ref(50)
let queryRequestId = 0
let localLogPollTimer: number | undefined

const filters = reactive({
  sourceId: '',
  businessTypes: [] as SyncRunBusinessType[],
  triggerTypes: [] as SyncRunTriggerType[],
  statuses: [] as SyncRunStatus[],
  executionRange: sevenDayRange(),
  keyword: '',
})

const rows = computed(() => response.value?.items || [])
const summary = computed(() => response.value?.summary)
const isLive = computed(() => Boolean(summary.value?.inProgressCount || 0))
const trendOption = computed<EChartsOption>(() => {
  const items = response.value?.trend || []
  return {
    color: ['#8a9caf', '#2fa69d', '#e9a23b', '#d76d80', '#4f8bc9'],
    tooltip: { trigger: 'axis', confine: true },
    legend: { data: ['排队中', '成功', '部分完成', '失败', '进行中'], bottom: 0 },
    grid: { left: 42, right: 20, top: 18, bottom: 46, containLabel: true },
    xAxis: { type: 'category', data: items.map((item) => formatTrendBucket(item.bucketStart)), axisLabel: { color: '#66798f' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#66798f' } },
    series: [
      { name: '排队中', type: 'bar', stack: 'run', data: items.map((item) => item.queuedCount) },
      { name: '成功', type: 'bar', stack: 'run', data: items.map((item) => item.succeededCount) },
      { name: '部分完成', type: 'bar', stack: 'run', data: items.map((item) => item.partialCount) },
      { name: '失败', type: 'bar', stack: 'run', data: items.map((item) => item.failedCount) },
      { name: '进行中', type: 'bar', stack: 'run', data: items.map((item) => item.runningCount) },
    ],
  }
})

function formatTrendBucket(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  const range = filters.executionRange
  const isShortRange = Boolean(
    range?.[0]
    && range?.[1]
    && range[1].getTime() - range[0].getTime() <= 3 * 24 * 60 * 60 * 1_000,
  )
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    ...(isShortRange ? { hour: '2-digit', hour12: false } : {}),
  }).format(parsed)
}

function sevenDayRange(): [Date, Date] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 6)
  start.setHours(0, 0, 0, 0)
  return [start, end]
}

function asIso(value: Date | undefined): string | undefined {
  return value ? value.toISOString() : undefined
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    dateStyle: 'medium',
    timeStyle: 'medium',
    hour12: false,
  }).format(new Date(value))
}

function typeLabel(value: SyncRunBusinessType): string {
  return businessTypeOptions.find((item) => item.value === value)?.label || value
}

function triggerLabel(value: SyncRunTriggerType): string {
  return triggerTypeOptions.find((item) => item.value === value)?.label || value
}

function operationLabel(value: SyncRunRecord['operationKind']): string {
  return value === 'excel_import' ? 'Excel 导入' : '远端同步'
}

function statusLabel(value: SyncRunStatus): string {
  return statusOptions.find((item) => item.value === value)?.label || value
}

function statusTagType(value: SyncRunStatus): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (value === 'succeeded') return 'success'
  if (value === 'partial' || value === 'queued' || value === 'running') return 'warning'
  if (value === 'failed') return 'danger'
  if (value === 'superseded' || value === 'cancelled') return 'info'
  return 'primary'
}

function virtualCellText(value: unknown): ReturnType<typeof h> {
  const text = value === null || value === undefined || value === '' ? '—' : String(value)
  return h('span', { class: 'sync-log-cell', title: text }, text)
}

function sourceCell(row: SyncRunRecord): ReturnType<typeof h> {
  const sourceName = row.sourceDisplayName || '已删除盘口'
  return h('div', { class: 'sync-log-cell-stack' }, [
    h('strong', { class: 'sync-log-cell-primary', title: sourceName }, sourceName),
    h('small', { class: 'sync-log-cell-code' }, row.sourceId || '历史盘口'),
  ])
}

function businessCell(row: SyncRunRecord): ReturnType<typeof h> {
  return h('div', { class: 'sync-log-cell-stack' }, [
    h('strong', { class: 'sync-log-cell-primary' }, typeLabel(row.businessType)),
    h('small', { class: 'sync-log-cell-code' }, operationLabel(row.operationKind)),
  ])
}

function triggerCell(row: SyncRunRecord): ReturnType<typeof h> {
  const user = row.requestedByDisplayName || (row.triggerType === 'automatic' ? '后台任务' : '—')
  return h('div', { class: 'sync-log-cell-stack' }, [
    h('strong', { class: 'sync-log-cell-primary' }, triggerLabel(row.triggerType)),
    h('small', { class: 'sync-log-cell-code', title: user }, user),
  ])
}

function qualityCell(row: SyncRunRecord): ReturnType<typeof h> {
  if (row.status === 'failed') return h(ElTag, { type: 'danger', size: 'small', effect: 'light' }, { default: () => '执行失败' })
  if (row.status === 'partial' || row.complete === false) return h(ElTag, { type: 'warning', size: 'small', effect: 'light' }, { default: () => '数据不完整' })
  if ((row.unresolvedUidCount || 0) > 0) return h(ElTag, { type: 'warning', size: 'small', effect: 'light' }, { default: () => `待解析 UID ${row.unresolvedUidCount}` })
  if (row.status === 'succeeded') return h(ElTag, { type: 'success', size: 'small', effect: 'light' }, { default: () => '完整' })
  return h(ElTag, { type: 'info', size: 'small', effect: 'light' }, { default: () => '进行中' })
}

function resultSummary(row: SyncRunRecord): string {
  const values: string[] = []
  if (row.remoteTotal !== null) values.push(`远端 ${row.remoteTotal.toLocaleString()}`)
  if (row.exportRowCount !== null) values.push(`导出 ${row.exportRowCount.toLocaleString()}`)
  if (row.importedCount !== null) values.push(`导入 ${row.importedCount.toLocaleString()}`)
  if (row.matchedCount !== null) values.push(`匹配 ${row.matchedCount.toLocaleString()}`)
  if (row.cachedTotal !== null) values.push(`缓存 ${row.cachedTotal.toLocaleString()}`)
  if (row.fetchedPages !== null) values.push(`${row.fetchedPages} 页`)
  return values.join(' · ') || '等待执行'
}

function durationLabel(row: SyncRunRecord): string {
  if (row.durationMs !== null) {
    const seconds = Math.max(0, Math.floor(row.durationMs / 1_000))
    if (seconds < 60) return `${seconds} 秒`
    const minutes = Math.floor(seconds / 60)
    return `${minutes} 分 ${seconds % 60} 秒`
  }
  if (!row.startedAt) return '—'
  const end = row.finishedAt ? new Date(row.finishedAt).getTime() : Date.now()
  const seconds = Math.max(0, Math.floor((end - new Date(row.startedAt).getTime()) / 1_000))
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} 分 ${seconds % 60} 秒`
}

const tableColumns = computed<Column<SyncRunRecord>[]>(() => [
  {
    key: 'status',
    title: '状态',
    width: 112,
    fixed: true,
    align: 'center',
    cellRenderer: ({ rowData }) => h(ElTag, { type: statusTagType(rowData.status), size: 'small', effect: 'light' }, { default: () => statusLabel(rowData.status) }),
  },
  {
    key: 'finishedAt',
    title: '执行时间（北京时间）',
    width: 186,
    cellRenderer: ({ rowData }) => virtualCellText(formatDateTime(rowData.finishedAt || rowData.startedAt || rowData.requestedAt)),
  },
  {
    key: 'businessType',
    title: '业务',
    width: 162,
    cellRenderer: ({ rowData }) => businessCell(rowData),
  },
  {
    key: 'source',
    title: '盘口',
    width: 150,
    cellRenderer: ({ rowData }) => sourceCell(rowData),
  },
  {
    key: 'trigger',
    title: '触发 / 发起人',
    width: 150,
    cellRenderer: ({ rowData }) => triggerCell(rowData),
  },
  {
    key: 'window',
    title: '数据窗口',
    width: 244,
    cellRenderer: ({ rowData }) => virtualCellText(
      rowData.windowStartUtc && rowData.windowEndUtc
        ? `${formatDateTime(rowData.windowStartUtc)} 至 ${formatDateTime(rowData.windowEndUtc)}`
        : rowData.queryRange || '—',
    ),
  },
  {
    key: 'result',
    title: '结果摘要',
    width: 220,
    cellRenderer: ({ rowData }) => virtualCellText(resultSummary(rowData)),
  },
  {
    key: 'quality',
    title: '数据质量',
    width: 142,
    align: 'center',
    cellRenderer: ({ rowData }) => qualityCell(rowData),
  },
  {
    key: 'duration',
    title: '耗时',
    width: 112,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(durationLabel(rowData)),
  },
  {
    key: 'actions',
    title: '操作',
    width: 94,
    fixed: TableV2FixedDir.RIGHT,
    align: 'center',
    cellRenderer: ({ rowData }) => h(ElButton, { link: true, type: 'primary', onClick: () => void openDetail(rowData.id) }, { default: () => '查看详情' }),
  },
])

function clearLocalLogPoll(): void {
  if (localLogPollTimer === undefined) return
  window.clearTimeout(localLogPollTimer)
  localLogPollTimer = undefined
}

function scheduleLocalLogPoll(): void {
  clearLocalLogPoll()
  if (!isLive.value) return
  localLogPollTimer = window.setTimeout(() => {
    localLogPollTimer = undefined
    void load()
  }, LOCAL_LOG_POLL_INTERVAL_MS)
}

async function load(resetPage = false): Promise<void> {
  clearLocalLogPoll()
  if (resetPage) page.value = 1
  const requestId = ++queryRequestId
  loading.value = true
  try {
    const range = filters.executionRange
    const next = await querySyncLogs({
      sourceId: filters.sourceId || undefined,
      businessTypes: filters.businessTypes.length ? filters.businessTypes : undefined,
      triggerTypes: filters.triggerTypes.length ? filters.triggerTypes : undefined,
      statuses: filters.statuses.length ? filters.statuses : undefined,
      startedAt: asIso(range?.[0]),
      endedAt: asIso(range?.[1]),
      keyword: filters.keyword.trim() || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (requestId !== queryRequestId) return
    response.value = next
  } catch (error) {
    if (requestId === queryRequestId) ElMessage.error(apiErrorMessage(error, '同步日志加载失败。'))
  } finally {
    if (requestId === queryRequestId) {
      loading.value = false
      scheduleLocalLogPoll()
    }
  }
}

async function openDetail(runId: string): Promise<void> {
  detailVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await fetchSyncLogDetail(runId)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '同步日志详情加载失败。'))
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

function resetFilters(): void {
  filters.sourceId = sources.value[0]?.sourceId || ''
  filters.businessTypes = []
  filters.triggerTypes = []
  filters.statuses = []
  filters.executionRange = sevenDayRange()
  filters.keyword = ''
  void load(true)
}

function pageChanged(value: number): void {
  page.value = value
  void load()
}

function pageSizeChanged(value: number): void {
  pageSize.value = value
  void load(true)
}

function eventLabel(eventType: string): string {
  const labels: Record<string, string> = {
    queued: '已进入队列',
    running: '开始执行',
    remote_export_started: '开始读取远端订单导出',
    remote_export_fetched: '远端订单导出读取完成',
    withdraw_status_dictionary_started: '开始读取提现状态字典',
    withdraw_status_dictionary_fetched: '提现状态字典读取完成',
    remote_fetch_started: '开始读取远端数据',
    remote_fetch_fetched: '远端数据读取完成',
    remote_fetch_completed: '远端数据读取完成',
    user_channel_resolution_started: '开始解析用户渠道来源',
    user_channel_resolution_completed: '用户渠道来源解析完成',
    uid_channel_resolution_started: '开始解析用户渠道来源',
    uid_channel_resolution_completed: '用户渠道来源解析完成',
    scoring_remote_fetch_started: '开始读取评分审核远端数据',
    scoring_remote_fetch_fetched: '评分审核远端数据读取完成',
    excel_parse_started: '开始校验 Excel',
    excel_parse_completed: 'Excel 校验完成',
    import_started: '开始写入本地评分补充数据',
    completed: '执行完成',
    partially_completed: '部分完成',
    failed: '执行失败',
    superseded: '已被后续请求替代',
    cancelled: '执行已取消',
  }
  return labels[eventType] || eventType
}

function formatFileSize(value: number | null): string {
  if (value === null || value < 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function eventStatusLabel(value: string | null): string {
  if (!value) return ''
  return statusLabel(value as SyncRunStatus)
}

function metricItems(item: SyncRunRecord | undefined): Array<{ label: string; value: string }> {
  if (!item) return []
  const metrics: Array<[string, number | null]> = [
    ['远端总数', item.remoteTotal],
    ['导出行数', item.exportRowCount],
    ['缓存总数', item.cachedTotal],
    ['抓取页数', item.fetchedPages],
    ['导入记录', item.importedCount],
    ['新增记录', item.createdCount],
    ['更新记录', item.updatedCount],
    ['重复记录', item.duplicateCount],
    ['匹配案件', item.matchedCount],
    ['未匹配案件', item.unmatchedCount],
    ['已解析 UID', item.resolvedUidCount],
    ['待解析 UID', item.unresolvedUidCount],
  ]
  return metrics.filter(([, value]) => value !== null).map(([label, value]) => ({ label, value: Number(value).toLocaleString() }))
}

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    filters.sourceId = sources.value[0]?.sourceId || ''
    await load(true)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。'))
  } finally {
    sourcesLoading.value = false
  }
})

onBeforeUnmount(clearLocalLogPoll)
</script>

<template>
  <div class="page-stack sync-log-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">SYNC ACTIVITY</span>
        <h1>同步日志</h1>
        <p>查看充值、提现、评分审核导入和转盘订单的本地同步记录；日志不会展示远端凭据、请求内容或原始 Excel。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="() => load()">刷新</el-button>
    </header>

    <section class="surface-card sync-log-query-card">
      <div class="sync-log-query-grid">
        <label class="sync-log-field"><span>盘口</span><el-select v-model="filters.sourceId" :loading="sourcesLoading" clearable placeholder="全部盘口"><el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" /></el-select></label>
        <label class="sync-log-field"><span>业务类型</span><el-select v-model="filters.businessTypes" multiple clearable collapse-tags placeholder="全部业务"><el-option v-for="item in businessTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
        <label class="sync-log-field"><span>触发方式</span><el-select v-model="filters.triggerTypes" multiple clearable collapse-tags placeholder="全部方式"><el-option v-for="item in triggerTypeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
        <label class="sync-log-field"><span>执行状态</span><el-select v-model="filters.statuses" multiple clearable collapse-tags placeholder="全部状态"><el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
        <label class="sync-log-field sync-log-field--time"><span>执行时间（北京时间）</span><el-date-picker v-model="filters.executionRange" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" style="width: 100%" /></label>
        <label class="sync-log-field"><span>关键词</span><el-input v-model.trim="filters.keyword" clearable placeholder="运行 ID、文件名或错误码" /></label>
      </div>
      <footer class="sync-log-query-actions"><span>筛选仅查询本地日志；同步进行中时页面每 15 秒刷新一次本地状态。</span><div><el-button @click="resetFilters">重置</el-button><el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">查询日志</el-button></div></footer>
    </section>

    <section class="sync-log-metrics" aria-label="同步日志概览">
      <article class="surface-card sync-log-metric sync-log-metric--live"><span>进行中</span><strong>{{ (summary?.inProgressCount || 0).toLocaleString() }}</strong><small>排队中 {{ summary?.queuedCount || 0 }} · 同步中 {{ summary?.runningCount || 0 }}</small></article>
      <article class="surface-card sync-log-metric"><span>当前筛选成功</span><strong>{{ (summary?.succeededCount || 0).toLocaleString() }}</strong><small>近 24 小时 {{ summary?.last24HoursSucceededCount || 0 }} 条成功</small></article>
      <article class="surface-card sync-log-metric"><span>异常 / 部分完成</span><strong>{{ ((summary?.failedCount || 0) + (summary?.partialCount || 0)).toLocaleString() }}</strong><small>近 24 小时异常 {{ summary?.last24HoursProblemCount || 0 }} 条</small></article>
      <article class="surface-card sync-log-metric"><span>最近一次成功</span><strong class="sync-log-metric__time">{{ formatDateTime(summary?.latestSucceededAt) }}</strong><small>按当前筛选条件计算</small></article>
    </section>

    <section class="surface-card sync-log-chart-card">
      <div class="section-heading"><div><h2>执行趋势</h2><p>按当前筛选时间与状态汇总真实执行记录；未真正启动同步的后台轮询不会计入。</p></div><el-tag :type="isLive ? 'warning' : 'info'" effect="plain">{{ isLive ? '存在进行中的任务' : '当前无进行中任务' }}</el-tag></div>
      <ChartPanel title="执行趋势" :option="trendOption" :empty="!(response?.trend.length)" :height="220" plain :show-title="false" />
    </section>

    <section class="surface-card sync-log-table-card">
      <div class="section-heading"><div><h2>执行记录</h2><p>共 {{ (response?.total || 0).toLocaleString() }} 条。表格固定高度，仅在表格内滚动；点击“查看详情”可追踪执行阶段和统计。</p></div><el-tag effect="plain">{{ filters.sourceId ? sources.find((item) => item.sourceId === filters.sourceId)?.displayName || filters.sourceId : '全部盘口' }}</el-tag></div>
      <div v-loading="loading" class="sync-log-virtual-table" aria-label="同步日志虚拟化表格"><el-auto-resizer><template #default="{ height, width }"><el-table-v2 :columns="tableColumns" :data="rows" :height="height" :width="width" :header-height="52" :row-height="58" row-key="id" fixed scrollbar-always-on><template #empty><el-empty :image-size="72" description="当前筛选条件下暂无同步日志" /></template></el-table-v2></template></el-auto-resizer></div>
      <div class="table-pagination"><el-pagination background layout="total, sizes, prev, pager, next, jumper" :total="response?.total || 0" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @update:current-page="pageChanged" @update:page-size="pageSizeChanged" /></div>
    </section>

    <el-drawer v-model="detailVisible" size="min(560px, 92vw)" direction="rtl" title="同步执行详情" destroy-on-close>
      <div v-loading="detailLoading" class="sync-log-detail">
        <template v-if="detail">
          <section class="sync-log-detail__hero"><div><span class="page-eyebrow">{{ typeLabel(detail.run.businessType) }}</span><h2>{{ detail.run.sourceDisplayName || '已删除盘口' }}</h2><p>运行 ID：<code>{{ detail.run.id }}</code></p></div><el-tag :type="statusTagType(detail.run.status)" effect="dark">{{ statusLabel(detail.run.status) }}</el-tag></section>
          <section class="sync-log-detail__section"><h3>执行信息</h3><dl class="sync-log-detail__facts"><div><dt>操作类型</dt><dd>{{ operationLabel(detail.run.operationKind) }}</dd></div><div><dt>触发方式</dt><dd>{{ triggerLabel(detail.run.triggerType) }}{{ detail.run.requestedByDisplayName ? ` · ${detail.run.requestedByDisplayName}` : '' }}</dd></div><div><dt>请求时间</dt><dd>{{ formatDateTime(detail.run.requestedAt) }}</dd></div><div><dt>开始时间</dt><dd>{{ formatDateTime(detail.run.startedAt) }}</dd></div><div><dt>完成时间</dt><dd>{{ formatDateTime(detail.run.finishedAt) }}</dd></div><div><dt>数据窗口</dt><dd>{{ detail.run.windowStartUtc && detail.run.windowEndUtc ? `${formatDateTime(detail.run.windowStartUtc)} 至 ${formatDateTime(detail.run.windowEndUtc)}` : detail.run.queryRange || '—' }}</dd></div><div><dt>耗时</dt><dd>{{ durationLabel(detail.run) }}</dd></div><div v-if="detail.run.inputFilename"><dt>导入文件</dt><dd>{{ detail.run.inputFilename }} · {{ formatFileSize(detail.run.inputSizeBytes) }}</dd></div></dl></section>
          <section v-if="metricItems(detail.run).length" class="sync-log-detail__section"><h3>结果统计</h3><dl class="sync-log-detail__facts sync-log-detail__facts--metrics"><div v-for="item in metricItems(detail.run)" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl></section>
          <section v-if="detail.run.errorCode || detail.run.errorMessage" class="sync-log-detail__section sync-log-detail__error"><h3>异常说明</h3><p><strong>{{ detail.run.errorCode || '同步失败' }}</strong></p><p>{{ detail.run.errorMessage || '任务未能完成，请稍后重试。' }}</p></section>
          <section class="sync-log-detail__section"><h3>执行时间线</h3><ol class="sync-log-timeline"><li v-for="event in detail.events" :key="event.id"><span class="sync-log-timeline__dot" /><div><strong>{{ eventLabel(event.eventType) }}<template v-if="event.status"> · {{ eventStatusLabel(event.status) }}</template></strong><small>{{ formatDateTime(event.occurredAt) }}</small><p v-if="event.message">{{ event.message }}</p></div></li></ol></section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.sync-log-page { min-width: 0; }
.sync-log-query-card { padding: 18px; }
.sync-log-query-grid { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 14px; }
.sync-log-field { display: grid; gap: 7px; min-width: 0; color: var(--ink); font-size: 12px; font-weight: 800; }
.sync-log-field :deep(.el-select) { width: 100%; }
.sync-log-field--time { grid-column: span 2; }
.sync-log-query-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 16px; color: var(--ink-muted); font-size: 12px; }
.sync-log-query-actions > div { display: flex; gap: 10px; }
.sync-log-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.sync-log-metric { display: grid; min-width: 0; gap: 7px; padding: 17px; }
.sync-log-metric span, .sync-log-metric small { color: var(--ink-muted); font-size: 12px; }
.sync-log-metric strong { overflow: hidden; color: var(--ink-strong); font-size: 25px; text-overflow: ellipsis; white-space: nowrap; }
.sync-log-metric--live { border-top: 3px solid var(--teal); }
.sync-log-metric__time { font-size: 16px !important; line-height: 1.55; }
.sync-log-chart-card, .sync-log-table-card { overflow: hidden; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px; }
.section-heading h2, .section-heading p { margin: 0; }.section-heading h2 { color: var(--ink-strong); font-size: 19px; }.section-heading p { margin-top: 6px; color: var(--ink-muted); font-size: 13px; line-height: 1.55; }
.sync-log-chart-card { padding-bottom: 8px; background: linear-gradient(180deg, #fff, #f8fcfc); }
.sync-log-virtual-table { width: 100%; min-height: 400px; height: clamp(400px, calc(100vh - 412px), 700px); overflow: hidden; border: 1px solid #dce6ee; border-radius: 8px; background: #fff; --el-table-border-color: #dce6ee; --el-table-header-bg-color: #f5f8fb; --el-table-row-hover-bg-color: #f7fbfb; --el-table-text-color: #43576a; --el-table-header-text-color: #183955; }
.sync-log-virtual-table :deep(.el-table-v2__header-cell) { padding: 0 14px; color: #183955; font-size: 12px; font-weight: 750; }
.sync-log-virtual-table :deep(.el-table-v2__row-cell) { padding: 0 14px; color: #43576a; font-size: 12px; }
.sync-log-virtual-table :deep(.el-table-v2__header-cell + .el-table-v2__header-cell), .sync-log-virtual-table :deep(.el-table-v2__row-cell + .el-table-v2__row-cell) { border-left: 1px solid #dce6ee; }
.sync-log-cell { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sync-log-cell-stack { display: grid; min-width: 0; gap: 2px; }.sync-log-cell-primary, .sync-log-cell-code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.sync-log-cell-primary { color: var(--ink); font-size: 12px; }.sync-log-cell-code { color: var(--ink-muted); font-size: 11px; font-weight: 500; }
.table-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }
.sync-log-detail { min-height: 180px; }.sync-log-detail__hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }.sync-log-detail__hero h2, .sync-log-detail__hero p { margin: 0; }.sync-log-detail__hero h2 { margin-top: 5px; color: var(--ink-strong); }.sync-log-detail__hero p { margin-top: 8px; color: var(--ink-muted); font-size: 12px; }.sync-log-detail__hero code { word-break: break-all; }
.sync-log-detail__section { padding: 20px 0; border-bottom: 1px solid var(--border); }.sync-log-detail__section h3 { margin: 0 0 14px; color: var(--ink-strong); font-size: 15px; }.sync-log-detail__facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 0; }.sync-log-detail__facts div { min-width: 0; }.sync-log-detail__facts dt { color: var(--ink-muted); font-size: 12px; }.sync-log-detail__facts dd { margin: 5px 0 0; color: var(--ink); font-size: 13px; line-height: 1.5; word-break: break-word; }.sync-log-detail__facts--metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }.sync-log-detail__facts--metrics dd { color: var(--ink-strong); font-size: 17px; font-weight: 750; }
.sync-log-detail__error { border-left: 3px solid #d76d80; padding-left: 14px; }.sync-log-detail__error p { margin: 6px 0 0; color: var(--ink-muted); font-size: 13px; line-height: 1.55; }.sync-log-detail__error strong { color: #b44155; }
.sync-log-timeline { display: grid; gap: 16px; margin: 0; padding: 0; list-style: none; }.sync-log-timeline li { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; }.sync-log-timeline li:not(:last-child)::before { position: absolute; top: 15px; bottom: -16px; left: 6px; width: 2px; background: #dce6ee; content: ''; }.sync-log-timeline__dot { z-index: 1; width: 14px; height: 14px; margin-top: 3px; border: 3px solid #d8f0ed; border-radius: 50%; background: var(--teal); }.sync-log-timeline strong, .sync-log-timeline small, .sync-log-timeline p { display: block; }.sync-log-timeline strong { color: var(--ink); font-size: 13px; }.sync-log-timeline small { margin-top: 3px; color: var(--ink-muted); font-size: 11px; }.sync-log-timeline p { margin: 5px 0 0; color: var(--ink-muted); font-size: 12px; line-height: 1.5; }
@media (max-width: 1180px) { .sync-log-query-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.sync-log-field--time { grid-column: span 2; }.sync-log-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .sync-log-query-grid, .sync-log-metrics, .sync-log-detail__facts, .sync-log-detail__facts--metrics { grid-template-columns: 1fr; }.sync-log-field--time { grid-column: auto; }.sync-log-query-actions, .section-heading { align-items: stretch; flex-direction: column; }.sync-log-query-actions > div { justify-content: flex-end; }.sync-log-virtual-table { min-height: 340px; height: min(56vh, 560px); }.table-pagination { justify-content: flex-start; overflow-x: auto; } }
</style>
