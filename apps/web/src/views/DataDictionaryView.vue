<script setup lang="ts">
import { EditPen, Plus, Refresh, RefreshRight, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  createChargeStatus,
  createWithdrawStatus,
  fetchChargeStatuses,
  fetchPaymentChannels,
  fetchPaymentChannelNames,
  fetchSpinOrderStatuses,
  fetchUserSourceChannels,
  fetchWithdrawStatuses,
  refreshUserSourceChannels,
  syncWithdrawStatuses,
  updateChargeStatus,
  updateWithdrawStatus,
} from '../api/dataDictionaries'
import { apiErrorMessage } from '../api/client'
import { fetchAllSources } from '../api/sources'
import type {
  DataDictionaryEntry,
  SourceConfig,
  UserSourceChannelSyncResult,
  WithdrawStatusSyncResult,
} from '../types'
import { formatDateTime } from '../ui'

type EntryState = 'active' | 'inactive' | 'all'
type EditableStatusType = 'withdraw_status' | 'charge_status'
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
const syncingUserSourceChannels = ref(false)
const withdrawStatuses = ref<DataDictionaryEntry[]>([])
const chargeStatuses = ref<DataDictionaryEntry[]>([])
const spinStatuses = ref<DataDictionaryEntry[]>([])
const paymentChannels = ref<DataDictionaryEntry[]>([])
const paymentChannelNames = ref<DataDictionaryEntry[]>([])
const userSourceChannels = ref<DataDictionaryEntry[]>([])
const sources = ref<SourceConfig[]>([])
const statusPage = ref(1)
const chargeStatusPage = ref(1)
const paymentChannelPage = ref(1)
const channelNamePage = ref(1)
const spinStatusPage = ref(1)
const userSourceChannelPage = ref(1)
const pageSize = ref(20)
const dialogVisible = ref(false)
const editingEntryId = ref<number | null>(null)
const editingStatusType = ref<EditableStatusType>('withdraw_status')
const withdrawStatusSyncFeedback = ref<SyncFeedback | null>(null)
const userSourceChannelSyncFeedback = ref<SyncFeedback | null>(null)
const statusFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const chargeStatusFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const channelFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const paymentChannelFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const spinStatusFilters = reactive({
  keyword: '',
  sourceId: '',
  state: 'active' as EntryState,
})
const userSourceChannelFilters = reactive({
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
const filteredChargeStatuses = computed(() =>
  filterEntries(chargeStatuses.value, chargeStatusFilters),
)
const filteredPaymentChannels = computed(() =>
  filterEntries(paymentChannels.value, paymentChannelFilters),
)
const filteredPaymentChannelNames = computed(() =>
  filterEntries(paymentChannelNames.value, channelFilters),
)
const filteredSpinStatuses = computed(() => filterEntries(spinStatuses.value, spinStatusFilters))
const filteredUserSourceChannels = computed(() =>
  filterEntries(userSourceChannels.value, userSourceChannelFilters),
)
const pagedWithdrawStatuses = computed(() =>
  pageEntries(filteredWithdrawStatuses.value, statusPage.value),
)
const pagedChargeStatuses = computed(() =>
  pageEntries(filteredChargeStatuses.value, chargeStatusPage.value),
)
const pagedPaymentChannels = computed(() =>
  pageEntries(filteredPaymentChannels.value, paymentChannelPage.value),
)
const pagedPaymentChannelNames = computed(() =>
  pageEntries(filteredPaymentChannelNames.value, channelNamePage.value),
)
const pagedSpinStatuses = computed(() => pageEntries(filteredSpinStatuses.value, spinStatusPage.value))
const pagedUserSourceChannels = computed(() =>
  pageEntries(filteredUserSourceChannels.value, userSourceChannelPage.value),
)
const activeWithdrawStatusCount = computed(
  () => withdrawStatuses.value.filter((entry) => entry.active).length,
)
const withdrawStatusSourceCount = computed(
  () => new Set(withdrawStatuses.value.map((entry) => entry.sourceId)).size,
)
const activeChargeStatusCount = computed(
  () => chargeStatuses.value.filter((entry) => entry.active).length,
)
const chargeStatusSourceCount = computed(
  () => new Set(chargeStatuses.value.map((entry) => entry.sourceId)).size,
)
const activePaymentChannelCount = computed(
  () => paymentChannels.value.filter((entry) => entry.active).length,
)
const paymentChannelSourceCount = computed(
  () => new Set(paymentChannels.value.map((entry) => entry.sourceId)).size,
)
const activeChannelNameCount = computed(
  () => paymentChannelNames.value.filter((entry) => entry.active).length,
)
const channelNameSourceCount = computed(
  () => new Set(paymentChannelNames.value.map((entry) => entry.sourceId)).size,
)
const activeSpinStatusCount = computed(() => spinStatuses.value.filter((entry) => entry.active).length)
const spinStatusSourceCount = computed(() => new Set(spinStatuses.value.map((entry) => entry.sourceId)).size)
const activeUserSourceChannelCount = computed(
  () => userSourceChannels.value.filter((entry) => entry.active).length,
)
const userSourceChannelSourceCount = computed(
  () => new Set(userSourceChannels.value.map((entry) => entry.sourceId)).size,
)
const isEditing = computed(() => editingEntryId.value !== null)
const editableStatusName = computed(() =>
  editingStatusType.value === 'charge_status' ? '充值订单状态' : '提现状态',
)
const statusExample = computed(() =>
  editingStatusType.value === 'charge_status' ? '例如：2' : '例如：3',
)
const statusLabelExample = computed(() =>
  editingStatusType.value === 'charge_status' ? '例如：已退款' : '例如：代付成功',
)
const selectedWithdrawStatusEntries = computed(() => {
  if (!statusFilters.sourceId) return withdrawStatuses.value
  return withdrawStatuses.value.filter((entry) => entry.sourceId === statusFilters.sourceId)
})
const latestWithdrawStatusSeenAt = computed(() => latestSeenAt(selectedWithdrawStatusEntries.value))

async function load(): Promise<void> {
  loading.value = true
  try {
    const [statuses, rechargeStatuses, channels, channelNames, spins, userChannels, availableSources] =
      await Promise.all([
        fetchWithdrawStatuses(),
        fetchChargeStatuses(),
        fetchPaymentChannels(),
        fetchPaymentChannelNames(),
        fetchSpinOrderStatuses(),
        fetchUserSourceChannels(),
        fetchAllSources(),
      ])
    withdrawStatuses.value = statuses
    chargeStatuses.value = rechargeStatuses
    paymentChannels.value = channels
    paymentChannelNames.value = channelNames
    spinStatuses.value = spins
    userSourceChannels.value = userChannels
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

async function loadChargeStatuses(): Promise<void> {
  try {
    chargeStatuses.value = await fetchChargeStatuses()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '充值订单状态字典刷新失败。'))
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

function replaceUserSourceChannelEntries(sourceId: string, entries: DataDictionaryEntry[]): void {
  userSourceChannels.value = [
    ...userSourceChannels.value.filter((entry) => entry.sourceId !== sourceId),
    ...entries,
  ]
}

function userSourceChannelSyncDescription(result: UserSourceChannelSyncResult): string {
  return `已于 ${formatDateTime(result.fetchedAt)} 从 ${result.sourceDisplayName} 读取 ${result.remoteTotal} 条渠道来源映射，并覆盖写入 ${result.replacedEntries} 条本地字典记录。`
}

async function syncUserSourceChannelDictionary(): Promise<void> {
  const sourceId = userSourceChannelFilters.sourceId
  if (!sourceId) {
    ElMessage.warning('请先选择需要从远端刷新的盘口。')
    return
  }
  syncingUserSourceChannels.value = true
  userSourceChannelSyncFeedback.value = null
  try {
    const result = await refreshUserSourceChannels(sourceId)
    replaceUserSourceChannelEntries(sourceId, result.entries)
    userSourceChannelPage.value = 1
    userSourceChannelSyncFeedback.value = {
      sourceId,
      type: 'success',
      title: '渠道来源字典已覆盖刷新',
      description: userSourceChannelSyncDescription(result),
    }
    ElMessage.success('远端渠道来源字典已覆盖刷新。')
  } catch (error) {
    const message = apiErrorMessage(error, '远端渠道来源字典刷新失败。')
    userSourceChannelSyncFeedback.value = {
      sourceId,
      type: 'error',
      title: '渠道来源字典刷新失败',
      description: `远端读取或校验失败，本地旧字典保持不变。${message}`,
    }
    ElMessage.error(message)
  } finally {
    syncingUserSourceChannels.value = false
  }
}

function resetStatusForm(dictionaryType: EditableStatusType): void {
  editingEntryId.value = null
  editingStatusType.value = dictionaryType
  statusForm.sourceId =
    (dictionaryType === 'charge_status' ? chargeStatusFilters.sourceId : statusFilters.sourceId) ||
    sources.value[0]?.sourceId ||
    ''
  statusForm.entryCode = ''
  statusForm.entryLabel = ''
  statusForm.active = true
}

function openCreateStatusDialog(dictionaryType: EditableStatusType): void {
  resetStatusForm(dictionaryType)
  dialogVisible.value = true
}

function openEditStatusDialog(entry: DataDictionaryEntry, dictionaryType: EditableStatusType): void {
  editingEntryId.value = entry.id
  editingStatusType.value = dictionaryType
  statusForm.sourceId = entry.sourceId
  statusForm.entryCode = entry.entryCode
  statusForm.entryLabel = entry.entryLabel
  statusForm.active = entry.active
  dialogVisible.value = true
}

async function saveStatus(): Promise<void> {
  const sourceId = statusForm.sourceId.trim()
  const entryCode = statusForm.entryCode.trim()
  const entryLabel = statusForm.entryLabel.trim()
  if (!sourceId || !entryCode || !entryLabel) {
    ElMessage.warning('请填写盘口、状态值和展示内容。')
    return
  }
  saving.value = true
  try {
    if (editingStatusType.value === 'charge_status') {
      if (editingEntryId.value === null) {
        await createChargeStatus({
          sourceId,
          entryCode,
          entryLabel,
          active: statusForm.active,
        })
        ElMessage.success('充值订单状态已新增。')
      } else {
        await updateChargeStatus(editingEntryId.value, {
          entryLabel,
          active: statusForm.active,
        })
        ElMessage.success('充值订单状态已更新。')
      }
    } else {
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
    }
    dialogVisible.value = false
    if (editingStatusType.value === 'charge_status') {
      await loadChargeStatuses()
    } else {
      await loadWithdrawStatuses()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, `${editableStatusName.value}保存失败。`))
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
  () => [
    chargeStatusFilters.keyword,
    chargeStatusFilters.sourceId,
    chargeStatusFilters.state,
  ],
  () => {
    chargeStatusPage.value = 1
  },
)
watch(
  () => [
    paymentChannelFilters.keyword,
    paymentChannelFilters.sourceId,
    paymentChannelFilters.state,
  ],
  () => {
    paymentChannelPage.value = 1
  },
)
watch(
  () => [channelFilters.keyword, channelFilters.sourceId, channelFilters.state],
  () => {
    channelNamePage.value = 1
  },
)
watch(
  () => [spinStatusFilters.keyword, spinStatusFilters.sourceId, spinStatusFilters.state],
  () => {
    spinStatusPage.value = 1
  },
)
watch(
  () => [
    userSourceChannelFilters.keyword,
    userSourceChannelFilters.sourceId,
    userSourceChannelFilters.state,
  ],
  () => {
    userSourceChannelPage.value = 1
  },
)
watch(
  () => userSourceChannelFilters.sourceId,
  (sourceId) => {
    if (userSourceChannelSyncFeedback.value?.sourceId !== sourceId) {
      userSourceChannelSyncFeedback.value = null
    }
  },
)
watch(pageSize, () => {
  statusPage.value = 1
  chargeStatusPage.value = 1
  paymentChannelPage.value = 1
  channelNamePage.value = 1
  spinStatusPage.value = 1
  userSourceChannelPage.value = 1
})

onMounted(load)
</script>

<template>
  <div class="page-stack dictionary-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Data dictionaries</span>
        <h1>数据字典</h1>
        <p>按盘口维护稳定的响应值与展示内容映射，并明确每套字典对应的远端字段。</p>
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
              <el-button
                type="primary"
                :icon="Plus"
                @click="openCreateStatusDialog('withdraw_status')"
              >
                新增状态
              </el-button>
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
                <el-button
                  text
                  type="primary"
                  :icon="EditPen"
                  @click="openEditStatusDialog(row, 'withdraw_status')"
                >
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

        <el-tab-pane label="充值订单状态" name="charge-statuses">
          <el-alert
            title="充值订单状态由人工核对并存入本地数据库"
            description="当前尚未找到远端字典接口；系统已保存 -1=已失效、0=待支付、1=已支付、2=已退款。管理员可手动新增、修改展示内容或停用状态；本页没有远端刷新操作。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>充值订单状态映射</h2>
              <p>充值订单筛选和状态列均从该数据库字典读取，未知状态显示为“状态 {值}”。</p>
            </div>
            <div class="dictionary-actions">
              <div class="field-binding">
                <span>对应响应字段</span>
                <code>status</code>
              </div>
              <el-button
                type="primary"
                :icon="Plus"
                @click="openCreateStatusDialog('charge_status')"
              >
                新增状态
              </el-button>
            </div>
          </div>

          <div class="summary-grid">
            <article>
              <span>有效记录</span>
              <strong>{{ activeChargeStatusCount }}</strong>
            </article>
            <article>
              <span>已初始化盘口</span>
              <strong>{{ chargeStatusSourceCount }}</strong>
            </article>
            <article>
              <span>数据来源</span>
              <strong>人工核对</strong>
            </article>
          </div>

          <div class="dictionary-toolbar">
            <el-input
              v-model="chargeStatusFilters.keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索展示内容或 status 值"
            />
            <el-select v-model="chargeStatusFilters.sourceId" placeholder="全部盘口">
              <el-option label="全部盘口" value="" />
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="source.displayName"
                :value="source.sourceId"
              />
            </el-select>
            <el-segmented
              v-model="chargeStatusFilters.state"
              :options="[
                { label: '有效', value: 'active' },
                { label: '停用', value: 'inactive' },
                { label: '全部', value: 'all' },
              ]"
            />
          </div>

          <el-table :data="pagedChargeStatuses" stripe>
            <el-table-column label="展示内容" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="status 值" width="160">
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
            <el-table-column label="数据库更新时间" min-width="190">
              <template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button
                  text
                  type="primary"
                  :icon="EditPen"
                  @click="openEditStatusDialog(row, 'charge_status')"
                >
                  编辑
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无充值订单状态字典">
                <span class="empty-help">请点击右上角“新增状态”建立首条映射。</span>
              </el-empty>
            </template>
          </el-table>

          <div v-if="filteredChargeStatuses.length" class="pagination-row">
            <span>共 {{ filteredChargeStatuses.length }} 条</span>
            <el-pagination
              v-model:current-page="chargeStatusPage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredChargeStatuses.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="支付渠道" name="payment-channels">
          <el-alert
            title="支付渠道字典对应充值订单响应字段 pay_method"
            description="系统从远端数据字典 pay_channel 读取 key/title：key 保存为 pay_method 值，title 作为页面展示内容；远端不再返回的条目会保留并标记为停用。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>支付渠道映射</h2>
              <p>
                充值订单明细、筛选和渠道汇总均使用这套映射；该字典为远端只读同步数据。
              </p>
            </div>
            <div class="field-binding">
              <span>对应响应字段</span>
              <code>pay_method</code>
            </div>
          </div>

          <div class="summary-grid">
            <article>
              <span>有效条目</span>
              <strong>{{ activePaymentChannelCount }}</strong>
            </article>
            <article>
              <span>已同步盘口</span>
              <strong>{{ paymentChannelSourceCount }}</strong>
            </article>
            <article>
              <span>最近同步</span>
              <strong>
                {{
                  latestAt(paymentChannels)
                    ? formatDateTime(latestAt(paymentChannels))
                    : '尚未同步'
                }}
              </strong>
            </article>
          </div>

          <div class="dictionary-toolbar">
            <el-input
              v-model="paymentChannelFilters.keyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜索展示内容或 pay_method 值"
            />
            <el-select v-model="paymentChannelFilters.sourceId" placeholder="全部盘口">
              <el-option label="全部盘口" value="" />
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="source.displayName"
                :value="source.sourceId"
              />
            </el-select>
            <el-segmented
              v-model="paymentChannelFilters.state"
              :options="[
                { label: '有效', value: 'active' },
                { label: '停用', value: 'inactive' },
                { label: '全部', value: 'all' },
              ]"
            />
          </div>

          <el-table :data="pagedPaymentChannels" stripe>
            <el-table-column label="展示内容（title）" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="pay_method 值（key）" min-width="190">
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
              <el-empty description="暂无支付渠道字典">
                <span class="empty-help">
                  请先到“盘口配置”完成连接测试，或等待下一次充值订单后台刷新。
                </span>
              </el-empty>
            </template>
          </el-table>

          <div v-if="filteredPaymentChannels.length" class="pagination-row">
            <span>共 {{ filteredPaymentChannels.length }} 条</span>
            <el-pagination
              v-model:current-page="paymentChannelPage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredPaymentChannels.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="支付渠道名称" name="payment-channel-names">
          <el-alert
            title="支付渠道名称字典对应充值订单响应字段 pay_channel_name"
            description="系统从充值订单模块的 payChannel 接口读取 value/label：value 保存为 pay_channel_name 值，label 作为页面展示内容；该字典与 pay_method 对应的 key/title 字典分开保存。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>支付渠道名称</h2>
              <p>充值订单明细会按该字典转换支付渠道名称；该字典为只读同步数据。</p>
            </div>
            <div class="field-binding">
              <span>对应响应字段</span>
              <code>pay_channel_name</code>
            </div>
          </div>

          <div class="summary-grid">
            <article>
              <span>有效条目</span>
              <strong>{{ activeChannelNameCount }}</strong>
            </article>
            <article>
              <span>已同步盘口</span>
              <strong>{{ channelNameSourceCount }}</strong>
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
              placeholder="搜索展示内容或 pay_channel_name 值"
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
            <el-table-column label="展示内容（label）" min-width="260">
              <template #default="{ row }">
                <strong class="entry-label">{{ row.entryLabel }}</strong>
              </template>
            </el-table-column>
            <el-table-column label="pay_channel_name 值（value）" min-width="230">
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
              v-model:current-page="channelNamePage"
              v-model:page-size="pageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredPaymentChannelNames.length"
              layout="sizes, prev, pager, next"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="转盘审核状态" name="spin-order-statuses">
          <el-alert
            title="转盘订单状态为已确认的固定字典"
            description="转盘订单列表的 status 与 statusTab 使用相同值。系统固定使用 0=待审核、1=审核通过、101=自动审核通过、2=已拒绝、3=已挂起；该字典只读，不提供人工修改。"
            type="info"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>转盘审核状态映射</h2>
              <p>对应远端字段 <code>status</code> 和 <code>statusTab</code>，并用于转盘订单筛选、详情和汇总。</p>
            </div>
            <div class="field-binding">
              <span>对应响应字段</span>
              <code>status / statusTab</code>
            </div>
          </div>

          <div class="summary-grid">
            <article><span>有效状态</span><strong>{{ activeSpinStatusCount }}</strong></article>
            <article><span>已初始化盘口</span><strong>{{ spinStatusSourceCount }}</strong></article>
            <article><span>维护方式</span><strong>固定系统字典</strong></article>
          </div>

          <div class="dictionary-toolbar">
            <el-input v-model="spinStatusFilters.keyword" :prefix-icon="Search" clearable placeholder="搜索状态值或展示内容" />
            <el-select v-model="spinStatusFilters.sourceId" placeholder="全部盘口">
              <el-option label="全部盘口" value="" />
              <el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" />
            </el-select>
            <el-segmented v-model="spinStatusFilters.state" :options="[
              { label: '有效', value: 'active' },
              { label: '停用', value: 'inactive' },
              { label: '全部', value: 'all' },
            ]" />
          </div>

          <el-table :data="pagedSpinStatuses" stripe>
            <el-table-column label="状态值" width="180"><template #default="{ row }"><el-tag effect="plain">{{ row.entryCode }}</el-tag></template></el-table-column>
            <el-table-column label="展示内容" min-width="260"><template #default="{ row }"><strong class="entry-label">{{ row.entryLabel }}</strong></template></el-table-column>
            <el-table-column label="来源盘口" min-width="190"><template #default="{ row }"><div class="source-cell"><strong>{{ row.sourceDisplayName }}</strong><span>{{ row.sourceId }}</span></div></template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.active ? 'success' : 'info'">{{ row.active ? '有效' : '停用' }}</el-tag></template></el-table-column>
            <el-table-column label="最近确认" min-width="190"><template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template></el-table-column>
            <template #empty><el-empty description="暂无转盘审核状态字典" /></template>
          </el-table>
          <div v-if="filteredSpinStatuses.length" class="pagination-row">
            <span>共 {{ filteredSpinStatuses.length }} 条</span>
            <el-pagination v-model:current-page="spinStatusPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="filteredSpinStatuses.length" layout="sizes, prev, pager, next" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="渠道来源" name="user-source-channels">
          <el-alert
            title="渠道来源字典对应用户详情的 channel_id"
            description="点击“覆盖刷新”后，系统会先读取并校验远端完整 channel_id 字典，再在同一事务中清空所选盘口的旧字典并写入新字典。远端失败、空字典或格式异常时，旧字典不会被改动。"
            type="warning"
            show-icon
            :closable="false"
          />

          <div class="dictionary-tab-heading">
            <div>
              <h2>渠道来源映射</h2>
              <p>转盘订单会按 UID 查询用户详情中的 <code>channel_id</code>，再用本字典展示为渠道来源名称。</p>
            </div>
            <div class="dictionary-actions">
              <el-tooltip content="请先在下方选择一个盘口。" :disabled="Boolean(userSourceChannelFilters.sourceId)" placement="top">
                <span>
                  <el-button
                    :icon="RefreshRight"
                    :loading="syncingUserSourceChannels"
                    :disabled="!userSourceChannelFilters.sourceId"
                    @click="syncUserSourceChannelDictionary"
                  >
                    覆盖刷新
                  </el-button>
                </span>
              </el-tooltip>
              <div class="field-binding"><span>用户详情字段</span><code>channel_id</code></div>
            </div>
          </div>

          <el-alert
            v-if="userSourceChannelSyncFeedback"
            class="sync-feedback"
            :title="userSourceChannelSyncFeedback.title"
            :description="userSourceChannelSyncFeedback.description"
            :type="userSourceChannelSyncFeedback.type"
            show-icon
            :closable="false"
          />

          <div class="summary-grid">
            <article><span>有效条目</span><strong>{{ activeUserSourceChannelCount }}</strong></article>
            <article><span>已同步盘口</span><strong>{{ userSourceChannelSourceCount }}</strong></article>
            <article><span>最近覆盖刷新</span><strong>{{ latestAt(userSourceChannels) ? formatDateTime(latestAt(userSourceChannels)) : '尚未同步' }}</strong></article>
          </div>

          <div class="dictionary-toolbar">
            <el-input v-model="userSourceChannelFilters.keyword" :prefix-icon="Search" clearable placeholder="搜索渠道名称或 channel_id" />
            <el-select v-model="userSourceChannelFilters.sourceId" placeholder="选择盘口后可覆盖刷新">
              <el-option label="全部盘口" value="" />
              <el-option v-for="source in sources" :key="source.sourceId" :label="source.displayName" :value="source.sourceId" />
            </el-select>
            <el-segmented v-model="userSourceChannelFilters.state" :options="[
              { label: '有效', value: 'active' },
              { label: '停用', value: 'inactive' },
              { label: '全部', value: 'all' },
            ]" />
          </div>

          <el-table :data="pagedUserSourceChannels" stripe>
            <el-table-column label="渠道来源名称" min-width="280"><template #default="{ row }"><strong class="entry-label">{{ row.entryLabel }}</strong></template></el-table-column>
            <el-table-column label="channel_id" min-width="210"><template #default="{ row }"><el-tag effect="plain">{{ row.entryCode }}</el-tag></template></el-table-column>
            <el-table-column label="来源盘口" min-width="190"><template #default="{ row }"><div class="source-cell"><strong>{{ row.sourceDisplayName }}</strong><span>{{ row.sourceId }}</span></div></template></el-table-column>
            <el-table-column label="最近覆盖刷新" min-width="190"><template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template></el-table-column>
            <template #empty><el-empty description="暂无渠道来源字典"><span class="empty-help">选择盘口后点击“覆盖刷新”读取远端完整字典。</span></el-empty></template>
          </el-table>
          <div v-if="filteredUserSourceChannels.length" class="pagination-row">
            <span>共 {{ filteredUserSourceChannels.length }} 条</span>
            <el-pagination v-model:current-page="userSourceChannelPage" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="filteredUserSourceChannels.length" layout="sizes, prev, pager, next" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? `编辑${editableStatusName}` : `新增${editableStatusName}`"
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
            :placeholder="statusExample"
          />
        </el-form-item>
        <el-form-item label="展示内容" required>
          <el-input v-model="statusForm.entryLabel" maxlength="255" :placeholder="statusLabelExample" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="statusForm.active" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveStatus">
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

.field-binding {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  border: 1px solid #b9ded8;
  border-radius: 9px;
  background: #effaf8;
  color: var(--ink-muted);
  font-size: 12px;
  white-space: nowrap;
}

.field-binding code {
  color: #087f72;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  font-weight: 700;
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
