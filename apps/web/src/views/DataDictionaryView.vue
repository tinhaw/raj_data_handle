<script setup lang="ts">
import { EditPen, Plus, Refresh, RefreshRight, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  createWithdrawStatus,
  fetchPaymentChannelNames,
  fetchWithdrawStatuses,
  syncWithdrawStatuses,
  updateWithdrawStatus,
} from '../api/dataDictionaries'
import { apiErrorMessage } from '../api/client'
import { fetchAllSources } from '../api/sources'
import type { DataDictionaryEntry, SourceConfig, WithdrawStatusSyncResult } from '../types'
import { formatDateTime } from '../ui'

type EntryState = 'active' | 'inactive' | 'all'
type SyncFeedback = {
  sourceId: string
  type: 'success' | 'error'
  title: string
  description: string
}

const activeTab = ref('withdraw-statuses')
const loading = ref(false)
const saving = ref(false)
const syncingWithdrawStatuses = ref(false)
const withdrawStatuses = ref<DataDictionaryEntry[]>([])
const paymentChannelNames = ref<DataDictionaryEntry[]>([])
const sources = ref<SourceConfig[]>([])
const statusPage = ref(1)
const channelPage = ref(1)
const pageSize = ref(20)
const dialogVisible = ref(false)
const editingEntryId = ref<number | null>(null)
const withdrawStatusSyncFeedback = ref<SyncFeedback | null>(null)
const statusFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const channelFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const statusForm = reactive({
  sourceId: '',
  entryCode: '',
  entryLabel: '',
  active: true,
})

function filterEntries(
  entries: DataDictionaryEntry[],
  filters: { keyword: string; sourceId: string; state: EntryState },
): DataDictionaryEntry[] {
  const keyword = filters.keyword.trim().toLocaleLowerCase()
  return entries.filter((entry) => {
    if (filters.sourceId && entry.sourceId !== filters.sourceId) return false
    if (filters.state === 'active' && !entry.active) return false
    if (filters.state === 'inactive' && entry.active) return false
    if (
      keyword &&
      !entry.entryLabel.toLocaleLowerCase().includes(keyword) &&
      !entry.entryCode.toLocaleLowerCase().includes(keyword)
    ) {
      return false
    }
    return true
  })
}

function pageEntries(entries: DataDictionaryEntry[], page: number): DataDictionaryEntry[] {
  const start = (page - 1) * pageSize.value
  return entries.slice(start, start + pageSize.value)
}

function latestAt(entries: DataDictionaryEntry[]): string | null {
  const timestamps = entries.map((entry) => Date.parse(entry.updatedAt)).filter(Number.isFinite)
  return timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null
}

function latestSeenAt(entries: DataDictionaryEntry[]): string | null {
  const timestamps = entries.map((entry) => Date.parse(entry.lastSeenAt)).filter(Number.isFinite)
  return timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null
}

const filteredWithdrawStatuses = computed(() => filterEntries(withdrawStatuses.value, statusFilters))
const filteredPaymentChannelNames = computed(() =>
  filterEntries(paymentChannelNames.value, channelFilters),
)
const pagedWithdrawStatuses = computed(() => pageEntries(filteredWithdrawStatuses.value, statusPage.value))
const pagedPaymentChannelNames = computed(() =>
  pageEntries(filteredPaymentChannelNames.value, channelPage.value),
)
const activeWithdrawStatusCount = computed(
  () => withdrawStatuses.value.filter((entry) => entry.active).length,
)
const withdrawStatusSourceCount = computed(
  () => new Set(withdrawStatuses.value.map((entry) => entry.sourceId)).size,
)
const activeChannelCount = computed(
  () => paymentChannelNames.value.filter((entry) => entry.active).length,
)
const channelSourceCount = computed(
  () => new Set(paymentChannelNames.value.map((entry) => entry.sourceId)).size,
)
const isEditing = computed(() => editingEntryId.value !== null)
const selectedWithdrawStatusEntries = computed(() => {
  if (!statusFilters.sourceId) return withdrawStatuses.value
  return withdrawStatuses.value.filter((entry) => entry.sourceId === statusFilters.sourceId)
})
const latestWithdrawStatusSeenAt = computed(() => latestSeenAt(selectedWithdrawStatusEntries.value))

