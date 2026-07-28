<script setup lang="ts">
import {
  Calendar,
  Check,
  CopyDocument,
  Download,
  InfoFilled,
  RefreshRight,
  VideoPause,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, ElTag } from 'element-plus'
import type { Column } from 'element-plus'
import { computed, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  cancelBatch,
  confirmBatch,
  downloadBatchExport,
  fetchBatch,
  fetchBatchResults,
  fetchBatchSummary,
  rerunBatch,
} from '../api/batches'
import { apiErrorMessage } from '../api/client'
import type {
  BatchRecord,
  BatchSummary,
  OrderResult,
  OrderResultList,
} from '../types'
import { formatDateTime, resultStatusLabel, statusLabel, statusTagType } from '../ui'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const acting = ref(false)
const batch = ref<BatchRecord | null>(null)
const summary = ref<BatchSummary | null>(null)
const missingResults = ref<OrderResultList>({ items: [], total: 0 })
const allResults = ref<OrderResultList>({ items: [], total: 0 })
const activeContentTab = ref<'missing' | 'orders'>('missing')
const resultStatus = ref('')
const missingCurrentPage = ref(1)
const pageSize = 10
const orderChunkSize = 200
const orderResultsLoading = ref(false)
const orderResultsInitialized = ref(false)
const batchId = computed(() => String(route.params.batchId))
let pollTimer: number | undefined

const activeStatuses = ['queued', 'validating', 'fetching_remote', 'comparing', 'rechecking']
const cancellable = computed(() => activeStatuses.includes(batch.value?.status || ''))
const rerunnable = computed(() =>
  ['completed', 'failed', 'comparison_incomplete', 'cancelled'].includes(
    batch.value?.status || '',
  ),
)
const awaitingConfirmation = computed(() => batch.value?.status === 'awaiting_confirmation')
const resultCounts = computed(() =>
  Object.fromEntries(
    Object.entries(summary.value?.counts || {}).filter(
      ([status]) => status !== 'confirmed_missing_success',
    ),
  ),
)
const statusOptions = computed(() => Object.keys(resultCounts.value).sort())
const totalOrders = computed(() =>
  Object.values(resultCounts.value).reduce((total, count) => total + Number(count || 0), 0),
)
const matchedOrders = computed(
  () =>
    Number(resultCounts.value.matched || 0) +
    Number(resultCounts.value.matched_after_recheck || 0),
)
const differenceOrders = computed(
  () =>
    Number(
      resultCounts.value.confirmed_missing ??
        summary.value?.counts.confirmed_missing_success ??
        missingResults.value.total,
    ),
)
const remoteOrderCount = computed(() => {
  const count = Number(batch.value?.progressJson.remoteRows)
  return Number.isFinite(count) ? count : matchedOrders.value
})
const matchedRate = computed(() =>
  totalOrders.value ? (matchedOrders.value / totalOrders.value) * 100 : 0,
)
const differenceRate = computed(() =>
  totalOrders.value ? (differenceOrders.value / totalOrders.value) * 100 : 0,
)
const orderResultsCanLoadMore = computed(
  () => !orderResultsInitialized.value || allResults.value.items.length < allResults.value.total,
)
const executionTime = computed(
  () => batch.value?.completedAt || batch.value?.startedAt || batch.value?.createdAt,
)
const shortBatchId = computed(() => batch.value?.id.slice(0, 8) || '—')
const numberFormatter = new Intl.NumberFormat('zh-CN')

function formatCount(value: number): string {
  return numberFormatter.format(value)
}

function formatRate(value: number): string {
  return `${value.toFixed(2)}%`
}

function resultTagType(
  value: string,
): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (value === 'matched' || value === 'matched_after_recheck') return 'success'
  if (value === 'confirmed_missing' || value === 'remote_status_not_success') return 'danger'
  if (value === 'recheck_inconclusive' || value === 'candidate_missing') return 'warning'
  return 'info'
}

function paymentStatusDisplay(row: OrderResult): string {
  const raw = row.paymentStatusRaw || row.paymentStatusGroup || '—'
  const normalized =
    row.paymentStatusGroup === 'success'
      ? '支付成功'
      : row.paymentStatusGroup === 'failed' || row.paymentStatusGroup === 'failure'
        ? '支付失败'
        : ''
  return normalized && raw !== normalized ? `${raw} / ${normalized}` : raw
}

