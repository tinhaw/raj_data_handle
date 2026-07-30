<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { fetchRetentionSettings } from '../api/systemSettings'
import { queryChargeOrders, startChargeOrderRefresh } from '../api/chargeOrders'
import type {
  ChargeOrder,
  ChargeOrderQueryRange,
  ChargeOrderQueryResponse,
  ChargeOrderSummary,
  SourceConfig,
} from '../types'
import { formatDateTime, yesterdayFullDayRange } from '../ui'

const RANGE_OPTIONS: Array<{ value: ChargeOrderQueryRange; label: string }> = [
  { value: 'today', label: '今日 00:00:00 至 23:59:59' },
  { value: 'last_1_hour', label: '最近 1 小时' },
  { value: 'last_2_hours', label: '最近 2 小时' },
  { value: 'last_3_hours', label: '最近 3 小时' },
  { value: 'last_6_hours', label: '最近 6 小时' },
  { value: 'last_12_hours', label: '最近 12 小时' },
  { value: 'last_24_hours', label: '最近 24 小时' },
  { value: 'last_48_hours', label: '最近 48 小时' },
]

const emptySummary: ChargeOrderSummary = {
  orderCount: 0,
  successfulOrderCount: 0,
  successfulAmount: '0.00',
  unpaidOrderCount: 0,
  noThirdPartyOrderCount: 0,
}

const loading = ref(false)
const sourcesLoading = ref(false)
const refreshStarting = ref(false)
const manualRefreshVisible = ref(false)
const rows = ref<ChargeOrder[]>([])
const response = ref<ChargeOrderQueryResponse | null>(null)
const sources = ref<SourceConfig[]>([])
const page = ref(1)
const pageSize = ref(50)
const queuedAt = ref<string | null>(null)
const manualRange = ref<ChargeOrderQueryRange>('today')
const manualRefreshSourceId = ref('')
const filters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  uid: '',
  status: '',
  payMethod: '',
  orderNum: '',
})
let requestId = 0

const selectedSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const selectedManualRefreshSource = computed(() =>
  sources.value.find((source) => source.sourceId === manualRefreshSourceId.value),
)
const summary = computed(() => response.value?.summary || emptySummary)
const total = computed(() => response.value?.total || 0)
const statusOptions = computed(() => response.value?.statusDictionary || [])
const channelOptions = computed(() => response.value?.channelDictionary || [])
const channelNameOptions = computed(() => response.value?.channelNameDictionary || [])
const statusNames = computed(
  () => new Map(statusOptions.value.map((item) => [item.code, item.label])),
)
const channelNames = computed(
  () => new Map(channelNameOptions.value.map((item) => [item.code, item.label])),
)
const paymentChannelNames = computed(
  () => new Map(channelOptions.value.map((item) => [item.code, item.label])),
)
const localUpdatedText = computed(() =>
  response.value ? formatDateTime(response.value.localUpdatedAt) : '尚未查询',
)
const refreshLabel = computed(() => {
  const status = response.value?.refreshStatus || 'not_started'
  const labels: Record<string, string> = {
    not_started: '暂无同步记录',
    idle: '等待下次同步',
    queued: '已排队',
    running: '同步中',
    succeeded: response.value?.complete === false ? '同步不完整' : '同步完成',
    failed: '同步失败',
  }
  return labels[status] || status
})