async function load(): Promise<void> {
  loading.value = true
  try {
    const [statuses, channels, availableSources] = await Promise.all([
      fetchWithdrawStatuses(),
      fetchPaymentChannelNames(),
      fetchAllSources(),
    ])
    withdrawStatuses.value = statuses
    paymentChannelNames.value = channels
    sources.value = availableSources
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '数据字典加载失败。'))
  } finally {
    loading.value = false
  }
}

async function loadWithdrawStatuses(): Promise<void> {
  try {
    withdrawStatuses.value = await fetchWithdrawStatuses()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '提现状态字典刷新失败。'))
  }
}

function replaceWithdrawStatusEntries(
  sourceId: string,
  entries: DataDictionaryEntry[],
): void {
  withdrawStatuses.value = [
    ...withdrawStatuses.value.filter((entry) => entry.sourceId !== sourceId),
    ...entries,
  ]
}

function syncSuccessDescription(result: WithdrawStatusSyncResult): string {
  return `已于 ${formatDateTime(result.fetchedAt)} 从 ${result.sourceDisplayName} 读取 ${result.remoteTotal} 个状态值；新增 ${result.createdEntries} 个，更新观测时间 ${result.refreshedEntries} 个。已有展示内容和启停状态未变更。`
}

async function syncWithdrawStatusDictionary(): Promise<void> {
  const sourceId = statusFilters.sourceId
  if (!sourceId) {
    ElMessage.warning('请先选择需要从远端刷新的盘口。')
    return
  }
  syncingWithdrawStatuses.value = true
  withdrawStatusSyncFeedback.value = null
  try {
    const result = await syncWithdrawStatuses(sourceId)
    replaceWithdrawStatusEntries(sourceId, result.entries)
    statusPage.value = 1
    withdrawStatusSyncFeedback.value = {
      sourceId,
      type: 'success',
      title: '远端状态字典已刷新',
      description: syncSuccessDescription(result),
    }
    ElMessage.success('远端提现状态字典已刷新。')
  } catch (error) {
    const message = apiErrorMessage(error, '远端提现状态字典刷新失败。')
    withdrawStatusSyncFeedback.value = {
      sourceId,
      type: 'error',
      title: '远端状态字典刷新失败',
      description: `本地人工映射未被修改。${message}`,
    }
    ElMessage.error(message)
  } finally {
    syncingWithdrawStatuses.value = false
  }
}

function resetStatusForm(): void {
  editingEntryId.value = null
  statusForm.sourceId = statusFilters.sourceId || sources.value[0]?.sourceId || ''
  statusForm.entryCode = ''
  statusForm.entryLabel = ''
  statusForm.active = true
}

function openCreateDialog(): void {
  resetStatusForm()
  dialogVisible.value = true
}

function openEditDialog(entry: DataDictionaryEntry): void {
  editingEntryId.value = entry.id
  statusForm.sourceId = entry.sourceId
  statusForm.entryCode = entry.entryCode
  statusForm.entryLabel = entry.entryLabel
  statusForm.active = entry.active
  dialogVisible.value = true
}

async function saveWithdrawStatus(): Promise<void> {
  const sourceId = statusForm.sourceId.trim()
  const entryCode = statusForm.entryCode.trim()
  const entryLabel = statusForm.entryLabel.trim()
  if (!sourceId || !entryCode || !entryLabel) {
    ElMessage.warning('请填写盘口、状态值和展示内容。')
    return
  }
  saving.value = true
  try {
    if (editingEntryId.value === null) {
      await createWithdrawStatus({
        sourceId,
        entryCode,
        entryLabel,
        active: statusForm.active,
      })
      ElMessage.success('提现状态已新增。')
    } else {
      await updateWithdrawStatus(editingEntryId.value, {
        entryLabel,
        active: statusForm.active,
      })
      ElMessage.success('提现状态已更新。')
    }
    dialogVisible.value = false
    await loadWithdrawStatuses()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '提现状态保存失败。'))
  } finally {
    saving.value = false
  }
}

watch(
  () => [statusFilters.keyword, statusFilters.sourceId, statusFilters.state],
  () => {
    statusPage.value = 1
  },
)
watch(
  () => statusFilters.sourceId,
  (sourceId) => {
    if (withdrawStatusSyncFeedback.value?.sourceId !== sourceId) {
      withdrawStatusSyncFeedback.value = null
    }
  },
)
watch(
  () => [channelFilters.keyword, channelFilters.sourceId, channelFilters.state],
  () => {
    channelPage.value = 1
  },
)
watch(pageSize, () => {
  statusPage.value = 1
  channelPage.value = 1
})