function remoteValue(row: OrderResult, key: string): string {
  const value = row.payloadJson.remoteOrder?.[key]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function virtualText(value: unknown): ReturnType<typeof h> {
  const text = value === null || value === undefined || value === '' ? '—' : String(value)
  return h('span', { class: 'virtual-cell-truncate', title: text }, text)
}

const orderTableColumns = computed<Column<OrderResult>[]>(() => [
  {
    key: 'resultStatus',
    dataKey: 'resultStatus',
    title: '比对结果',
    width: 165,
    fixed: true,
    cellRenderer: ({ rowData }) =>
      h(
        ElTag,
        { type: resultTagType(rowData.resultStatus), effect: 'light', size: 'small' },
        { default: () => resultStatusLabel(rowData.resultStatus) },
      ),
  },
  {
    key: 'paymentStatus',
    title: '支付状态',
    width: 180,
    cellRenderer: ({ rowData }) =>
      h('span', { class: 'payment-status' }, [
        h('i', { class: `payment-status-dot payment-status-dot--${rowData.paymentStatusGroup}` }),
        h('span', paymentStatusDisplay(rowData)),
      ]),
  },
  {
    key: 'merchantOrderNo',
    dataKey: 'merchantOrderNo',
    title: '商户订单号',
    width: 230,
    cellRenderer: ({ rowData }) => virtualText(rowData.merchantOrderNo),
  },
  {
    key: 'platformOrderNo',
    dataKey: 'platformOrderNo',
    title: '支付平台订单号',
    width: 230,
    cellRenderer: ({ rowData }) => virtualText(rowData.platformOrderNo),
  },
  {
    key: 'amount',
    title: '金额 / 币种',
    width: 150,
    cellRenderer: ({ rowData }) =>
      virtualText(`${rowData.payloadJson.amount || '—'} ${rowData.payloadJson.currency || ''}`.trim()),
  },
  {
    key: 'remoteStatus',
    title: '远端状态',
    width: 130,
    cellRenderer: ({ rowData }) => virtualText(remoteValue(rowData, 'status')),
  },
  {
    key: 'remoteChannel',
    title: '远端渠道',
    width: 180,
    cellRenderer: ({ rowData }) => virtualText(remoteValue(rowData, '_remote_channel_label')),
  },
  {
    key: 'sourceRows',
    title: '来源行',
    width: 130,
    cellRenderer: ({ rowData }) => virtualText(rowData.payloadJson.sourceRowNumbers?.join(', ') || '—'),
  },
])

async function loadMissingResults(): Promise<void> {
  missingResults.value = await fetchBatchResults(batchId.value, {
    result_status: 'confirmed_missing',
    limit: pageSize,
    offset: (missingCurrentPage.value - 1) * pageSize,
  })
}

async function loadAllResults(reset = false): Promise<void> {
  if (orderResultsLoading.value) return
  if (reset) {
    allResults.value = { items: [], total: 0 }
    orderResultsInitialized.value = false
  }
  if (
    orderResultsInitialized.value &&
    allResults.value.items.length >= allResults.value.total
  ) {
    return
  }
  orderResultsLoading.value = true
  const offset = allResults.value.items.length
  try {
    const response = await fetchBatchResults(batchId.value, {
      result_status: resultStatus.value || undefined,
      limit: orderChunkSize,
      offset,
    })
    const existingIds = new Set(allResults.value.items.map((item) => item.id))
    allResults.value = {
      items: [
        ...allResults.value.items,
        ...response.items.filter((item) => !existingIds.has(item.id)),
      ],
      total: response.total,
    }
    orderResultsInitialized.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '订单明细加载失败。'))
  } finally {
    orderResultsLoading.value = false
  }
}

function loadNextOrderChunk(): void {
  void loadAllResults()
}

async function loadVisibleResults(): Promise<void> {
  if (activeContentTab.value === 'missing') {
    await loadMissingResults()
  } else if (activeContentTab.value === 'orders') {
    await loadAllResults()
  }
}

