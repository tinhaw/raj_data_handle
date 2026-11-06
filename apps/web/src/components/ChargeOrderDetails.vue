<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElTag } from 'element-plus'
import type { Column } from 'element-plus'
import { computed, h, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { queryChargeOrders, startChargeOrderRefresh } from '../api/chargeOrders'
import type {
  ChargeOrder,
  ChargeOrderRefreshRange,
  ChargeOrderQueryResponse,
  ChargeOrderSummary,
  SourceConfig,
} from '../types'
import { businessFullDayRange, formatDateTime, yesterdayFullDayRange } from '../ui'

const RANGE_OPTIONS: Array<{ value: ChargeOrderRefreshRange; label: string }> = [
  { value: 'day_before_yesterday', label: '前天 00:00:00 至 23:59:59' },
  { value: 'yesterday', label: '昨天 00:00:00 至 23:59:59' },
  { value: 'today', label: '今天 00:00:00 至 23:59:59' },
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
const manualRange = ref<ChargeOrderRefreshRange>('yesterday')
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
const dateRangeShortcuts = computed(() => {
  const timeZone = selectedSource.value?.businessTimezone || 'Asia/Kolkata'
  return [
    { text: '昨天', value: () => businessFullDayRange(timeZone, 1) },
    { text: '前天', value: () => businessFullDayRange(timeZone, 2) },
    { text: '今天', value: () => businessFullDayRange(timeZone, 0) },
  ]
})
const summary = computed(() => response.value?.summary || emptySummary)
const total = computed(() => response.value?.total || 0)
const statusOptions = computed(() => response.value?.statusDictionary || [])
const channelOptions = computed(() => response.value?.channelDictionary || [])
const statusNames = computed(
  () => new Map(statusOptions.value.map((item) => [item.code, item.label])),
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

function virtualCellText(value: unknown): ReturnType<typeof h> {
  const text = value === null || value === undefined || value === '' ? '—' : String(value)
  return h('span', { class: 'charge-virtual-cell', title: text }, text)
}

const chargeOrderTableColumns = computed<Column<ChargeOrder>[]>(() => [
  {
    key: 'id',
    dataKey: 'id',
    title: '订单id',
    width: 150,
    fixed: true,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.id),
  },
  {
    key: 'uid',
    dataKey: 'uid',
    title: '用户uid',
    width: 132,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.uid),
  },
  {
    key: 'orderNum',
    dataKey: 'orderNum',
    title: '我方订单号',
    width: 204,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.orderNum),
  },
  {
    key: 'chargeProductId',
    dataKey: 'chargeProductId',
    title: '充值商品id',
    width: 150,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.chargeProductId),
  },
  {
    key: 'productName',
    dataKey: 'productName',
    title: '商品名称',
    width: 178,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.productName),
  },
  {
    key: 'payChannelName',
    dataKey: 'payChannelName',
    title: '支付渠道名称',
    width: 188,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payChannelName),
  },
  {
    key: 'payMethod',
    dataKey: 'payMethod',
    title: '支付渠道',
    width: 154,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payMethod),
  },
  {
    key: 'payType',
    dataKey: 'payType',
    title: '支付方式',
    width: 154,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payType),
  },
  {
    key: 'outTradeNo',
    dataKey: 'outTradeNo',
    title: '三方支付订单号',
    width: 204,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.outTradeNo),
  },
  {
    key: 'amount',
    title: '支付金额',
    width: 144,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.amount)),
  },
  {
    key: 'balance',
    title: '发放金额',
    width: 144,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.balance)),
  },
  {
    key: 'extra',
    title: '赠送金额',
    width: 144,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.extra)),
  },
  {
    key: 'status',
    title: '订单状态',
    width: 136,
    align: 'center',
    cellRenderer: ({ rowData }) =>
      h(
        ElTag,
        { type: 'info', effect: 'light', size: 'small' },
        { default: () => statusLabel(rowData.status) },
      ),
  },
  {
    key: 'createTime',
    title: '创建时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.createTime),
  },
  {
    key: 'payTime',
    title: '支付时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payTime),
  },
  {
    key: 'updateTime',
    title: '完成时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.updateTime),
  },
  {
    key: 'firstPay',
    dataKey: 'firstPay',
    title: '是否首充',
    width: 112,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.firstPay),
  },
  {
    key: 'channel',
    dataKey: 'channel',
    title: '用户渠道',
    width: 154,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.channel),
  },
])

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
  manualRange.value = 'yesterday'
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
        <p>仅查询本地已导出并缓存的充值订单；远端同步由后台工作进程按天执行。</p>
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
            :shortcuts="dateRangeShortcuts"
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
        <div><h2>充值订单列表</h2><p>共 {{ total.toLocaleString() }} 条；本地数据更新时间：{{ localUpdatedText }}。表格固定高度，仅在表格内滚动。</p></div>
        <el-tag effect="plain" type="info">{{ refreshLabel }}</el-tag>
      </div>
      <div v-loading="loading" class="charge-virtual-table" aria-label="充值订单明细虚拟化表格">
        <el-auto-resizer>
          <template #default="{ height, width }">
            <el-table-v2
              :columns="chargeOrderTableColumns"
              :data="rows"
              :height="height"
              :width="width"
              :header-height="52"
              :row-height="56"
              row-key="id"
              fixed
              scrollbar-always-on
            >
              <template #empty>
                <el-empty description="当前本地数据中暂无充值订单" />
              </template>
            </el-table-v2>
          </template>
        </el-auto-resizer>
      </div>
      <div class="charge-pagination">
        <el-pagination background layout="total, sizes, prev, pager, next, jumper" :total="total" :current-page="page" :page-size="pageSize" :page-sizes="[20, 50, 100]" @update:current-page="handlePageChange" @update:page-size="handlePageSizeChange" />
      </div>
    </section>

    <el-dialog v-model="manualRefreshVisible" title="选择本次充值订单刷新条件" width="min(480px, calc(100vw - 32px))">
      <p>将为 {{ selectedManualRefreshSource?.displayName || '所选盘口' }} 导出指定自然日的充值订单并更新本地缓存，不会修改系统配置的定时导出日期。</p>
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
.charge-virtual-table {
  width: 100%;
  min-height: 360px;
  height: clamp(360px, calc(100vh - 430px), 720px);
  overflow: hidden;
  border: 1px solid #dce6ee;
  border-radius: 8px;
  background: #ffffff;
  --el-table-border-color: #dce6ee;
  --el-table-header-bg-color: #f5f8fb;
  --el-table-row-hover-bg-color: #f7fbfb;
  --el-table-text-color: #43576a;
  --el-table-header-text-color: #183955;
}
.charge-virtual-table :deep(.el-table-v2__header-cell) {
  padding: 0 14px;
  color: #183955;
  font-size: 12px;
  font-weight: 750;
}
.charge-virtual-table :deep(.el-table-v2__row-cell) {
  padding: 0 14px;
  color: #43576a;
  font-size: 12px;
}
.charge-virtual-table :deep(.el-table-v2__header-cell + .el-table-v2__header-cell),
.charge-virtual-table :deep(.el-table-v2__row-cell + .el-table-v2__row-cell) { border-left: 1px solid #dce6ee; }
.charge-virtual-table :deep(.el-table-v2__row-cell .el-tag) { font-weight: 650; }
.charge-virtual-cell { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.charge-pagination { display: flex; justify-content: flex-end; padding: 16px 20px; }
.manual-refresh-dialog__field { display: grid; gap: 7px; margin-top: 14px; color: var(--ink); font-size: 13px; font-weight: 800; }
@media (max-width: 980px) { .charge-query__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .charge-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .charge-header, .charge-header__actions, .charge-query__footer { align-items: flex-start; flex-direction: column; } .sync-state { text-align: left; } }
@media (max-width: 640px) { .charge-query__grid, .charge-metrics { grid-template-columns: 1fr; } .charge-query__time { grid-column: span 1; } .charge-virtual-table { min-height: 320px; height: min(56vh, 520px); } .charge-pagination { overflow-x: auto; justify-content: flex-start; } }
</style>