onMounted(load)
</script>

<template>
  <div class="page-stack dictionary-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Data dictionaries</span>
        <h1>数据字典</h1>
        <p>按盘口维护稳定的值与展示内容映射；同一状态值在不同盘口可使用不同文案。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新本地数据</el-button>
    </header>

    <section v-loading="loading" class="surface-card dictionary-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="提现状态" name="withdraw-statuses">
          <el-alert
            title="提现状态可从远端按需刷新，展示文案由管理员维护"
            description="选择盘口后可拉取远端状态值。刷新只补充新状态并更新观测时间，不会覆盖已有展示内容或启停状态；远端暂不返回的值也不会自动停用。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>提现状态映射</h2>
              <p>提现订单页面会优先显示这里配置的文案，未配置的值保留为原始状态值。</p>
            </div>
            <div class="dictionary-actions">
              <el-tooltip
                content="请先在下方选择一个盘口。"
                :disabled="Boolean(statusFilters.sourceId)"
                placement="top"
              >
                <span>
                  <el-button
                    :icon="RefreshRight"
                    :loading="syncingWithdrawStatuses"
                    :disabled="!statusFilters.sourceId"
                    @click="syncWithdrawStatusDictionary"
                  >
                    从远端刷新
                  </el-button>
                </span>
              </el-tooltip>
              <el-button type="primary" :icon="Plus" @click="openCreateDialog">新增状态</el-button>
            </div>
          </div>

          <el-alert
            v-if="withdrawStatusSyncFeedback"
            class="sync-feedback"
            :title="withdrawStatusSyncFeedback.title"
            :description="withdrawStatusSyncFeedback.description"
            :type="withdrawStatusSyncFeedback.type"
            show-icon
            :closable="false"
          />

          <div class="summary-grid">
            <article>
              <span>启用状态</span>
              <strong>{{ activeWithdrawStatusCount }}</strong>
            </article>
            <article>
              <span>已配置盘口</span>
              <strong>{{ withdrawStatusSourceCount }}</strong>
            </article>
            <article>
              <span>最近远端观测</span>
              <strong>{{ latestWithdrawStatusSeenAt ? formatDateTime(latestWithdrawStatusSeenAt) : '尚未同步' }}</strong>
            </article>
          </div>

          <div class="dictionary-toolbar">
            <el-input
              v-model="statusFilters.keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索状态值或展示内容"
            />
            <el-select v-model="statusFilters.sourceId" placeholder="选择盘口后可从远端刷新">
              <el-option label="全部盘口" value="" />
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="source.displayName"
                :value="source.sourceId"
              />
            </el-select>
            <el-segmented
              v-model="statusFilters.state"
              :options="[
                { label: '启用', value: 'active' },
                { label: '停用', value: 'inactive' },
                { label: '全部', value: 'all' },
              ]"
            />
          </div>

          <el-table :data="pagedWithdrawStatuses" stripe>
            <el-table-column label="状态值" width="150">
              <template #default="{ row }">
                <el-tag effect="plain">{{ row.entryCode }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="展示内容" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="来源盘口" min-width="190">
              <template #default="{ row }">
                <div class="source-cell">
                  <strong>{{ row.sourceDisplayName }}</strong>
                  <span>{{ row.sourceId }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'">
                  {{ row.active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近远端观测" min-width="190">
              <template #default="{ row }">{{ formatDateTime(row.lastSeenAt) }}</template>
            </el-table-column>
            <el-table-column label="最近修改" min-width="190">
              <template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" :icon="EditPen" @click="openEditDialog(row)">
                  编辑
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无提现状态映射">
                <span class="empty-help">请点击右上角“新增状态”建立首条映射。</span>
              </el-empty>
            </template>
          </el-table>

          <div v-if="filteredWithdrawStatuses.length" class="pagination-row">
            <span>共 {{ filteredWithdrawStatuses.length }} 条</span>
            <el-pagination
              v-model:current-page="statusPage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredWithdrawStatuses.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="支付渠道名称" name="payment-channel-names">
          <el-alert
            title="支付渠道名称由盘口连接测试同步"
            description="连接测试成功后，系统从充值订单模块读取远端 label/value；远端不再返回的条目会保留并标记为停用。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>支付渠道名称</h2>
              <p>该字典为只读同步数据，不能在本页面手工修改。</p>
            </div>
          </div>

          <div class="summary-grid">
            <article>
              <span>有效条目</span>
              <strong>{{ activeChannelCount }}</strong>
            </article>
            <article>
              <span>已同步盘口</span>
              <strong>{{ channelSourceCount }}</strong>
            </article>
            <article>
              <span>最近同步</span>
              <strong>{{ latestAt(paymentChannelNames) ? formatDateTime(latestAt(paymentChannelNames)) : '尚未同步' }}</strong>
            </article>
          </div>

          <div class="dictionary-toolbar">
            <el-input
              v-model="channelFilters.keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索渠道名称或 ID"
            />
            <el-select v-model="channelFilters.sourceId" placeholder="全部盘口">
              <el-option label="全部盘口" value="" />
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="source.displayName"
                :value="source.sourceId"
              />
            </el-select>
            <el-segmented
              v-model="channelFilters.state"
              :options="[
                { label: '有效', value: 'active' },
                { label: '停用', value: 'inactive' },
                { label: '全部', value: 'all' },
              ]"
            />
          </div>

          <el-table :data="pagedPaymentChannelNames" stripe>
            <el-table-column label="支付渠道名称" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="渠道 ID" width="150">
              <template #default="{ row }">
                <el-tag effect="plain">{{ row.entryCode }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="来源盘口" min-width="190">
              <template #default="{ row }">
                <div class="source-cell">
                  <strong>{{ row.sourceDisplayName }}</strong>
                  <span>{{ row.sourceId }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.active ? 'success' : 'info'">
                  {{ row.active ? '有效' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近同步" min-width="190">
              <template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无支付渠道名称字典">
                <span class="empty-help">请先到“盘口配置”完成一次连接测试。</span>
              </el-empty>
            </template>
          </el-table>

          <div v-if="filteredPaymentChannelNames.length" class="pagination-row">
            <span>共 {{ filteredPaymentChannelNames.length }} 条</span>
            <el-pagination
              v-model:current-page="channelPage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredPaymentChannelNames.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑提现状态' : '新增提现状态'"
      width="min(560px, calc(100vw - 32px))"
      :close-on-click-modal="!saving"
    >
      <el-alert
        v-if="isEditing"
        title="盘口和状态值是映射身份，编辑时不能修改。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-form label-position="top" class="status-form">
        <el-form-item label="盘口" required>
          <el-select v-model="statusForm.sourceId" :disabled="isEditing" placeholder="选择盘口">
            <el-option
              v-for="source in sources"
              :key="source.sourceId"
              :label="source.displayName"
              :value="source.sourceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态值" required>
          <el-input
            v-model="statusForm.entryCode"
            :disabled="isEditing"
            maxlength="80"
            placeholder="例如：3"
          />
        </el-form-item>
        <el-form-item label="展示内容" required>
          <el-input v-model="statusForm.entryLabel" maxlength="255" placeholder="例如：代付成功" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="statusForm.active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveWithdrawStatus">
          {{ isEditing ? '保存修改' : '新增状态' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dictionary-page {
  grid-template-columns: minmax(0, 1fr);
}

.dictionary-card {
  min-width: 0;
  padding: 8px 24px 24px;
}

.dictionary-tab-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-top: 18px;
}

.dictionary-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.sync-feedback {
  margin-top: 16px;
}

.dictionary-tab-heading h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 19px;
}

.dictionary-tab-heading p {
  margin: 5px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 18px 0 22px;
}

.summary-grid article {
  display: grid;
  gap: 7px;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #f8fbfd;
}

.summary-grid span,
.source-cell span,
.pagination-row,
.empty-help {
  color: var(--ink-muted);
}

.summary-grid span,
.source-cell span,
.empty-help {
  font-size: 12px;
}

.summary-grid strong {
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dictionary-toolbar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 220px auto;
  gap: 12px;
  margin-bottom: 18px;
}

.entry-label {
  color: var(--ink-strong);
}

.source-cell {
  display: grid;
  gap: 2px;
}

.pagination-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 18px;
}

.empty-help {
  display: block;
}

.status-form {
  padding-top: 16px;
}

.status-form :deep(.el-select) {
  width: 100%;
}

@media (max-width: 900px) {
  .summary-grid,
  .dictionary-toolbar {
    grid-template-columns: 1fr;
  }

  .dictionary-tab-heading,
  .pagination-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .dictionary-actions {
    width: 100%;
  }
}
</style>
