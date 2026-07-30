<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { queryChargeChannelSummary } from '../api/chargeOrders'
import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import ChartPanel from './ChartPanel.vue'
import type { ChargeChannelSummaryItem, ChargeChannelSummaryResponse, SourceConfig } from '../types'
import { formatDateTime, yesterdayFullDayRange } from '../ui'

const loading = ref(false)
const sources = ref<SourceConfig[]>([])
const response = ref<ChargeChannelSummaryResponse | null>(null)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({ sourceId: '', createTimeRange: null as [string, string] | null, payMethod: '' })
let requestId = 0

const selectedSource = computed(() => sources.value.find((source) => source.sourceId === filters.sourceId))
const rows = computed(() => response.value?.items || [])
const chartEmpty = computed(() => !rows.value.some((row) => Number(row.successfulAmount) > 0))
const chartOption = computed<EChartsOption>(() => ({
  grid: { left: 28, right: 24, top: 20, bottom: 42, containLabel: true },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `₹${Number(value).toLocaleString('en-IN')}` },
  xAxis: { type: 'category', data: rows.value.map((row) => row.payChannelName), axisLabel: { interval: 0, rotate: 24 } },
  yAxis: { type: 'value', axisLabel: { formatter: (value) => `₹${Number(value).toLocaleString('en-IN')}` } },
  series: [{ type: 'bar', data: rows.value.map((row) => Number(row.successfulAmount)), itemStyle: { color: '#2fa69d', borderRadius: [6, 6, 0, 0] }, barMaxWidth: 42 }],
}))

function percentage(value: string): string { return `${value}%` }
function amountText(value: string): string { return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }

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
      <label class="channel-query__time"><span>创建时间（{{ selectedSource?.businessTimezone || '盘口业务时区' }}）</span><el-date-picker v-model="filters.createTimeRange" type="datetimerange" value-format="YYYY-MM-DD HH:mm:ss" format="YYYY-MM-DD HH:mm:ss" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" style="width: 100%" /></label>
      <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">查询汇总</el-button>
    </section>
    <section class="surface-card chart-card"><ChartPanel title="充值成功金额分布" :option="chartOption" :empty="chartEmpty" :height="280" plain /></section>
    <section class="surface-card channel-table">
      <div class="channel-table__heading"><div><h2>支付渠道统计</h2><p>共 {{ response?.total || 0 }} 个渠道；本地数据更新时间：{{ formatDateTime(response?.localUpdatedAt) }}。</p></div><el-tag type="info" effect="plain">{{ response?.sourceDisplayName || '未选择盘口' }}</el-tag></div>
      <el-table v-loading="loading" :data="rows" empty-text="当前本地筛选条件下暂无支付渠道数据">
        <el-table-column label="支付渠道名称" prop="payChannelName" min-width="180" fixed="left" />
        <el-table-column label="充值总订单数" prop="orderCount" min-width="130" align="right" />
        <el-table-column label="成功订单数" prop="successfulOrderCount" min-width="130" align="right" />
        <el-table-column label="充值成功金额" min-width="160" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ amountText(row.successfulAmount) }}</template></el-table-column>
        <el-table-column label="未支付订单数" prop="unpaidOrderCount" min-width="130" align="right" />
        <el-table-column label="无三方订单号数" prop="noThirdPartyOrderCount" min-width="150" align="right" />
        <el-table-column label="渠道成功订单量占比" min-width="170" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successfulOrderShare) }}</template></el-table-column>
        <el-table-column label="渠道成功金额占比" min-width="170" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successfulAmountShare) }}</template></el-table-column>
        <el-table-column label="成功率" min-width="110" align="right"><template #default="{ row }: { row: ChargeChannelSummaryItem }">{{ percentage(row.successRate) }}</template></el-table-column>
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
.chart-card { padding: 16px; }.channel-table { overflow: hidden; }.channel-table__heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px; }.channel-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }
@media (max-width: 820px) { .channel-query { grid-template-columns: 1fr; align-items: stretch; } .channel-pagination { overflow-x: auto; justify-content: flex-start; } }
</style>