async function load(showLoading = true): Promise<void> {
  if (showLoading) loading.value = true
  try {
    const [detail, aggregate] = await Promise.all([
      fetchBatch(batchId.value),
      fetchBatchSummary(batchId.value),
    ])
    batch.value = detail
    summary.value = aggregate
    await loadVisibleResults()
    if (!activeStatuses.includes(detail.status) && pollTimer) {
      window.clearInterval(pollTimer)
      pollTimer = undefined
    }
  } catch (error) {
    if (showLoading) ElMessage.error(apiErrorMessage(error, '批次详情加载失败。'))
  } finally {
    loading.value = false
  }
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = window.setInterval(() => void load(false), 3000)
}

async function confirmAndStart(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将按当前模板、渠道和时间口径启动只读比对。确认后参数不可修改。',
      '确认并启动',
      { type: 'warning', confirmButtonText: '启动比对' },
    )
    acting.value = true
    batch.value = await confirmBatch(batchId.value)
    ElMessage.success('批次已进入执行队列。')
    startPolling()
    await load(false)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '启动比对失败。'))
  } finally {
    acting.value = false
  }
}

async function rerun(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将使用当前盘口配置创建新的执行版本，启动前仍需再次确认。',
      '确认重新比对',
      { type: 'warning', confirmButtonText: '创建新版本' },
    )
    const created = await rerunBatch(batchId.value)
    ElMessage.success(`已创建执行版本 V${created.runVersion}`)
    await router.push(`/batches/${created.id}`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '重新比对失败。'))
  }
}