function amountText(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number)
    ? `₹${number.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : value
}

function statusLabel(value: string): string {
  return statusNames.value.get(value) || `状态 ${value}`
}

function paymentChannelName(row: ChargeOrder): string {
  const nameCode = String(row.payChannelName || '').trim()
  const methodCode = String(row.payMethod || '').trim()
  return (
    channelNames.value.get(nameCode) ||
    paymentChannelNames.value.get(methodCode) ||
    nameCode ||
    methodCode ||
    '—'
  )
}

async function load(resetPage = false): Promise<void> {
  if (!filters.sourceId) return
  if (resetPage) page.value = 1
  const currentRequest = ++requestId
  loading.value = true
  try {
    const result = await queryChargeOrders({
      sourceId: filters.sourceId,
      createTimeStart: filters.createTimeRange?.[0],
      createTimeEnd: filters.createTimeRange?.[1],
      uid: filters.uid || undefined,
      status: filters.status || undefined,
      payMethod: filters.payMethod || undefined,
      orderNum: filters.orderNum || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (currentRequest !== requestId) return
    response.value = result
    rows.value = result.items
  } catch (error) {
    if (currentRequest === requestId) {
      ElMessage.error(apiErrorMessage(error, '本地充值订单加载失败。'))
    }
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

async function handleSourceChange(): Promise<void> {
  filters.createTimeRange = yesterdayFullDayRange(
    selectedSource.value?.businessTimezone || 'Asia/Kolkata',
  )
  filters.status = ''
  filters.payMethod = ''
  await load(true)
}

function handlePageChange(value: number): void {
  page.value = value
  void load()
}

function handlePageSizeChange(value: number): void {
  pageSize.value = value
  void load(true)
}

async function openManualRefresh(): Promise<void> {
  manualRefreshSourceId.value = filters.sourceId
  try {
    manualRange.value = (await fetchRetentionSettings()).chargeOrderQueryRange
  } catch {
    manualRange.value = 'today'
  }
  manualRefreshVisible.value = true
}

async function startRefresh(): Promise<void> {
  if (!manualRefreshSourceId.value) {
    ElMessage.warning('请选择需要刷新的盘口。')
    return
  }
  refreshStarting.value = true
  try {
    const result = await startChargeOrderRefresh({
      sourceId: manualRefreshSourceId.value,
      queryRange: manualRange.value,
    })
    queuedAt.value = result.requestedAt
    manualRefreshVisible.value = false
    ElMessage.success(result.message)
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '充值订单刷新任务提交失败。'))
  } finally {
    refreshStarting.value = false
  }
}

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value[0]) {
      filters.sourceId = sources.value[0].sourceId
      filters.createTimeRange = yesterdayFullDayRange(sources.value[0].businessTimezone)
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
  <div class="charge-stack">
    <header class="charge-header">
      <div>
        <h2>充值订单明细</h2>
        <p>仅查询本地已同步的充值订单；远端同步由后台工作进程执行。</p>
      </div>
      <div class="charge-header__actions">
        <div class="sync-state">
          <strong>后台同步：{{ refreshLabel }}</strong>
          <small>本地更新 {{ localUpdatedText }}</small>
        </div>
        <el-button :icon="Refresh" :disabled="!filters.sourceId" :loading="refreshStarting" @click="openManualRefresh">
          启动一次刷新
        </el-button>
      </div>
    </header>

    <section class="charge-query surface-card">
      <div class="charge-query__grid">
        <label>
          <span>盘口</span>
          <el-select v-model="filters.sourceId" :loading="sourcesLoading" @change="handleSourceChange">
            <el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" />
          </el-select>
        </label>
        <label class="charge-query__time">
          <span>创建时间（{{ selectedSource?.businessTimezone || '盘口业务时区' }}）</span>
          <el-date-picker
            v-model="filters.createTimeRange"
            type="datetimerange"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm:ss"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            style="width: 100%"
          />
        </label>
        <label><span>用户 UID</span><el-input v-model.trim="filters.uid" clearable placeholder="精确 UID" /></label>
        <label><span>订单号</span><el-input v-model.trim="filters.orderNum" clearable placeholder="包含匹配" /></label>
        <label>
          <span>订单状态</span>
          <el-select v-model="filters.status" clearable placeholder="全部状态">
            <el-option v-for="item in statusOptions" :key="item.code" :label="item.label" :value="item.code" />
          </el-select>
        </label>
        <label>
          <span>支付渠道</span>
          <el-select v-model="filters.payMethod" clearable filterable placeholder="全部渠道">
            <el-option v-for="item in channelOptions" :key="item.code" :label="item.label" :value="item.code" />
          </el-select>
        </label>
      </div>
      <div class="charge-query__footer">
        <span>筛选只作用于本地缓存；时间范围按盘口业务时区解释，不影响后台同步范围。</span>
        <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">查询本地订单</el-button>
      </div>
    </section>

    <section class="charge-metrics" aria-label="充值订单汇总">
      <article class="surface-card"><span>充值总订单数</span><strong>{{ summary.orderCount.toLocaleString() }}</strong><small>当前本地筛选条件</small></article>
      <article class="surface-card"><span>成功订单数</span><strong>{{ summary.successfulOrderCount.toLocaleString() }}</strong><small>已支付订单（status = 1）</small></article>
      <article class="surface-card"><span>充值成功金额</span><strong>{{ amountText(summary.successfulAmount) }}</strong><small>已支付订单 amount 汇总</small></article>
      <article class="surface-card"><span>未支付 / 无三方单</span><strong>{{ summary.unpaidOrderCount.toLocaleString() }} / {{ summary.noThirdPartyOrderCount.toLocaleString() }}</strong><small>待支付 status = 0；无三方单按订单号统计</small></article>
    </section>

    <section class="surface-card charge-table">
      <div class="charge-table__heading">
        <div><h2>充值订单列表</h2><p>共 {{ total.toLocaleString() }} 条；本地数据更新时间：{{ localUpdatedText }}。</p></div>
        <el-tag effect="plain" type="info">{{ refreshLabel }}</el-tag>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="当前本地数据中暂无充值订单">
        <el-table-column label="订单 ID" prop="id" fixed="left" min-width="132" />
        <el-table-column label="用户 UID" prop="uid" min-width="118" />
        <el-table-column label="充值订单号" prop="orderNum" min-width="180" show-overflow-tooltip />
        <el-table-column label="三方订单号" prop="outTradeNo" min-width="180" show-overflow-tooltip />
        <el-table-column label="支付渠道名称" min-width="170"><template #default="{ row }">{{ paymentChannelName(row) }}</template></el-table-column>
        <el-table-column label="充值金额" min-width="132" align="right"><template #default="{ row }">{{ amountText(row.amount) }}</template></el-table-column>
        <el-table-column label="到账余额" min-width="132" align="right"><template #default="{ row }">{{ amountText(row.balance) }}</template></el-table-column>
        <el-table-column label="赠送金额" min-width="132" align="right"><template #default="{ row }">{{ amountText(row.extra) }}</template></el-table-column>
        <el-table-column label="创建时间" min-width="172"><template #default="{ row }">{{ row.createTime || '—' }}</template></el-table-column>
        <el-table-column label="支付时间" min-width="172"><template #default="{ row }">{{ row.payTime || '—' }}</template></el-table-column>
        <el-table-column label="状态" fixed="right" min-width="120"><template #default="{ row }"><el-tag type="info">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      </el-table>
      <div class="charge-pagination">
        <el-pagination background layout="total, sizes, prev, pager, next, jumper" :total="total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @update:current-page="handlePageChange" @update:page-size="handlePageSizeChange" />
      </div>
    </section>

    <el-dialog v-model="manualRefreshVisible" title="选择本次充值订单刷新条件" width="min(480px, calc(100vw - 32px))">
      <p>将为 {{ selectedManualRefreshSource?.displayName || '所选盘口' }} 提交一次后台同步任务，不会修改系统配置的定时同步范围。</p>
      <label class="manual-refresh-dialog__field">
        <span>刷新盘口</span>
        <el-select v-model="manualRefreshSourceId" style="width: 100%">
          <el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" />
        </el-select>
      </label>
      <label class="manual-refresh-dialog__field">
        <span>刷新时间范围</span>
        <el-select v-model="manualRange" style="width: 100%"><el-option v-for="option in RANGE_OPTIONS" :key="option.value" :label="option.label" :value="option.value" /></el-select>
      </label>
      <template #footer><el-button @click="manualRefreshVisible = false">取消</el-button><el-button type="primary" :loading="refreshStarting" @click="startRefresh">确认并刷新</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.charge-stack { display: grid; gap: 20px; min-width: 0; }
.charge-header, .charge-header__actions, .charge-query__footer, .charge-table__heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.charge-header h2, .charge-table__heading h2 { margin: 0; color: var(--ink-strong); font-size: 20px; }
.charge-header p, .charge-table__heading p, .sync-state small, .charge-query__footer { color: var(--ink-muted); font-size: 13px; }
.charge-header p, .charge-table__heading p { margin: 6px 0 0; }
.sync-state { display: grid; gap: 3px; text-align: right; }
.sync-state strong { color: var(--ink); font-size: 13px; }
.charge-query { overflow: hidden; }
.charge-query__grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 14px; padding: 18px; }
.charge-query__grid label { display: grid; gap: 7px; min-width: 0; color: var(--ink); font-size: 12px; font-weight: 800; }
.charge-query__grid :deep(.el-select) { width: 100%; }
.charge-query__time { grid-column: span 2; }
.charge-query__footer { border-top: 1px solid var(--border); padding: 14px 18px; }
.charge-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.charge-metrics article { display: grid; gap: 7px; min-width: 0; padding: 18px 20px; border-top: 3px solid var(--teal); }
.charge-metrics span, .charge-metrics small { color: var(--ink-muted); font-size: 13px; }
.charge-metrics strong { color: var(--ink-strong); font-size: 27px; line-height: 1.15; }
.charge-table { overflow: hidden; }
.charge-table__heading { padding: 18px 20px; }
.charge-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }
.manual-refresh-dialog__field { display: grid; gap: 7px; margin-top: 14px; color: var(--ink); font-size: 13px; font-weight: 800; }
@media (max-width: 980px) { .charge-query__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .charge-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .charge-header, .charge-header__actions, .charge-query__footer { align-items: flex-start; flex-direction: column; } .sync-state { text-align: left; } }
@media (max-width: 640px) { .charge-query__grid, .charge-metrics { grid-template-columns: 1fr; } .charge-query__time { grid-column: span 1; } .charge-pagination { overflow-x: auto; justify-content: flex-start; } }
</style>
