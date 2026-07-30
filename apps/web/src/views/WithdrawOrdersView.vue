<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import { queryWithdrawOrders, startWithdrawOrderRefresh } from '../api/withdrawOrders'
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
  uid: '',
  status: '',
  auditAdmin: '',
})

const selectedSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const summary = computed(() => response.value?.summary || emptySummary)
const statusDictionary = computed(() => response.value?.statusDictionary || [])
const statusEntryByCode = computed(
  () => new Map(statusDictionary.value.map((entry) => [entry.code, entry])),
)
const currency = computed(() => response.value?.currency || selectedSource.value?.currency || 'INR')
const localUpdatedText = computed(() =>
  response.value ? formatDateTime(response.value.localUpdatedAt) : '尚未查询',
)
const refreshIsIncomplete = computed(
  () => response.value?.refreshStatus === 'succeeded' && response.value.complete === false,
)
const syncTimingText = computed(() => {
  if (response.value?.lastRefreshedAt) {
    if (refreshIsIncomplete.value) {
      return `上次同步 ${formatDateTime(response.value.lastRefreshedAt)} · 结果不完整，已保留本地缓存`
    }
    return `上次成功 ${formatDateTime(response.value.lastRefreshedAt)}`
  }
  if (queuedAt.value) return `请求于 ${formatDateTime(queuedAt.value)}`
  return '尚未成功同步'
})
const normalizedRefreshStatus = computed(() => {
  const responseStatus = response.value?.refreshStatus
  const status = queuedAt.value && (!responseStatus || responseStatus === 'not_started')
    ? 'queued'
    : (responseStatus || 'not_started')
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
  const code = status.trim()
  const label = statusEntryByCode.value.get(code)?.label?.trim()
  return label || code || '—'
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
  knownStatuses.value = [
    ...new Set([...knownStatuses.value, ...values.map((value) => value.trim()).filter(Boolean)]),
  ].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }))
}

function validateFilters(): boolean {
  if (!filters.sourceId) {
    ElMessage.warning('请先选择盘口。')
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
  } catch (error) {
    if (!quiet) ElMessage.error(apiErrorMessage(error, '本地提现订单加载失败。'))
  } finally {
    loading.value = false
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
  response.value = null
  rows.value = []
  total.value = 0
  knownStatuses.value = []
  queuedAt.value = null
}

function handleSourceChange(): void {
  page.value = 1
  filters.status = ''
  resetLocalResult()
  void load(true)
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void load(false)
}

function handlePageSizeChange(nextPageSize: number): void {
  pageSize.value = nextPageSize
  void load(true)
}

onMounted(async () => {
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value.length) {
      filters.sourceId = sources.value[0]!.sourceId
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
      </div>
      <div class="query-card__footer">
        <span>筛选只作用于本地数据库；后台同步的时间范围与间隔由系统配置统一控制。</span>
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
</template>

<style scoped>
.withdraw-page {
  min-width: 0;
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

@media (max-width: 1100px) {
  .query-card__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .page-header,
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
  .query-card__grid {
    grid-template-columns: 1fr;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