async function cancel(): Promise<void> {
  try {
    const result = await ElMessageBox.prompt(
      '取消后不会发布确认遗漏结论。原因可选。',
      '取消执行',
      { type: 'warning', confirmButtonText: '确认取消', inputPlaceholder: '取消原因（可选）' },
    )
    await cancelBatch(batchId.value, result.value)
    ElMessage.success('批次已取消。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '取消批次失败。'))
  }
}

async function download(
  format: 'csv' | 'xlsx',
  resultStatusFilter?: string,
): Promise<void> {
  try {
    await downloadBatchExport(batchId.value, format, resultStatusFilter)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导出失败。'))
  }
}

async function copyBatchId(): Promise<void> {
  if (!batch.value) return
  try {
    await navigator.clipboard.writeText(batch.value.id)
    ElMessage.success('批次 ID 已复制。')
  } catch {
    ElMessage.warning('复制失败，请手动复制批次 ID。')
  }
}

async function changeResultFilter(): Promise<void> {
  await loadAllResults(true)
}

async function changeContentTab(): Promise<void> {
  await loadVisibleResults()
}

onMounted(async () => {
  await load()
  if (activeStatuses.includes(batch.value?.status || '')) startPolling()
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div v-loading="loading" class="page-stack result-page">
    <header class="result-page-header">
      <div class="result-title-block">
        <div class="result-title-row">
          <h1>{{ batch?.sourceDisplayName || '盘口' }} · 批次结果</h1>
          <el-tag v-if="batch" :type="statusTagType(batch.status)" effect="light">
            {{ statusLabel(batch.status) }}
          </el-tag>
        </div>
      </div>
      <div class="result-header-side">
        <div class="execution-stamp">
          <el-icon><Calendar /></el-icon>
          <div>
            <span>结果生成时间</span>
            <strong>{{ formatDateTime(executionTime) }}</strong>
          </div>
        </div>
        <div v-if="awaitingConfirmation || cancellable" class="header-actions">
          <el-button
            v-if="awaitingConfirmation"
            type="primary"
            :icon="Check"
            :loading="acting"
            @click="confirmAndStart"
          >
            确认并启动
          </el-button>
          <el-button v-if="cancellable" type="danger" plain :icon="VideoPause" @click="cancel">
            取消执行
          </el-button>
        </div>
      </div>
    </header>

    <section v-if="batch" class="batch-context-bar">
      <div class="context-item context-batch-id">
        <span>批次 ID</span>
        <strong>{{ shortBatchId }}</strong>
        <el-button
          text
          circle
          :icon="CopyDocument"
          aria-label="复制完整批次 ID"
          @click="copyBatchId"
        />
      </div>
      <div class="context-item context-file">
        <span>表格文件</span>
        <strong :title="batch.uploadedFileName">{{ batch.uploadedFileName }}</strong>
      </div>
      <div class="context-item">
        <span>盘口</span>
        <strong>{{ batch.sourceDisplayName }}</strong>
      </div>
      <div class="context-item">
        <span>执行时间</span>
        <strong>{{ formatDateTime(batch.startedAt || batch.createdAt) }}</strong>
      </div>
      <div class="context-item">
        <span>执行版本</span>
        <strong>V{{ batch.runVersion }}</strong>
      </div>
    </section>

    <el-alert
      v-if="batch && !batch.isFinal"
      class="result-state-alert"
      :type="batch.status === 'awaiting_confirmation' ? 'info' : 'warning'"
      :closable="false"
      show-icon
      title="当前结果不是最终业务结论"
      :description="
        batch.status === 'awaiting_confirmation'
          ? '请核对支付模板、渠道、时间口径与币种后启动。'
          : batch.status === 'comparison_incomplete'
            ? batch.errorMessage || '远端数据未完整读取，没有发布确认遗漏结论。'
            : '批次正在执行或已终止；只有完成状态可以导出最终结果。'
      "
    />

    <section class="result-overview" aria-label="批次结果汇总">
      <article class="overview-metric">
        <div class="metric-label">
          <span>表格总订单数</span>
          <el-tooltip content="本次上传文件去重、归组后的订单总数" placement="top">
            <el-icon><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <strong>{{ formatCount(totalOrders) }}</strong>
        <small>上传表格解析结果</small>
      </article>
      <article class="overview-metric overview-metric--matched">
        <div class="metric-label">
          <span>已匹配订单数</span>
          <el-tooltip content="首次比对或精确复查后已在后台找到的订单" placement="top">
            <el-icon><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <strong>{{ formatCount(matchedOrders) }}</strong>
        <small class="rate-chip rate-chip--success">{{ formatRate(matchedRate) }}</small>
      </article>
      <article class="overview-metric overview-metric--difference">
        <div class="metric-label">
          <span>差异订单数</span>
          <el-tooltip content="已完成精确复查，仍未在后台找到的订单" placement="top">
            <el-icon><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <strong>{{ formatCount(differenceOrders) }}</strong>
        <small class="rate-chip rate-chip--danger">{{ formatRate(differenceRate) }}</small>
      </article>
      <article class="overview-metric">
        <div class="metric-label">
          <span>后台读取订单数</span>
          <el-tooltip content="本次查询窗口和所选渠道内，从管理后台读取的订单数" placement="top">
            <el-icon><InfoFilled /></el-icon>
          </el-tooltip>
        </div>
        <strong>{{ formatCount(remoteOrderCount) }}</strong>
        <small>{{ batch?.sourceDisplayName || '远端盘口' }} · 只读查询</small>
      </article>
    </section>

    <el-tabs v-model="activeContentTab" class="detail-tabs" @tab-change="changeContentTab">
      <el-tab-pane name="missing">
        <template #label>
          <span class="tab-label">
            差异明细
            <em class="tab-count tab-count--difference">{{ formatCount(differenceOrders) }}</em>
          </span>
        </template>
        <section class="result-content-pane difference-pane">
          <div class="content-heading">
            <div>
              <h2>表格有、后台未找到</h2>
              <p>仅展示已完成精确复查且管理后台未返回相同支付平台订单号的订单。</p>
            </div>
            <div class="header-actions">
              <el-button
                :disabled="!batch?.isFinal || missingResults.total === 0"
                :icon="Download"
                @click="download('csv', 'confirmed_missing')"
              >
                导出差异
              </el-button>
              <el-button
                v-if="rerunnable"
                class="rerun-button"
                type="primary"
                :icon="RefreshRight"
                @click="rerun"
              >
                重新比对
              </el-button>
            </div>
          </div>
          <el-alert
            class="difference-alert"
            :type="batch?.isFinal ? 'warning' : 'info'"
            :closable="false"
            show-icon
            :title="
              batch?.isFinal
                ? '下列订单存在于上传表格中，但未在管理后台找到对应记录。'
                : '比对完成后将在此展示最终差异。'
            "
            :description="
              batch?.isFinal
                ? '请核查支付平台订单号、支付时间或交易状态；系统已按 out_trade_no 完成渠道内精确复查。'
                : '执行中的候选结果不会被视为后台缺失。'
            "
          />
          <el-table
            border
            class="result-table difference-table"
            :data="missingResults.items"
            :empty-text="batch?.isFinal ? '本次比对没有表格有、后台未找到的订单' : '等待比对完成后生成差异明细'"
          >
            <el-table-column label="差异结论" min-width="150">
              <template #default>
                <el-tag type="danger" effect="light">后台未找到</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="支付平台订单号" min-width="210" prop="platformOrderNo" show-overflow-tooltip />
            <el-table-column label="商户订单号" min-width="190" prop="merchantOrderNo" show-overflow-tooltip />
            <el-table-column label="支付状态" min-width="150">
              <template #default="{ row }">
                <span class="payment-status">
                  <i :class="`payment-status-dot payment-status-dot--${row.paymentStatusGroup}`" />
                  {{ paymentStatusDisplay(row) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="金额 / 币种" min-width="140">
              <template #default="{ row }">{{ row.payloadJson.amount || '—' }} {{ row.payloadJson.currency || '' }}</template>
            </el-table-column>
            <el-table-column label="支付时间" min-width="180">
              <template #default="{ row }">{{ formatDateTime(row.payloadJson.paymentTime) }}</template>
            </el-table-column>
            <el-table-column label="表格来源" min-width="170">
              <template #default="{ row }">
                <div class="source-cell">
                  <strong>{{ batch?.uploadedFileName || '—' }}</strong>
                  <small>
                    {{ row.payloadJson.sourceSheet || '—' }} · 第
                    {{ row.payloadJson.sourceRowNumbers?.join(', ') || '—' }} 行
                  </small>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-footer">
            <span>共 {{ formatCount(missingResults.total) }} 条</span>
            <el-pagination
              v-model:current-page="missingCurrentPage"
              class="result-pagination"
              background
              :page-size="pageSize"
              :total="missingResults.total"
              layout="prev, pager, next"
              @current-change="loadMissingResults"
            />
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane name="orders">
        <template #label>
          <span class="tab-label">
            订单明细
            <em class="tab-count">{{ formatCount(totalOrders) }}</em>
          </span>
        </template>
        <section class="result-content-pane">
          <div class="content-heading">
            <div>
              <h2>全部订单明细</h2>
              <p>查看支付平台订单与管理后台订单的完整匹配结果。</p>
            </div>
            <div class="header-actions">
              <el-select
                v-model="resultStatus"
                clearable
                placeholder="全部结果状态"
                style="width: 190px"
                @change="changeResultFilter"
              >
                <el-option v-for="item in statusOptions" :key="item" :label="resultStatusLabel(item)" :value="item" />
              </el-select>
              <el-button :disabled="!batch?.isFinal" :icon="Download" @click="download('xlsx')">完整 Excel</el-button>
              <el-button :disabled="!batch?.isFinal" @click="download('csv')">完整 CSV</el-button>
            </div>
          </div>
          <div v-loading="orderResultsLoading" class="virtual-orders-table" aria-label="全部订单明细虚拟化表格">
            <el-auto-resizer>
              <template #default="{ height, width }">
                <el-table-v2
                  :columns="orderTableColumns"
                  :data="allResults.items"
                  :height="height"
                  :width="width"
                  :header-height="52"
                  :row-height="64"
                  row-key="id"
                  fixed
                  scrollbar-always-on
                  :on-end-reached="loadNextOrderChunk"
                >
                  <template #empty>
                    <el-empty description="当前筛选条件下没有结果" />
                  </template>
                </el-table-v2>
              </template>
            </el-auto-resizer>
          </div>
          <div class="virtual-table-footer">
            <span>已加载 {{ formatCount(allResults.items.length) }} / {{ formatCount(allResults.total) }} 条</span>
            <div>
              <span v-if="orderResultsCanLoadMore">继续向下滚动即可加载下一批</span>
              <span v-else>已加载全部结果</span>
              <el-button
                v-if="orderResultsCanLoadMore"
                text
                type="primary"
                :loading="orderResultsLoading"
                @click="loadNextOrderChunk"
              >
                加载下一批
              </el-button>
            </div>
          </div>
        </section>
      </el-tab-pane>

    </el-tabs>
  </div>
</template>

<style scoped>
.result-page {
  min-height: calc(100vh - 56px);
  min-width: 0;
  grid-template-columns: minmax(0, 1fr);
  margin: -28px;
  padding: 26px 32px 34px;
  color: #31475c;
  background: #fff;
}

.result-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 2px 0 20px;
}

.result-title-block {
  min-width: 0;
}

.result-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-title-row h1 {
  margin: 0;
  color: #0c2d4f;
  font-size: clamp(26px, 2.3vw, 31px);
  line-height: 1.2;
  letter-spacing: -0.025em;
}

.result-header-side {
  display: grid;
  flex: 0 0 auto;
  justify-items: end;
  gap: 14px;
}

.execution-stamp {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #52687c;
}

.execution-stamp .el-icon {
  color: #8094a7;
  font-size: 18px;
}

.execution-stamp > div {
  display: grid;
  gap: 2px;
}

.execution-stamp span {
  color: #92a3b2;
  font-size: 11px;
}

.execution-stamp strong {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}

.batch-context-bar {
  display: grid;
  grid-template-columns: 1.1fr 2fr 1fr 1.55fr 0.7fr;
  gap: 28px;
  padding: 18px 0;
  border-top: 1px solid #e1e9f0;
}

.context-item {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.context-item > span {
  flex: 0 0 auto;
  color: #7c91a4;
  font-size: 12px;
}

.context-item strong {
  overflow: hidden;
  color: #2d4357;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-item :deep(.el-button) {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  margin-left: -6px;
  color: #72879a;
}

.result-state-alert {
  margin: 0 0 18px;
}

.result-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  margin-top: 4px;
  border: 1px solid #dce6ee;
  border-radius: 8px;
  background: #fff;
}

.overview-metric {
  position: relative;
  min-height: 150px;
  display: grid;
  align-content: center;
  gap: 9px;
  padding: 25px 30px;
}

.overview-metric + .overview-metric::before {
  position: absolute;
  top: 24px;
  bottom: 24px;
  left: 0;
  width: 1px;
  background: #dce6ee;
  content: "";
}

.metric-label {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #42586b;
  font-size: 13px;
  font-weight: 650;
}

.metric-label .el-icon {
  color: #8296a8;
  font-size: 14px;
}

.overview-metric > strong {
  color: #0c2d4f;
  font-size: clamp(30px, 3vw, 42px);
  line-height: 1;
  letter-spacing: -0.035em;
}

.overview-metric--matched > strong {
  color: #169d95;
}

.overview-metric--difference > strong {
  color: #ef654f;
}

.overview-metric > small {
  width: fit-content;
  min-height: 20px;
  color: #8a9cac;
  font-size: 11px;
}

.rate-chip {
  padding: 3px 7px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
}

.rate-chip--success {
  color: #159189 !important;
  background: #e5f5f3;
}

.rate-chip--danger {
  color: #ec624d !important;
  background: #fff0ed;
}

.detail-tabs {
  margin-top: 20px;
}

.detail-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.detail-tabs :deep(.el-tabs__item) {
  height: 58px;
  padding: 0 18px;
  color: #3e5367;
  font-size: 14px;
  font-weight: 700;
}

.detail-tabs :deep(.el-tabs__item:first-child) {
  padding-left: 16px;
}

.detail-tabs :deep(.el-tabs__item.is-active) {
  color: #159a93;
}

.detail-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: #159a93;
}

.detail-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: #dce6ee;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 9px;
}

.tab-count {
  min-width: 26px;
  padding: 2px 7px;
  border-radius: 5px;
  color: #52677b;
  background: #edf1f5;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}

.tab-count--difference {
  color: #fff;
  background: #2a9d98;
}

.result-content-pane {
  padding-top: 22px;
}

.content-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 17px;
}

.content-heading h2 {
  margin: 0;
  color: #0c2d4f;
  font-size: 23px;
  line-height: 1.3;
}

.content-heading p {
  margin: 6px 0 0;
  color: #8195a7;
  font-size: 13px;
  line-height: 1.55;
}

.rerun-button {
  --el-button-bg-color: #179e96;
  --el-button-border-color: #179e96;
  --el-button-hover-bg-color: #128a83;
  --el-button-hover-border-color: #128a83;
  min-width: 118px;
}

.difference-alert {
  margin-bottom: 16px;
  border: 1px solid #ffd4cb;
  background: #fffaf8;
}

.difference-alert :deep(.el-alert__title) {
  color: #516578;
  font-size: 13px;
  font-weight: 650;
}

.difference-alert :deep(.el-alert__description) {
  color: #7d8e9d;
  font-size: 12px;
}

.difference-alert :deep(.el-alert__icon) {
  color: #ef654f;
}

.result-table {
  width: 100%;
  overflow: hidden;
  border-radius: 6px;
  --el-table-border-color: #dce6ee;
  --el-table-header-bg-color: #f5f8fb;
  --el-table-row-hover-bg-color: #f7fbfb;
  --el-table-text-color: #43576a;
  --el-table-header-text-color: #183955;
}

.result-table :deep(th.el-table__cell) {
  height: 52px;
  font-size: 12px;
  font-weight: 750;
}

.result-table :deep(td.el-table__cell) {
  height: 64px;
  font-size: 12px;
}

.result-table :deep(.el-tag) {
  font-weight: 650;
}

.virtual-orders-table {
  width: 100%;
  min-height: 440px;
  height: min(64vh, 640px);
  overflow: hidden;
  border: 1px solid #dce6ee;
  border-radius: 6px;
  --el-table-border-color: #dce6ee;
  --el-table-header-bg-color: #f5f8fb;
  --el-table-row-hover-bg-color: #f7fbfb;
  --el-table-text-color: #43576a;
  --el-table-header-text-color: #183955;
}

.virtual-orders-table :deep(.el-table-v2__header-cell) {
  padding: 0 16px;
  color: #183955;
  font-size: 12px;
  font-weight: 750;
}

.virtual-orders-table :deep(.el-table-v2__row-cell) {
  padding: 0 16px;
  color: #43576a;
  font-size: 12px;
}

.virtual-orders-table :deep(.el-table-v2__header-cell + .el-table-v2__header-cell),
.virtual-orders-table :deep(.el-table-v2__row-cell + .el-table-v2__row-cell) {
  border-left: 1px solid #dce6ee;
}

.virtual-orders-table :deep(.el-table-v2__row-cell .el-tag) {
  font-weight: 650;
}

.virtual-cell-truncate {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.virtual-table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  min-height: 40px;
  margin-top: 12px;
  color: #5f7284;
  font-size: 13px;
}

.virtual-table-footer > div {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #8a9cac;
  font-size: 12px;
}

.payment-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.payment-status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: #8fa2b3;
}

.payment-status-dot--success {
  background: #24a99e;
  box-shadow: 0 0 0 3px rgba(36, 169, 158, 0.09);
}

.payment-status-dot--failed,
.payment-status-dot--failure {
  background: #ef654f;
}

.source-cell {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.source-cell strong,
.source-cell small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-cell strong {
  color: #43576a;
  font-size: 12px;
  font-weight: 650;
}

.source-cell small {
  color: #8a9cad;
  font-size: 11px;
}

.pagination-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-top: 17px;
}

.pagination-footer > span {
  color: #5f7284;
  font-size: 13px;
}

@media (max-width: 1280px) {
  .batch-context-bar {
    grid-template-columns: 1fr 1.8fr 1fr;
    row-gap: 12px;
  }
}

@media (max-width: 1100px) {
  .result-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .overview-metric:nth-child(3)::before {
    display: none;
  }

  .overview-metric:nth-child(n + 3) {
    border-top: 1px solid #dce6ee;
  }

  .result-page-header,
  .content-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .result-header-side {
    justify-items: start;
  }

  .content-heading .header-actions {
    width: 100%;
    flex-wrap: wrap;
  }
}

@media (max-width: 860px) {
  .result-page {
    min-height: calc(100vh - 36px);
    margin: -18px;
    padding: 22px 20px 28px;
  }

  .batch-context-bar {
    grid-template-columns: 1fr 1fr;
    gap: 13px 20px;
  }

  .context-file {
    grid-column: span 2;
    grid-row: 1;
  }
}

@media (max-width: 620px) {
  .result-overview,
  .batch-context-bar {
    grid-template-columns: 1fr;
  }

  .context-file {
    grid-column: auto;
    grid-row: auto;
  }

  .overview-metric {
    min-height: 120px;
  }

  .overview-metric + .overview-metric::before {
    display: none;
  }

  .overview-metric:nth-child(n + 2) {
    border-top: 1px solid #dce6ee;
  }

  .detail-tabs :deep(.el-tabs__item) {
    padding: 0 10px;
  }

  .tab-count {
    display: none;
  }
}
</style>
