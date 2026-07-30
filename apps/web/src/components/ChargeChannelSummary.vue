<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { queryChargeChannelSummary } from '../api/chargeOrders'
import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { currentUser } from '../stores/auth'
import ChartPanel from './ChartPanel.vue'
import type { ChargeChannelSummaryItem, ChargeChannelSummaryResponse, SourceConfig } from '../types'
import { businessFullDayRange, formatDateTime, yesterdayFullDayRange } from '../ui'

type ChartMetric = 'successfulAmount' | 'successfulAmountByDenominationCount' | 'successfulAmountByDenominationValue' | 'successfulOrderShare' | 'successfulAmountShare' | 'successRate'
type ChartDisplayType = 'bar' | 'pie' | 'line'

interface ChartMetricDefinition {
  value: ChartMetric
  label: string
  kind: 'amount' | 'count' | 'percentage'
  color: string
  dimension: 'channel' | 'denomination'
  read?: (row: ChargeChannelSummaryItem) => string
}

const CHART_METRICS: ChartMetricDefinition[] = [
  { value: 'successfulAmount', label: '充值成功金额分布（渠道）', kind: 'amount', color: '#2fa69d', dimension: 'channel', read: (row) => row.successfulAmount },
  { value: 'successfulAmountByDenominationCount', label: '充值成功金额分布（面额数）', kind: 'count', color: '#397de5', dimension: 'denomination' },
  { value: 'successfulAmountByDenominationValue', label: '充值成功金额分布（面额值）', kind: 'amount', color: '#d87835', dimension: 'denomination' },
  { value: 'successfulOrderShare', label: '渠道成功订单量占比', kind: 'percentage', color: '#397de5', dimension: 'channel', read: (row) => row.successfulOrderShare },
  { value: 'successfulAmountShare', label: '渠道成功金额占比', kind: 'percentage', color: '#8a67d6', dimension: 'channel', read: (row) => row.successfulAmountShare },
  { value: 'successRate', label: '成功率', kind: 'percentage', color: '#e9a23b', dimension: 'channel', read: (row) => row.successRate },
]
const CHART_DISPLAY_OPTIONS: Array<{ value: ChartDisplayType; label: string }> = [
  { value: 'bar', label: '柱状图' },
  { value: 'pie', label: '饼图' },
  { value: 'line', label: '折线图' },
]
const CHART_PREFERENCE_KEY_PREFIX = 'raj-charge-channel-chart-preferences'

const loading = ref(false)
const sources = ref<SourceConfig[]>([])
const response = ref<ChargeChannelSummaryResponse | null>(null)
const page = ref(1)
const pageSize = ref(50)
const chartMetric = ref<ChartMetric>('successfulAmount')
const chartDisplayType = ref<ChartDisplayType>('bar')
const chartPreferences = ref<Partial<Record<ChartMetric, ChartDisplayType>>>({})
const filters = reactive({ sourceId: '', createTimeRange: null as [string, string] | null, payMethod: '' })
let requestId = 0

const selectedSource = computed(() => sources.value.find((source) => source.sourceId === filters.sourceId))
const dateRangeShortcuts = computed(() => {
  const timeZone = selectedSource.value?.businessTimezone || 'Asia/Kolkata'
  return [
    { text: '昨天', value: () => businessFullDayRange(timeZone, 1) },
    { text: '前天', value: () => businessFullDayRange(timeZone, 2) },
    { text: '今天', value: () => businessFullDayRange(timeZone, 0) },
  ]
})
const rows = computed(() => response.value?.items || [])
const selectedChartMetric = computed<ChartMetricDefinition>(
  () => CHART_METRICS.find((metric) => metric.value === chartMetric.value) || CHART_METRICS[0]!,
)
const chartValues = computed(() => {
  const metric = selectedChartMetric.value
  if (metric.dimension === 'denomination') {
    return (response.value?.denominationDistribution || []).map((item) => ({
      name: `₹${item.amount}`,
      value: metric.value === 'successfulAmountByDenominationCount'
        ? item.successfulOrderCount
        : numericValue(item.successfulAmount),
    }))
  }
  return rows.value.map((row) => ({
    name: row.payChannelName,
    value: numericValue(metric.read?.(row) || '0'),
  }))
})
const chartEmpty = computed(() => !chartValues.value.some((item) => item.value > 0))
const chartOption = computed<EChartsOption>(() => {
  const metric = selectedChartMetric.value
  const formatter = (value: unknown) => chartValueText(value, metric.kind)
  if (chartDisplayType.value === 'pie') {
    return {
      color: [metric.color, '#4f8bc9', '#6fc6bd', '#e9a23b', '#8a67d6', '#d76d80', '#6f849c'],
      tooltip: { trigger: 'item', triggerOn: 'mousemove|click|mousewheel', valueFormatter: formatter },
      legend: { type: 'scroll' as const, bottom: 0, data: chartValues.value.map((item) => item.name) },
      series: [{
        type: 'pie',
        radius: ['42%', '70%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        label: { formatter: '{b}' },
        labelLine: { length: 12, length2: 8 },
        data: chartValues.value,
      }],
    }
  }
  return {
    grid: { left: 28, right: 24, top: 20, bottom: 52, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: chartDisplayType.value === 'bar' ? 'shadow' : 'line' },
      valueFormatter: formatter,
    },
    xAxis: {
      type: 'category',
      data: chartValues.value.map((item) => item.name),
      axisLabel: { interval: 0, rotate: 24 },
    },
    yAxis: { type: 'value', axisLabel: { formatter } },
    series: [{
      type: chartDisplayType.value,
      data: chartValues.value.map((item) => item.value),
      smooth: chartDisplayType.value === 'line',
      symbol: chartDisplayType.value === 'line' ? 'circle' : undefined,
      itemStyle: { color: metric.color, borderRadius: chartDisplayType.value === 'bar' ? [6, 6, 0, 0] : undefined },
      lineStyle: chartDisplayType.value === 'line' ? { width: 3 } : undefined,
      areaStyle: chartDisplayType.value === 'line' ? { color: `${metric.color}22` } : undefined,
      barMaxWidth: chartDisplayType.value === 'bar' ? 42 : undefined,
    }],
  }
})

