<script setup lang="ts">
import type { EChartsOption } from 'echarts'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchBatches, fetchOperationalSummary } from '../api/batches'
import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import ChartPanel from '../components/ChartPanel.vue'
import type { BatchRecord, OperationalSummary, SourceConfig } from '../types'
import { formatDateTime, statusLabel, statusTagType } from '../ui'

const router = useRouter()
const loading = ref(false)
const batches = ref<BatchRecord[]>([])
const sources = ref<SourceConfig[]>([])
const total = ref(0)
const summary = ref<OperationalSummary>({
  executionStatusDistribution: [],
  executionCreatedTimeSeries: [],
  executionDurationBuckets: [],
  failureCategoryDistribution: [],
  aggregationVersion: 'v1',
})
const filters = reactive({
  sourceId: '',
  businessType: '',
  batchStatus: '',
})

const chartBase = {
  textStyle: { fontFamily: 'Inter, "PingFang SC", sans-serif' },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 42, right: 18, top: 24, bottom: 34, containLabel: true },
} satisfies EChartsOption

const statusOption = computed<EChartsOption>(() => ({
  ...chartBase,
  xAxis: { type: 'category', data: summary.value.executionStatusDistribution.map((item) => statusLabel(item.status)) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'bar',
    data: summary.value.executionStatusDistribution.map((item) => item.count),
    itemStyle: { color: '#2a9d8f', borderRadius: [6, 6, 0, 0] },
  }],
}))

const trendOption = computed<EChartsOption>(() => ({
  ...chartBase,
  xAxis: { type: 'category', data: summary.value.executionCreatedTimeSeries.map((item) => item.date) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'line',
    smooth: true,
    symbolSize: 8,
    data: summary.value.executionCreatedTimeSeries.map((item) => item.count),
    lineStyle: { color: '#1d4e89', width: 3 },
    itemStyle: { color: '#1d4e89' },
    areaStyle: { color: 'rgba(29, 78, 137, .12)' },
  }],
}))

const durationOption = computed<EChartsOption>(() => ({
  ...chartBase,
  xAxis: { type: 'category', data: summary.value.executionDurationBuckets.map((item) => item.bucket) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [{
    type: 'bar',
    data: summary.value.executionDurationBuckets.map((item) => item.count),
    itemStyle: { color: '#e9c46a', borderRadius: [6, 6, 0, 0] },
  }],
}))

const failureOption = computed<EChartsOption>(() => ({
  ...chartBase,
  xAxis: { type: 'value', minInterval: 1 },
  yAxis: { type: 'category', data: summary.value.failureCategoryDistribution.map((item) => item.category) },
  series: [{
    type: 'bar',
    data: summary.value.failureCategoryDistribution.map((item) => item.count),
    itemStyle: { color: '#e76f51', borderRadius: [0, 6, 6, 0] },
  }],
}))

function queryParams(): Record<string, string> {
  const params: Record<string, string> = {}
  if (filters.sourceId) params.source_id = filters.sourceId
  if (filters.businessType) params.business_type = filters.businessType
  if (filters.batchStatus) params.batch_status = filters.batchStatus
  return params
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [list, metrics] = await Promise.all([
      fetchBatches(queryParams()),
      fetchOperationalSummary(queryParams()),
    ])
    batches.value = list.items
    total.value = list.total
    summary.value = metrics
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批次数据加载失败。'))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    sources.value = await fetchEnabledSources()
  } catch {
    sources.value = []
  }
  await load()
})
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Shared workspace</span>
        <h1>比对批次中心</h1>
        <p>团队共享查看所有执行版本；这里的图表只统计运行状态，不跨批次累加订单。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="router.push('/batches/new')">
          新建比对
        </el-button>
      </div>
    </header>

    <section class="filter-bar surface-card">
      <el-select v-model="filters.sourceId" clearable placeholder="全部盘口" @change="load">
        <el-option
          v-for="source in sources"
          :key="source.sourceId"
          :label="source.displayName"
          :value="source.sourceId"
        />
      </el-select>
      <el-select v-model="filters.businessType" clearable placeholder="全部业务" @change="load">
        <el-option label="充值 / 代收" value="payin" />
        <el-option label="提现 / 代付" value="payout" />
      </el-select>
      <el-select v-model="filters.batchStatus" clearable placeholder="全部状态" @change="load">
        <el-option label="待确认" value="awaiting_confirmation" />
        <el-option label="执行中" value="validating" />
        <el-option label="已完成" value="completed" />
        <el-option label="失败" value="failed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <span class="filter-total">共 {{ total }} 个执行版本</span>
    </section>

    <div class="chart-grid">
      <ChartPanel
        title="执行状态分布"
        :option="statusOption"
        :empty="!summary.executionStatusDistribution.length"
      />
      <ChartPanel
        title="执行数量趋势"
        :option="trendOption"
        :empty="!summary.executionCreatedTimeSeries.length"
      />
      <ChartPanel
        title="完成耗时分布"
        :option="durationOption"
        :empty="!summary.executionDurationBuckets.length"
      />
      <ChartPanel
        title="失败 / 不完整原因"
        :option="failureOption"
        :empty="!summary.failureCategoryDistribution.length"
      />
    </div>

    <section class="surface-card table-card">
      <div class="section-heading">
        <div>
          <h2>执行版本</h2>
          <p>重新比对会作为新版本显示，但仍归属于原比较系列。</p>
        </div>
      </div>
      <el-table
        v-loading="loading"
        :data="batches"
        empty-text="暂无批次，请先创建一个比对草稿"
        @row-click="(row: BatchRecord) => router.push(`/batches/${row.id}`)"
      >
        <el-table-column label="盘口" min-width="130" prop="sourceDisplayName" />
        <el-table-column label="业务类型" width="120">
          <template #default="{ row }">
            {{ row.businessType === 'payin' ? '充值 / 代收' : '提现 / 代付' }}
          </template>
        </el-table-column>
        <el-table-column label="文件" min-width="220" prop="uploadedFileName" show-overflow-tooltip />
        <el-table-column label="版本" width="90">
          <template #default="{ row }">
            V{{ row.runVersion }}
            <el-tag v-if="row.rerunOfBatchId" size="small" type="info">重跑</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="结果到期" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.resultExpiresAt) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>
