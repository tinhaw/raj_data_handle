<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { fetchBatches, fetchOperationalSummary } from '../api/batches'
import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import ChargeChannelSummary from '../components/ChargeChannelSummary.vue'
import ChargeOrderDetails from '../components/ChargeOrderDetails.vue'
import type { BatchRecord, OperationalSummary, SourceConfig } from '../types'
import { formatDateTime, statusLabel, statusTagType } from '../ui'

const router = useRouter()
const activeTab = ref('comparison')
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

const activeStatuses = new Set([
  'queued',
  'validating',
  'fetching_remote',
  'comparing',
  'rechecking',
  'cancelling',
])
const issueStatuses = new Set(['failed', 'comparison_incomplete'])

function countStatuses(statuses: Set<string>): number {
  return summary.value.executionStatusDistribution
    .filter((item) => statuses.has(item.status))
    .reduce((sum, item) => sum + item.count, 0)
}

const awaitingCount = computed(() => countStatuses(new Set(['awaiting_confirmation'])))
const activeCount = computed(() => countStatuses(activeStatuses))
const issueCount = computed(() => countStatuses(issueStatuses))

const statusPriority: Record<string, number> = {
  failed: 0,
  comparison_incomplete: 0,
  awaiting_confirmation: 1,
  queued: 2,
  validating: 2,
  fetching_remote: 2,
  comparing: 2,
  rechecking: 2,
  cancelling: 2,
  completed: 3,
  cancelled: 4,
}

const sortedBatches = computed(() =>
  [...batches.value].sort((left, right) => {
    const priorityDelta =
      (statusPriority[left.status] ?? 5) - (statusPriority[right.status] ?? 5)
    if (priorityDelta !== 0) return priorityDelta
    return new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime()
  }),
)

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
        <span class="page-eyebrow">PAYIN ORDERS</span>
        <h1>充值订单</h1>
        <p>集中查看充值订单的对比任务、运行状态和处理结果。</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="payin-tabs">
      <el-tab-pane label="对比任务" name="comparison">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>对比任务</h2>
              <p>集中查看历史任务、运行状态和处理结果，并从这里发起新的数据对比。</p>
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
            <span class="filter-total">共 {{ total }} 条任务记录</span>
          </section>

          <section class="task-summary surface-card" aria-label="任务状态摘要">
            <article class="task-summary__item">
              <span>任务总数</span>
              <strong>{{ total }}</strong>
              <small>当前筛选结果</small>
            </article>
            <article class="task-summary__item task-summary__item--warning">
              <span>待确认</span>
              <strong>{{ awaitingCount }}</strong>
              <small>确认后才会开始执行</small>
            </article>
            <article class="task-summary__item task-summary__item--active">
              <span>执行中</span>
              <strong>{{ activeCount }}</strong>
              <small>正在查询或比对</small>
            </article>
            <article class="task-summary__item task-summary__item--danger">
              <span>失败 / 不完整</span>
              <strong>{{ issueCount }}</strong>
              <small>需要优先处理</small>
            </article>
          </section>

          <section class="surface-card table-card">
            <div class="section-heading">
              <div>
                <h2>任务记录</h2>
                <p>异常、待确认与执行中的任务优先展示；每次重新比对都会保留执行版本。</p>
              </div>
            </div>
            <el-table
              v-loading="loading"
              :data="sortedBatches"
              empty-text="暂无对比任务，请点击右上角“新建对比”"
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
      </el-tab-pane>
      <el-tab-pane label="充值订单明细" name="orders" lazy>
        <ChargeOrderDetails />
      </el-tab-pane>
      <el-tab-pane label="支付渠道汇总" name="channels" lazy>
        <ChargeChannelSummary />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.task-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
}

.task-summary__item {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 18px 20px;
}

.task-summary__item + .task-summary__item {
  border-left: 1px solid var(--border);
}

.task-summary__item span,
.task-summary__item small {
  color: var(--ink-muted);
}

.task-summary__item span {
  font-size: 13px;
  font-weight: 700;
}

.task-summary__item strong {
  color: var(--ink-strong);
  font-size: 30px;
  line-height: 1.1;
}

.task-summary__item small {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-summary__item--warning strong {
  color: #b7791f;
}

.task-summary__item--active strong {
  color: var(--primary);
}

.task-summary__item--danger strong {
  color: var(--danger);
}

.payin-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.payin-tabs :deep(.el-tabs__item) {
  height: 52px;
  padding: 0 18px;
  color: var(--ink);
  font-weight: 800;
}

.payin-tabs :deep(.el-tabs__item.is-active) {
  color: var(--teal);
}

.payin-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: var(--teal);
}

.payin-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border);
}

.payin-tabs :deep(.el-tabs__content) {
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

@media (max-width: 980px) {
  .tab-pane-header,
  .header-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .task-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-summary__item:nth-child(3) {
    border-top: 1px solid var(--border);
    border-left: 0;
  }

  .task-summary__item:nth-child(4) {
    border-top: 1px solid var(--border);
  }
}

@media (max-width: 640px) {
  .payin-tabs :deep(.el-tabs__item) {
    padding: 0 12px;
  }

  .task-summary {
    grid-template-columns: 1fr;
  }

  .task-summary__item + .task-summary__item {
    border-top: 1px solid var(--border);
    border-left: 0;
  }
}
</style>