function percentage(value: string): string { return `${value}%` }
function amountText(value: string): string { return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
function numericValue(value: string): number { const number = Number(value); return Number.isFinite(number) ? number : 0 }
function chartValueText(value: unknown, kind: ChartMetricDefinition['kind']): string {
  const numeric = Array.isArray(value) ? numericValue(String(value[0] ?? 0)) : numericValue(String(value ?? 0))
  return kind === 'amount'
    ? `₹${numeric.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : kind === 'count'
      ? numeric.toLocaleString('en-IN')
      : `${numeric.toFixed(2)}%`
}
function chartPreferenceKey(): string { return `${CHART_PREFERENCE_KEY_PREFIX}:${currentUser.value?.id || 'current'}` }
function loadChartPreferences(): void {
  try {
    const saved = JSON.parse(window.localStorage.getItem(chartPreferenceKey()) || '{}') as Record<string, unknown>
    chartPreferences.value = Object.fromEntries(
      Object.entries(saved).filter(([metric, chartType]) =>
        CHART_METRICS.some((item) => item.value === metric) &&
        CHART_DISPLAY_OPTIONS.some((item) => item.value === chartType),
      ),
    ) as Partial<Record<ChartMetric, ChartDisplayType>>
  } catch {
    chartPreferences.value = {}
  }
  chartDisplayType.value = chartPreferences.value[chartMetric.value] || 'bar'
}
function handleChartMetricChange(value: ChartMetric): void {
  chartMetric.value = value
  chartDisplayType.value = chartPreferences.value[value] || 'bar'
}
function saveChartPreference(): void {
  chartPreferences.value = { ...chartPreferences.value, [chartMetric.value]: chartDisplayType.value }
  try {
    window.localStorage.setItem(chartPreferenceKey(), JSON.stringify(chartPreferences.value))
    ElMessage.success(`已保存“${selectedChartMetric.value.label}”的${CHART_DISPLAY_OPTIONS.find((item) => item.value === chartDisplayType.value)?.label || '图表'}偏好。`)
  } catch {
    ElMessage.error('图表偏好保存失败，请检查浏览器本地存储权限。')
  }
}

async function load(resetPage = false): Promise<void> {
  if (!filters.sourceId) return
  if (resetPage) page.value = 1
  const currentRequest = ++requestId
  loading.value = true
  try {
    response.value = await queryChargeChannelSummary({ sourceId: filters.sourceId, createTimeStart: filters.createTimeRange?.[0], createTimeEnd: filters.createTimeRange?.[1], payMethod: filters.payMethod || undefined, page: page.value, pageSize: pageSize.value })
  } catch (error) {
    if (currentRequest === requestId) ElMessage.error(apiErrorMessage(error, '充值渠道汇总加载失败。'))
  } finally { if (currentRequest === requestId) loading.value = false }
}

async function sourceChanged(): Promise<void> {
  filters.createTimeRange = yesterdayFullDayRange(selectedSource.value?.businessTimezone || 'Asia/Kolkata')
  filters.payMethod = ''
  await load(true)
}

function handlePageChange(value: number): void { page.value = value; void load() }
function handlePageSizeChange(value: number): void { pageSize.value = value; void load(true) }

onMounted(async () => {
  loadChartPreferences()
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value[0]) {
      filters.sourceId = sources.value[0].sourceId
      filters.createTimeRange = yesterdayFullDayRange(sources.value[0].businessTimezone)
      await load(true)
    }
  }
  catch (error) { ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。')) }
})
</script>

<template>
  <div class="channel-stack">
    <header><h2>支付渠道汇总</h2><p>按创建时间统计本地缓存的充值订单；统计口径仅采用充值订单指标。</p></header>
    <section class="channel-query surface-card">
      <label><span>盘口</span><el-select v-model="filters.sourceId" @change="sourceChanged"><el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" /></el-select></label>
      <label class="channel-query__time"><span>创建时间（{{ selectedSource?.businessTimezone || '盘口业务时区' }}）</span><el-date-picker v-model="filters.createTimeRange" type="datetimerange" :shortcuts="dateRangeShortcuts" value-format="YYYY-MM-DD HH:mm:ss" format="YYYY-MM-DD HH:mm:ss" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" style="width: 100%" /></label>
      <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">查询汇总</el-button>
    </section>
    <section class="surface-card chart-card">
      <div class="chart-card__heading">
        <div><h2>充值金额图表</h2><p>渠道指标以支付渠道为横坐标；面额数、面额值均以支付金额的精确值为横坐标。保存后会默认使用当前指标的展示方式。</p></div>
        <div class="chart-card__controls">
          <label><span>指标</span><el-select :model-value="chartMetric" @update:model-value="handleChartMetricChange"><el-option v-for="metric in CHART_METRICS" :key="metric.value" :label="metric.label" :value="metric.value" /></el-select></label>
          <label><span>展示方式</span><el-select v-model="chartDisplayType"><el-option v-for="option in CHART_DISPLAY_OPTIONS" :key="option.value" :label="option.label" :value="option.value" /></el-select></label>
          <el-button type="primary" plain @click="saveChartPreference">保存偏好</el-button>
        </div>
      </div>
      <ChartPanel :title="selectedChartMetric.label" :option="chartOption" :empty="chartEmpty" :height="300" plain :show-title="false" />
    </section>
    <section class="surface-card channel-table">
      <div class="channel-table__heading"><div><h2>支付渠道统计</h2><p>共 {{ response?.total || 0 }} 个渠道；本地数据更新时间：{{ formatDateTime(response?.localUpdatedAt) }}。</p></div><el-tag type="info" effect="plain">{{ response?.sourceDisplayName || '未选择盘口' }}</el-tag></div>
      <el-table v-loading="loading" :data="rows" empty-text="当前本地筛选条件下暂无支付渠道数据">
        <el-table-column label="支付渠道名称" prop="payChannelName" min-width="180" fixed="left" />
        <el-table-column label="渠道成功订单量占比" min-width="170" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successfulOrderShare) }}</template></el-table-column>
        <el-table-column label="渠道成功金额占比" min-width="170" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successfulAmountShare) }}</template></el-table-column>
        <el-table-column label="成功率" min-width="110" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successRate) }}</template></el-table-column>
        <el-table-column label="充值总订单数" prop="orderCount" min-width="130" align="right" />
        <el-table-column label="成功订单数" prop="successfulOrderCount" min-width="130" align="right" />
        <el-table-column label="充值成功金额" min-width="160" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ amountText(row.successfulAmount) }}</template></el-table-column>
        <el-table-column label="未支付订单数" prop="unpaidOrderCount" min-width="130" align="right" />
        <el-table-column label="无三方订单号数" prop="noThirdPartyOrderCount" min-width="150" align="right" />
      </el-table>
      <div class="channel-pagination"><el-pagination background layout="total, sizes, prev, pager, next" :total="response?.total || 0" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @update:current-page="handlePageChange" @update:page-size="handlePageSizeChange" /></div>
    </section>
  </div>
</template>

<style scoped>
.channel-stack { display: grid; gap: 20px; min-width: 0; }
.channel-stack header h2, .channel-table__heading h2 { margin: 0; color: var(--ink-strong); font-size: 20px; }
.channel-stack header p, .channel-table__heading p { margin: 6px 0 0; color: var(--ink-muted); font-size: 13px; }
.channel-query { display: grid; grid-template-columns: minmax(180px, 0.8fr) minmax(320px, 2fr) auto; align-items: end; gap: 14px; padding: 18px; }
.channel-query label { display: grid; gap: 7px; color: var(--ink); font-size: 12px; font-weight: 800; }.channel-query :deep(.el-select) { width: 100%; }
.chart-card { padding: 18px; }.chart-card__heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 8px; }.chart-card__heading h2 { margin: 0; color: var(--ink-strong); font-size: 20px; }.chart-card__heading p { margin: 6px 0 0; color: var(--ink-muted); font-size: 13px; }.chart-card__controls { display: flex; align-items: end; gap: 10px; }.chart-card__controls label { display: grid; gap: 6px; min-width: 146px; color: var(--ink-muted); font-size: 12px; font-weight: 800; }.chart-card__controls :deep(.el-select) { width: 100%; }.channel-table { overflow: hidden; }.channel-table__heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px; }.channel-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }
@media (max-width: 980px) { .chart-card__heading, .chart-card__controls { align-items: stretch; flex-direction: column; }.chart-card__controls { width: 100%; }.chart-card__controls label { min-width: 0; }.chart-card__controls .el-button { align-self: flex-start; } }
@media (max-width: 820px) { .channel-query { grid-template-columns: 1fr; align-items: stretch; } .channel-pagination { overflow-x: auto; justify-content: flex-start; } }
</style>
