<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Plus, Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, TableV2FixedDir } from 'element-plus'
import type { Columns } from 'element-plus'
import { api } from '@/api/client'
import { configurationPublicationLabel, publicationLabel, acquisitionLabel, acceptsManualPublication, configurationVerificationSummary, type PublicationVerification } from './publicationStatus'
import type {
  RedemptionBatchDetail,
  RedemptionCampaign,
  RedemptionCodeGroupInput,
  RedemptionDuplicateConflict,
  RedemptionDuplicateMarket,
  RedemptionDuplicateReview,
  RedemptionCodeIssue,
  RedemptionRecoveryView,
  RedemptionRewardPolicyView,
  RedemptionCodeType,
  RedemptionCodeNaming,
  RedemptionRemoteConnection,
  RedemptionRemoteCreationOptions,
  RedemptionRemoteTag,
  RedemptionRewardTierPreset,
} from '@/api/types'
import { saveDownloadedFile } from '@/utils/download'
import RedemptionTaskDeletionDialog from './RedemptionTaskDeletionDialog.vue'
import { useSessionStore } from '@/stores/session'

interface TierProfile {
  name: string
  minDepositAmount: number
  bonusAmount: number
  bonusMaxAmount: number
}

interface SevenDayTierProfile extends TierProfile {
  /** The known RajWin ID keeps the dialog usable before its tag directory is loaded. */
  fallbackLabelId: number
  maxDepositAmount?: number
}

interface CodeGroupTierDraft {
  userType: CodeGroupUserType
  displayName: string
  minDepositAmount: number
  bonusAmount: number
  bonusMaxAmount: number
  labelIds: Array<string | number>
}

type CodeGroupUserType = 'ALL_USERS' | 'LABEL_USERS'
type ValidityMode = 'CLAIM_DAY' | 'CUSTOM_OFFSETS'

interface CodeGroupForm {
  dateRange: [string, string]
  validityMode: ValidityMode
  validFromDayOffset: number
  validToDayOffset: number
  remoteMarketIds: Array<string | number>
  /** The selected market currently being configured in the editor. */
  remoteMarketId?: string | number
  redemptionType: RedemptionCodeType
  specialCodeNaming: RedemptionCodeNaming
  tiers: CodeGroupTierDraft[]
  remoteOptions: RedemptionRemoteCreationOptions
}

interface MarketTierDraft {
  tiers: CodeGroupTierDraft[]
  remoteTags: RedemptionRemoteTag[]
  remoteTagsLoaded: boolean
  rewardTierPreset?: RedemptionRewardTierPreset
}

interface CodeGroupRow {
  campaign: RedemptionCampaign
  detail: RedemptionBatchDetail
}

/** One operator-facing task.  A multi-market selection keeps per-market batches underneath it. */
interface CodeGroupTask {
  id: string
  taskId: string | number
  exportGroupKey?: string
  members: CodeGroupRow[]
}

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const taskTable = ref<{ scrollToTop: (top: number) => void }>()
const taskTableScroll = ref(Math.max(0, Number(route.query.tableScroll) || 0))
const loading = ref(false)
const codeGroupLoadError = ref('')
const working = ref(false)
const exportingId = ref<string | number>()
const exportingGroupKey = ref<string>()
const remoteConnectionsLoading = ref(false)
const remoteTagsLoading = ref(false)
const remoteTagsLoaded = ref(false)
const marketConfigurationError = ref('')
const rewardTierPresetLoading = ref(false)
const rewardTierPresetSaving = ref(false)
const codeGroupDialogVisible = ref(false)
const publishDialogVisible = ref(false)
const detailMode = computed(() => route.name === 'redemption-task-detail')
const narrowTaskDetail = ref(false)
function resizeTaskDetail() { narrowTaskDetail.value = window.innerWidth <= 900 }
const detailSearch = ref('')
const detailDate = ref('')
const detailStatus = ref('')
const detailPane = ref('configurations')
const selectedDeletionIds = ref<Array<string | number>>([])
const deletionPanelKey = ref(0)
const advancedOptionsOpen = ref<string[]>([])
const publishOptionsOpen = ref<string[]>([])
const campaigns = ref<RedemptionCampaign[]>([])
const codeGroups = ref<CodeGroupRow[]>([])
const codeGroupTaskCurrentPage = ref(Math.max(1, Number(route.query.page) || 1))
const codeGroupTaskPageSize = ref([10, 20, 50, 100].includes(Number(route.query.pageSize)) ? Number(route.query.pageSize) : 20)
const selectedTaskMembers = ref<CodeGroupRow[]>([])
const activeTaskBatchId = ref('')
const remoteConnections = ref<RedemptionRemoteConnection[]>([])
const remoteTags = ref<RedemptionRemoteTag[]>([])
const rewardTierPreset = ref<RedemptionRewardTierPreset>()
const marketTierDrafts = ref<Record<string, MarketTierDraft>>({})
const activeMarketTab = ref('')
const selectedGroup = ref<CodeGroupRow>()
const checkRemoteDuplicates = ref(false)
const checkingDuplicates = ref(false)
const duplicateCheckProgress = ref('')
const duplicateConflicts = ref<RedemptionDuplicateConflict[]>([])
const duplicateDialogVisible = ref(false)
const duplicateReviewAcknowledged = ref(false)
const duplicateCreationReview = ref<RedemptionDuplicateReview>()
// The server owns durable task approval; this cache only avoids repeating a review in this page.
const taskDuplicateReviews = new Map<string, RedemptionDuplicateReview>()
let duplicateReviewResolve: ((confirmed: boolean) => void) | undefined


const taskDeletionTarget = ref<{ taskId: string | number; taskNumber: string; issueIds?: Array<string | number>; startNew?: boolean }>()
const selectedTaskId = computed(() => selectedTaskMembers.value[0]?.detail.batch.taskId ?? selectedTaskMembers.value[0]?.detail.batch.id)
const selectedTaskDisplayId = computed(() => selectedTaskMembers.value[0]?.detail.batch.taskNumber || String(selectedTaskId.value ?? '—'))
const publishTarget = ref<CodeGroupRow | CodeGroupTask>()
const publishing = ref(false)
const publicationChecks = ref<Record<string, PublicationVerification>>({})
const publicationCheckErrors = ref<Record<string, string>>({})
const verifyingPublicationIds = ref(new Set<string>())
const publicationRequests = new Map<string, Promise<PublicationVerification | undefined>>()
type DownloadChoice = 'publish' | 'manual' | 'direct'
const downloadDecision = ref<{ market: string; state: string; canPublish: boolean; canRegister: boolean }>()
const downloadingTask = ref(false)
let resolveDownloadChoice: ((choice?: DownloadChoice) => void) | undefined
const verificationDialogVisible = ref(false)
const verificationTarget = ref<CodeGroupRow>()
const resolvingMissingBatchId = ref<string | number>()
const continuingCreationBatchId = ref<string | number>()
function missingConfigurations(row: CodeGroupRow) {
  const check = publicationCheck(row)
  return (check?.configurations || []).filter(item => item.state === 'MISSING').map((item) => ({
    ...item,
    issue: row.detail.issues.find(issue => issue.remoteConfigurationId === item.configurationId),
  }))
}
function showPublicationResult(row: CodeGroupRow) {
  verificationTarget.value = row
  verificationDialogVisible.value = true
}
async function inspectPublication(row: CodeGroupRow) {
  try {
    if (row.detail.overview) row = await loadFullGroup(row)
    showPublicationResult(row)
    await verifyRemotePublication(row, true)
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '读取任务明细失败') }
}
function publicationCheck(row: CodeGroupRow) {
  const check = publicationChecks.value[String(row.detail.batch.id)]
  return check?.remotePublishTaskId === row.detail.batch.remotePublishTaskId ? check : undefined
}
async function verifyRemotePublication(row: CodeGroupRow, silent = false): Promise<PublicationVerification | undefined> {
  const key = String(row.detail.batch.id)
  const requestKey = `${key}:${row.detail.batch.remotePublishTaskId}`
  const existing = publicationRequests.get(requestKey)
  if (existing) return existing
  const request = (async () => {
    verifyingPublicationIds.value.add(key)
    delete publicationCheckErrors.value[key]
    try {
      const check = await api.redemption.verifyRemotePublication(row.detail.batch.id)
      publicationChecks.value[key] = check
      if (!silent) ElMessage.info(`${publicationLabel(check)}；${acquisitionLabel(isSuccess(row), row.detail.issues.some(issue => Boolean(issue.remoteError || issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status))), check)}`)
      return check
    } catch (error) {
      delete publicationChecks.value[key]
      const message = error instanceof Error ? error.message : '远端核验失败，请稍后重试'
      publicationCheckErrors.value[key] = message
      if (!silent) ElMessage.error(message)
      return undefined
    } finally { verifyingPublicationIds.value.delete(key); publicationRequests.delete(requestKey) }
  })()
  publicationRequests.set(requestKey, request)
  return request
}
function codeAcquisitionStatus(row: CodeGroupRow) {
  return acquisitionLabel(isSuccess(row), row.detail.issues.some(issue => Boolean(issue.remoteError || issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status))), publicationCheck(row))
}
function taskAcquisitionStatus(task: CodeGroupTask) {
  const completed = task.members.filter(isSuccess).length
  if (isMultiMarketTask(task) && completed > 0 && completed < task.members.length) return `${completed}/${task.members.length} 个盘口兑换码已入库`
  return [...new Set(task.members.filter(row => ['PUBLISHED', 'COMPLETED'].includes(row.detail.batch.status)).map(codeAcquisitionStatus))].join(' / ')
}
async function verifyPendingPublications() {
  for (const row of codeGroups.value.filter(row => row.detail.batch.status === 'PUBLISHED')) {
    const last = publicationCheck(row)
    if (last && Date.now() - Date.parse(last.checkedAt) < 60_000) continue
    await verifyRemotePublication(row, true)
  }
}
const cancellingPublishId = ref<string | number>()
const recoveringPublishId = ref<string | number>()
const retryingIssueId = ref<string | number>()
const retryingSelectedFailedTasks = ref(false)
const selectedFailedIssueIds = ref<Array<string | number>>([])
const failedIssueTable = ref<{ clearSelection: () => void }>()
const publishForm = ref<{ mode: 'IMMEDIATE' | 'SCHEDULED'; scheduledTime?: string; fallbackToScheduled: boolean }>({ mode: 'IMMEDIATE', fallbackToScheduled: true })
const processingGroupIds = ref(new Set<string>())
const indiaNow = ref('')
let indiaClock: number | undefined

const fallbackTags: RedemptionRemoteTag[] = [
  { id: 901091, name: '(901091)近7天充值总金额100-499' },
  { id: 901092, name: '(901092)近7天充值总金额500-1999' },
  { id: 901093, name: '(901093)近7天充值总金额2000-4999' },
  { id: 901095, name: '(901095)近7天充值总金额5000-9999' },
  { id: 901094, name: '(901094)近7天充值总金额10000以上' },
]

const sevenDayTierProfiles: SevenDayTierProfile[] = [
  { fallbackLabelId: 901091, name: '近 7 天充值总金额 100–499', minDepositAmount: 100, maxDepositAmount: 499, bonusAmount: 1, bonusMaxAmount: 3 },
  { fallbackLabelId: 901092, name: '近 7 天充值总金额 500–1,999', minDepositAmount: 500, maxDepositAmount: 1999, bonusAmount: 5, bonusMaxAmount: 7 },
  { fallbackLabelId: 901093, name: '近 7 天充值总金额 2,000–4,999', minDepositAmount: 2000, maxDepositAmount: 4999, bonusAmount: 9, bonusMaxAmount: 11 },
  { fallbackLabelId: 901095, name: '近 7 天充值总金额 5,000–9,999', minDepositAmount: 5000, maxDepositAmount: 9999, bonusAmount: 17, bonusMaxAmount: 27 },
  { fallbackLabelId: 901094, name: '近 7 天充值总金额 10,000 以上', minDepositAmount: 10000, bonusAmount: 37, bonusMaxAmount: 57 },
]

const previousDayTierProfiles: Array<TierProfile & { maxDepositAmount?: number }> = [
  { name: '日充值 0（所有用户）', minDepositAmount: 0, bonusAmount: 1, bonusMaxAmount: 3 },
  { name: '日充值 100–199', minDepositAmount: 100, maxDepositAmount: 199, bonusAmount: 3, bonusMaxAmount: 5 },
  { name: '日充值 200–999', minDepositAmount: 200, maxDepositAmount: 999, bonusAmount: 7, bonusMaxAmount: 9 },
  { name: '日充值 1,000–2,999', minDepositAmount: 1000, maxDepositAmount: 2999, bonusAmount: 13, bonusMaxAmount: 17 },
  { name: '日充值 3,000–9,999', minDepositAmount: 3000, maxDepositAmount: 9999, bonusAmount: 27, bonusMaxAmount: 37 },
  { name: '日充值 10,000+', minDepositAmount: 10000, bonusAmount: 57, bonusMaxAmount: 77 },
]

const form = ref<CodeGroupForm>(newCodeGroupForm())
const validityOffsets = computed<[number, number]>(() => form.value.validityMode === 'CLAIM_DAY'
  ? [0, 0]
  : [form.value.validFromDayOffset, form.value.validToDayOffset])
const validityRuleSummary = computed(() => {
  const [fromOffset, toOffset] = validityOffsets.value
  if (fromOffset === 0 && toOffset === 0) return '跟随开始兑换日，当天有效'
  const offsetLabel = (value: number) => value === 0 ? '当天' : `第 ${value + 1} 天（+${value} 天）`
  return `相对开始兑换日：${offsetLabel(fromOffset)}至${offsetLabel(toOffset)}`
})
const validityPreview = computed(() => {
  const [claimFrom, claimTo] = form.value.dateRange || []
  if (!claimFrom || !claimTo) return []
  const [fromOffset, toOffset] = validityOffsets.value
  const preview = (claimDate: string) => ({
    claimDate,
    validFrom: shiftDate(claimDate, fromOffset),
    validTo: shiftDate(claimDate, toOffset),
  })
  return claimFrom === claimTo ? [preview(claimFrom)] : [preview(claimFrom), preview(claimTo)]
})
const canGenerate = computed(() => hasPermission('REDEMPTION_MANAGE') && hasPermission('REDEMPTION_GENERATE'))
const canExport = computed(() => hasPermission('REDEMPTION_EXPORT'))
const codeGroupTasks = computed<CodeGroupTask[]>(() => {
  const grouped = new Map<string, CodeGroupTask>()
  for (const member of codeGroups.value) {
    const exportGroupKey = member.detail.batch.exportGroupKey
    const taskId = member.detail.batch.taskId ?? member.detail.batch.id
    const id = `task:${taskId}`
    const task = grouped.get(id) || { id, taskId, exportGroupKey, members: [] }
    task.members.push(member)
    grouped.set(id, task)
  }
  return [...grouped.values()]
    .map((task) => ({ ...task, members: [...task.members].sort((left, right) =>
      String(left.detail.batch.createdAt || '').localeCompare(String(right.detail.batch.createdAt || '')),
    ) }))
    .sort((left, right) => String(right.members.at(-1)?.detail.batch.createdAt || '')
      .localeCompare(String(left.members.at(-1)?.detail.batch.createdAt || '')))
})
const paginatedCodeGroupTasks = computed(() => {
  const start = (codeGroupTaskCurrentPage.value - 1) * codeGroupTaskPageSize.value
  return codeGroupTasks.value.slice(start, start + codeGroupTaskPageSize.value)
})
const codeGroupTaskColumns: Columns<CodeGroupTask> = [
  { key: 'taskId', dataKey: 'taskId', title: '任务编号', width: 142, align: 'center', fixed: TableV2FixedDir.LEFT },
  { key: 'operator', dataKey: 'id', title: '操作人', width: 120 },
  { key: 'name', dataKey: 'id', title: '兑换码组', width: 210 },
  { key: 'claimDate', dataKey: 'id', title: '开始兑换日期', width: 175 },
  { key: 'account', dataKey: 'id', title: '远端账号', width: 135 },
  { key: 'market', dataKey: 'id', title: '盘口', width: 150 },
  { key: 'status', dataKey: 'id', title: '发布 / 兑换码状态', width: 200, align: 'center' },
  { key: 'labels', dataKey: 'id', title: '用户类型 / 标签 ID', width: 240 },
  { key: 'redemptionType', dataKey: 'id', title: '兑换码类型', width: 128 },
  { key: 'singleKeyLimit', dataKey: 'id', title: '单兑换码领取次数', width: 160, align: 'center' },
  { key: 'tiers', dataKey: 'id', title: '充值档位 · 兑换金额', width: 250 },
  { key: 'progress', dataKey: 'id', title: '生成进度', width: 180 },
  { key: 'publishedAt', dataKey: 'id', title: '发布时间', width: 205 },
  { key: 'remark', dataKey: 'id', title: '备注', width: 250 },
  { key: 'createdAt', dataKey: 'id', title: '创建时间', width: 170 },
  { key: 'actions', dataKey: 'id', title: '操作', width: 228, fixed: TableV2FixedDir.RIGHT },
]

function changeCodeGroupTaskPageSize(pageSize: number) {
  codeGroupTaskPageSize.value = pageSize
  codeGroupTaskCurrentPage.value = 1
}

function openClaimStatistics(task: CodeGroupTask) {
  router.push({ name: 'redemption-claim-statistics', params: { taskId: task.taskId }, query: {
    returnPage: codeGroupTaskCurrentPage.value, returnPageSize: codeGroupTaskPageSize.value,
    returnTableScroll: taskTableScroll.value,
  } })
}

function trackTaskScroll({ scrollTop }: { scrollTop: number }) { taskTableScroll.value = scrollTop }

watch([() => codeGroupTasks.value.length, codeGroupTaskPageSize], () => {
  const lastPage = Math.max(1, Math.ceil(codeGroupTasks.value.length / codeGroupTaskPageSize.value))
  if (codeGroupTaskCurrentPage.value > lastPage) codeGroupTaskCurrentPage.value = lastPage
})
const failedRemoteCreationCount = computed(() => selectedGroup.value ? countIssues(failedRemoteCreationIssues(selectedGroup.value)) : 0)
const selectedFailedIssueCount = computed(() => selectedFailedRemoteCreations().length)
const tagOptions = computed(() => {
  const tags = new Map<string, RedemptionRemoteTag>()
  // A tag directory belongs to the selected market.  Do not briefly show the
  // RajWin fallback labels while another market is being loaded.
  const source = remoteTagsLoaded.value
    ? remoteTags.value
    : rewardTierPreset.value?.tagSnapshot?.length
      ? rewardTierPreset.value.tagSnapshot
      : isRajWinMarket.value ? fallbackTags : []
  for (const tag of source) tags.set(String(tag.id), tag)
  return [...tags.values()]
})
const previousDayTagOptions = computed(() => {
  const tags = new Map<string, RedemptionRemoteTag>()
  const source = remoteTagsLoaded.value ? remoteTags.value : rewardTierPreset.value?.tagSnapshot || []
  for (const tag of source) tags.set(String(tag.id), tag)
  return [...tags.values()]
})
const availableRemoteMarkets = computed(() => {
  const markets = new Map<string, { id: string | number; code?: string; name?: string }>()
  for (const connection of remoteConnections.value) {
    if (connection.marketId === undefined || connection.marketId === null) continue
    const key = String(connection.marketId)
    if (!markets.has(key)) markets.set(key, { id: connection.marketId, code: connection.marketCode, name: connection.marketName })
  }
  return [...markets.values()]
})
function marketKey(marketId?: string | number) { return marketId === undefined || marketId === null ? '' : String(marketId) }
function remoteConnectionForMarket(marketId?: string | number) {
  return remoteConnections.value.find((connection) => String(connection.marketId) === String(marketId))
}
function marketLabel(marketId?: string | number) {
  const market = availableRemoteMarkets.value.find((item) => String(item.id) === String(marketId))
  return [market?.code, market?.name].filter(Boolean).join(' · ') || '未命名盘口'
}
function marketIdentities(marketId?: string | number) {
  const market = availableRemoteMarkets.value.find((item) => String(item.id) === String(marketId))
  const connection = remoteConnectionForMarket(marketId)
  return [market?.code, market?.name, connection?.marketCode, connection?.marketName]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.replace(/[^a-z0-9]/gi, '').toLowerCase())
}
const selectedRemoteConnection = computed(() => remoteConnectionForMarket(form.value.remoteMarketId))
const selectedMarketIdentities = computed(() => marketIdentities(form.value.remoteMarketId))
const isRajWinMarket = computed(() => selectedMarketIdentities.value.some((value) => value === 'rajwin'))
const usesSpecialCode = computed(() => form.value.redemptionType === 'SEVEN_DAY_DEPOSIT'
  || form.value.redemptionType === 'PREVIOUS_DAY_DEPOSIT')
const codesPerGroup = computed(() => usesSpecialCode.value ? 1 : form.value.remoteOptions.keyNumber)

function hasPermission(permission: string) {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes(permission) || user?.roles.includes('SUPER_ADMIN'))
}

function todayIso() {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

function shiftDate(date: string, amount: number) {
  const point = new Date(`${date}T12:00:00`)
  point.setDate(point.getDate() + amount)
  return point.toISOString().slice(0, 10)
}

function futureRange(days: number): [string, string] {
  const from = shiftDate(todayIso(), 1)
  return [from, shiftDate(from, days - 1)]
}

function defaultRemoteOptions(): RedemptionRemoteCreationOptions {
  return {
    publishEnvironment: 'test', flowTimes: 5, creationIntervalSeconds: 5, keyNumber: 1, singleUserLimit: 1, singleKeyLimit: 3000,
    requireBindBankCard: false, requireBindPhone: true, checkUuid: true, uuidRewardLimit: 1,
    checkLoginIp: true, loginIpRewardLimit: 1, checkRegisterIp: true, registerIpRewardLimit: 1,
  }
}

function draftTier(labelId?: string | number): CodeGroupTierDraft {
  const tag = labelId === undefined ? undefined : tagOptions.value.find((item) => String(item.id) === String(labelId))
  const profile = tag ? sevenDayTierProfileForTag(tag) : sevenDayTierProfiles.find((item) => item.fallbackLabelId === Number(labelId))
  const fallback = profile || sevenDayTierProfiles[0]
  return {
    userType: 'LABEL_USERS',
    displayName: tag?.name.replace(/^\(\d+\)/, '').trim() || fallback.name,
    minDepositAmount: profile?.minDepositAmount ?? minimumDepositFromTag(tag?.name) ?? fallback.minDepositAmount,
    bonusAmount: profile?.bonusAmount ?? fallback.bonusAmount,
    bonusMaxAmount: profile?.bonusMaxAmount ?? fallback.bonusMaxAmount,
    labelIds: [labelId ?? fallback.fallbackLabelId],
  }
}

function previousDayTiers(): CodeGroupTierDraft[] {
  return previousDayTierProfiles.map((tier) => {
    const allUsers = tier.minDepositAmount === 0
    const matches = previousDayTagOptions.value.filter((tag) => {
      if (!/日充值|每日充值|recharge\s*today|daily\s*(?:recharge|deposit)/i.test(tag.name)) return false
      const range = tagDepositRange(tag.name.replace(/^\s*\(\d+\)\s*/, ''))
      return range?.min === tier.minDepositAmount && range?.max === tier.maxDepositAmount
    })
    // Missing or ambiguous labels must be selected explicitly, never borrowed from another market.
    const tag = !allUsers && matches.length === 1 ? matches[0] : undefined
    return {
      userType: allUsers ? 'ALL_USERS' : 'LABEL_USERS',
      displayName: tag?.name.replace(/^\(\d+\)/, '').trim() || tier.name,
      minDepositAmount: tier.minDepositAmount,
      bonusAmount: tier.bonusAmount,
      bonusMaxAmount: tier.bonusMaxAmount,
      labelIds: tag ? [tag.id] : [],
    }
  })
}

function isPreviousDayDeposit() { return form.value.redemptionType === 'PREVIOUS_DAY_DEPOSIT' }
function isAgentCodeGroup() { return form.value.redemptionType === 'AGENT' }
function isAllUsersTier(tier: CodeGroupTierDraft) { return tier.userType === 'ALL_USERS' }
function redemptionTypeLabel(type: RedemptionCodeType) {
  if (type === 'AGENT') return '代理'
  return type === 'PREVIOUS_DAY_DEPOSIT' ? '日充值' : '近 7 天充值'
}

const specialCodeExample = computed(() => {
  const date = form.value.dateRange[0].replaceAll('-', '').slice(4)
  const prefix = isPreviousDayDeposit() ? 'raj' : 'raj7days'
  return `${date}${prefix}${form.value.specialCodeNaming === 'TEN_K' ? '10K' : '10000'}`
})

function newCodeGroupForm(): CodeGroupForm {
  const range = futureRange(7)
  return {
    dateRange: range,
    validityMode: 'CLAIM_DAY',
    validFromDayOffset: 0,
    validToDayOffset: 0,
    remoteMarketIds: [],
    redemptionType: 'SEVEN_DAY_DEPOSIT',
    specialCodeNaming: 'TEN_K',
    // The selected market supplies its own standard five tiers after the dialog opens.
    tiers: [],
    remoteOptions: defaultRemoteOptions(),
  }
}

function cloneTiers(tiers: CodeGroupTierDraft[]) {
  return tiers.map((tier) => ({ ...tier, labelIds: [...tier.labelIds] }))
}

function cloneTags(tags: RedemptionRemoteTag[]) {
  return tags.map((tag) => ({ ...tag }))
}

function cloneRewardTierPreset(preset?: RedemptionRewardTierPreset) {
  return preset && {
    ...preset,
    tiers: preset.tiers.map((tier) => ({ ...tier, labelIds: [...tier.labelIds] })),
    tagSnapshot: cloneTags(preset.tagSnapshot),
  }
}

function saveActiveMarketDraft() {
  const key = marketKey(form.value.remoteMarketId)
  if (!key) return
  marketTierDrafts.value[key] = {
    tiers: cloneTiers(form.value.tiers),
    remoteTags: cloneTags(remoteTags.value),
    remoteTagsLoaded: remoteTagsLoaded.value,
    rewardTierPreset: cloneRewardTierPreset(rewardTierPreset.value),
  }
}

function restoreMarketDraft(marketId: string | number) {
  const draft = marketTierDrafts.value[marketKey(marketId)]
  if (!draft) return false
  form.value.tiers = cloneTiers(draft.tiers)
  remoteTags.value = cloneTags(draft.remoteTags)
  remoteTagsLoaded.value = draft.remoteTagsLoaded
  rewardTierPreset.value = cloneRewardTierPreset(draft.rewardTierPreset)
  return true
}

async function activateMarket(marketId?: string | number) {
  if (marketId === undefined || marketId === null) return
  if (String(form.value.remoteMarketId) === String(marketId)) return
  ++marketConfigurationRequest
  if (String(form.value.remoteMarketId) !== String(marketId)) saveActiveMarketDraft()
  form.value.remoteMarketId = marketId
  activeMarketTab.value = marketKey(marketId)
  marketConfigurationError.value = ''
  if (restoreMarketDraft(marketId)) {
    remoteTagsLoading.value = false
    rewardTierPresetLoading.value = false
    if (!remoteTagsLoaded.value || !rewardTierPreset.value) await loadMarketTierConfiguration()
    return
  }
  form.value.tiers = []
  remoteTags.value = []
  remoteTagsLoaded.value = false
  rewardTierPreset.value = undefined
  await loadMarketTierConfiguration()
}

async function ensureSelectedMarketDrafts() {
  const currentMarketId = form.value.remoteMarketId
  for (const marketId of form.value.remoteMarketIds) await activateMarket(marketId)
  if (currentMarketId !== undefined && form.value.remoteMarketIds.some((marketId) => String(marketId) === String(currentMarketId))) {
    await activateMarket(currentMarketId)
  }
  saveActiveMarketDraft()
}

function generatedGroupName(dateRange: [string, string], marketId?: string | number) {
  return `批量兑换码 ${dateRange[0].replaceAll('-', '')} · ${marketLabel(marketId)}`
}

function generatedGroupDescription(claimDateFrom: string, claimDateTo: string) {
  return `批量生成兑换码组（领取日期：${claimDateFrom} 至 ${claimDateTo}）`
}

function changeValidityMode(mode: ValidityMode) {
  if (mode !== 'CLAIM_DAY') return
  form.value.validFromDayOffset = 0
  form.value.validToDayOffset = 0
}

function keepValidityOffsetsOrdered() {
  if (form.value.validToDayOffset < form.value.validFromDayOffset) {
    form.value.validToDayOffset = form.value.validFromDayOffset
  }
}

function batchValidityRuleLabel(batch: RedemptionBatchDetail['batch']) {
  const fromOffset = batch.validFromDayOffset ?? 0
  const toOffset = batch.validToDayOffset ?? 0
  if (fromOffset === 0 && toOffset === 0) return '跟随开始兑换日（当天）'
  return `开始兑换日 +${fromOffset} 天 至 +${toOffset} 天`
}

function issueValidityLabel(batch: RedemptionBatchDetail['batch'], claimDate: string) {
  const from = shiftDate(claimDate, batch.validFromDayOffset ?? 0)
  const to = shiftDate(claimDate, batch.validToDayOffset ?? 0)
  return `${formatDate(from)} 00:00:00 至 ${formatDate(to)} 23:59:59`
}

function formatDate(value?: string) { return value ? value.replaceAll('-', '/') : '—' }
function formatDateTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}
function formatIndiaDateTime(value?: string) {
  return value ? value.replace('T', ' ') : '—'
}
function indiaNowText(at: Date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(at).reduce<Record<string, string>>((result, part) => {
    if (part.type !== 'literal') result[part.type] = part.value
    return result
  }, {})
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}
function formatAmount(value?: string | number) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 }).format(numeric) : '—'
}
function groupKey(batchId: string | number) { return String(batchId) }
function expectedTaskCount() {
  const [from, to] = form.value.dateRange || []
  if (!from || !to || to < from) return 0
  const days = Math.round((new Date(`${to}T12:00:00`).getTime() - new Date(`${from}T12:00:00`).getTime()) / 86_400_000) + 1
  return form.value.remoteMarketIds.reduce<number>((total, marketId) => total + (marketTierDrafts.value[marketKey(marketId)]?.tiers.length || 0) * days, 0)
}
function isProcessing(row: CodeGroupRow) { return processingGroupIds.value.has(groupKey(row.detail.batch.id)) }
function needsCreationReconciliation(issue: RedemptionCodeIssue) { return issue.creationNeedsReconciliation === true }
function needsCreationRewardCheck(issue: RedemptionCodeIssue) {
  return ['REWARD_CHECK_REQUIRED', 'REWARD_CONFIRM_REQUIRED'].includes(issue.workflowStatus || '')
}
function creationRewardIssues(row: CodeGroupRow) { return row.detail.issues.filter(needsCreationRewardCheck) }
function creationRewardLabel(issues: RedemptionCodeIssue[]) {
  return issues.some(issue => issue.workflowStatus === 'REWARD_CONFIRM_REQUIRED') ? '待确认奖励修改' : '实际奖励待核验'
}
function countIssues(issues: RedemptionCodeIssue[]) {
  return issues.reduce((total, issue) => total + (issue.overviewCount ?? 1), 0)
}
function reconciliationIssues(row: CodeGroupRow) { return row.detail.issues.filter(needsCreationReconciliation) }
function awaitingReviewIssues(row: CodeGroupRow) { return row.detail.issues.filter(issue => issue.creationAwaitingRemoteReview === true) }
function creationHoldSummary(rows: CodeGroupRow[]) {
  const review = rows.reduce((total, row) => total + countIssues(awaitingReviewIssues(row)), 0)
  const uncertain = rows.reduce((total, row) => total + countIssues(reconciliationIssues(row)), 0) - review
  return [review ? `${review} 条待远端主管审核` : '', uncertain ? `${uncertain} 条结果待核对` : ''].filter(Boolean).join('，')
}
function issueRemark(issue: RedemptionCodeIssue) {
  if (issue.creationAwaitingRemoteReview) return issue.remoteError || '配置触发风控规则，待远端主管审核；请勿重复创建，审核通过后核对配置再登记和发布。'
  return needsCreationReconciliation(issue)
    ? '远端创建回执无效，尚不能确认配置是否创建；请先核对，暂停重试和发布。'
    : issue.remoteError
}
function isSuccess(row: CodeGroupRow) { return row.detail.batch.status === 'COMPLETED' && !creationRewardIssues(row).length }
function isRepairing(row: CodeGroupRow) { return row.detail.batch.status === 'CREATING' && Boolean(row.detail.batch.publishedAt) }
function pendingRemoteCreationIssues(row: CodeGroupRow) {
  return row.detail.issues.filter((issue) => issue.workflowStatus === 'PENDING_CREATION')
}
function hasRemoteCreationInProgress(row: CodeGroupRow) {
  return countIssues(reconciliationIssues(row)) > 0 || row.detail.issues.some((issue) => issue.workflowStatus === 'CREATING_REMOTE')
}
function isCreatingConfigurations(row: CodeGroupRow) {
  return row.detail.batch.status === 'CREATING' && isProcessing(row)
}
function confirmedConfigurationCount(row: CodeGroupRow) {
  return countIssues(row.detail.issues.filter(issue => !needsCreationReconciliation(issue) && ['CREATED', 'PUBLISHED', 'CODE_IMPORTED'].includes(issue.workflowStatus || '')))
}
function uncreatedIssues(row: CodeGroupRow) {
  return pendingRemoteCreationIssues(row).filter(issue => !issue.remoteConfigurationId && !issue.remoteReferenceId && !issue.overviewHasConfiguration && !issue.overviewHasReference)
}
function canContinuePendingCreation(row: CodeGroupRow) {
  return canGenerate.value && row.detail.batch.status === 'CREATING' && !row.detail.batch.publishedAt
    && !hasRemoteCreationInProgress(row) && countIssues(uncreatedIssues(row)) > 0
}
function failedIssues(row: CodeGroupRow) {
  return row.detail.issues.filter((issue) => !needsCreationReconciliation(issue) && (issue.workflowStatus === 'FAILED' || (issue.workflowStatus === 'PUBLISHED' && Boolean(issue.remoteError || issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status)))))
}
function failedRemoteCreationIssues(row: CodeGroupRow) {
  return row.detail.issues.filter(isFailedRemoteCreation)
}
function isFailedRemoteCreation(issue: RedemptionCodeIssue) {
  return !needsCreationReconciliation(issue) && issue.workflowStatus === 'FAILED'
}
function selectedFailedRemoteCreations() {
  const group = selectedGroup.value
  if (!group) return []
  const selectedIds = new Set(selectedFailedIssueIds.value.map(String))
  return failedRemoteCreationIssues(group).filter((issue) => selectedIds.has(String(issue.id)))
}
function updateSelectedFailedIssues(selection: RedemptionCodeIssue[]) {
  selectedFailedIssueIds.value = selection.filter(isFailedRemoteCreation).map((issue) => issue.id)
}
function clearFailedIssueSelection() {
  selectedFailedIssueIds.value = []
  selectedDeletionIds.value = []
  failedIssueTable.value?.clearSelection()
}
function groupRemark(row: CodeGroupRow) {
  const reasons = [publicationCheckErrors.value[String(row.detail.batch.id)], row.detail.batch.remotePublishNote, row.detail.batch.remotePublishError, ...row.detail.issues.map(issueRemark)]
    .filter((reason): reason is string => Boolean(reason))
  return [...new Set(reasons)].join('；') || '—'
}
function deletionHeld(issue: RedemptionCodeIssue) { return ['REMOTE_DELETE_PENDING', 'REMOTE_DELETED'].includes(issue.workflowStatus || '') }
function deletionLabel(issues: RedemptionCodeIssue[]) {
  return issues.some(issue => issue.workflowStatus === 'REMOTE_DELETE_PENDING') ? '删除结果待核对' : '远端配置已删除'
}
function groupStatus(row: CodeGroupRow) {
  if (row.detail.issues.some(deletionHeld)) return { text: deletionLabel(row.detail.issues), type: 'danger' as const }
  if (creationRewardIssues(row).length) return { text: creationRewardLabel(creationRewardIssues(row)), type: 'warning' as const }
  if (countIssues(awaitingReviewIssues(row))) return { text: '待远端主管审核', type: 'warning' as const }
  if (countIssues(reconciliationIssues(row))) return { text: '创建结果待核对', type: 'warning' as const }
  if (isSuccess(row)) return { text: publicationCheck(row) ? publicationLabel(publicationCheck(row)) : row.detail.batch.remotePublishTaskId ? '发布待核验' : '未关联发布任务', type: 'info' as const }
  if (isRepairing(row)) return { text: isCreatingConfigurations(row) ? '补齐缺失配置中' : hasRemoteCreationInProgress(row) ? '创建结果待确认' : repairReadyForPublish(row) ? '待发布' : '待补齐缺失配置', type: 'warning' as const }
  if (row.detail.batch.status === 'PUBLISHED') {
    const check = publicationCheck(row)
    return { text: publicationLabel(check), type: check?.publicationState === 'COMPLETED' ? 'success' as const : check?.publicationState === 'FAILED' ? 'danger' as const : 'info' as const }
  }
  if (row.detail.batch.remotePublishError) return { text: '发布不成功', type: 'danger' as const }
  if (countIssues(failedRemoteCreationIssues(row))) return { text: '配置创建失败', type: 'danger' as const }
  if (row.detail.batch.status === 'READY_TO_PUBLISH') return { text: '待发布', type: 'info' as const }
  if (isCreatingConfigurations(row)) return { text: '配置创建中', type: 'warning' as const }
  if (hasRemoteCreationInProgress(row)) return { text: '创建结果待确认', type: 'warning' as const }
  if (countIssues(pendingRemoteCreationIssues(row))) return { text: '待继续创建', type: 'warning' as const }
  return { text: '创建状态待核对', type: 'warning' as const }
}
function groupProgress(row: CodeGroupRow) {
  if (row.detail.issues.some(deletionHeld)) return `${deletionLabel(row.detail.issues)}；历史库存保留，任务不能继续发布或下载`
  const batch = row.detail.batch
  const review = countIssues(reconciliationIssues(row))
  if (review) return `${confirmedConfigurationCount(row)} / ${batch.expectedCodeCount} 条远端配置已创建，${countIssues(failedIssues(row))} 个失败，${creationHoldSummary([row])}`
  if (isSuccess(row)) return `${batch.importedCodeCount} / ${batch.plannedCodeCount} 个兑换码已入库`
  if (isRepairing(row)) return `${batch.importedCodeCount} / ${batch.plannedCodeCount} 个兑换码已入库；${groupStatus(row).text}`
  if (batch.remotePublishError) return `发布不成功：${batch.remotePublishError}`
  if (batch.status === 'PUBLISHED') return `${publicationLabel(publicationCheck(row))}；${codeAcquisitionStatus(row)}`
  if (countIssues(failedIssues(row))) return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建，${countIssues(failedIssues(row))} 个任务失败`
  if (batch.status === 'READY_TO_PUBLISH') return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建，待发布`
  const pending = countIssues(pendingRemoteCreationIssues(row))
  if (pending) return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建，${pending} 条待创建（尚未向远端发起）`
  return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建`
}

function taskPrimary(task: CodeGroupTask) { return task.members[0] }
function isMultiMarketTask(task: CodeGroupTask) { return task.members.length > 1 }
function taskName(task: CodeGroupTask) {
  const first = taskPrimary(task)
  if (!isMultiMarketTask(task)) return first?.campaign.name || '兑换码组'
  return `${first?.campaign.name?.replace(/\s*·\s*[^·]+$/, '') || '批量兑换码组'} · ${task.members.length} 个盘口`
}
function taskBatchNumbers(task: CodeGroupTask) {
  return task.members.map(subtaskDisplayId).join('、')
}
function taskSummary(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return `子任务 ${subtaskDisplayId(taskPrimary(task))}`
  return `子任务 ${taskBatchNumbers(task)} · 包含 ${task.members.length} 个盘口，按选择顺序串行执行`
}
function taskMemberLabel(member: CodeGroupRow) {
  return member.detail.batch.remoteMarketName || member.detail.batch.remoteMarketCode || subtaskDisplayId(member)
}
function subtaskDisplayId(member: CodeGroupRow | undefined) {
  if (!member) return '—'
  return member.detail.batch.subtaskNumber || `#${member.detail.batch.id}`
}
function taskMarkets(task: CodeGroupTask) {
  return task.members.map(remoteMarketLabel).filter((value, index, values) => values.indexOf(value) === index).join(' → ') || '—'
}
function taskAccounts(task: CodeGroupTask) {
  return task.members.map((member) => member.detail.batch.remoteConnectionName || '—')
    .filter((value, index, values) => values.indexOf(value) === index).join('、')
}
function taskOperator(task: CodeGroupTask) {
  return taskPrimary(task)?.detail.batch.operatorUsername || '—'
}
function taskLabels(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return labelsFor(taskPrimary(task))
  return task.members.map((member) => `${remoteMarketLabel(member)}：${labelsFor(member)}`).join('；')
}
function taskTiers(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return tiersFor(taskPrimary(task))
  return task.members.map((member) => `${remoteMarketLabel(member)}：${tiersFor(member)}`).join('；')
}
function singleKeyLimitLabel(row: CodeGroupRow) {
  const limit = row.detail.batch.remoteOptions?.singleKeyLimit
  return typeof limit === 'number' && Number.isFinite(limit) ? `${formatAmount(limit)} 次` : '—'
}
function taskSingleKeyLimit(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return singleKeyLimitLabel(taskPrimary(task))
  return task.members.map((member) => `${remoteMarketLabel(member)}：${singleKeyLimitLabel(member)}`).join('；')
}
function taskStatus(task: CodeGroupTask) {
  const deleted = task.members.flatMap(member => member.detail.issues).filter(deletionHeld)
  if (deleted.length) return { text: deletionLabel(deleted), type: 'danger' as const }
  const pendingRewards = task.members.flatMap(creationRewardIssues)
  if (pendingRewards.length) return { text: creationRewardLabel(pendingRewards), type: 'warning' as const }
  const recovery = task.members.flatMap(member => member.detail.issues).find(issue => issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status))?.recovery
  if (recovery) return { text: recoveryStatusLabel(recovery.status), type: 'warning' as const }

  if (task.members.some(member => countIssues(awaitingReviewIssues(member)) > 0)) return { text: '待远端主管审核', type: 'warning' as const }
  if (task.members.some(member => countIssues(reconciliationIssues(member)) > 0)) return { text: '创建结果待核对', type: 'warning' as const }
  if (!isMultiMarketTask(task)) return groupStatus(taskPrimary(task))
  // Creation problems must remain visible even when other markets have already published.
  if (task.members.some(member => countIssues(failedRemoteCreationIssues(member)) > 0)) return { text: '配置创建失败', type: 'danger' as const }
  if (task.members.some(isCreatingConfigurations)) return { text: task.members.some(isRepairing) ? '补齐缺失配置中' : '配置创建中', type: 'warning' as const }
  if (task.members.some(hasRemoteCreationInProgress)) return { text: '创建结果待确认', type: 'warning' as const }
  if (task.members.some(member => isRepairing(member) && !repairReadyForPublish(member))) return { text: '待补齐缺失配置', type: 'warning' as const }
  if (task.members.some(member => member.detail.batch.status === 'CREATING' && countIssues(pendingRemoteCreationIssues(member)) > 0)) return { text: '待继续创建', type: 'warning' as const }
  if (task.members.some(member => member.detail.batch.remotePublishError)) return { text: '发布不成功', type: 'danger' as const }
  if (task.members.every(isSuccess)) return { text: '生成成功', type: 'success' as const }
  if (task.members.every(member => publicationCheck(member)?.publicationState === 'COMPLETED')) return { text: '发布完成', type: 'success' as const }
  if (task.members.some(member => member.detail.batch.status === 'PUBLISHED' && ['FAILED', 'CANCELLED'].includes(publicationCheck(member)?.publicationState || ''))) return { text: '发布不成功', type: 'warning' as const }
  if (task.members.some(member => member.detail.batch.status === 'PUBLISHED')) return { text: '发布待核验', type: 'info' as const }
  if (task.members.every((member) => isSuccess(member) || member.detail.batch.status === 'READY_TO_PUBLISH' || repairReadyForPublish(member))) return { text: '待发布', type: 'info' as const }
  if (task.members.some(isScheduledPublish)) return { text: '发布中', type: 'warning' as const }
  return { text: '创建状态待核对', type: 'warning' as const }
}
function taskCreationSummary(task: CodeGroupTask) {
  return task.members.filter(member => member.detail.batch.status === 'CREATING').map(member => {
    const pending = countIssues(pendingRemoteCreationIssues(member))
    const failed = countIssues(failedRemoteCreationIssues(member))
    const uncertain = countIssues(member.detail.issues.filter(issue => issue.workflowStatus === 'CREATING_REMOTE'))
    const rewards = countIssues(creationRewardIssues(member))
    const states = [rewards ? `${rewards} 条奖励待核验或确认` : '', failed ? `${failed} 条创建失败` : '', creationHoldSummary([member]), uncertain && !isCreatingConfigurations(member) ? `${uncertain} 条请求待确认` : '', pending ? `${pending} 条待创建` : ''].filter(Boolean)
    if (isCreatingConfigurations(member)) states.unshift('正在创建')
    return states.length ? `${remoteMarketLabel(member)}：${states.join('，')}` : ''
  }).filter(Boolean).join('；')
}
function taskPendingCreationMembers(task: CodeGroupTask) {
  return task.members.filter(canContinuePendingCreation)
}
function taskPendingCreationCount(task: CodeGroupTask) {
  return taskPendingCreationMembers(task).reduce((total, member) => total + countIssues(uncreatedIssues(member)), 0)
}
function canOpenPendingCreationTask(task: CodeGroupTask) {
  return taskPendingCreationCount(task) > 0 && !working.value && continuingCreationBatchId.value === undefined
    && !task.members.some(member => isProcessing(member) || hasRemoteCreationInProgress(member))
}
async function openPendingCreationTask(task: CodeGroupTask) {
  if (!canOpenPendingCreationTask(task)) return
  const member = taskPendingCreationMembers(task)[0]
  if (member) await navigateTaskDetail(task.taskId, member.detail.batch.id)
}
function taskProgress(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return groupProgress(taskPrimary(task))
  const expected = task.members.reduce((total, member) => total + member.detail.batch.expectedCodeCount, 0)
  const created = task.members.reduce((total, member) => total + confirmedConfigurationCount(member), 0)
  const imported = task.members.reduce((total, member) => total + member.detail.batch.importedCodeCount, 0)
  const plannedCodes = task.members.reduce((total, member) => total + member.detail.batch.plannedCodeCount, 0)
  const review = task.members.reduce((total, member) => total + countIssues(reconciliationIssues(member)), 0)
  if (review) return `${created} / ${expected} 条远端配置已创建，${task.members.reduce((total, member) => total + countIssues(failedIssues(member)), 0)} 个失败，${creationHoldSummary(task.members)}`
  if (task.members.every(isSuccess)) return `${imported} / ${plannedCodes} 个兑换码已入库`
  if (task.members.every((member) => member.detail.batch.status === 'PUBLISHED')) {
    return task.members.map(member => `${remoteMarketLabel(member)}：${groupProgress(member)}`).join('；')
  }
  const failed = task.members.reduce((total, member) => total + countIssues(failedIssues(member)), 0)
  if (failed) return `${created} / ${expected} 条远端配置已创建，${failed} 个失败`
  const pending = task.members.reduce((total, member) => total + countIssues(pendingRemoteCreationIssues(member)), 0)
  if (pending) return `${created} / ${expected} 条远端配置已创建，${pending} 条待创建（尚未向远端发起）`
  return `${created} / ${expected} 条远端配置已创建（按盘口串行执行）`
}
function taskPublishTime(task: CodeGroupTask) {
  return isMultiMarketTask(task) ? '各盘口独立发布' : publishTime(taskPrimary(task))
}
function taskRemark(task: CodeGroupTask) {
  return task.members.map(groupRemark).filter((value) => value !== '—').join('；') || '—'
}
function taskCreatedAt(task: CodeGroupTask) { return taskPrimary(task)?.detail.batch.createdAt }
function taskDisplayId(task: CodeGroupTask) { return taskPrimary(task)?.detail.batch.taskNumber || String(task.taskId) }
function canExportMultiMarketTask(task: CodeGroupTask) {
  return Boolean(task.exportGroupKey) && isMultiMarketTask(task) && task.members.every(canStartDownload)
}
function canPublishMultiMarketTask(task: CodeGroupTask) {
  const rows = publishRows(task)
  return isMultiMarketTask(task) && rows.length > 0 && rows.every((member) => member.detail.batch.status === 'READY_TO_PUBLISH' && !member.detail.batch.remotePublishTaskId && !countIssues(reconciliationIssues(member)))
}
function isMultiMarketPublishTarget(target?: CodeGroupRow | CodeGroupTask): target is CodeGroupTask {
  return Boolean(target && 'members' in target)
}
function publishRows(target: CodeGroupRow | CodeGroupTask) {
  return isMultiMarketPublishTarget(target) ? target.members.filter(member => member.detail.batch.remotePublishMode !== 'EXTERNAL') : [target]
}

function canCancelScheduledPublish(row: CodeGroupRow) {
  const check = publicationCheck(row)
  return isScheduledPublish(row) && check?.canCancel === true && Date.now() - Date.parse(check.checkedAt) < 60_000
}
function isScheduledPublish(row: CodeGroupRow) {
  const batch = row.detail.batch
  return batch.status === 'PUBLISHED' && batch.remotePublishMode === 'SCHEDULED' && !batch.remotePublishCancelledAt
}
function canDownloadScheduledCodes(row: CodeGroupRow) {
  if (row.detail.batch.status === 'PUBLISHED' && !row.detail.batch.remotePublishTaskId) {
    return row.detail.issues.some(issue => issue.workflowStatus === 'PUBLISHED')
      && row.detail.issues.every(issue => ['PUBLISHED', 'CODE_IMPORTED'].includes(issue.workflowStatus || ''))
  }
  return row.detail.batch.status === 'PUBLISHED' && publicationCheck(row)?.publicationState === 'COMPLETED'
    && row.detail.issues.some(issue => issue.workflowStatus !== 'CODE_IMPORTED' && publicationCheck(row)?.configurations.some(config => (issue.overviewConfigurationIds || [issue.remoteConfigurationId]).includes(config.configurationId) && config.state === 'MATCHED'))
}
const externalTarget = ref<CodeGroupRow>()
const externalChoices = ref<CodeGroupRow[]>([])
const externalDialog = ref(false)
const externalTaskId = ref('')
const externalError = ref('')
const linkingExternal = ref(false)
function canLinkExternal(row: CodeGroupRow) {
  const batch = row.detail.batch
  if (!canGenerate.value || batch.rowVersion == null || !batch.remoteConnectionId) return false
  if (row.detail.issues.some(issue => issue.workflowStatus === 'CODE_IMPORTED') && !row.detail.allImportedDirectly) return false
  return acceptsManualPublication(batch, publicationCheck(row), row.detail.allImportedDirectly)
}
let resumeAfterRegistration: ((row?: CodeGroupRow) => void) | undefined
function finishRegistration(row?: CodeGroupRow) {
  resumeAfterRegistration?.(row)
  resumeAfterRegistration = undefined
}
watch(externalDialog, open => { if (!open) finishRegistration() }, { flush: 'sync' })
function externalActionLabel(row: CodeGroupRow) {
  const id = row.detail.batch.remotePublishTaskId
  return id && !id.startsWith('PENDING:') ? '换绑手动发布 ID' : '登记手动发布 ID'
}
function openExternalPublication(target: CodeGroupRow | CodeGroupTask, resume?: (row?: CodeGroupRow) => void) {
  if (externalDialog.value) { resume?.(); return }
  resumeAfterRegistration = resume
  verificationDialogVisible.value = false
  publishDialogVisible.value = false
  externalChoices.value = publishRows(target).filter(canLinkExternal)
  if (!externalChoices.value.length) { finishRegistration(); return }
  externalTarget.value = externalChoices.value.length === 1 ? externalChoices.value[0] : undefined
  externalTaskId.value = ''
  externalError.value = ''
  externalDialog.value = true
}
async function linkExternalPublication() {
  const row = externalTarget.value
  const taskId = externalTaskId.value.trim()
  if (!row || row.detail.batch.rowVersion == null || linkingExternal.value || !/^[1-9]\d{0,254}$/.test(taskId)) return
  linkingExternal.value = true
  externalError.value = ''
  try {
    const current = { campaign: row.campaign, detail: await api.redemption.batch(row.detail.batch.id) }
    if (!canLinkExternal(current) || current.detail.batch.rowVersion == null || current.detail.batch.remotePublishTaskId !== row.detail.batch.remotePublishTaskId) throw new Error('当前盘口状态或发布 ID 已变化，请刷新后重新核验')
    const detail = await api.redemption.adoptExternalPublication(row.detail.batch.id, current.detail.batch.rowVersion, taskId)
    const replacement = { campaign: row.campaign, detail }
    replaceCodeGroup(replacement)
    const continueDownload = Boolean(resumeAfterRegistration)
    finishRegistration(replacement)
    externalDialog.value = false
    ElMessage.success('已关联该盘口的远端发布任务，未重新发布')
    if (!continueDownload) await inspectPublication(replacement)
  } catch (error) {
    externalError.value = error instanceof Error ? error.message : '核验未完成，请核对盘口与发布任务 ID'
  } finally { linkingExternal.value = false }
}
function publishTime(row: CodeGroupRow) {
  const batch = row.detail.batch
  if (batch.remotePublishMode === 'EXTERNAL') return '远端后台手动发布'
  if (batch.remotePublishMode === 'IMMEDIATE') return '立即发布'
  if (batch.remotePublishMode === 'SCHEDULED' && batch.remoteScheduledPublishAt) {
    return `${formatIndiaDateTime(batch.remoteScheduledPublishAt)}（印度时间）${batch.remotePublishCancelledAt ? '，已撤销' : ''}`
  }
  return '—'
}
function labelsFor(row: CodeGroupRow) {
  const audiences = row.detail.issues.map((issue) => {
    const ids = issue.remoteLabelIds || []
    if (!ids.length) return '全部用户'
    return ids.map((id) => tagOptions.value.find((tag) => String(tag.id) === String(id))?.name || `标签 ID ${id}`).join('、')
  }).filter(Boolean)
  return [...new Set(audiences)].join('、') || '—'
}
function tiersFor(row: CodeGroupRow) {
  return row.campaign.tiers.map((tier) => `${tier.displayName || `充值 ≥ ${formatAmount(tier.minDepositAmount)}`}：${formatAmount(tier.bonusAmount)}–${formatAmount(tier.bonusMaxAmount || tier.bonusAmount)}`).join('；')
}
function issueStatus(issue: RedemptionCodeIssue) {
  if (deletionHeld(issue)) return { text: deletionLabel([issue]), type: 'danger' as const }
  if (needsCreationRewardCheck(issue)) return { text: creationRewardLabel([issue]), type: 'warning' as const }
  if (issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status)) return { text: recoveryStatusLabel(issue.recovery.status), type: 'warning' as const }
  if (issue.creationAwaitingRemoteReview) return { text: '待远端主管审核', type: 'warning' as const }
  if (needsCreationReconciliation(issue)) return { text: '创建结果待核对', type: 'warning' as const }
  if (issue.workflowStatus === 'CODE_IMPORTED') return { text: '兑换码已下载', type: 'success' as const }
  if (issue.workflowStatus === 'FAILED') return { text: '生成失败', type: 'danger' as const }
  if (issue.workflowStatus === 'PUBLISHED' && issue.remoteError) return { text: '下载失败', type: 'danger' as const }
  const group = selectedGroup.value
  if (group?.detail.batch.status === 'PUBLISHED' && (issue.workflowStatus === 'CREATED' || issue.workflowStatus === 'PUBLISHED')) {
    const text = configurationPublicationLabel(issue.remoteConfigurationId, publicationCheck(group))
    return { text, type: text === '已发布，待下载' ? 'primary' as const : 'warning' as const }
  }
  if (issue.workflowStatus === 'PUBLISHED') return { text: '已发布', type: 'primary' as const }
  if (issue.workflowStatus === 'CREATED') return { text: '待发布', type: 'warning' as const }
  if (issue.workflowStatus === 'PENDING_CREATION') return { text: '待创建', type: 'info' as const }
  return { text: '生成中', type: 'info' as const }
}

function canRetryRemoteCreation(issue: RedemptionCodeIssue) {
  return issue.overviewCount === undefined && (!issue.recovery || ['PRESENT', 'COMPLETED'].includes(issue.recovery.status)) && !needsCreationReconciliation(issue) && !issue.remoteConfigurationId && (issue.workflowStatus === 'FAILED' || issue.workflowStatus === 'CREATING_REMOTE')
}

function canCreatePendingRemoteConfiguration(issue: RedemptionCodeIssue) {
  const group = selectedGroup.value
  return Boolean(group && canContinuePendingCreation(group) && !isProcessing(group)
    && continuingCreationBatchId.value === undefined && retryingIssueId.value === undefined
    && !reusingConfigurations.value && issue.overviewCount === undefined && issue.workflowStatus === 'PENDING_CREATION'
    && !needsCreationReconciliation(issue) && !issue.remoteConfigurationId && !issue.remoteReferenceId && !issue.overviewHasConfiguration && !issue.overviewHasReference)
}

async function loadRemoteConnections() {
  remoteConnectionsLoading.value = true
  try {
    remoteConnections.value = (await api.redemptionRemoteConnections.list()).filter((connection) => connection.enabled && connection.marketEnabled)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '读取远端账号失败')
  } finally {
    remoteConnectionsLoading.value = false
  }
}

async function loadRemoteTags() {
  const connection = selectedRemoteConnection.value
  if (!connection) { ElMessage.warning('请先选择盘口，再同步标签'); return }
  const type = form.value.redemptionType
  const request = ++marketConfigurationRequest
  remoteTagsLoading.value = true
  try {
    const result = await api.redemptionRemoteConnections.syncTags(connection.id!)
    if (request !== marketConfigurationRequest || form.value.redemptionType !== type) return
    remoteTags.value = result.tags
    remoteTagsLoaded.value = true
    const preset = await api.redemptionRemoteConnections.rewardTierPreset(connection.id!, type)
    if (request !== marketConfigurationRequest) return
    rewardTierPreset.value = preset
    if (preset.exists && preset.stale) {
      ElMessage.warning(`已同步 ${result.tags.length} 个标签；奖励分档预设已过期，请确认后重新保存`)
    } else {
      ElMessage.success(`已同步 ${result.tags.length} 个标签`)
    }
    saveActiveMarketDraft()
  } catch (error) {
    if (request !== marketConfigurationRequest) return
    ElMessage.error(error instanceof Error ? error.message : '读取标签 ID 数组失败')
  } finally {
    if (request === marketConfigurationRequest) remoteTagsLoading.value = false
  }
}

let marketConfigurationRequest = 0

/**
 * A market change must load its own tag directory before selecting any labels.
 * Saved mappings are still account-backed on the server, but the account is
 * selected automatically and deterministically for the current market.
 */
async function loadMarketTierConfiguration() {
  const connection = selectedRemoteConnection.value
  const request = ++marketConfigurationRequest
  if (!connection) {
    remoteTags.value = []
    remoteTagsLoaded.value = false
    rewardTierPreset.value = undefined
    if (!isPreviousDayDeposit()) form.value.tiers = []
    return
  }
  remoteTagsLoading.value = true
  rewardTierPresetLoading.value = true
  marketConfigurationError.value = ''
  try {
    const [tags, preset] = await Promise.allSettled([
      api.redemptionRemoteConnections.tags(connection.id!),
      api.redemptionRemoteConnections.rewardTierPreset(connection.id!, form.value.redemptionType),
    ])
    if (request !== marketConfigurationRequest) return
    const errors: string[] = []
    if (tags.status === 'fulfilled') {
      remoteTags.value = tags.value
      remoteTagsLoaded.value = true
    } else {
      errors.push('标签读取失败')
    }
    if (preset.status === 'fulfilled') {
      rewardTierPreset.value = preset.value
    } else {
      errors.push('组合预设读取失败')
    }
    marketConfigurationError.value = errors.join('；')
    // A retry or a late response must not overwrite tiers entered by the user.
    if (!form.value.tiers.length && tags.status === 'fulfilled' && preset.status === 'fulfilled') applyMarketTierDefaults()
    saveActiveMarketDraft()
  } catch (error) {
    if (request !== marketConfigurationRequest) return
    marketConfigurationError.value = error instanceof Error ? error.message : '读取当前盘口配置失败'
  } finally {
    if (request === marketConfigurationRequest) {
      remoteTagsLoading.value = false
      rewardTierPresetLoading.value = false
    }
  }
}

async function loadCodeGroups() {
  if (detailMode.value) { await loadTaskDetail(); return }
  loading.value = true
  codeGroupLoadError.value = ''
  try {
    const [loadedCampaigns, details] = await Promise.all([api.redemption.list(), api.redemption.batchOverviews()])
    const campaignById = new Map(loadedCampaigns.map(campaign => [String(campaign.id), campaign]))
    const groups = details.flatMap(detail => {
      const campaign = campaignById.get(String(detail.batch.campaignId))
      return campaign ? [{ campaign, detail }] : []
    })
    campaigns.value = loadedCampaigns
    codeGroups.value = groups.sort((left, right) => String(right.detail.batch.createdAt || '').localeCompare(String(left.detail.batch.createdAt || '')))
    void verifyPendingPublications()
  } catch (error) {
    const detail = error instanceof Error ? error.message : '请求失败，请稍后重试'
    codeGroupLoadError.value = /timeout|超时/i.test(detail)
      ? '任务列表加载超时，请点击刷新重试；已创建的任务仍保存在系统中。'
      : `任务列表读取失败：${detail}`
    ElMessage.error(codeGroupLoadError.value)
  } finally {
    loading.value = false
  }
}

async function openCodeGroupDialog() {
  form.value = newCodeGroupForm()
  marketTierDrafts.value = {}
  activeMarketTab.value = ''
  codeGroupDialogVisible.value = true
  if (!remoteConnections.value.length) await loadRemoteConnections()
  const firstMarketId = availableRemoteMarkets.value[0]?.id
  if (firstMarketId !== undefined) {
    form.value.remoteMarketIds = [firstMarketId]
    await activateMarket(firstMarketId)
  }
}

async function changeRemoteMarkets() {
  saveActiveMarketDraft()
  const selected = new Set(form.value.remoteMarketIds.map(String))
  for (const key of Object.keys(marketTierDrafts.value)) if (!selected.has(key)) delete marketTierDrafts.value[key]
  const currentSelected = form.value.remoteMarketIds.some((marketId) => String(marketId) === String(form.value.remoteMarketId))
  const nextMarketId = form.value.remoteMarketIds.find((marketId) => !marketTierDrafts.value[marketKey(marketId)])
    ?? (currentSelected ? form.value.remoteMarketId : form.value.remoteMarketIds[form.value.remoteMarketIds.length - 1])
  if (nextMarketId === undefined) {
    form.value.remoteMarketId = undefined
    activeMarketTab.value = ''
    form.value.tiers = []
    remoteTags.value = []
    remoteTagsLoaded.value = false
    rewardTierPreset.value = undefined
    return
  }
  await activateMarket(nextMarketId)
}

async function changeActiveMarket(tabName: string | number) {
  const marketId = form.value.remoteMarketIds.find((item) => marketKey(item) === String(tabName))
  if (marketId !== undefined) await activateMarket(marketId)
}

function changeRedemptionType() {
  marketTierDrafts.value = {}
  form.value.tiers = []
  remoteTags.value = []
  remoteTagsLoaded.value = false
  rewardTierPreset.value = undefined
  if (!form.value.remoteMarketId) return
  void loadMarketTierConfiguration()
}

function resetPreviousDayTiers() {
  form.value.tiers = previousDayTiers()
  if (form.value.tiers.some((tier) => tier.userType === 'LABEL_USERS' && !tier.labelIds.length)) {
    ElMessage.warning('部分日充值档位未匹配到唯一标签，请按当前盘口标签手动选择，或删除不需要的档位')
  }
}

function tagDepositRange(name?: string) {
  if (!name) return undefined
  const normalized = name.replace(/[，,\s]/g, '').replace(/[～—–~至]/g, '-')
  const range = normalized.match(/(\d[\d,]*)-(\d[\d,]*)/)
  if (range) return { min: Number(range[1].replaceAll(',', '')), max: Number(range[2].replaceAll(',', '')) }
  const lowerBound = normalized.match(/(\d[\d,]*)(?:以上|\+)/)
  return lowerBound ? { min: Number(lowerBound[1].replaceAll(',', '')) } : undefined
}

function sevenDayTierProfileForTag(tag?: RedemptionRemoteTag) {
  if (!tag || !/近\s*7\s*天.*充值/i.test(tag.name)) return undefined
  const range = tagDepositRange(tag.name)
  if (!range || !Number.isFinite(range.min)) return undefined
  return sevenDayTierProfiles.find((profile) => profile.minDepositAmount === range.min && profile.maxDepositAmount === range.max)
}

function tiersFromRewardPreset(preset: RedemptionRewardTierPreset) {
  return preset.tiers.map((tier) => ({
    userType: tier.userType || (tier.labelIds.length ? 'LABEL_USERS' : 'ALL_USERS'),
    displayName: tier.displayName,
    minDepositAmount: (tier.userType === 'ALL_USERS' || !tier.labelIds.length)
      ? 0
      : minimumDepositFromTag(tagOptions.value.find((tag) => String(tag.id) === String(tier.labelIds[0]))?.name)
        ?? minimumDepositFromTag(tier.displayName)
        ?? Number(tier.minDepositAmount),
    bonusAmount: Number(tier.bonusAmount),
    bonusMaxAmount: Number(tier.bonusMaxAmount),
    labelIds: [...tier.labelIds],
  }))
}

function savedPresetMatchesCurrentMarket(preset: RedemptionRewardTierPreset) {
  const currentIds = new Set(tagOptions.value.map((tag) => String(tag.id)))
  return preset.tiers.every((tier) => tier.userType === 'ALL_USERS' || tier.labelIds.every((id) => currentIds.has(String(id))))
}

function standardSevenDayTiers() {
  const found = sevenDayTierProfiles.map((profile) => {
    const tag = tagOptions.value.find((item) => sevenDayTierProfileForTag(item) === profile)
    return tag ? draftTier(tag.id) : undefined
  })
  return {
    tiers: found.filter((tier): tier is CodeGroupTierDraft => Boolean(tier)),
    missing: sevenDayTierProfiles.filter((_, index) => !found[index]),
  }
}

function defaultAgentTiers(): CodeGroupTierDraft[] {
  return [{
    userType: 'ALL_USERS', displayName: '全部用户', minDepositAmount: 0,
    bonusAmount: 1, bonusMaxAmount: 3, labelIds: [],
  }]
}

/** Applies a usable saved preset, otherwise builds defaults from the current market's tags. */
function applyMarketTierDefaults() {
  const preset = rewardTierPreset.value
  if (preset?.exists && !preset.stale && savedPresetMatchesCurrentMarket(preset)) {
    form.value.tiers = tiersFromRewardPreset(preset)
    return
  }
  if (isPreviousDayDeposit()) {
    resetPreviousDayTiers()
    return
  }
  if (isAgentCodeGroup()) {
    form.value.tiers = defaultAgentTiers()
    return
  }
  const standard = standardSevenDayTiers()
  form.value.tiers = standard.tiers
  if (standard.missing.length) {
    ElMessage.warning(`当前盘口未识别到完整的近 7 天标准五档（缺少 ${standard.missing.map((tier) => tier.minDepositAmount).join('、')} 起档）；请同步标签后手动配置并另存预设`)
  }
}

function applyFutureRange(days: number) {
  form.value.dateRange = futureRange(days)
}

function updateTierFromLabel(tier: CodeGroupTierDraft, selectedLabelId?: string | number) {
  const labelId = selectedLabelId ?? tier.labelIds[0]
  if (labelId === undefined) return
  const tag = tagOptions.value.find((item) => String(item.id) === String(labelId))
  const profile = sevenDayTierProfileForTag(tag)
  const minimum = profile?.minDepositAmount ?? minimumDepositFromTag(tag?.name) ?? tier.minDepositAmount
  Object.assign(tier, {
    displayName: profile?.name || tag?.name.replace(/^\(\d+\)/, '').trim() || `标签 ID ${labelId}`,
    minDepositAmount: minimum,
    bonusAmount: profile?.bonusAmount ?? tier.bonusAmount,
    bonusMaxAmount: profile?.bonusMaxAmount ?? tier.bonusMaxAmount,
    labelIds: [labelId],
  })
}

function updatePreviousDayTierLabel(tier: CodeGroupTierDraft, selectedLabelId?: string | number) {
  if (selectedLabelId === undefined) return
  tier.labelIds = [selectedLabelId]
  const tag = previousDayTagOptions.value.find((item) => String(item.id) === String(selectedLabelId))
  tier.displayName = tag?.name.replace(/^\(\d+\)/, '').trim() || `标签 ID ${selectedLabelId}`
  tier.minDepositAmount = minimumDepositFromTag(tag?.name) ?? tier.minDepositAmount
}

function changeTierUserType(tier: CodeGroupTierDraft, userType: CodeGroupUserType) {
  tier.userType = userType
  if (userType === 'ALL_USERS') {
    tier.labelIds = []
    tier.minDepositAmount = 0
    tier.displayName = tier.displayName.replace(/（所有用户）$/, '').trim() || '全部用户'
    return
  }
  if (tier.labelIds.length) return
  const options = isPreviousDayDeposit() ? previousDayTagOptions.value : tagOptions.value
  const available = options.find((tag) => !isLabelUsedByOtherTier(tag.id, tier))
  if (!available) return
  if (isPreviousDayDeposit()) updatePreviousDayTierLabel(tier, available.id)
  else updateTierFromLabel(tier, available.id)
}

function minimumDepositFromTag(name?: string) {
  if (!name) return undefined
  const normalized = name.replace(/^\s*\(\d+\)\s*/, '').replace(/[，,]/g, '')
  // Remote labels also use mixed names such as 日充值recharge today–200+.
  // Start after the deposit keyword so label IDs and “近7天” are not amounts.
  const matched = normalized.match(/(?:充值总金额|充值|recharge|deposit|存款)[^\d]*(\d+)/i)
  if (!matched) return undefined
  const amount = Number(matched[1].replaceAll(',', ''))
  return Number.isFinite(amount) ? amount : undefined
}

function addTier() {
  form.value.tiers.push({
    userType: 'LABEL_USERS', displayName: '', minDepositAmount: 0,
    bonusAmount: 1, bonusMaxAmount: 3, labelIds: [],
  })
}

function isLabelUsedByOtherTier(labelId: string | number, currentTier: CodeGroupTierDraft) {
  return form.value.tiers.some((tier) => tier !== currentTier && tier.labelIds.some((id) => String(id) === String(labelId)))
}

function restoreStandardTiers() {
  if (isAgentCodeGroup()) {
    form.value.tiers = defaultAgentTiers()
    return
  }
  const standard = standardSevenDayTiers()
  if (standard.missing.length) {
    ElMessage.warning(`当前盘口标签目录未包含完整标准五档；缺少 ${standard.missing.map((tier) => tier.minDepositAmount).join('、')} 起档`)
    return
  }
  form.value.tiers = standard.tiers
}

function applyRewardTierPreset() {
  const preset = rewardTierPreset.value
  if (!preset?.exists) { ElMessage.warning('当前远端账号还没有已保存的奖励分档预设'); return }
  if (preset.stale) { ElMessage.warning('标签已同步，现有奖励分档预设已过期，请按当前标签重新保存'); return }
  if (!savedPresetMatchesCurrentMarket(preset)) { ElMessage.warning('已保存预设含有当前盘口不存在的标签 ID，请同步标签并重新配置'); return }
  form.value.tiers = tiersFromRewardPreset(preset)
  ElMessage.success('已应用保存的奖励分档预设')
}

async function saveRewardTierPreset() {
  const connection = selectedRemoteConnection.value
  if (!connection) { ElMessage.warning('请先选择盘口'); return }
  const type = form.value.redemptionType
  const marketId = form.value.remoteMarketId
  if (form.value.tiers.some((tier) => tier.userType === 'LABEL_USERS' && !tier.labelIds.length)) { ElMessage.warning('标签用户档位必须选择标签 ID'); return }
  if (form.value.tiers.some((tier) => tier.bonusMaxAmount < tier.bonusAmount)) { ElMessage.warning('兑换金额上下限不正确'); return }
  rewardTierPresetSaving.value = true
  try {
    const savedPreset = await api.redemptionRemoteConnections.saveRewardTierPreset(connection.id!, {
      tiers: form.value.tiers.map((tier) => ({
        userType: tier.userType,
        labelIds: tier.userType === 'ALL_USERS' ? [] : [...tier.labelIds],
        displayName: tier.displayName,
        minDepositAmount: String(tier.minDepositAmount),
        bonusAmount: String(tier.bonusAmount),
        bonusMaxAmount: String(tier.bonusMaxAmount),
      })),
      tagSnapshot: tagOptions.value.map((tag) => ({ id: tag.id, name: tag.name })),
    }, type)
    if (form.value.redemptionType !== type || form.value.remoteMarketId !== marketId) return
    rewardTierPreset.value = savedPreset
    saveActiveMarketDraft()
    ElMessage.success('当前奖励分档已保存为预设')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存奖励分档预设失败')
  } finally {
    rewardTierPresetSaving.value = false
  }
}

function removeTier(index: number) {
  if (form.value.tiers.length === 1) { ElMessage.warning('兑换码组至少需要一个充值档位'); return }
  form.value.tiers.splice(index, 1)
}

function makeGroupCode(marketId: string | number, sequence: number) {
  return `CODE_GROUP_${todayIso().replaceAll('-', '')}_${marketKey(marketId)}_${String(Date.now()).slice(-8)}_${sequence}`
}

function makeExportGroupKey() {
  return `MULTI_MARKET_${todayIso().replaceAll('-', '')}_${String(Date.now()).slice(-8)}`
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))
}

function validateForm() {
  const keyNumber = form.value.remoteOptions.keyNumber
  if (!usesSpecialCode.value && (!Number.isInteger(keyNumber) || keyNumber < 1 || keyNumber > 1000)) return '每组兑换码数量请输入 1–1000 的整数'
  const [from, to] = form.value.dateRange || []
  if (!from || !to || to < from) return '请选择有效的兑换日期范围'
  const [validFromDayOffset, validToDayOffset] = validityOffsets.value
  if (!Number.isInteger(validFromDayOffset) || !Number.isInteger(validToDayOffset)
    || validFromDayOffset < 0 || validToDayOffset < validFromDayOffset || validToDayOffset > 365) {
    return '请设置有效的远端生效日期：结束日不得早于开始日，且最多延后 365 天'
  }
  if (!form.value.remoteMarketIds.length) return '请至少选择一个盘口；如未配置，请先前往“远端连接”完成账号配置'
  for (const marketId of form.value.remoteMarketIds) {
    const label = marketLabel(marketId)
    const draft = marketTierDrafts.value[marketKey(marketId)]
    if (!remoteConnectionForMarket(marketId)) return `${label} 暂无可用远端账号，请前往“远端连接”完成账号配置`
    if (!draft?.tiers.length) return `${label} 请先配置至少一个充值档位`
    if (usesSpecialCode.value) {
      const amounts = draft.tiers.map((tier) => tier.minDepositAmount)
      if (amounts.some((amount) => !Number.isInteger(amount) || amount < 0)) return `${label} 的特殊兑换码充值门槛必须是非负整数`
      if (new Set(amounts).size !== amounts.length) return `${label} 的相同充值门槛会生成重复的特殊兑换码，请调整档位`
    }
    if (draft.tiers.some((tier) => tier.userType === 'LABEL_USERS' && !tier.labelIds.length)) return `${label} 的标签用户档位必须选择至少一个标签 ID`
    if (isPreviousDayDeposit() && draft.tiers.some((tier) => tier.userType === 'LABEL_USERS')) {
      if (!draft.remoteTagsLoaded) return `${label} 的标签尚未加载成功，请重新加载后再创建`
      const currentIds = new Set(draft.remoteTags.map((tag) => String(tag.id)))
      if (draft.tiers.some((tier) => tier.userType === 'LABEL_USERS' && tier.labelIds.some((id) => !currentIds.has(String(id))))) {
        return `${label} 的档位含有当前盘口不存在的标签 ID，请重新选择标签`
      }
    }
    if (draft.tiers.some((tier) => tier.bonusAmount < 0 || tier.bonusMaxAmount < tier.bonusAmount)) return `${label} 的兑换金额上下限不正确`
  }
  return ''
}

async function checkCreationDuplicates() {
  duplicateCreationReview.value = undefined
  if (!usesSpecialCode.value) return true
  const markets: RedemptionDuplicateMarket[] = form.value.remoteMarketIds.map(marketId => ({
    marketId, redemptionType: form.value.redemptionType, specialCodeNaming: form.value.specialCodeNaming,
    from: form.value.dateRange[0], to: form.value.dateRange[1],
    deposits: marketTierDrafts.value[marketKey(marketId)].tiers.map(tier => String(tier.minDepositAmount)),
  }))
  duplicateConflicts.value = []
  duplicateCheckProgress.value = '正在进行本地查重…'
  const local = await api.redemption.checkDuplicates(markets, false)
  duplicateConflicts.value = local.conflicts
  if (checkRemoteDuplicates.value) {
    for (const [index, market] of markets.entries()) {
      duplicateCheckProgress.value = `正在远端查重（${index + 1}/${markets.length}）：${marketLabel(market.marketId)}，可能耗时较长…`
      const checked = await api.redemption.checkDuplicates([market], true)
      if (!checked.remoteChecked) throw Error('远端查重未完成，本次未创建配置')
      const combined = new Map([...duplicateConflicts.value, ...checked.conflicts].map(conflict =>
        [`${conflict.marketId}:${conflict.code}:${conflict.issueId || conflict.configurationId}`, conflict]))
      duplicateConflicts.value = [...combined.values()]
    }
  }
  if (duplicateConflicts.value.length) {
    duplicateReviewAcknowledged.value = false
    duplicateDialogVisible.value = true
    const confirmed = await new Promise<boolean>(resolve => { duplicateReviewResolve = resolve })
    if (!confirmed) return false
    duplicateCreationReview.value = { confirmed: true, fingerprints: Object.fromEntries(duplicateConflicts.value
      .filter(conflict => conflict.source === 'LOCAL' && conflict.issueId && conflict.reviewFingerprint)
      .map(conflict => [String(conflict.issueId), conflict.reviewFingerprint!])) }
  }
  return true
}

function creationReviewKey(detail: RedemptionBatchDetail) {
  return detail.batch.taskId != null ? `task:${detail.batch.taskId}` : `batch:${detail.batch.id}`
}

async function checkPendingCreationDuplicates(detail: RedemptionBatchDetail): Promise<RedemptionDuplicateReview | false | undefined> {
  if (duplicateReviewResolve) throw new Error('请先完成当前同码记录的阅览确认')
  const result = await api.redemption.checkPendingTaskDuplicates(detail.batch.id)
  if (result.reviewConfirmed) return undefined // Execution loads the persisted task approval.
  const key = creationReviewKey(detail)
  const previous = taskDuplicateReviews.get(key)
  if (!result.conflicts.length) return previous || { confirmed: true, fingerprints: {} }
  if (previous?.confirmed && result.conflicts.every(conflict => conflict.source === 'LOCAL'
    && conflict.issueId != null && conflict.reviewFingerprint
    && previous.fingerprints[String(conflict.issueId)] === conflict.reviewFingerprint)) return previous
  duplicateConflicts.value = result.conflicts
  duplicateReviewAcknowledged.value = false
  duplicateDialogVisible.value = true
  const confirmed = await new Promise<boolean>(resolve => { duplicateReviewResolve = resolve })
  if (!confirmed) return false
  const review: RedemptionDuplicateReview = { confirmed: true, fingerprints: Object.fromEntries(result.conflicts
    .filter(conflict => conflict.source === 'LOCAL' && conflict.issueId != null && conflict.reviewFingerprint)
    .map(conflict => [String(conflict.issueId), conflict.reviewFingerprint!])) }
  await api.redemption.confirmTaskDuplicateReview(detail.batch.id, review)
  taskDuplicateReviews.set(key, review)
  return review
}

function finishDuplicateReview(confirmed: boolean) {
  if (confirmed && !duplicateReviewAcknowledged.value) return
  const resolve = duplicateReviewResolve
  duplicateReviewResolve = undefined
  duplicateDialogVisible.value = false
  resolve?.(confirmed)
}

async function openDuplicateTask(conflict: RedemptionDuplicateConflict) {
  if (!conflict.batchId) return
  try {
    const detail = await api.redemption.batch(conflict.batchId)
    const campaign = await api.redemption.get(detail.batch.campaignId)
    finishDuplicateReview(false)
    codeGroupDialogVisible.value = false
    await openGroupDetail({ campaign, detail })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '旧任务读取失败，请刷新后重试')
  }
}

async function createCodeGroup() {
  if (working.value || checkingDuplicates.value) return
  checkingDuplicates.value = true
  try {
  await ensureSelectedMarketDrafts()
  const message = validateForm()
  if (message) { ElMessage.warning(message); return }
  const creationIntent = JSON.stringify({ form: form.value, tiers: form.value.remoteMarketIds.map(id => marketTierDrafts.value[marketKey(id)].tiers) })
  if (!await checkCreationDuplicates()) return
  try {
    if (!duplicateCreationReview.value?.confirmed) await ElMessageBox.confirm(
      `系统会将 ${form.value.remoteMarketIds.length} 个盘口汇总为一条任务，并按盘口顺序串行创建 ${expectedTaskCount()} 组远端配置，每组 ${codesPerGroup.value} 个${usesSpecialCode.value ? '特殊' : '普通'}兑换码，共 ${expectedTaskCount() * codesPerGroup.value} 个；生效规则为“${validityRuleSummary.value}”。此次仅创建配置。下载时可按盘口选择系统发布、手动发布或直接取码。`,
      '确认批量生成兑换码组',
      { type: 'warning', confirmButtonText: '确认并开始生成', cancelButtonText: '取消' },
    )
    if (creationIntent !== JSON.stringify({ form: form.value, tiers: form.value.remoteMarketIds.map(id => marketTierDrafts.value[marketKey(id)].tiers) })) {
      ElMessage.warning('创建参数已变化，请重新查重并确认')
      return
    }
  } catch {
    return
  }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '查重未完成，本次未创建配置')
    return
  } finally {
    checkingDuplicates.value = false
    duplicateCheckProgress.value = ''
  }
  const [claimDateFrom, claimDateTo] = form.value.dateRange
  const [validFromDayOffset, validToDayOffset] = validityOffsets.value
  const exportGroupKey = form.value.remoteMarketIds.length > 1 ? makeExportGroupKey() : undefined
  working.value = true
  try {
    const created: RedemptionBatchDetail[] = []
    const failedMarkets: string[] = []
    for (const [index, marketId] of form.value.remoteMarketIds.entries()) {
      const draft = marketTierDrafts.value[marketKey(marketId)]
      if (!draft) continue
      const input: RedemptionCodeGroupInput = {
        duplicateReview: duplicateCreationReview.value,
        code: makeGroupCode(marketId, index + 1),
        name: generatedGroupName(form.value.dateRange, marketId),
        claimDateFrom,
        claimDateTo,
        validFromDayOffset,
        validToDayOffset,
        lookbackDays: isPreviousDayDeposit() ? 1 : 7,
        // Remote group_desc and remark are generated per task on the server.
        description: generatedGroupDescription(claimDateFrom, claimDateTo),
        tiers: draft.tiers.map((tier, tierIndex) => ({
          displayName: tier.displayName,
          minDepositAmount: String(tier.minDepositAmount),
          bonusAmount: String(tier.bonusAmount),
          bonusMaxAmount: String(tier.bonusMaxAmount),
          sortOrder: tierIndex + 1,
        })),
        remoteMarketId: marketId,
        exportGroupKey,
        redemptionType: form.value.redemptionType,
        specialCodeNaming: usesSpecialCode.value ? form.value.specialCodeNaming : 'ORIGINAL',
        tierUserTypes: draft.tiers.map((tier) => tier.userType),
        tierLabelIds: draft.tiers.map((tier) => tier.userType === 'ALL_USERS' ? [] : tier.labelIds),
        remoteOptions: { ...form.value.remoteOptions, keyNumber: codesPerGroup.value },
      }
      try {
        created.push(await api.redemption.createGroup(input))
      } catch (error) {
        failedMarkets.push(`${marketLabel(marketId)}：${error instanceof Error ? error.message : '创建失败'}`)
      }
    }
    if (!created.length) {
      ElMessage.error(`所有盘口的兑换码组均创建失败：${failedMarkets.join('；')}`)
      return
    }
    codeGroupDialogVisible.value = false
    await loadCodeGroups()
    const taskCount = created.reduce((total, detail) => total + detail.batch.expectedCodeCount, 0)
    ElMessage[failedMarkets.length ? 'warning' : 'success'](failedMarkets.length
      ? `已创建 1 条多盘口任务，包含 ${created.length} 个盘口、${taskCount} 条远端配置；${failedMarkets.join('；')}`
      : `已创建 1 条${created.length > 1 ? '多盘口' : ''}任务，包含 ${created.length} 个盘口、${taskCount} 条远端配置，正在按盘口顺序自动生成`)
    for (const detail of created) {
      if (duplicateCreationReview.value) taskDuplicateReviews.set(creationReviewKey(detail), duplicateCreationReview.value)
      if (!await generateCodes(detail, duplicateCreationReview.value)) break
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建兑换码组失败')
  } finally {
    working.value = false
  }
}

function markProcessing(batchId: string | number, active: boolean) {
  const next = new Set(processingGroupIds.value)
  if (active) next.add(groupKey(batchId))
  else next.delete(groupKey(batchId))
  processingGroupIds.value = next
}

async function generateCodes(initial: RedemptionBatchDetail, duplicateReview?: RedemptionDuplicateReview) {
  let detail = initial
  markProcessing(detail.batch.id, true)
  try {
    detail = await api.redemption.batch(detail.batch.id)
    if (detail.issues.some(needsCreationReconciliation)) {
      ElMessage.warning('任务含待审核或待核对的配置，已停止自动创建，请查看任务明细')
      return false
    }
    if (detail.issues.some(issue => issue.workflowStatus === 'RECOVERY_REQUIRED')) {
      ElMessage.warning('已保存进度：旧配置需要核验或重建，请点击“重试并重建”后继续')
      return false
    }
    const pendingIssues = detail.issues.filter((issue) => issue.workflowStatus === 'PENDING_CREATION')
    const reviewed = duplicateReview ?? (pendingIssues.length ? await checkPendingCreationDuplicates(detail) : undefined)
    if (reviewed === false) return false
    const intervalMs = Math.max(1, detail.batch.remoteOptions?.creationIntervalSeconds ?? form.value.remoteOptions.creationIntervalSeconds ?? 5) * 1000
    for (const [index, issue] of pendingIssues.entries()) {
      if (issue.workflowStatus !== 'PENDING_CREATION') continue
      const requestStartedAt = Date.now()
      detail = reviewed
        ? await api.redemption.createRemoteConfiguration(issue.id, false, reviewed)
        : await api.redemption.createRemoteConfiguration(issue.id)
      if (index < pendingIssues.length - 1) await wait(Math.max(0, intervalMs - (Date.now() - requestStartedAt)))
    }
    const verified = await confirmCreationRewards(detail)
    if (!verified) return false
    detail = verified
    if (detail.issues.some(issue => !['CREATED', 'PUBLISHED', 'CODE_IMPORTED'].includes(issue.workflowStatus || ''))) {
      ElMessage.warning('仍有配置待处理，当前任务尚未完成创建')
      return false
    }
    ElMessage.success('远端配置已创建，实际奖励已核验。下载时可选择是否先发布')
    return true
  } catch (error) {
    ElMessage.warning(`已停止后续自动创建：${error instanceof Error ? error.message : '请求结果未确认，请查看任务明细'}`)
    return false
  } finally {
    markProcessing(detail.batch.id, false)
    try {
      detail = await api.redemption.batch(detail.batch.id)
      await loadCodeGroups()
      if (selectedGroup.value?.detail.batch.id === detail.batch.id) replaceCodeGroup({ campaign: selectedGroup.value.campaign, detail })
    } catch { ElMessage.warning('任务明细刷新失败，请点击刷新查看最新状态') }
  }
}

async function openPublishDialog(target: CodeGroupRow | CodeGroupTask) {
  if (publishRows(target).some(row => row.detail.overview)) {
    try {
      const rows = await Promise.all(publishRows(target).map(loadFullGroup))
      target = isMultiMarketPublishTarget(target) ? { ...target, members: rows } : rows[0]
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : '读取完整任务明细失败')
      return
    }
  }
  if (publishRows(target).some(row => creationRewardIssues(row).length)) {
    ElMessage.warning('实际奖励尚未核验一致，请先确认并完成奖励核验')
    return
  }
  if (publishRows(target).some(row => countIssues(reconciliationIssues(row)) > 0)) {
    ElMessage.warning('有创建结果待核对的配置，请先核对后再发布')
    return
  }
  publishTarget.value = target
  publishForm.value = { mode: 'IMMEDIATE', fallbackToScheduled: true }
  publishOptionsOpen.value = []
  publishDialogVisible.value = true
}

function earliestUnpublishedExpiry(row: CodeGroupRow) {
  return row.detail.issues.filter(issue => issue.workflowStatus === 'CREATED')
    .map(issue => `${shiftDate(issue.claimDate, row.detail.batch.validToDayOffset ?? 0)} 23:59:59`).sort()[0]
}

async function publishWithSelectedOptions(row: CodeGroupRow, mode: 'IMMEDIATE' | 'SCHEDULED', scheduledTime: string | undefined, offerScheduledFallback: boolean) {
  const expiry = earliestUnpublishedExpiry(row)
  if (mode === 'SCHEDULED') {
    if (isRepairing(row) && (!expiry || !scheduledTime || scheduledTime >= expiry)) {
      throw new Error(`补齐配置必须在 ${expiry || '未知到期时间'}（印度时间）之前发布`)
    }
    return api.redemption.publishRemoteBatch(row.detail.batch.id, row.detail.batch.rowVersion, mode, scheduledTime, false)
  }
  try {
    // Both initial and supplemental publication use the same explicit fallback flow.
    // A remote rejection is known before proposing a scheduled write to the operator.
    return await api.redemption.publishRemoteBatch(row.detail.batch.id, row.detail.batch.rowVersion, 'IMMEDIATE', undefined, false)
  } catch (error) {
    if (!offerScheduledFallback || !(error instanceof Error) || !hasPendingScheduledConflict(error.message)) throw error
    let latestError: Error = error
    const candidateTimes = [15, 30, 60].map(minutes => indiaNowText(new Date(Date.now() + minutes * 60_000)))
    candidateTimes.push(`${row.detail.batch.claimDateFrom} 00:00:00`)
    for (const time of [...new Set(candidateTimes)]) {
      if (time <= indiaNowText()) continue
      if (expiry && time >= expiry) continue
      await ElMessageBox.confirm(
        `立即发布被远端已有定时任务阻止。是否改为 ${time}（印度时间）定时发布？${expiry ? `待发布配置最早于 ${expiry} 到期。` : ''}远端会发布该账号届时所有尚未发布的兑换码，只有执行完成并核验通过后才能下载。`,
        '确认定时发布时间', { type: 'warning', confirmButtonText: '按此时间发布', cancelButtonText: '暂不发布' },
      )
      if (time <= indiaNowText()) throw new Error('确认时定时时间已过，请重新选择发布方式')
      const current = await api.redemption.batch(row.detail.batch.id)
      if (current.batch.status !== row.detail.batch.status || current.issues.some(issue => issue.workflowStatus === 'PENDING_CREATION')) {
        throw new Error('配置状态已变化，请刷新后重新选择发布方式')
      }
      try {
        return await api.redemption.publishRemoteBatch(current.batch.id, current.batch.rowVersion, 'SCHEDULED', time, false)
      } catch (scheduledError) {
        if (!(scheduledError instanceof Error) || !hasPendingScheduledConflict(scheduledError.message)) throw scheduledError
        latestError = scheduledError
      }
    }
    throw new Error(`可用的定时时间均未被远端接受，未安排发布：${latestError.message}`)
  }
}

function hasPendingPublishReservation(row: CodeGroupRow) {
  return (row.detail.batch.status === 'READY_TO_PUBLISH' || isRepairing(row)) && Boolean(row.detail.batch.remotePublishTaskId?.startsWith('PENDING:'))
}

function repairReadyForPublish(row: CodeGroupRow) {
  return !countIssues(reconciliationIssues(row)) && isRepairing(row) && row.detail.issues.some(issue => issue.workflowStatus === 'CREATED')
    && row.detail.issues.every(issue => ['CREATED', 'PUBLISHED', 'CODE_IMPORTED'].includes(issue.workflowStatus || ''))
}

function canContinueRepair(row: CodeGroupRow) {
  return !countIssues(reconciliationIssues(row)) && isRepairing(row) && !hasPendingPublishReservation(row)
    && (repairReadyForPublish(row) || row.detail.issues.some(issue => issue.workflowStatus === 'PENDING_CREATION'))
}

function repairActionLabel(row: CodeGroupRow) {
  return repairReadyForPublish(row) ? '选择发布方式' : '继续补齐配置'
}

function handleRepairAction(row: CodeGroupRow) {
  if (repairReadyForPublish(row)) openPublishDialog(row)
  else void continueMissingConfigurationRepair(row)
}

function remoteMarketLabel(row: CodeGroupRow) {
  const { remoteMarketCode, remoteMarketName } = row.detail.batch
  if (remoteMarketCode && remoteMarketName) return `${remoteMarketCode} · ${remoteMarketName}`
  return remoteMarketName || remoteMarketCode || '—'
}

async function recoverPublishReservation(row: CodeGroupRow) {
  try {
    await ElMessageBox.confirm('该操作只会解除本地发布占位，不会再次调用远端。上次远端发布结果未知，请先在远端管理后台核对是否已发布。仅超过 2 分钟的占位可以恢复。', '恢复发布状态', { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' })
  } catch {
    return
  }
  recoveringPublishId.value = row.detail.batch.id
  try {
    const detail = await api.redemption.recoverRemotePublish(row.detail.batch.id, row.detail.batch.rowVersion)
    const replacement = { campaign: row.campaign, detail }
    replaceCodeGroup(replacement)
    ElMessage.success('已恢复本地发布状态；请核对远端后台后再选择发布方式')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复发布状态失败')
  } finally {
    recoveringPublishId.value = undefined
  }
}

async function submitPublish() {
  const target = publishTarget.value
  if (!target) return
  if (publishRows(target).some(row => countIssues(reconciliationIssues(row)) > 0)) {
    ElMessage.warning('有创建结果待核对的配置，请先核对后再发布')
    return
  }
  if (publishForm.value.mode === 'SCHEDULED' && !publishForm.value.scheduledTime) { ElMessage.warning('请选择定时发布时间（印度时间）'); return }
  const rows = publishRows(target)
  if (rows.some((row) => row.detail.batch.status !== 'READY_TO_PUBLISH' && !repairReadyForPublish(row))) {
    ElMessage.warning('仍有配置尚未创建完成，请先处理完成后再发布')
    return
  }
  // Keep the submitted options after the dialog is destroyed.  A multi-market
  // publish also downloads codes serially, which can take considerably longer
  // than the request that accepts the publish action.
  const { mode, scheduledTime, fallbackToScheduled } = publishForm.value
  publishing.value = true
  publishDialogVisible.value = false
  ElMessage.info(rows.length > 1
    ? `已开始按盘口顺序发布 ${rows.length} 个盘口，任务进度会自动刷新`
    : '已开始发布，任务进度会自动刷新')
  try {
    const failures: string[] = []
    for (const row of rows) {
      try {
        if (codeGroups.value.find(group => group.detail.batch.id === row.detail.batch.id)?.detail.batch.remotePublishMode === 'EXTERNAL') continue
        const detail = await publishWithSelectedOptions(row, mode, scheduledTime, fallbackToScheduled)
        const replacement = { campaign: row.campaign, detail }
        replaceCodeGroup(replacement)
        if (detail.batch.remotePublishMode === 'EXTERNAL') continue
        if (detail.batch.remotePublishMode === 'SCHEDULED') {
          ElMessage.info(`远端已接受定时发布（印度时间 ${formatIndiaDateTime(detail.batch.remoteScheduledPublishAt)}）；待执行完成并核验后再下载`)
        }
        const checked = await verifyRemotePublication(replacement, true)
        if (checked?.publicationState === 'COMPLETED' && checked.configurations.some(item => item.state === 'MATCHED')) {
          const complete = await downloadPublishedCodes(replacement)
          if (complete && isRepairing(row)) await exportGroup({ campaign: row.campaign, detail: await api.redemption.batch(detail.batch.id) })
        }
      } catch (error) {
        failures.push(`${remoteMarketLabel(row)}：${error === 'cancel' || error === 'close' ? '已取消转定时发布' : error instanceof Error ? error.message : '发布失败'}`)
      }
    }
    const scheduled = mode === 'SCHEDULED'
    ElMessage[failures.length ? 'warning' : 'success'](failures.length
      ? `${scheduled ? '定时发布' : '发布'}部分失败：${failures.join('；')}`
      : rows.length > 1
        ? '各盘口发布处理结束，手动发布的盘口不再提交，请查看各盘口核验结果'
      : '已提交发布请求，请查看实际发布方式和远端核验结果')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '远端发布失败') }
  finally {
    publishing.value = false
    await loadCodeGroups()
  }
}

async function downloadPublishedCodes(row: CodeGroupRow) {
  if (row.detail.overview) {
    try { row = await loadFullGroup(row) }
    catch (error) { ElMessage.error(error instanceof Error ? error.message : '读取完整任务明细失败'); return false }
  }
  let detail = row.detail
  let failed = false
  let attemptedDownload = false
  markProcessing(detail.batch.id, true)
  try {
    // Shared configurations may have been published by several original tasks.
    // The server resolves and verifies each original publication before its download.
    const sharedPublication = detail.batch.status === 'PUBLISHED' && !detail.batch.remotePublishTaskId
    const check = sharedPublication ? undefined : await verifyRemotePublication(row, true)
    if (!sharedPublication && (!check || check.publicationState !== 'COMPLETED')) {
      showPublicationResult(row)
      return false
    }
    const pending = detail.issues.filter(item => item.workflowStatus !== 'CODE_IMPORTED')
    const downloadable = pending.filter(item => sharedPublication
      ? item.workflowStatus === 'PUBLISHED'
      : check?.configurations.some(config => config.configurationId === item.remoteConfigurationId && config.state === 'MATCHED'))
    if (pending.length && !downloadable.length) {
      showPublicationResult(row)
      return false
    }
    failed = downloadable.length !== pending.length
    for (const issue of downloadable) {
      attemptedDownload = true
      try { detail = await api.redemption.downloadRemoteCode(issue.id) }
      catch (error) { failed = true; ElMessage.error(error instanceof Error ? error.message : '兑换码下载失败') }
    }
    replaceCodeGroup({ campaign: row.campaign, detail })
    const complete = detail.batch.status === 'COMPLETED'
    ElMessage[complete ? 'success' : 'warning'](complete ? '兑换码已全部入库，可下载 Excel' : failed ? '发布已完成，但部分配置待核对或下载异常，请查看任务明细' : '兑换码尚未全部入库')
    return complete
  } finally {
    markProcessing(detail.batch.id, false)
    if (attemptedDownload) await loadCodeGroups()
  }
}

async function cancelScheduledPublish(row: CodeGroupRow) {
  const check = await verifyRemotePublication(row, true)
  if (!check?.canCancel) { ElMessage.warning('远端任务已执行、已撤销或状态未知，不能撤销'); return }
  try { await ElMessageBox.confirm('撤销后该批次不会再自动进行后续定时发布尝试。', '撤销定时发布', { type: 'warning' }) } catch { return }
  cancellingPublishId.value = row.detail.batch.id
  try {
    const detail = await api.redemption.cancelScheduledPublish(row.detail.batch.id, row.detail.batch.rowVersion)
    replaceCodeGroup({ campaign: row.campaign, detail })
    ElMessage.success('已撤销定时发布')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '撤销定时发布失败') }
  finally { cancellingPublishId.value = undefined }
}

async function loadFullGroup(row: CodeGroupRow): Promise<CodeGroupRow> {
  if (!row.detail.overview) return row
  const detail = await api.redemption.batch(row.detail.batch.id)
  if (detail.overview) throw new Error('未读取到完整任务明细，请刷新后重试')
  const replacement = { campaign: row.campaign, detail }
  replaceCodeGroup(replacement)
  return replacement
}

async function openGroupDetail(row: CodeGroupRow) {
  await navigateTaskDetail(row.detail.batch.taskId || row.detail.batch.id, row.detail.batch.id)
}
function navigateTaskDetail(taskId: string | number, batchId?: string | number) {
  return router.push({ name: 'redemption-task-detail', params: { taskId }, query: {
    batch: batchId, returnPage: codeGroupTaskCurrentPage.value, returnPageSize: codeGroupTaskPageSize.value,
    returnTableScroll: taskTableScroll.value,
  } })
}
function returnToTaskList() {
  return router.push({ name: 'redemption', query: { page: route.query.returnPage, pageSize: route.query.returnPageSize, tableScroll: route.query.returnTableScroll } })
}
function verifyDetailPublication(group?: CodeGroupRow) {
  if (group && canGenerate.value && ['PUBLISHED', 'COMPLETED'].includes(group.detail.batch.status) && group.detail.batch.remotePublishTaskId) {
    void verifyRemotePublication(group, true)
  }
}
async function loadTaskDetail() {
  loading.value = true; codeGroupLoadError.value = ''
  try {
    const data = await api.redemption.taskDetail(String(route.params.taskId))
    const campaignById = new Map(data.campaigns.map(c => [String(c.id), c]))
    const members = data.batches.flatMap(detail => { const campaign = campaignById.get(String(detail.batch.campaignId)); return campaign ? [{ campaign, detail }] : [] })
    campaigns.value = data.campaigns; codeGroups.value = members; selectedTaskMembers.value = members
    const batchId = String(route.query.batch || activeTaskBatchId.value)
    selectedGroup.value = members.find(m => String(m.detail.batch.id) === batchId) || members[0]
    activeTaskBatchId.value = String(selectedGroup.value?.detail.batch.id || '')
    clearFailedIssueSelection()
    verifyDetailPublication(selectedGroup.value)
    if (!members.length) codeGroupLoadError.value = '此任务暂无配置'
  } catch (error) { codeGroupLoadError.value = error instanceof Error ? error.message : '任务读取失败，请重试' }
  finally { loading.value = false }
}
const filteredDetailIssues = computed(() => (selectedGroup.value?.detail.issues || []).filter(issue => {
  const text = detailSearch.value.trim().toLowerCase()
  return (!text || [issue.remoteConfigurationId, issue.redemptionCode, issue.tierName, issue.remoteConfigurationName, issue.remoteConfigurationRemark, issueRemark(issue)].some(value => String(value || '').toLowerCase().includes(text)))
    && (!detailDate.value || issue.claimDate === detailDate.value)
    && (!detailStatus.value || issueStatus(issue).text === detailStatus.value)
}))
const detailStatusOptions = computed(() => [...new Set((selectedGroup.value?.detail.issues || []).map(issue => issueStatus(issue).text))])
function selectableDetailIssue(issue: RedemptionCodeIssue) {
  return isFailedRemoteCreation(issue) || Boolean(canGenerate.value && issue.remoteConfigurationId && !deletionHeld(issue))
}
function updateDetailSelection(rows: RedemptionCodeIssue[]) {
  updateSelectedFailedIssues(rows)
  selectedDeletionIds.value = rows.filter(i => i.remoteConfigurationId && !deletionHeld(i)).map(i => i.id)
}
function showTaskDeletion(issueIds?: Array<string | number>, startNew = true) {
  if (selectedTaskId.value == null || !canGenerate.value) return
  if (issueIds && !issueIds.length) return
  taskDeletionTarget.value = { taskId: selectedTaskId.value, taskNumber: selectedTaskDisplayId.value, issueIds: issueIds ? [...issueIds] : undefined, startNew }
  deletionPanelKey.value++; detailPane.value = 'deletion'
}
function closeTaskDeletion() { taskDeletionTarget.value = undefined; detailPane.value = 'configurations' }
watch([detailSearch, detailDate, detailStatus], clearFailedIssueSelection)

async function openTaskDetail(task: CodeGroupTask, preferredBatchId?: string | number) {
  clearFailedIssueSelection()
  const members = await Promise.all(task.members.map(async (member) => ({
    campaign: member.campaign,
    detail: await api.redemption.batch(member.detail.batch.id),
  })))
  selectedTaskMembers.value = members
  selectedGroup.value = members.find(member => String(member.detail.batch.id) === String(preferredBatchId)) || members[0]
  activeTaskBatchId.value = selectedGroup.value ? String(selectedGroup.value.detail.batch.id) : ''

}

function selectTaskMember(batchId: string | number) {
  const member = selectedTaskMembers.value.find((item) => String(item.detail.batch.id) === String(batchId))
  if (member) {
    clearFailedIssueSelection()
    selectedGroup.value = member
    verifyDetailPublication(member)
    if (detailMode.value) void router.replace({ query: { ...route.query, batch: String(batchId) } })
  }
}

function replaceCodeGroup(replacement: CodeGroupRow) {
  codeGroups.value = codeGroups.value.map((item) => item.detail.batch.id === replacement.detail.batch.id ? replacement : item)
  if (verificationTarget.value?.detail.batch.id === replacement.detail.batch.id) verificationTarget.value = replacement
  selectedTaskMembers.value = selectedTaskMembers.value.map((item) => item.detail.batch.id === replacement.detail.batch.id ? replacement : item)
  if (selectedGroup.value?.detail.batch.id === replacement.detail.batch.id) {
    selectedGroup.value = replacement
    clearFailedIssueSelection()
  }
}

const checkingRewardPolicy = ref(false)
const applyingRewardPolicy = ref(false)
const rewardPolicyDialog = ref(false)
const rewardPolicyPlans = ref<RedemptionRewardPolicyView[]>([])
const rewardPolicyProgress = ref('')
function rewardPolicyIntent(view: RedemptionRewardPolicyView) {
  const { issueVersion, ownerVersion, batchVersion, sharedBatches, ...intent } = view.parameters
  return JSON.stringify(intent)
}
function rewardConfirmationKey(view: RedemptionRewardPolicyView) {
  return JSON.stringify([view.configurationId, view.previousMin, view.previousMax, rewardPolicyIntent(view)])
}
function rewardPolicySummary(plans: RedemptionRewardPolicyView[]) {
  return plans.map(plan => `${plan.parameters.marketName} ${plan.parameters.claimDate}：实际 ${plan.previousMin}–${plan.previousMax} → 本任务 ${plan.parameters.bonusMin}–${plan.parameters.bonusMax}，共享 ${plan.parameters.sharedBatches?.length || 0} 个批次`).join('\n')
}

/** Creation waits here for one explicit confirmation per market; cancellation leaves the durable pending state. */
async function confirmCreationRewards(initial: RedemptionBatchDetail): Promise<RedemptionBatchDetail | undefined> {
  let detail = await api.redemption.batch(initial.batch.id)
  const pending = detail.issues.filter(needsCreationRewardCheck)
  if (!pending.length) return detail
  const plans: RedemptionRewardPolicyView[] = []
  for (const issue of pending) {
    const plan = await api.redemption.checkRewardPolicy(issue.id)
    if (plan.status !== 'MATCHED') plans.push(plan)
  }
  if (plans.length) {
    if (plans.some(plan => !['CHECKED', 'UPDATED', 'UNCONFIRMED'].includes(plan.status))) {
      ElMessage.warning('奖励修改仍在执行或结果待核对，当前任务尚未完成，请稍后核验')
      return undefined
    }
    try {
      await ElMessageBox.confirm(
        `发现 ${plans.length} 条配置的实际奖励尚未满足本任务：\n${rewardPolicySummary(plans)}\n确认后按本任务奖励修改，共享这些配置的历史任务也会受到影响。保留原码、配置 ID 和库存。取消将保存进度并保持待确认状态。`,
        '确认修改同码配置的实际奖励',
        { type: 'warning', confirmButtonText: '确认修改并继续', cancelButtonText: '暂不修改', customClass: 'redemption-recovery-confirm' },
      )
    } catch {
      ElMessage.warning('已保存进度，奖励尚未确认，任务未完成；可从“核验实际奖励”继续')
      return undefined
    }
    for (const plan of plans) {
      const started = Date.now()
      const fresh = await api.redemption.checkRewardPolicy(plan.requestedIssueId)
      if (fresh.status === 'MATCHED') continue
      if (rewardConfirmationKey(fresh) !== rewardConfirmationKey(plan)) throw new Error('实际奖励、任务参数或共享范围已变化，请重新确认')
      if (!['CHECKED', 'UPDATED', 'UNCONFIRMED'].includes(fresh.status) || fresh.id == null || fresh.rowVersion == null)
        throw new Error('奖励修改尚未就绪，请核验后继续')
      detail = await api.redemption.applyRewardPolicy(fresh.requestedIssueId, fresh.id, fresh.rowVersion)
      if (detail.issues.some(issue => String(issue.id) === String(fresh.requestedIssueId) && needsCreationRewardCheck(issue)))
        throw new Error('修改后的实际奖励尚未核验一致，已停止后续处理')
      await wait(Math.max(0, Math.max(5, fresh.parameters.options.creationIntervalSeconds || 5) * 1000 - (Date.now() - started)))
    }
  }
  detail = await api.redemption.batch(initial.batch.id)
  if (detail.issues.some(needsCreationRewardCheck)) throw new Error('仍有实际奖励待核验或确认，当前任务未完成')
  return detail
}
async function openTaskRewardPolicies(task: CodeGroupTask) {
  await openTaskDetail(task)
  await inspectRewardPolicies()
}
async function inspectRewardPolicies(onlyIssue?: RedemptionCodeIssue) {
  if (!canGenerate.value || checkingRewardPolicy.value || applyingRewardPolicy.value) return
  const group = selectedGroup.value
  if (!group) return
  checkingRewardPolicy.value = true
  rewardPolicyDialog.value = true
  rewardPolicyPlans.value = []
  let checked = 0, matched = 0, unavailable = 0
  try {
    const members = onlyIssue ? [group] : selectedTaskMembers.value.length ? selectedTaskMembers.value : [group]
    for (const member of members) {
      const fresh = await api.redemption.batch(member.detail.batch.id)
      for (const issue of fresh.issues.filter(issue => !onlyIssue || String(issue.id) === String(onlyIssue.id))) {
        rewardPolicyProgress.value = `正在回读实际奖励 ${++checked} 条，已匹配 ${matched} 条`
        try {
          const plan = await api.redemption.checkRewardPolicy(issue.id, issue.rowVersion)
          if (plan.status === 'MATCHED' || plan.status === 'APPLIED') matched++
          else rewardPolicyPlans.value.push(plan)
        } catch { unavailable++ }
      }
    }
    rewardPolicyProgress.value = `已核验 ${checked} 条：${matched} 条实际匹配，${rewardPolicyPlans.value.length} 条需处理${unavailable ? `，${unavailable} 条不可核验，请先处理配置缺失或读取问题` : ''}。本次核验没有修改远端奖励。`
  } finally {
    checkingRewardPolicy.value = false
    await refreshRecoveryGroups()
  }
}
async function applyRewardPolicies() {
  if (checkingRewardPolicy.value || applyingRewardPolicy.value) return
  const candidates = rewardPolicyPlans.value.filter(plan => ['CHECKED', 'UPDATED', 'UNCONFIRMED'].includes(plan.status))
  if (!candidates.length) return
  try {
    await ElMessageBox.confirm(`确认处理 ${candidates.length} 条已有配置奖励：\n${rewardPolicySummary(candidates)}\n保留原配置 ID、原码、描述和库存；仅对齐奖励。结果未知的请求只核对回读，不重复提交。调整后仍需单独发布和下载核验。`, '确认修改实际奖励', { type: 'warning', confirmButtonText: '确认对齐奖励 / 恢复登记', cancelButtonText: '取消', customClass: 'redemption-recovery-confirm' })
  } catch { return }
  applyingRewardPolicy.value = true
  let done = 0
  let attempted: RedemptionRewardPolicyView | undefined
  try {
    for (const plan of candidates) {
      attempted = plan
      const started = Date.now()
      rewardPolicyProgress.value = `正在对齐奖励 ${done + 1} / ${candidates.length}；已完成 ${done} 条`
      const fresh = await api.redemption.checkRewardPolicy(plan.requestedIssueId)
      if (fresh.status === 'MATCHED' || fresh.status === 'APPLIED') { done++; continue }
      if (rewardConfirmationKey(fresh) !== rewardConfirmationKey(plan)) throw new Error('实际奖励、任务参数或共享范围已变化，请重新核验确认')
      if (fresh.id == null || fresh.rowVersion == null) throw new Error('奖励修改记录无效，请重新核验')
      const detail = await api.redemption.applyRewardPolicy(fresh.requestedIssueId, fresh.id, fresh.rowVersion)
      const member = selectedTaskMembers.value.find(member => String(member.detail.batch.id) === String(detail.batch.id))
      if (member) replaceCodeGroup({ campaign: member.campaign, detail })
      done++
      await wait(Math.max(0, Math.max(5, fresh.parameters.options.creationIntervalSeconds || 5) * 1000 - (Date.now() - started)))
    }
    rewardPolicyProgress.value = `已回读确认 ${done} 条实际奖励符合本次任务快照；请单独确认发布。`
    ElMessage.success(rewardPolicyProgress.value)
    rewardPolicyPlans.value = []
    rewardPolicyDialog.value = false
    await refreshRecoveryGroups()
    for (const member of selectedTaskMembers.value) {
      if (member.detail.issues.some(issue => issue.workflowStatus === 'PENDING_CREATION')) {
        if (!await generateCodes(member.detail)) break
      }
    }
  } catch (error) {
    if (attempted) {
      try { const latest = await api.redemption.checkRewardPolicy(attempted.requestedIssueId)
        rewardPolicyPlans.value = rewardPolicyPlans.value.map(plan => String(plan.requestedIssueId) === String(latest.requestedIssueId) ? latest : plan)
      } catch { /* leave the durable state for the next explicit check */ }
    }
    rewardPolicyProgress.value = `已保存 ${done} 条进度；${error instanceof Error ? error.message : '奖励修改中断'}。请核验后继续。`
    ElMessage.warning(rewardPolicyProgress.value)
  } finally {
    applyingRewardPolicy.value = false
    await refreshRecoveryGroups()
  }
}

const deletingIssueId = ref<string | number>()
async function deleteRemoteConfiguration(issue: RedemptionCodeIssue) {
  if (!canGenerate.value || deletingIssueId.value || !issue.remoteConfigurationId) return
  if (detailMode.value) { showTaskDeletion([issue.id]); return }
  deletingIssueId.value = issue.id
  try {
    if (deletionHeld(issue)) {
      const result = await api.redemption.reconcileDeletion(issue.id)
      ElMessage.info(result.message)
      return
    }
    const plan = await api.redemption.previewDeletion(issue.id, issue.rowVersion)
    if (plan.status !== 'CHECKED') { ElMessage.warning(plan.message); return }
    const related = plan.parameters.sharedBatches?.map(batch => `#${batch.id}`).join('、') || '—'
    try {
      await ElMessageBox.confirm(`即将永久删除 ${plan.parameters.marketName} 的配置 ${plan.configurationId}（${plan.remote.description || issue.tierName || '—'}，指定码 ${plan.remote.giftCode || '普通兑换码'}）。共享批次：${related}，共 ${plan.parameters.sharedBatches?.length || 0} 个。所有共享任务都会受到影响。原码、历史库存和审计保留，删除后本系统将阻止继续发布、下载和自动重建。已发布的兑换码是否立即失效需单独核验。此操作不可恢复。`, '确认永久删除远端配置', { type: 'warning', confirmButtonText: `确认真删除 ${plan.configurationId}`, cancelButtonText: '取消', customClass: 'redemption-recovery-confirm' })
    } catch { return }
    const result = await api.redemption.confirmDeletion(issue.id, plan)
    ElMessage.success(result.message)
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : '删除未完成，请核对结果')
  } finally {
    deletingIssueId.value = undefined
    await refreshRecoveryGroups()
  }
}

const checkingRecovery = ref(false)
const rebuildingMissing = ref(false)
const recoveryDialogVisible = ref(false)
const recoveryViews = ref<RedemptionRecoveryView[]>([])
const recoveryProgress = ref('')
function recoveryStatusLabel(status: string) {
  return ({ CHECK_UNAVAILABLE: '核验不可用', PRESENT: '配置仍存在', MISSING: '配置缺失，待重建', CREATING: '重建中', UNCONFIRMED: '创建结果待核对', RECEIPT_SAVED: '登记待恢复', APPLYING: '登记中', COMPLETED: '重建完成，待发布' } as Record<string, string>)[status] || status
}
function taskRecoveries(task: CodeGroupTask) {
  return task.members.flatMap(member => member.detail.issues).filter(issue => issue.recovery && !['PRESENT', 'COMPLETED'].includes(issue.recovery.status))
}
async function openTaskRecovery(task: CodeGroupTask) {
  await openTaskDetail(task)
  await inspectMissingConfigurations()
}
function recoveryParameterKey(view: RedemptionRecoveryView) {
  const { issueVersion, ownerVersion, batchVersion, sharedBatches, ...parameters } = view.parameters
  return JSON.stringify(parameters)
}
async function inspectMissingConfigurations(onlyIssue?: RedemptionCodeIssue) {
  if (checkingRecovery.value || rebuildingMissing.value || !canGenerate.value) return
  const group = selectedGroup.value
  if (!group) return
  checkingRecovery.value = true
  recoveryViews.value = []
  recoveryDialogVisible.value = true
  const members = onlyIssue ? [group] : selectedTaskMembers.value.length ? selectedTaskMembers.value : [group]
  let checked = 0, unavailable = 0
  const seen = new Set<string>()
  try {
    for (const member of members) {
      const fresh = await api.redemption.batch(member.detail.batch.id)
      for (const issue of fresh.issues.filter(issue => !onlyIssue || String(issue.id) === String(onlyIssue.id))) {
        const identity = `${fresh.batch.remoteMarketCode}:${issue.reusedFromIssueId || issue.id}`
        if (seen.has(identity)) continue
        seen.add(identity)
        recoveryProgress.value = `正在核验 ${++checked} 条，已发现 ${recoveryViews.value.filter(view => view.status === 'MISSING').length} 条缺失`
        try {
          const view = await api.redemption.inspectRecovery(issue.id, issue.rowVersion)
          if (view.status !== 'PRESENT' && view.status !== 'COMPLETED') recoveryViews.value.push(view)
        } catch { unavailable++ }
      }
    }
    const count = recoveryViews.value.filter(view => view.status === 'MISSING').length
    recoveryProgress.value = `已保存进度：核验 ${checked} 条，${count} 条旧配置确认缺失${unavailable ? `，${unavailable} 条未取得有效核验` : ''}。${count ? '请点击“重试并重建”，按本次任务参数重新创建缺失部分。' : '已有配置保持当前状态。'}`
  } finally {
    checkingRecovery.value = false
    await refreshRecoveryGroups()
  }
}
async function refreshRecoveryGroups() {
  const members = selectedTaskMembers.value.length ? [...selectedTaskMembers.value] : selectedGroup.value ? [selectedGroup.value] : []
  for (const member of members) {
    try { replaceCodeGroup({ campaign: member.campaign, detail: await api.redemption.batch(member.detail.batch.id) }) } catch { /* the persistent journal remains available on refresh */ }
  }
  await loadCodeGroups()
}
async function rebuildMissingConfigurations() {
  if (rebuildingMissing.value || checkingRecovery.value) return
  const candidates = recoveryViews.value.filter(view => ['MISSING', 'RECEIPT_SAVED'].includes(view.status))
  if (!candidates.length) return
  const descriptions = candidates.map(view => {
    const p = view.parameters
    return `${p.marketName} · ${p.claimDate} · 奖励 ${p.bonusMin}–${p.bonusMax} · 每码 ${p.options.singleKeyLimit} 次 / 每用户 ${p.options.singleUserLimit} 次 · 每组 ${p.options.keyNumber} 码 · ${p.validFrom} 至 ${p.validTo} · ${p.labels.length ? '标签 ' + p.labels.join('、') : '全部用户'} · 影响 ${view.relatedBatchCount} 个共享批次`
  })
  try {
    await ElMessageBox.confirm(`将按以下任务快照处理 ${candidates.length} 条配置：\n${descriptions.join('\n')}\n保留旧身份和历史库存；已有回执仅恢复登记。创建后仍需单独确认发布。`, '确认重试并重建', { type: 'warning', confirmButtonText: '确认重新创建 / 恢复登记', cancelButtonText: '取消', customClass: 'redemption-recovery-confirm' })
  } catch { return }
  rebuildingMissing.value = true
  let completed = 0
  let attempted: RedemptionRecoveryView | undefined
  try {
    for (const preview of candidates) {
      attempted = preview
      recoveryProgress.value = `正在恢复 ${completed + 1} / ${candidates.length}，已登记 ${completed} 条`
      const fresh = await api.redemption.inspectRecovery(preview.requestedIssueId)
      if (fresh.status === 'PRESENT' || fresh.status === 'COMPLETED') continue
      if (recoveryParameterKey(fresh) !== recoveryParameterKey(preview)) throw new Error('任务参数已变化，请重新核验并确认')
      const detail = await api.redemption.rebuildMissing(fresh.requestedIssueId, fresh.id, fresh.rowVersion)
      const member = selectedTaskMembers.value.find(member => String(member.detail.batch.id) === String(detail.batch.id))
      if (member) replaceCodeGroup({ campaign: member.campaign, detail })
      completed++
    }
    recoveryProgress.value = `已恢复登记 ${completed} 条，正在继续本任务余下的待创建项。创建完成后请单独确认发布。`
    let continuationStopped = false
    for (const member of [...selectedTaskMembers.value]) {
      const detail = await api.redemption.batch(member.detail.batch.id)
      if (detail.issues.some(issue => issue.workflowStatus === 'RECOVERY_REQUIRED')
          || detail.issues.some(issue => issue.workflowStatus === 'PENDING_CREATION') && !await generateCodes(detail)) {
        continuationStopped = true
        break
      }
    }
    if (continuationStopped) {
      recoveryProgress.value = `已保存进度：${completed} 条重建已登记，余下配置尚未完成，请查看任务原因后重试。`
      ElMessage.warning(recoveryProgress.value)
      return
    }
    ElMessage.success(`已恢复登记 ${completed} 条；创建结果请查看任务明细，发布需单独确认`)
    recoveryViews.value = []
    recoveryDialogVisible.value = false
  } catch (error) {
    if (attempted) {
      try {
        const fresh = await api.redemption.inspectRecovery(attempted.requestedIssueId)
        recoveryViews.value = recoveryViews.value.map(view => String(view.id) === String(fresh.id) ? fresh : view)
      } catch { /* keep the last confirmed journal state */ }
    }
    recoveryProgress.value = `已保存 ${completed} 条进度；${error instanceof Error ? error.message : '恢复中断，请重新核验'}。请重新核验后重试。`
    ElMessage.warning(recoveryProgress.value)
  } finally {
    rebuildingMissing.value = false
    await refreshRecoveryGroups()
  }
}

const reusingConfigurations = ref(false)
const reuseCheckErrors = ref<Record<string, string>>({})
function canReuseExistingConfiguration(issue: RedemptionCodeIssue) {
  return canGenerate.value && issue.overviewCount === undefined && !issue.reusedFromIssueId && issue.rowVersion !== undefined
    && (needsCreationReconciliation(issue) || !issue.remoteConfigurationId)
    && ['PENDING_CREATION', 'FAILED', 'CREATING_REMOTE', 'CREATED'].includes(issue.workflowStatus || '')
}
function reusedIssueLimitLabel(group: CodeGroupRow, issue: RedemptionCodeIssue) {
  return issue.reusedFromIssueId ? '沿用远端已有配置' : singleKeyLimitLabel(group)
}
function reuseOrigin(issue: RedemptionCodeIssue) {
  if (issue.recovery?.status === 'COMPLETED') return `已按重建任务快照创建新配置 ${issue.recovery.newConfigurationId}；${issue.recovery.reason}`
  if (!issue.reusedFromIssueId) return ''
  const origin = codeGroups.value.find(row => String(row.detail.batch.id) === String(issue.reusedFromBatchId))
  const source = origin?.detail.batch.taskNumber ? `复用任务 ${origin.detail.batch.taskNumber}` : '已复用现有配置'
  return `${source}；实际奖励须与本任务一致，领取次数、标签及有效期沿用远端已有配置`
}
async function reuseExistingConfigurations(onlyIssue?: RedemptionCodeIssue) {
  const group = selectedGroup.value
  if (!group || reusingConfigurations.value || isProcessing(group)) return
  reusingConfigurations.value = true
  let matched = 0
  let unresolved = 0
  try {
    const fresh = await api.redemption.batch(group.detail.batch.id)
    replaceCodeGroup({ campaign: group.campaign, detail: fresh })
    const candidates = fresh.issues.filter(issue => canReuseExistingConfiguration(issue)
      && (!onlyIssue || String(issue.id) === String(onlyIssue.id)))
    for (const issue of candidates) {
      try {
        let detail: RedemptionBatchDetail
        try { detail = await api.redemption.reuseExistingConfiguration(issue.id, issue.rowVersion!) }
        catch (failure) {
          const problem = failure as { code?: string; details?: { candidates?: Array<{configurationId: string}> } }
          if (!onlyIssue || problem.code !== 'REUSE_AMBIGUOUS_CONFIGURATION') throw failure
          const ids = [...new Set((problem.details?.candidates || []).map(c => c.configurationId))]
          if (!ids.length) throw failure
          const { value } = await ElMessageBox.prompt(
            `本地有多个同码历史配置：${ids.join('、')}。请输入你已核验仍存在且要沿用的配置 ID。系统会再次回读并检查任务参数、共享身份和删除保护；本次不会新建或修改远端配置。`,
            '明确选择复用配置', { inputValidator: value => ids.includes(value.trim()) || '请输入清单中的配置 ID', confirmButtonText: '核验并关联所选配置', cancelButtonText: '取消' })
          detail = await api.redemption.reuseExistingConfiguration(issue.id, issue.rowVersion!, value.trim())
        }
        replaceCodeGroup({ campaign: group.campaign, detail })
        delete reuseCheckErrors.value[String(issue.id)]
        matched++
      } catch (error) {
        unresolved++
        reuseCheckErrors.value[String(issue.id)] = error instanceof Error ? error.message : '配置复用核验失败'
      }
    }
    const verified = await confirmCreationRewards(await api.redemption.batch(group.detail.batch.id))
    if (!verified) return
    replaceCodeGroup({ campaign: group.campaign, detail: verified })
    const message = `已复用 ${matched} 条配置${unresolved ? `，${unresolved} 条未关联，请查看核验说明` : ''}`
    if (unresolved) ElMessage.warning(message)
    else ElMessage.success(message)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '读取任务失败')
  } finally {
    reusingConfigurations.value = false
    try { await loadCodeGroups() } catch { ElMessage.warning('列表刷新失败，请手动刷新') }
  }
}

async function retryRemoteCreation(issue: RedemptionCodeIssue) {
  const group = selectedGroup.value
  if (!group || !canRetryRemoteCreation(issue)) return
  if (issue.workflowStatus === 'CREATING_REMOTE' || isRepairing(group)) {
    try {
      await ElMessageBox.confirm(`请先在远端后台确认“${issue.remoteConfigurationName || issue.tierName || '该配置'}”（备注：${issue.remoteConfigurationRemark || '未记录'}）仍不存在。上次请求结果可能不确定；确认后才会恢复或重试创建。`, '核对后重试创建', { type: 'warning', confirmButtonText: '已核对，确认重试', cancelButtonText: '取消' })
    } catch {
      return
    }
  }
  retryingIssueId.value = issue.id
  try {
    const review = await checkPendingCreationDuplicates(await api.redemption.batch(group.detail.batch.id))
    if (review === false) return
    const created = await api.redemption.createRemoteConfiguration(issue.id, true, review)
    const detail = await confirmCreationRewards(created)
    if (!detail) return
    const replacement = { campaign: group.campaign, detail }
    replaceCodeGroup(replacement)
    ElMessage.success(detail.issues.find(item => String(item.id) === String(issue.id))?.reusedFromIssueId ? '已复用现有配置' : '已重新创建远端兑换码配置')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重试创建远端配置失败')
  } finally {
    retryingIssueId.value = undefined
    try {
      replaceCodeGroup({ campaign: group.campaign, detail: await api.redemption.batch(group.detail.batch.id) })
      await loadCodeGroups()
    } catch { ElMessage.warning('任务明细刷新失败，请点击刷新查看最新状态') }
  }
}

async function createOnePendingRemoteConfiguration(issue: RedemptionCodeIssue) {
  const group = selectedGroup.value
  if (!group || !canCreatePendingRemoteConfiguration(issue)) return
  retryingIssueId.value = issue.id
  markProcessing(group.detail.batch.id, true)
  try {
    const fresh = await api.redemption.batch(group.detail.batch.id)
    replaceCodeGroup({ campaign: group.campaign, detail: fresh })
    if (!canContinuePendingCreation({ campaign: group.campaign, detail: fresh })
      || !uncreatedIssues({ campaign: group.campaign, detail: fresh }).some(item => String(item.id) === String(issue.id))) {
      ElMessage.warning('任务状态已变化，请查看最新明细')
      return
    }
    const detail = await api.redemption.createRemoteConfiguration(issue.id)
    replaceCodeGroup({ campaign: group.campaign, detail })
    ElMessage.success('本条配置已处理，请核对明细；其余待创建项保留')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '单条配置创建失败，请核对最新明细')
  } finally {
    retryingIssueId.value = undefined
    markProcessing(group.detail.batch.id, false)
    try {
      replaceCodeGroup({ campaign: group.campaign, detail: await api.redemption.batch(group.detail.batch.id) })
      await loadCodeGroups()
    } catch { ElMessage.warning('任务明细刷新失败，请点击刷新查看最新状态') }
  }
}

async function continuePendingCreation(row: CodeGroupRow) {
  if (!canContinuePendingCreation(row) || isProcessing(row) || continuingCreationBatchId.value !== undefined) return
  const batchId = row.detail.batch.id
  continuingCreationBatchId.value = batchId
  markProcessing(batchId, true)
  try {
    let current = { campaign: row.campaign, detail: await api.redemption.batch(batchId) }
    replaceCodeGroup(current)
    if (!canContinuePendingCreation(current)) { ElMessage.warning('任务状态已变化，请查看最新明细'); return }
    const targets = uncreatedIssues(current).map(issue => issue.id)
    const review = await checkPendingCreationDuplicates(current.detail)
    if (review === false) return
    try {
      await ElMessageBox.confirm(
        `将继续创建 ${remoteMarketLabel(row)} 的 ${targets.length} 条待创建配置。已有配置将保留；下载时可选择是否先发布。`,
        '继续创建剩余配置', { type: 'warning', confirmButtonText: '继续创建', cancelButtonText: '取消' },
      )
    } catch { return }
    for (const [index, issueId] of targets.entries()) {
      // Refresh after confirmation and between writes; another page may have made progress.
      current = { campaign: row.campaign, detail: await api.redemption.batch(batchId) }
      replaceCodeGroup(current)
      if (current.detail.batch.status !== 'CREATING' || current.detail.batch.publishedAt || hasRemoteCreationInProgress(current)) {
        ElMessage.warning('任务状态已变化，已停止继续创建，请查看最新明细')
        return
      }
      if (!uncreatedIssues(current).some(issue => String(issue.id) === String(issueId))) continue
      const requestStartedAt = Date.now()
      current.detail = await api.redemption.createRemoteConfiguration(issueId, false, review)
      replaceCodeGroup(current)
      if (index < targets.length - 1) {
        const intervalMs = Math.max(1, current.detail.batch.remoteOptions?.creationIntervalSeconds ?? 5) * 1000
        await wait(Math.max(0, intervalMs - (Date.now() - requestStartedAt)))
      }
    }
    const verified = await confirmCreationRewards(current.detail)
    if (!verified) return
    current.detail = verified
    replaceCodeGroup(current)
    ElMessage.success(current.detail.batch.status === 'READY_TO_PUBLISH'
      ? '剩余配置已创建完成，下载时可选择是否先发布' : '本次待创建项已处理，请查看最新任务明细')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '继续创建失败，请查看最新明细后处理')
  } finally {
    try {
      replaceCodeGroup({ campaign: row.campaign, detail: await api.redemption.batch(batchId) })
      await loadCodeGroups()
    } catch { ElMessage.warning('任务明细刷新失败，请点击刷新查看最新状态') }
    continuingCreationBatchId.value = undefined
    markProcessing(batchId, false)
  }
}

async function retrySelectedFailedRemoteCreations() {
  const group = selectedGroup.value
  if (!group) return
  if (isRepairing(group)) { ElMessage.warning('补齐流程中请逐条核对远端后重试创建'); return }
  const targets = selectedFailedRemoteCreations().map((issue) => ({ row: group, issue }))
  if (!targets.length) return
  try {
    await ElMessageBox.confirm(
      `将逐项重试当前盘口中已选的 ${targets.length} 条失败子任务。该操作会再次请求远端创建；如之前请求的结果不确定，请先在远端后台确认不存在同名配置，以避免重复创建。`,
      '批量重试失败子任务',
      { type: 'warning', confirmButtonText: '确认重试', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  markProcessing(group.detail.batch.id, true)
  retryingSelectedFailedTasks.value = true
  let succeeded = 0
  const failures: string[] = []
  try {
    const review = await checkPendingCreationDuplicates(await api.redemption.batch(group.detail.batch.id))
    if (review === false) return
    for (const [index, { row, issue }] of targets.entries()) {
      const requestStartedAt = Date.now()
      try {
        const detail = await api.redemption.createRemoteConfiguration(issue.id, true, review)
        replaceCodeGroup({ campaign: row.campaign, detail })
        succeeded += 1
      } catch (error) {
        failures.push(`${remoteMarketLabel(row)} · ${formatDate(issue.claimDate)}：${error instanceof Error ? error.message : '重试失败'}`)
        break
      }
      if (index < targets.length - 1) {
        const intervalMs = Math.max(1, row.detail.batch.remoteOptions?.creationIntervalSeconds ?? form.value.remoteOptions.creationIntervalSeconds ?? 5) * 1000
        await wait(Math.max(0, intervalMs - (Date.now() - requestStartedAt)))
      }
    }
    if (!failures.length) {
      const verified = await confirmCreationRewards(await api.redemption.batch(group.detail.batch.id))
      if (!verified) return
      replaceCodeGroup({ campaign: group.campaign, detail: verified })
    }
    ElMessage[failures.length ? 'warning' : 'success'](failures.length
      ? `${succeeded} 条已选任务重试成功，已停止后续重试：${failures.join('；')}`
      : `${succeeded} 条已选失败任务已全部重新创建，下载时可选择是否先发布`)
  } finally {
    retryingSelectedFailedTasks.value = false
    markProcessing(group.detail.batch.id, false)
    clearFailedIssueSelection()
    await loadCodeGroups()
  }
}

function chooseDownload(choice?: DownloadChoice) {
  const resolve = resolveDownloadChoice
  resolveDownloadChoice = undefined
  downloadDecision.value = undefined
  resolve?.(choice)
}
function canStartDownload(row: CodeGroupRow) {
  if (row.detail.issues.some(deletionHeld)) return false
  if (isSuccess(row)) return true
  return canGenerate.value && ['READY_TO_PUBLISH', 'PUBLISHED'].includes(row.detail.batch.status)
    && !hasPendingPublishReservation(row) && !creationRewardIssues(row).length
}
async function requestDownload(target: CodeGroupRow | CodeGroupTask, excel: boolean) {
  if (downloadingTask.value) return
  downloadingTask.value = true
  verificationDialogVisible.value = false
  try {
    const members = 'members' in target ? target.members : [target]
    for (const member of members) {
      let row = { campaign: member.campaign, detail: await api.redemption.batch(member.detail.batch.id) }
      if (!canStartDownload(row)) throw new Error('请先完成配置创建与奖励核验')
      const batch = row.detail.batch
      const receipt = batch.remotePublishTaskId
      if (isSuccess(row) && (!batch.remoteConnectionId || (!receipt && batch.publishedAt && !row.detail.allImportedDirectly))) continue
      if (batch.status === 'PUBLISHED' && !receipt && canDownloadScheduledCodes(row)) {
        if (!await downloadPublishedCodes(row)) return
        continue
      }
      const check = receipt && canGenerate.value ? await verifyRemotePublication(row, true) : undefined
      let direct = false
      if (check?.publicationState !== 'COMPLETED') {
        const failed = check?.publicationState === 'FAILED' || check?.publicationState === 'CANCELLED'
        const choice = await new Promise<DownloadChoice | undefined>(resolve => {
          resolveDownloadChoice = resolve
          downloadDecision.value = {
            market: remoteMarketLabel(row),
            state: receipt ? publicationLabel(check) : batch.remotePublishError ? '发布不成功' : '未关联发布任务',
            canRegister: canLinkExternal(row),
            canPublish: canGenerate.value && !hasPendingPublishReservation(row) && (failed || (!receipt && batch.status !== 'PUBLISHED')),
          }
        })
        if (!choice) return
        direct = choice === 'direct'
        if (choice === 'manual') {
          const linked = await new Promise<CodeGroupRow | undefined>(resolve => openExternalPublication(row, resolve))
          if (!linked) return
          row = linked
        }
        if (choice === 'publish') {
          row.detail = await api.redemption.publishRemoteBatch(batch.id, batch.rowVersion, 'IMMEDIATE', undefined, false, failed ? receipt || undefined : undefined)
          replaceCodeGroup(row)
          const published = await verifyRemotePublication(row, true)
          if (published?.publicationState !== 'COMPLETED') throw new Error('发布已提交，尚未核验为发布完成。可稍后继续下载。')
        }
      }
      if (isSuccess(row)) continue
      if (direct) {
        markProcessing(batch.id, true)
        try {
          for (const issue of row.detail.issues.filter(item => item.workflowStatus !== 'CODE_IMPORTED')) {
            row.detail = await api.redemption.downloadRemoteCode(issue.id, true)
            replaceCodeGroup(row)
          }
        } finally { markProcessing(batch.id, false) }
        if (!isSuccess(row)) throw new Error('兑换码尚未全部入库，请查看配置明细')
      } else if (!await downloadPublishedCodes(row)) return
    }
    if (excel) {
      if ('members' in target) await exportMultiMarketGroup(target)
      else await exportGroup(target)
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error instanceof Error ? error.message : '下载失败，请检查当前盘口')
  } finally { downloadingTask.value = false }
}

async function exportMultiMarketGroup(task: CodeGroupTask) {
  const groupKey = task.exportGroupKey
  if (!groupKey) return
  exportingGroupKey.value = groupKey
  try {
    saveDownloadedFile(await api.redemption.exportMultiMarketGroup(groupKey))
    ElMessage.success('多盘口兑换码 Excel 已开始下载，每个盘口分别保存为一个 Sheet')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '多盘口兑换码 Excel 处理失败')
  } finally {
    exportingGroupKey.value = undefined
  }
}

async function exportGroup(row: CodeGroupRow) {
  exportingId.value = row.detail.batch.id
  try {
    saveDownloadedFile(await api.redemption.exportBatch(row.detail.batch.id))
    ElMessage.success('兑换码 Excel 已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '兑换码 Excel 处理失败')
  } finally {
    exportingId.value = undefined
  }
}

async function acceptAvailableCodes(row: CodeGroupRow) {
  resolvingMissingBatchId.value = row.detail.batch.id
  try {
    // A configuration already matched by the fresh remote check may still need its codes imported.
    if (canDownloadScheduledCodes(row)) await downloadPublishedCodes(row)
    const detail = await api.redemption.batch(row.detail.batch.id)
    replaceCodeGroup({ campaign: row.campaign, detail })
    if (!detail.issues.some(issue => issue.workflowStatus === 'CODE_IMPORTED' && Boolean(issue.redemptionCode))) {
      ElMessage.warning('当前没有已入库的兑换码可下载')
      return
    }
    saveDownloadedFile(await api.redemption.exportAvailableBatch(detail.batch.id))
    ElMessage.success('已下载当前已入库的兑换码；未补齐配置列在文件的“未补齐配置”工作表，任务继续保留待补齐状态')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '下载现有兑换码失败') }
  finally { resolvingMissingBatchId.value = undefined }
}

function hasPendingScheduledConflict(message?: string) {
  return Boolean(message?.includes('同个配置有等待发布的定时任务'))
}

async function continueMissingConfigurationRepair(row: CodeGroupRow) {
  resolvingMissingBatchId.value = row.detail.batch.id
  let detail = row.detail
  try {
    if (row.detail.overview) { row = await loadFullGroup(row); detail = row.detail }
    // Each POST is separately recorded. A failed or uncertain create stops before any publish call.
    const pending = detail.issues.filter(item => item.workflowStatus === 'PENDING_CREATION')
    for (const [index, issue] of pending.entries()) {
      if (!issue.id) throw new Error('缺失配置任务缺少本地 ID，请刷新后重试')
      detail = await api.redemption.createRemoteConfiguration(issue.id, issue.workflowStatus === 'FAILED')
      replaceCodeGroup({ campaign: row.campaign, detail })
      if (index < pending.length - 1) await new Promise(resolve => window.setTimeout(resolve, Math.max(1, detail.batch.remoteOptions?.creationIntervalSeconds ?? 5) * 1000))
    }
    const verified = await confirmCreationRewards(detail)
    if (!verified) return
    detail = verified
    if (!detail.issues.some(item => item.workflowStatus === 'CREATED')
      || detail.issues.some(item => !['CREATED', 'PUBLISHED', 'CODE_IMPORTED'].includes(item.workflowStatus || ''))) {
      ElMessage.warning('仍有配置待创建或待核对，暂不能重新发布')
      return
    }
    const replacement = { campaign: row.campaign, detail }
    replaceCodeGroup(replacement)
    openPublishDialog(replacement)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '补齐配置失败；任务已保留当前进度，可在明细中继续处理')
  } finally {
    resolvingMissingBatchId.value = undefined
    await loadCodeGroups()
  }
}

async function regenerateMissingConfigurations(row: CodeGroupRow) {
  try {
    await ElMessageBox.confirm(
      '仅针对本次核验确认为“远端未找到”、且兑换码尚未入库的配置重建。新配置会获得新的远端 ID，原 ID 保存在操作审计中；重建失败时不会自动发布。确定继续吗？',
      '重建缺失配置', { type: 'warning', confirmButtonText: '确认重建', cancelButtonText: '取消' },
    )
  } catch { return }
  resolvingMissingBatchId.value = row.detail.batch.id
  try {
    const current = await api.redemption.batch(row.detail.batch.id)
    const started = await api.redemption.startMissingConfigurationRepair(current.batch.id, current.batch.rowVersion)
    delete publicationChecks.value[String(current.batch.id)]
    verificationDialogVisible.value = false
    const replacement = { campaign: row.campaign, detail: started }
    replaceCodeGroup(replacement)
    await continueMissingConfigurationRepair(replacement)
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '重建缺失配置失败') }
  finally { resolvingMissingBatchId.value = undefined }
}

onMounted(async () => {
  resizeTaskDetail()
  window.addEventListener('resize', resizeTaskDetail)
  indiaNow.value = indiaNowText()
  indiaClock = window.setInterval(() => { indiaNow.value = indiaNowText() }, 15_000)
  if (detailMode.value) await loadTaskDetail()
  else await Promise.all([loadCodeGroups(), loadRemoteConnections()])
  await nextTick()
  taskTable.value?.scrollToTop(taskTableScroll.value)
})

onUnmounted(() => {
  chooseDownload()
  finishRegistration()
  window.removeEventListener('resize', resizeTaskDetail)
  if (indiaClock) window.clearInterval(indiaClock)
})
</script>

<template>
  <section class="redemption-page" :class="{ 'task-detail-page': detailMode }">
    <template v-if="!detailMode">
    <div class="page-title-row">
      <div>
        <h2>兑换码管理</h2>
        <p class="page-subtitle">按开始兑换日、用户类型和兑换金额批量创建兑换码组；远端生效时间可跟随开始兑换日或单独设置。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadCodeGroups">刷新</el-button>
        <el-button v-if="canGenerate" type="primary" :icon="Plus" @click="openCodeGroupDialog">批量生成兑换码组</el-button>
      </div>
    </div>

    <el-alert class="redemption-alert" type="info" :closable="false" show-icon>
      <template #title>批量生成流程</template>
      系统将为每个开始兑换日 × 用户类型/标签档位创建远端配置，并为每条兑换码自动写入独立的描述和备注。远端生效时间默认是开始兑换日当天，也可在生成时设置相对有效期。配置全部创建后，下载时可选择是否先发布。
    </el-alert>

    <article class="panel code-group-list">
      <header class="code-group-list__heading">
        <div>
          <h3>批量生成兑换码组任务</h3>
          <p>分别显示远端发布结果与兑换码下载状态；点击下载 Excel 可取码并导出。</p>
        </div>
        <span class="code-group-list__count">{{ loading && !codeGroupTasks.length ? '正在加载任务…' : codeGroupLoadError && !codeGroupTasks.length ? '任务读取失败' : `共 ${codeGroupTasks.length} 个兑换码组任务` }}</span>
      </header>

      <el-alert v-if="codeGroupLoadError" type="error" :closable="false" show-icon :title="codeGroupLoadError" />
      <div v-if="codeGroupTasks.length" v-loading="loading" class="code-group-virtual-table">
        <el-auto-resizer>
          <template #default="{ height, width }">
            <el-table-v2
              ref="taskTable"
              @scroll="trackTaskScroll"
              :columns="codeGroupTaskColumns"
              :data="paginatedCodeGroupTasks"
              :width="width"
              :height="height"
              :header-height="42"
              :row-height="94"
              row-key="id"
              fixed
              scrollbar-always-on
              class="code-group-table"
            >
              <template #cell="{ column, rowData: row }">
                <span v-if="column.key === 'taskId'">{{ taskDisplayId(row) }}</span>
                <span v-else-if="column.key === 'operator'" class="virtual-cell">{{ taskOperator(row) }}</span>
                <div v-else-if="column.key === 'name'" class="group-name">
                  <strong>{{ taskName(row) }}</strong>
                  <span>{{ taskSummary(row) }}</span>
                </div>
                <span v-else-if="column.key === 'claimDate'" class="virtual-cell" :title="`${formatDate(taskPrimary(row).detail.batch.claimDateFrom)} 至 ${formatDate(taskPrimary(row).detail.batch.claimDateTo)}`">{{ formatDate(taskPrimary(row).detail.batch.claimDateFrom) }} 至 {{ formatDate(taskPrimary(row).detail.batch.claimDateTo) }}</span>
                <span v-else-if="column.key === 'account'" class="virtual-cell" :title="taskAccounts(row)">{{ taskAccounts(row) }}</span>
                <span v-else-if="column.key === 'market'" class="virtual-cell" :title="taskMarkets(row)">{{ taskMarkets(row) }}</span>
                <div v-else-if="column.key === 'status'" class="publication-status-cell">
                  <el-tag :type="taskStatus(row).type" effect="light">{{ taskStatus(row).text }}</el-tag>
                  <small v-if="taskRecoveries(row).length" class="creation-status-summary" :title="taskRecoveries(row)[0]?.recovery?.reason">{{ taskRecoveries(row)[0]?.recovery?.reason }}</small>
                  <small v-if="taskCreationSummary(row)" class="creation-status-summary" :title="taskCreationSummary(row)">{{ taskCreationSummary(row) }}</small>
                  <small v-if="taskAcquisitionStatus(row)">{{ taskAcquisitionStatus(row) }}</small>
                </div>
                <span v-else-if="column.key === 'labels'" class="virtual-cell" :title="taskLabels(row)">{{ taskLabels(row) }}</span>
                <span v-else-if="column.key === 'redemptionType'" class="virtual-cell">{{ redemptionTypeLabel(taskPrimary(row).detail.batch.redemptionType) }}</span>
                <span v-else-if="column.key === 'singleKeyLimit'" class="virtual-cell" :title="taskSingleKeyLimit(row)">{{ taskSingleKeyLimit(row) }}</span>
                <span v-else-if="column.key === 'tiers'" class="virtual-cell" :title="taskTiers(row)">{{ taskTiers(row) }}</span>
                <span v-else-if="column.key === 'progress'" class="group-progress">{{ taskProgress(row) }}</span>
                <span v-else-if="column.key === 'publishedAt'" class="virtual-cell" :title="taskPublishTime(row)">{{ taskPublishTime(row) }}</span>
                <span v-else-if="column.key === 'remark'" class="virtual-cell" :title="taskRemark(row)">{{ taskRemark(row) }}</span>
                <span v-else-if="column.key === 'createdAt'" class="virtual-cell">{{ formatDateTime(taskCreatedAt(row)) }}</span>
                <div v-else-if="column.key === 'actions'" class="virtual-actions">
                  <el-button link type="primary" size="small" :loading="row.members.some(isProcessing)" @click="navigateTaskDetail(row.taskId)">查看任务</el-button>
                  <el-button v-if="row.members.some(canLinkExternal)" link type="primary" size="small" @click="openExternalPublication(row)">已手动发布</el-button>
                  <el-button link type="primary" size="small" @click="openClaimStatistics(row)">领取统计</el-button>
                  <el-button v-if="canGenerate && taskRecoveries(row).length" link type="warning" size="small" @click="openTaskRecovery(row)">重试并重建（{{ taskRecoveries(row).length }}）</el-button>
                  <el-button v-if="canGenerate" link type="primary" size="small" @click="openTaskRewardPolicies(row)">核验实际奖励</el-button>
                  <el-button v-if="canGenerate" link type="danger" size="small" @click="taskDeletionTarget = { taskId: row.taskId, taskNumber: taskDisplayId(row) }">批量删除</el-button>
                  <el-button v-if="taskPendingCreationCount(row)" link type="warning" size="small" :disabled="!canOpenPendingCreationTask(row)" @click="openPendingCreationTask(row)">处理待创建（{{ taskPendingCreationCount(row) }}）</el-button>
                  <template v-if="!isMultiMarketTask(row)">
                    <el-button v-if="taskPrimary(row).detail.batch.status === 'PUBLISHED'" link type="primary" size="small" :loading="verifyingPublicationIds.has(String(taskPrimary(row).detail.batch.id))" @click="inspectPublication(taskPrimary(row))">{{ missingConfigurations(taskPrimary(row)).length ? '处理缺失配置' : '查看核验结果' }}</el-button>
                    <el-button v-if="hasPendingPublishReservation(taskPrimary(row))" link type="warning" size="small" :loading="recoveringPublishId === taskPrimary(row).detail.batch.id" @click="recoverPublishReservation(taskPrimary(row))">恢复发布</el-button>
                    <el-button v-else-if="taskPrimary(row).detail.batch.status === 'READY_TO_PUBLISH'" link type="primary" size="small" @click="openPublishDialog(taskPrimary(row))">选择发布方式</el-button>
                    <el-button v-if="canContinueRepair(taskPrimary(row))" link type="warning" size="small" :loading="resolvingMissingBatchId === taskPrimary(row).detail.batch.id || publishing" @click="handleRepairAction(taskPrimary(row))">{{ repairActionLabel(taskPrimary(row)) }}</el-button>
                    <el-button v-if="canCancelScheduledPublish(taskPrimary(row))" link type="danger" size="small" :disabled="!canCancelScheduledPublish(taskPrimary(row))" :loading="cancellingPublishId === taskPrimary(row).detail.batch.id" @click="cancelScheduledPublish(taskPrimary(row))">撤销发布</el-button>
                    <el-button v-if="canStartDownload(taskPrimary(row)) && !isSuccess(taskPrimary(row))" link type="primary" size="small" :loading="isProcessing(taskPrimary(row))" :disabled="downloadingTask" @click="requestDownload(taskPrimary(row), false)">{{ taskPrimary(row).detail.issues.some((issue: RedemptionCodeIssue) => issue.remoteError) ? '重试下载' : '下载兑换码' }}</el-button>
                    <el-button v-if="canStartDownload(taskPrimary(row)) && canExport" link type="primary" size="small" :icon="Download" :loading="exportingId === taskPrimary(row).detail.batch.id" :disabled="downloadingTask" @click="requestDownload(taskPrimary(row), true)">下载 Excel</el-button>
                  </template>
                  <el-button v-if="canPublishMultiMarketTask(row)" link type="primary" size="small" :loading="publishing" @click="openPublishDialog(row)">选择发布方式</el-button>
                  <el-button v-if="canExportMultiMarketTask(row) && canExport" link type="primary" size="small" :icon="Download" :loading="exportingGroupKey === row.exportGroupKey" :disabled="downloadingTask" @click="requestDownload(row, true)">下载 Excel</el-button>
                </div>
              </template>
            </el-table-v2>
          </template>
        </el-auto-resizer>
      </div>
      <div v-if="codeGroupTasks.length" class="code-group-list__pagination">
        <el-pagination
          v-model:current-page="codeGroupTaskCurrentPage"
          :page-size="codeGroupTaskPageSize"
          :page-sizes="[20, 50, 100]"
          :total="codeGroupTasks.length"
          :disabled="loading"
          background
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="changeCodeGroupTaskPageSize"
        />
      </div>
      <div v-else-if="loading" v-loading="loading" class="code-group-loading" />
      <el-empty v-else-if="!codeGroupLoadError" :image-size="68" description="还没有兑换码组，点击右上角“批量生成兑换码组”开始创建" />
    </article>

    </template>
    <el-dialog v-model="codeGroupDialogVisible" title="批量生成兑换码组" width="1040px" destroy-on-close :close-on-click-modal="!checkingDuplicates && !working" :close-on-press-escape="!checkingDuplicates && !working" :show-close="!checkingDuplicates && !working">
      <el-form label-position="top" class="code-group-form" :disabled="checkingDuplicates || working">
        <div class="code-group-form__grid">
          <el-form-item class="code-group-form__date-range" label="开始兑换日期范围（表格列）" required>
            <el-date-picker v-model="form.dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :disabled-date="(date: Date) => date < new Date(`${todayIso()}T00:00:00`)" style="width: 100%" />
            <div class="date-presets"><span>快捷选择</span><el-button size="small" @click="applyFutureRange(7)">未来 7 天</el-button><el-button size="small" @click="applyFutureRange(30)">未来 30 天</el-button></div>
            <p class="field-note">范围内每一天对应表格中的一列；系统按照“开始兑换日 × 用户类型/标签档位”生成独立兑换码组，例如 <strong>{{ isAgentCodeGroup() ? '9-02代理存款200' : (isPreviousDayDeposit() ? 'NEW-818存款200' : 'NEW-808到814存款100') }}</strong>。</p>
          </el-form-item>
          <el-form-item class="code-group-form__validity" label="兑换码生效时间（远端 valid_time）" required>
            <div class="validity-editor">
              <el-radio-group v-model="form.validityMode" @change="(value) => changeValidityMode(value as ValidityMode)">
                <el-radio value="CLAIM_DAY">跟随开始兑换日（默认）</el-radio>
                <el-radio value="CUSTOM_OFFSETS">自定义相对日期</el-radio>
              </el-radio-group>
              <div v-if="form.validityMode === 'CUSTOM_OFFSETS'" class="validity-editor__offsets">
                <label><span>生效开始</span><span class="validity-editor__formula">开始兑换日 +</span><el-input-number v-model="form.validFromDayOffset" :min="0" :max="365" :precision="0" controls-position="right" @change="keepValidityOffsetsOrdered" /><span>天</span></label>
                <label><span>生效结束</span><span class="validity-editor__formula">开始兑换日 +</span><el-input-number v-model="form.validToDayOffset" :min="0" :max="365" :precision="0" controls-position="right" @change="keepValidityOffsetsOrdered" /><span>天</span></label>
              </div>
              <div class="validity-preview">
                <div class="validity-preview__heading"><strong>{{ validityRuleSummary }}</strong><span>按每一列表格日期分别计算</span></div>
                <div v-for="(item, index) in validityPreview" :key="item.claimDate" class="validity-preview__row">
                  <span>{{ validityPreview.length === 1 ? '当前列' : index === 0 ? '首列' : '末列' }} {{ formatDate(item.claimDate) }}</span>
                  <code>{{ item.validFrom }} 00:00:00</code><span>至</span><code>{{ item.validTo }} 23:59:59</code>
                </div>
              </div>
              <p class="field-note">只改变远端兑换码的实际生效区间；表格列、任务分组和充值统计窗口仍以开始兑换日为准。</p>
            </div>
          </el-form-item>
          <el-form-item class="code-group-form__code-type" label="兑换码类型" required>
            <el-radio-group v-model="form.redemptionType" @change="changeRedemptionType">
              <el-radio value="SEVEN_DAY_DEPOSIT">近 7 天充值</el-radio>
              <el-radio value="PREVIOUS_DAY_DEPOSIT">日充值</el-radio>
              <el-radio value="AGENT">代理</el-radio>
            </el-radio-group>
            <p class="field-note">日充值只核验开始兑换日前一天的充值金额；代理类型将按生效首日生成“9-02代理全部 / 9-02代理存款200”名称，并导出代理模板样式。兑换码实际有效期以上方规则为准。</p>
          </el-form-item>
          <el-form-item v-if="usesSpecialCode" class="code-group-form__code-type" label="10000 档位码串后缀">
            <div>
              <el-radio-group v-model="form.specialCodeNaming">
                <el-radio value="TEN_K">10K</el-radio>
                <el-radio value="ORIGINAL">10000</el-radio>
              </el-radio-group>
              <p class="field-note">码串示例：{{ specialCodeExample }}。仅改变 10000 档位的码串后缀，充值门槛与奖励不变。</p>
              <p class="field-note">选择会随任务保存；刷新、继续创建及重试仍使用本次命名方式。</p>
            </div>
          </el-form-item>
          <el-form-item v-if="isPreviousDayDeposit() && form.remoteMarketId" class="code-group-form__code-type" label="当前编辑盘口的日充值标签方案">
            <el-tag type="info">使用当前盘口标签与档位配置</el-tag>
            <p class="field-note">所有已配置可用账号的盘口均可创建日充值兑换码。优先使用已保存预设；默认档位按当前盘口标签的充值区间匹配，未匹配的档位请手动选择标签。充值 0 档为所有用户。</p>
          </el-form-item>
          <el-form-item class="code-group-form__market" label="盘口" required>
            <el-select v-model="form.remoteMarketIds" :loading="remoteConnectionsLoading" multiple collapse-tags collapse-tags-tooltip filterable placeholder="选择一个或多个盘口" @change="changeRemoteMarkets">
              <el-option v-for="market in availableRemoteMarkets" :key="market.id" :label="[market.code, market.name].filter(Boolean).join(' · ') || '未命名盘口'" :value="market.id" />
            </el-select>
            <p v-if="selectedRemoteConnection" class="field-note">当前编辑 {{ marketLabel(form.remoteMarketId) }}，系统将自动选择账号 {{ selectedRemoteConnection.username }}。</p>
            <p v-else-if="!remoteConnectionsLoading" class="field-note field-note--danger">暂无可用盘口，请先在“远端连接”中完成盘口和账号配置。</p>
          </el-form-item>
        </div>

        <el-tabs v-if="form.remoteMarketIds.length" v-model="activeMarketTab" class="market-tier-tabs" @tab-change="changeActiveMarket">
          <el-tab-pane v-for="marketId in form.remoteMarketIds" :key="marketKey(marketId)" :name="marketKey(marketId)" :label="marketLabel(marketId)" />
        </el-tabs>
        <section class="tier-panel">
          <div class="tier-panel__heading">
          <div><strong>{{ marketLabel(form.remoteMarketId) }} · 用户类型与兑换金额</strong><p>每个档位先选择用户类型。“标签用户”必须选择标签 ID；“全部用户”不会向远端发送标签数组。预设按当前账号和兑换码类型独立保存，三种兑换码类型互不覆盖。</p>
            <p v-if="rewardTierPresetLoading" class="field-note">正在读取已保存标签和组合预设…</p>
            <p v-else-if="marketConfigurationError" class="field-note field-note--danger">{{ marketConfigurationError }}，请重新加载；已填写档位和金额会保留。</p>
            <p v-else-if="rewardTierPreset?.exists" class="field-note"><el-tag size="small" :type="rewardTierPreset.stale ? 'warning' : 'success'">{{ rewardTierPreset.stale ? '预设待确认' : '已保存预设' }}</el-tag> 保存于 {{ formatDateTime(rewardTierPreset.savedAt) }}</p>
            <p v-else class="field-note">当前类型尚未保存预设，已加载默认档位。修改后可另存当前预设。</p>
          </div>
            <div class="tier-panel__actions">
              <el-button plain :loading="remoteTagsLoading || rewardTierPresetLoading" @click="loadMarketTierConfiguration">重新加载</el-button>
              <el-button plain :icon="Refresh" :loading="remoteTagsLoading" @click="loadRemoteTags">同步当前盘口标签</el-button>
              <el-button plain :disabled="!rewardTierPreset?.exists || rewardTierPreset.stale || rewardTierPresetLoading" @click="applyRewardTierPreset">重新应用预设</el-button>
              <el-button plain type="primary" :disabled="remoteTagsLoading || !remoteTagsLoaded" :loading="rewardTierPresetSaving" @click="saveRewardTierPreset">另存当前预设</el-button>
              <el-button plain @click="isPreviousDayDeposit() ? resetPreviousDayTiers() : restoreStandardTiers()">恢复默认档位</el-button>
              <el-button plain :icon="Plus" @click="addTier">添加档位</el-button>
            </div>
          </div>
          <div class="tier-editor">
            <p v-if="!remoteTagsLoading && !remoteTagsLoaded" class="field-note field-note--danger">标签尚未加载成功。可先新增档位，重新加载后再选择标签。</p>
            <p v-else-if="!remoteTagsLoading && !remoteTags.length" class="field-note">当前盘口尚无已保存标签，请同步当前盘口标签。</p>
            <div class="tier-editor__header"><span>用户类型</span><span>标签 ID 数组</span><span>兑换金额下限</span><span>兑换金额上限</span><span></span></div>
            <div v-for="(tier, index) in form.tiers" :key="index" class="tier-editor__row">
              <el-select :model-value="tier.userType" :clearable="false" @update:model-value="(value) => changeTierUserType(tier, value as CodeGroupUserType)">
                <el-option label="标签用户" value="LABEL_USERS" />
                <el-option label="全部用户" value="ALL_USERS" />
              </el-select>
              <div v-if="isAllUsersTier(tier)" class="tier-editor__all-users"><strong>全部用户</strong><span>无需标签</span></div>
              <el-select v-else-if="isPreviousDayDeposit()" :model-value="tier.labelIds[0]" filterable :loading="remoteTagsLoading" placeholder="选择当前盘口标签 ID" @update:model-value="(labelId) => updatePreviousDayTierLabel(tier, labelId)">
                <el-option v-for="tag in previousDayTagOptions" :key="tag.id" :label="tag.name" :value="tag.id" :disabled="isLabelUsedByOtherTier(tag.id, tier)" />
              </el-select>
              <el-select v-else :model-value="tier.labelIds[0]" filterable :loading="remoteTagsLoading" placeholder="选择标签 ID" @update:model-value="(labelId) => updateTierFromLabel(tier, labelId)">
                <el-option v-for="tag in tagOptions" :key="tag.id" :label="tag.name" :value="tag.id" :disabled="isLabelUsedByOtherTier(tag.id, tier)" />
              </el-select>
              <el-input-number v-model="tier.bonusAmount" :min="0" :max="1000000" :precision="2" controls-position="right" />
              <el-input-number v-model="tier.bonusMaxAmount" :min="0" :max="1000000" :precision="2" controls-position="right" />
              <el-button type="danger" link @click="removeTier(index)">删除</el-button>
            </div>
          </div>
        </section>

        <el-form-item v-if="usesSpecialCode" label="创建前查重">
          <el-checkbox v-model="checkRemoteDuplicates">同时进行远端查重</el-checkbox>
          <p class="field-note">本地查重始终执行。开启远端查重后会读取所选盘口的配置目录，配置较多时可能耗时较长。</p>
          <p v-if="!checkRemoteDuplicates" class="field-note">当前仅检查本系统记录，无法发现只在远端后台创建的同码配置。创建后的实际奖励核验仍会执行。</p>
        </el-form-item>

        <el-collapse v-model="advancedOptionsOpen" class="advanced-options">
          <el-collapse-item name="options">
            <template #title><el-icon><Setting /></el-icon><span>其他创建参数（已预填）</span></template>
            <div class="code-group-form__grid code-group-form__grid--options">
              <el-form-item label="发布环境">
                <el-select v-model="form.remoteOptions.publishEnvironment" :clearable="false">
                  <el-option label="正式环境" value="test" />
                </el-select>
              </el-form-item>
              <el-form-item label="流水倍数"><el-input-number v-model="form.remoteOptions.flowTimes" :min="0" :max="1000" controls-position="right" /></el-form-item>
              <el-form-item label="串行间隔时间"><el-input-number v-model="form.remoteOptions.creationIntervalSeconds" :min="1" :max="60" controls-position="right" /><span class="field-unit">秒</span><p class="field-note">每条远端配置创建请求的最小间隔，默认 5 秒。</p></el-form-item>
              <el-form-item v-if="usesSpecialCode" label="特殊兑换码"><p class="field-note">{{ isPreviousDayDeposit() ? '每组 1 个码，例如 1110rajfree 或 1110raj200。' : '每组 1 个码，例如 1110raj7days100。' }}</p></el-form-item>
              <el-form-item v-else label="普通兑换码每组数量"><el-input-number v-model="form.remoteOptions.keyNumber" :min="1" :max="1000" :precision="0" step-strictly controls-position="right" /><p class="field-note">默认 1，可填写 1–1000。每个“开始兑换日 × 档位”生成一组，每组包含此数量的独立兑换码。</p></el-form-item>
              <el-form-item label="最低累计充值金额"><el-input-number v-model="form.remoteOptions.activityRecharge" :min="0" :max="100000000" :precision="2" controls-position="right" placeholder="不限制" /></el-form-item>
              <el-form-item label="最低充值次数"><el-input-number v-model="form.remoteOptions.activityRechargeCount" :min="0" :max="100000" controls-position="right" placeholder="不限制" /></el-form-item>
              <el-form-item label="关联活动 ID"><el-input-number v-model="form.remoteOptions.activityId" :min="1" :max="999999999999" controls-position="right" placeholder="不关联" /></el-form-item>
              <el-form-item label="单用户领取次数"><el-input-number v-model="form.remoteOptions.singleUserLimit" :min="1" :max="100" controls-position="right" /></el-form-item>
              <el-form-item label="单兑换码领取次数"><el-input-number v-model="form.remoteOptions.singleKeyLimit" :min="1" :max="100000" controls-position="right" /></el-form-item>
            </div>
            <div class="advanced-options__fixed"><span>配置状态：待发布</span><span>用户类型：按各档位设置</span><span>有效时间：{{ validityRuleSummary }}</span></div>
            <div class="advanced-options__toggle-grid">
              <el-form-item label="是否绑定银行卡"><el-radio-group v-model="form.remoteOptions.requireBindBankCard"><el-radio :value="false">关闭</el-radio><el-radio :value="true">开启</el-radio></el-radio-group></el-form-item>
              <el-form-item label="是否绑定手机号"><el-radio-group v-model="form.remoteOptions.requireBindPhone"><el-radio :value="false">关闭</el-radio><el-radio :value="true">开启</el-radio></el-radio-group></el-form-item>
              <el-form-item label="检测设备 ID"><el-radio-group v-model="form.remoteOptions.checkUuid"><el-radio :value="false">关闭</el-radio><el-radio :value="true">开启</el-radio></el-radio-group></el-form-item>
              <el-form-item label="单设备最大领取次数"><el-input-number v-model="form.remoteOptions.uuidRewardLimit" :min="1" :max="100" controls-position="right" :disabled="!form.remoteOptions.checkUuid" /></el-form-item>
              <el-form-item label="检测登录 IP"><el-radio-group v-model="form.remoteOptions.checkLoginIp"><el-radio :value="false">关闭</el-radio><el-radio :value="true">开启</el-radio></el-radio-group></el-form-item>
              <el-form-item label="单登录 IP 最大领取次数"><el-input-number v-model="form.remoteOptions.loginIpRewardLimit" :min="1" :max="100" controls-position="right" :disabled="!form.remoteOptions.checkLoginIp" /></el-form-item>
              <el-form-item label="检测注册 IP"><el-radio-group v-model="form.remoteOptions.checkRegisterIp"><el-radio :value="false">关闭</el-radio><el-radio :value="true">开启</el-radio></el-radio-group></el-form-item>
              <el-form-item label="单注册 IP 最大领取次数"><el-input-number v-model="form.remoteOptions.registerIpRewardLimit" :min="1" :max="100" controls-position="right" :disabled="!form.remoteOptions.checkRegisterIp" /></el-form-item>
            </div>
            <p class="field-note">最低累计充值金额、最低充值次数和关联活动 ID 默认不限制；留空时创建请求会省略对应字段。</p>
          </el-collapse-item>
        </el-collapse>
        <p v-if="form.remoteMarketIds.length" class="submit-hint">已选择 {{ form.remoteMarketIds.length }} 个盘口，共创建 {{ expectedTaskCount() }} 组远端配置，预计 {{ expectedTaskCount() * (codesPerGroup || 1) }} 个兑换码。远端生效时间：{{ validityRuleSummary }}。全部创建完成后，可在下载时按盘口选择是否先发布。</p>
      </el-form>
      <template #footer><span v-if="checkingDuplicates" role="status" class="field-note">{{ duplicateCheckProgress }}</span><el-button :disabled="checkingDuplicates || working" @click="codeGroupDialogVisible = false">取消</el-button><el-button type="primary" :loading="checkingDuplicates || working" @click="createCodeGroup">{{ checkingDuplicates ? '正在查重' : '开始生成' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="duplicateDialogVisible" title="发现同码记录，请确认是否继续创建" width="1000px" append-to-body @close="finishDuplicateReview(false)">
      <el-alert type="warning" :closable="false" show-icon title="发现同码记录。阅览并确认后，仍可按本次任务参数继续创建。" />
      <p class="field-note">以下 {{ duplicateConflicts.length }} 条同码记录集中确认一次，无需逐码确认。确认随任务保存，刷新页面、继续创建和重试均会沿用；同一任务不因历史同码记录变化再次要求确认。</p>
      <p class="field-note">本地记录是历史资料，不代表远端配置仍然存在或仍是表中奖励。管理员在远端删除后，本系统可能尚未记录；无需删除本地历史记录才能继续。</p>
      <p class="field-note">本次确认用于创建新配置；旧记录会保留，不会自动复用旧配置。若远端仍有同码，可能拒绝创建；系统会展示实际结果，结果不明时暂停。</p>
      <el-table :data="duplicateConflicts" max-height="420" :row-key="row => `${row.marketId}:${row.code}:${row.issueId || row.configurationId}`">
        <el-table-column label="盘口" min-width="120"><template #default="{ row }">{{ marketLabel(row.marketId) }}</template></el-table-column>
        <el-table-column prop="code" label="兑换码" min-width="170" />
        <el-table-column label="来源" width="90"><template #default="{ row }">{{ row.source === 'LOCAL' ? '本地记录' : '远端目录' }}</template></el-table-column>
        <el-table-column label="旧任务" min-width="140"><template #default="{ row }">{{ row.taskNumber || '本地未登记' }}</template></el-table-column>
        <el-table-column label="配置 ID" width="100"><template #default="{ row }">{{ row.configurationId || '待核对' }}</template></el-table-column>
        <el-table-column label="本地记录奖励" width="125"><template #default="{ row }">{{ row.localRewardMin == null ? '—' : `${row.localRewardMin}–${row.localRewardMax}` }}</template></el-table-column>
        <el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.batchId" link type="primary" @click="openDuplicateTask(row)">查看旧任务</el-button></template></el-table-column>
      </el-table>
      <el-checkbox v-model="duplicateReviewAcknowledged">我已阅览以上同码记录，确认按本次任务参数继续创建</el-checkbox>
      <template #footer><el-button @click="finishDuplicateReview(false)">返回调整</el-button><el-button type="primary" :disabled="!duplicateReviewAcknowledged" @click="finishDuplicateReview(true)">确认，继续创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="publishDialogVisible" title="选择发布方式" width="560px" destroy-on-close>
      <p class="field-note publish-dialog__intro">{{ isMultiMarketPublishTarget(publishTarget) ? '将按盘口顺序串行执行；每个盘口仅发布其远端账号下尚未发布的配置。' : '默认先尝试立即发布；若被已有定时任务阻止，会先显示具体印度时间，确认后才转为定时发布。' }}</p>
      <el-alert v-if="publishTarget && publishRows(publishTarget).some(isRepairing)" type="warning" :closable="false" title="补齐发布会发布该账号下所有尚未发布的兑换码；已发布的配置不会重新下载。若上次发布结果不确定，请先到远端后台核对。" />
      <el-collapse v-model="publishOptionsOpen" class="advanced-options publish-options">
        <el-collapse-item name="publish">
          <template #title><el-icon><Setting /></el-icon><span>发布相关设置（默认：立即发布，冲突时提示定时发布）</span></template>
          <el-form label-width="112px">
            <el-form-item label="发布方式"><el-radio-group v-model="publishForm.mode"><el-radio value="IMMEDIATE">立即发布（默认）</el-radio><el-radio value="SCHEDULED">定时发布</el-radio></el-radio-group></el-form-item>
            <el-form-item v-if="publishForm.mode === 'SCHEDULED'" label="发布时间" required><el-date-picker v-model="publishForm.scheduledTime" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="选择印度时间" style="width: 100%" /><p class="field-note">远端按印度时间（Asia/Kolkata）执行；撤销必须早于该时间。</p></el-form-item>
            <el-form-item v-if="publishForm.mode === 'IMMEDIATE'" label="失败后转定时"><el-switch v-model="publishForm.fallbackToScheduled" inline-prompt active-text="开" inactive-text="关" /><p class="field-note">默认开启。仅在远端明确拒绝立即发布且提示已有定时任务时，才会逐次提示定时时间；每次均须确认。</p></el-form-item>
            <el-alert v-if="publishForm.mode === 'IMMEDIATE' && publishForm.fallbackToScheduled" type="info" :closable="false" title="发生定时任务冲突时，依次提供约 15、30、60 分钟后的印度时间及最早领取日 00:00:00；到期前无法执行的时间会跳过。" />
          </el-form>
        </el-collapse-item>
      </el-collapse>
      <template #footer><el-button @click="publishDialogVisible = false">取消</el-button><el-button v-if="publishTarget && publishRows(publishTarget).some(canLinkExternal)" @click="openExternalPublication(publishTarget)">已手动发布</el-button><el-button type="primary" :loading="publishing" @click="submitPublish">确认发布</el-button></template>
    </el-dialog>

    <el-dialog v-model="externalDialog" :title="externalTarget ? externalActionLabel(externalTarget) : '登记或换绑手动发布 ID'" width="min(520px, 95vw)" append-to-body :show-close="!linkingExternal" :close-on-click-modal="false" :close-on-press-escape="!linkingExternal">
      <el-select v-if="externalChoices.length > 1" v-model="externalTarget" value-key="detail.batch.id" aria-label="手动发布的盘口" placeholder="选择手动发布的盘口" :disabled="linkingExternal" @change="externalTaskId = ''; externalError = ''">
        <el-option v-for="row in externalChoices" :key="row.detail.batch.id" :value="row" :label="remoteMarketLabel(row)" />
      </el-select>
      <template v-if="externalTarget">
        <p>{{ remoteMarketLabel(externalTarget) }} · {{ externalTarget.detail.batch.remoteConnectionName }} · 子任务 {{ subtaskDisplayId(externalTarget) }}</p>
        <p v-if="externalActionLabel(externalTarget) === '换绑手动发布 ID'">原系统发布 ID：{{ externalTarget.detail.batch.remotePublishTaskId }}。原发布确认失败或撤销，且新发布已完成、配置匹配后才会换绑。</p>
        <p>请从此盘口的远端发布记录复制任务 ID，不是 ERP 任务编号或配置 ID。确认后停止该盘口后续系统发布，改为跟踪这个 ID。已经发往远端的请求无法撤回。</p>
        <el-input v-model.trim="externalTaskId" aria-label="远端发布任务 ID" placeholder="输入远端发布任务 ID（正整数）" maxlength="255" :disabled="linkingExternal" @keyup.enter="linkExternalPublication" />
        <el-alert v-if="externalError" :title="externalError" type="error" :closable="false" />
      </template>
      <template #footer>
        <el-button :disabled="linkingExternal" @click="externalDialog = false">取消</el-button>
        <el-button type="primary" :loading="linkingExternal" :disabled="!/^[1-9]\d{0,254}$/.test(externalTaskId)" @click="linkExternalPublication">核验并关联</el-button>
      </template>
    </el-dialog>
    <el-dialog :model-value="Boolean(downloadDecision)" title="选择下载方式" width="540px" append-to-body @update:model-value="visible => { if (!visible) chooseDownload() }">
      <template v-if="downloadDecision">
        <p>{{ downloadDecision.market }} · {{ downloadDecision.state }}</p>
        <p>系统发布会提交该账号下全部待发布的兑换码配置。直接下载仅获取远端已有的码，兑换是否生效取决于远端发布结果。</p>
        <el-button type="primary" :disabled="!downloadDecision.canPublish" @click="chooseDownload('publish')">系统发布后下载</el-button>
        <el-button :disabled="!downloadDecision.canRegister" @click="chooseDownload('manual')">去远端手动发布</el-button>
        <el-button @click="chooseDownload('direct')">不发布，直接下载</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="verificationDialogVisible" title="发布与下载检查" width="760px" append-to-body>
      <template v-if="verificationTarget">
        <p>任务 {{ verificationTarget.detail.batch.taskNumber || verificationTarget.detail.batch.id }} · {{ remoteMarketLabel(verificationTarget) }}</p>
        <p v-if="verifyingPublicationIds.has(String(verificationTarget.detail.batch.id))" role="status">正在查询远端状态，请稍候…</p>
        <template v-else>
          <el-alert :title="publicationCheckErrors[String(verificationTarget.detail.batch.id)] ? '本次核验未完成' : publicationLabel(publicationCheck(verificationTarget))" :description="configurationVerificationSummary(publicationCheck(verificationTarget), publicationCheckErrors[String(verificationTarget.detail.batch.id)], verificationTarget.detail.issues)" :type="missingConfigurations(verificationTarget).length ? 'warning' : 'info'" :closable="false" show-icon />
          <p v-if="publicationCheck(verificationTarget)?.checkedAt" class="field-note">本次核验时间：{{ formatDateTime(publicationCheck(verificationTarget)?.checkedAt) }}</p>
          <template v-if="missingConfigurations(verificationTarget).length">
            <p class="field-note">以下配置在 RAJACE 当前列表不可见。可只下载现有已入库兑换码，或重建缺失配置并在再次发布、核验后合并下载。</p>
            <el-table :data="missingConfigurations(verificationTarget)" size="small" max-height="260" border>
              <el-table-column label="配置名称" min-width="145"><template #default="{ row }">{{ row.issue?.remoteConfigurationName || '名称未记录' }}</template></el-table-column>
              <el-table-column label="配置备注" min-width="145"><template #default="{ row }">{{ row.issue?.remoteConfigurationRemark || '备注未记录' }}</template></el-table-column>
              <el-table-column label="原配置 ID" prop="configurationId" width="115" />
              <el-table-column label="兑换日" width="115"><template #default="{ row }">{{ row.issue?.claimDate || '—' }}</template></el-table-column>
            </el-table>
          </template>
        </template>
      </template>
      <template #footer>
        <el-button @click="verificationDialogVisible = false">关闭</el-button>
        <el-button v-if="verificationTarget && canLinkExternal(verificationTarget)" @click="openExternalPublication(verificationTarget)">{{ externalActionLabel(verificationTarget) }}</el-button>
        <el-button v-if="verificationTarget" :loading="verifyingPublicationIds.has(String(verificationTarget.detail.batch.id))" @click="inspectPublication(verificationTarget)">刷新状态</el-button>
        <el-button v-if="verificationTarget && missingConfigurations(verificationTarget).length && canExport" :loading="resolvingMissingBatchId === verificationTarget.detail.batch.id" @click="acceptAvailableCodes(verificationTarget)">接受当前配置，下载已有兑换码</el-button>
        <el-button v-if="verificationTarget && missingConfigurations(verificationTarget).length && canGenerate" type="warning" :loading="resolvingMissingBatchId === verificationTarget.detail.batch.id" @click="regenerateMissingConfigurations(verificationTarget)">重建缺失配置并补齐下载</el-button>
        <el-button v-if="verificationTarget && canStartDownload(verificationTarget) && !isSuccess(verificationTarget)" type="primary" :loading="isProcessing(verificationTarget)" :disabled="downloadingTask" @click="requestDownload(verificationTarget, false)">下载兑换码</el-button>
      </template>
    </el-dialog>

    <RedemptionTaskDeletionDialog v-if="taskDeletionTarget && !detailMode" :key="String(taskDeletionTarget.taskId)" :task-id="taskDeletionTarget.taskId" :task-number="taskDeletionTarget.taskNumber" @close="taskDeletionTarget = undefined" @changed="refreshRecoveryGroups" />
    <el-dialog v-model="rewardPolicyDialog" title="核验并对齐实际奖励" width="900px" :close-on-click-modal="!applyingRewardPolicy" :close-on-press-escape="!applyingRewardPolicy" :show-close="!applyingRewardPolicy">
    <el-alert :title="rewardPolicyProgress || '正在读取远端实际奖励'" type="warning" :closable="false" show-icon />
    <el-table :data="rewardPolicyPlans" max-height="450">
      <el-table-column label="盘口 / 日期" min-width="180"><template #default="{ row }">{{ row.parameters.marketName }} · {{ row.parameters.claimDate }}</template></el-table-column>
      <el-table-column label="原配置" prop="configurationId" width="110" />
      <el-table-column label="实际奖励 → 本次任务" min-width="180"><template #default="{ row }">{{ row.previousMin }}–{{ row.previousMax }} → {{ row.parameters.bonusMin }}–{{ row.parameters.bonusMax }}</template></el-table-column>
      <el-table-column label="状态 / 说明" min-width="260"><template #default="{ row }">{{ row.status }}：{{ row.reason }}</template></el-table-column>
    </el-table>
    <template #footer><el-button :disabled="applyingRewardPolicy" @click="rewardPolicyDialog = false">关闭</el-button><el-button type="warning" :loading="applyingRewardPolicy" :disabled="checkingRewardPolicy || !rewardPolicyPlans.some(plan => ['CHECKED', 'UPDATED', 'UNCONFIRMED'].includes(plan.status))" @click="applyRewardPolicies()">确认对齐奖励 / 恢复登记</el-button></template>
  </el-dialog>

  <el-dialog v-model="recoveryDialogVisible" title="缺失配置恢复" width="850px" :close-on-click-modal="!rebuildingMissing" :close-on-press-escape="!rebuildingMissing" :show-close="!rebuildingMissing">
    <el-alert :title="recoveryProgress || '正在核验远端配置；核验本身不会创建配置'" type="warning" :closable="false" show-icon />
    <el-table :data="recoveryViews" max-height="450">
      <el-table-column label="盘口 / 日期" min-width="150"><template #default="{ row }">{{ row.parameters.marketName }} · {{ row.parameters.claimDate }}</template></el-table-column>
      <el-table-column label="原配置 ID" prop="oldConfigurationId" width="100" />
      <el-table-column label="状态 / 原因" min-width="240"><template #default="{ row }">{{ recoveryStatusLabel(row.status) }}：{{ row.reason }}</template></el-table-column>
      <el-table-column label="本次任务参数" min-width="230"><template #default="{ row }">奖励 {{ row.parameters.bonusMin }}–{{ row.parameters.bonusMax }}；每码 {{ row.parameters.options.singleKeyLimit }} 次；每组 {{ row.parameters.options.keyNumber }} 码；共享 {{ row.relatedBatchCount }} 批次</template></el-table-column>
    </el-table>
    <template #footer>
      <el-button :disabled="rebuildingMissing" @click="recoveryDialogVisible = false">关闭</el-button>
      <el-button type="warning" :loading="rebuildingMissing" :disabled="checkingRecovery || recoveryViews.some(view => ['CREATING', 'UNCONFIRMED', 'APPLYING'].includes(view.status)) || !recoveryViews.some(view => ['MISSING', 'RECEIPT_SAVED'].includes(view.status))" @click="rebuildMissingConfigurations()">重试并重建 / 恢复登记</el-button>
    </template>
  </el-dialog>

  <article v-if="detailMode" class="task-detail-workspace" v-loading="loading">
    <header class="task-detail-heading">
      <div><el-button link @click="returnToTaskList">← 返回任务列表</el-button><h2>任务 {{ selectedTaskDisplayId }} <span>兑换码明细</span></h2></div>
      <div class="task-detail-actions"><el-button :icon="Refresh" :loading="loading" @click="loadTaskDetail">刷新</el-button><el-button v-if="canGenerate" @click="showTaskDeletion(undefined, false)">删除进度 / 恢复</el-button><el-button v-if="canGenerate && selectedGroup" type="danger" plain @click="showTaskDeletion()">删除整任务配置</el-button></div>
    </header>
    <el-alert v-if="codeGroupLoadError" :title="codeGroupLoadError" type="error" :closable="false" show-icon />

      <template v-if="selectedGroup">
        <el-tabs v-if="selectedTaskMembers.length > 1" v-model="activeTaskBatchId" class="task-market-tabs" @tab-change="selectTaskMember">
          <el-tab-pane v-for="member in selectedTaskMembers" :key="member.detail.batch.id" :name="String(member.detail.batch.id)" :label="taskMemberLabel(member)" />
        </el-tabs>
        <p v-if="selectedTaskMembers.length > 1" class="field-note task-detail-note">各盘口保留独立的远端创建、发布与下载进度；系统会按盘口顺序完成创建，所有盘口完成后可在任务列表下载同一份多 Sheet Excel。</p>
        <div v-if="canContinuePendingCreation(selectedGroup)" class="repair-action-strip" role="status">
          <span>当前盘口还有 {{ countIssues(uncreatedIssues(selectedGroup)) }} 条配置待创建，可继续处理。</span>
          <el-button type="warning" :loading="continuingCreationBatchId === selectedGroup.detail.batch.id" :disabled="isProcessing(selectedGroup) || continuingCreationBatchId !== undefined" @click="continuePendingCreation(selectedGroup)">继续创建剩余配置（{{ countIssues(uncreatedIssues(selectedGroup)) }}）</el-button>
        </div>
        <div v-if="isRepairing(selectedGroup)" class="repair-action-strip" role="status">
          <span>{{ repairReadyForPublish(selectedGroup) ? '补齐配置已创建，尚未再次发布；请选择发布方式。' : '缺失配置仍在补齐；完成后再选择发布方式。' }}</span>
          <el-button v-if="canContinueRepair(selectedGroup)" type="warning" :loading="resolvingMissingBatchId === selectedGroup.detail.batch.id || publishing" @click="handleRepairAction(selectedGroup)">{{ repairActionLabel(selectedGroup) }}</el-button>
        </div>
        <div v-if="selectedGroup.detail.issues.some(canReuseExistingConfiguration)" class="repair-action-strip">
          <span>创建时阅览确认过的同码记录会随任务保存，刷新页面、继续创建和重试会自动沿用；同一任务不因历史同码记录变化再次要求确认。</span>
          <el-button type="primary" :loading="checkingRewardPolicy" :disabled="applyingRewardPolicy" @click="inspectRewardPolicies()">核验并对齐实际奖励</el-button>
          <el-button type="warning" :loading="checkingRecovery" :disabled="rebuildingMissing" @click="inspectMissingConfigurations()">核验缺失 / 重试重建</el-button>
          <el-button type="primary" :loading="reusingConfigurations" :disabled="isProcessing(selectedGroup)" @click="reuseExistingConfigurations()">核验并复用已有配置</el-button>
        </div>
        <div v-if="canLinkExternal(selectedGroup)" class="repair-action-strip">
          <span>已在远端后台手动发布？关联当前盘口的发布记录后再下载兑换码。</span>
          <el-button type="primary" plain @click="openExternalPublication(selectedGroup)">{{ externalActionLabel(selectedGroup) }}</el-button>
        </div>
        <div class="task-summary-strip">
          <div><span>当前盘口</span><strong>{{ remoteMarketLabel(selectedGroup) }}</strong></div>
          <div><span>兑换类型 / 日期</span><strong>{{ redemptionTypeLabel(selectedGroup.detail.batch.redemptionType) }}</strong><small>{{ formatDate(selectedGroup.detail.batch.claimDateFrom) }} 至 {{ formatDate(selectedGroup.detail.batch.claimDateTo) }}</small></div>
          <div><span>配置进度</span><strong>{{ confirmedConfigurationCount(selectedGroup) }} / {{ selectedGroup.detail.issues.length }}</strong><small>{{ codeAcquisitionStatus(selectedGroup) }}</small></div>
          <div><span>发布状态</span><el-tag :type="groupStatus(selectedGroup).type">{{ groupStatus(selectedGroup).text }}</el-tag></div>
        </div>
        <details class="task-parameters"><summary>查看完整任务参数、标签与核验说明</summary>
        <el-descriptions :column="narrowTaskDetail ? 1 : 3" border class="group-detail-summary">
          <el-descriptions-item label="任务编号">{{ selectedTaskDisplayId }}</el-descriptions-item>
          <el-descriptions-item label="操作人">{{ selectedGroup.detail.batch.operatorUsername || '—' }}</el-descriptions-item>
          <el-descriptions-item label="子任务编号">{{ subtaskDisplayId(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="开始兑换日期">{{ formatDate(selectedGroup.detail.batch.claimDateFrom) }} 至 {{ formatDate(selectedGroup.detail.batch.claimDateTo) }}</el-descriptions-item>
          <el-descriptions-item label="发布状态"><el-tag :type="groupStatus(selectedGroup).type">{{ groupStatus(selectedGroup).text }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="兑换码状态">{{ codeAcquisitionStatus(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="远端核验">{{ publicationCheckErrors[String(selectedGroup.detail.batch.id)] || publicationCheck(selectedGroup)?.configurationError || (publicationCheck(selectedGroup)?.checkedAt ? `核验时间：${formatDateTime(publicationCheck(selectedGroup)?.checkedAt)}` : '尚未核验') }}</el-descriptions-item>
          <el-descriptions-item v-if="publicationCheck(selectedGroup)?.configurations.some(item => item.state !== 'MATCHED')" label="配置核验结果" :span="2">{{ configurationVerificationSummary(publicationCheck(selectedGroup), undefined, selectedGroup.detail.issues) }}</el-descriptions-item>
          <el-descriptions-item label="远端账号">{{ selectedGroup.detail.batch.remoteConnectionName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="盘口">{{ remoteMarketLabel(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="兑换码类型">{{ redemptionTypeLabel(selectedGroup.detail.batch.redemptionType) }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedGroup.detail.batch.redemptionType !== 'AGENT'" label="10000 档位码串后缀">{{ selectedGroup.detail.batch.specialCodeNaming === 'TEN_K' ? '10K' : '10000' }}</el-descriptions-item>
          <el-descriptions-item label="用户类型 / 标签 ID">{{ labelsFor(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="本任务填写的单码领取上限">{{ singleKeyLimitLabel(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="远端生效规则" :span="2">{{ batchValidityRuleLabel(selectedGroup.detail.batch) }}</el-descriptions-item>
          <el-descriptions-item label="发布时间" :span="2">{{ publishTime(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item v-if="groupRemark(selectedGroup) !== '—'" label="备注" :span="2">{{ groupRemark(selectedGroup) }}</el-descriptions-item>
        </el-descriptions>
        </details>
        <el-alert v-if="selectedGroup.detail.batch.remotePublishError" class="group-detail-error" type="error" :closable="false" show-icon>{{ selectedGroup.detail.batch.remotePublishError }}</el-alert>
        <div class="task-detail-views"><el-button :type="detailPane === 'configurations' ? 'primary' : 'default'" @click="closeTaskDeletion">配置列表（{{ selectedGroup.detail.issues.length }}）</el-button><el-button v-if="canGenerate" :type="detailPane === 'deletion' ? 'primary' : 'default'" @click="showTaskDeletion(undefined, false)">删除进度与结果</el-button></div>
        <RedemptionTaskDeletionDialog v-if="detailPane === 'deletion' && taskDeletionTarget" :key="deletionPanelKey" :task-id="taskDeletionTarget.taskId" :task-number="taskDeletionTarget.taskNumber" :issue-ids="taskDeletionTarget.issueIds" :start-new="taskDeletionTarget.startNew" embedded read-only-open @close="closeTaskDeletion" @changed="refreshRecoveryGroups" />
        <section v-if="detailPane === 'configurations'" class="task-configurations">
        <div class="task-config-filters">
          <el-input v-model="detailSearch" clearable placeholder="搜索兑换码、配置 ID 或档位" aria-label="搜索配置" />
          <el-date-picker v-model="detailDate" type="date" clearable value-format="YYYY-MM-DD" placeholder="开始兑换日" aria-label="筛选开始兑换日" />
          <el-select v-model="detailStatus" clearable placeholder="全部状态" aria-label="筛选配置状态"><el-option v-for="status in detailStatusOptions" :key="status" :value="status" :label="status" /></el-select>
          <span>{{ filteredDetailIssues.length }} / {{ selectedGroup.detail.issues.length }} 条配置</span>
        </div>
        <div class="task-selection-bar"><span>已选 {{ selectedDeletionIds.length }} 条可删除配置</span><el-button v-if="canGenerate" type="danger" :disabled="!selectedDeletionIds.length" @click="showTaskDeletion(selectedDeletionIds)">删除已选（{{ selectedDeletionIds.length }}）</el-button><el-button :disabled="!selectedDeletionIds.length && !selectedFailedIssueCount" @click="clearFailedIssueSelection">清除选择</el-button></div>
        <div v-if="failedRemoteCreationCount" class="group-detail-toolbar">
          <span>当前盘口有 {{ failedRemoteCreationCount }} 条远端配置生成失败；勾选后可批量重试。</span>
          <el-button type="warning" :disabled="!selectedFailedIssueCount || isRepairing(selectedGroup)" :loading="retryingSelectedFailedTasks" @click="retrySelectedFailedRemoteCreations">批量重试已选（{{ selectedFailedIssueCount }}）</el-button>
        </div>
        <p class="field-note">展开行首箭头可查看完整生效时间、配置备注、标签与核验说明。</p>
        <el-table ref="failedIssueTable" :data="filteredDetailIssues" row-key="id" class="group-detail-table" height="clamp(320px, 56vh, 780px)" @selection-change="updateDetailSelection">
          <el-table-column type="selection" width="44" fixed="left" :selectable="selectableDetailIssue" />
          <el-table-column type="expand" width="44"><template #default="{ row }"><dl class="configuration-expanded">
            <div><dt>远端配置名称</dt><dd>{{ row.remoteConfigurationName || '—' }}</dd></div>
            <div><dt>远端生效日期</dt><dd>{{ issueValidityLabel(selectedGroup.detail.batch, row.claimDate) }}</dd></div>
            <div><dt>兑换码 / 完整内容</dt><dd>{{ row.redemptionCode || '尚未下载' }}</dd></div>
            <div><dt>远端配置备注</dt><dd>{{ row.remoteConfigurationRemark || '—' }}</dd></div>
            <div><dt>状态与错误说明</dt><dd>{{ issueRemark(row) || issueStatus(row).text }}</dd></div>
            <div><dt>复用关联 / 核验说明</dt><dd>{{ row.recovery?.reason || reuseCheckErrors[String(row.id)] || reuseOrigin(row) || '—' }}</dd></div>
            <div><dt>标签 ID</dt><dd>{{ row.remoteLabelIds?.join('、') || '全部用户 / 无标签' }}</dd></div>
          </dl></template></el-table-column>
          <el-table-column prop="remoteConfigurationId" label="配置 ID" width="88"><template #default="{ row }">{{ row.remoteConfigurationId || '—' }}</template></el-table-column>
          <el-table-column label="兑换码" min-width="160"><template #default="{ row }"><strong class="configuration-code">{{ row.redemptionCode || '尚未下载' }}</strong></template></el-table-column>
          <el-table-column label="开始兑换日" width="118"><template #default="{ row }">{{ formatDate(row.claimDate) }}</template></el-table-column>
          <el-table-column label="充值档位" min-width="150"><template #default="{ row }">{{ row.tierName || `充值 ≥ ${formatAmount(row.minDepositAmount)}` }}</template></el-table-column>
          <el-table-column label="任务奖励" width="110"><template #default="{ row }">{{ formatAmount(row.bonusAmount) }}–{{ formatAmount(row.bonusMaxAmount || row.bonusAmount) }}</template></el-table-column>
          <el-table-column label="每码领取上限" width="116"><template #default="{ row }">{{ reusedIssueLimitLabel(selectedGroup, row) }}</template></el-table-column>
          <el-table-column label="状态" width="116"><template #default="{ row }"><el-tag :type="issueStatus(row).type" size="small">{{ issueStatus(row).text }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="188" :fixed="narrowTaskDetail ? undefined : 'right'"><template #default="{ row }"><div class="configuration-row-actions"><el-button v-if="canGenerate && row.remoteConfigurationId" link type="danger" :loading="deletingIssueId === row.id" :disabled="Boolean(deletingIssueId)" @click="deleteRemoteConfiguration(row)">{{ deletionHeld(row) ? '核对删除结果' : '删除配置' }}</el-button><el-button v-if="canGenerate && !deletionHeld(row)" link type="primary" :disabled="checkingRewardPolicy || applyingRewardPolicy" @click="inspectRewardPolicies(row)">核验奖励</el-button><el-button v-if="canGenerate && !deletionHeld(row)" link type="warning" :disabled="checkingRecovery || rebuildingMissing" @click="inspectMissingConfigurations(row)">{{ row.recovery ? '核验 / 重试重建' : '核验缺失' }}</el-button><el-button v-if="canCreatePendingRemoteConfiguration(row)" link type="primary" :loading="retryingIssueId === row.id" @click="createOnePendingRemoteConfiguration(row)">创建此配置</el-button><el-button v-if="canReuseExistingConfiguration(row)" link type="primary" :loading="reusingConfigurations" @click="reuseExistingConfigurations(row)">核验复用</el-button><el-button v-if="canRetryRemoteCreation(row)" link type="primary" :loading="retryingIssueId === row.id" :disabled="retryingSelectedFailedTasks" @click="retryRemoteCreation(row)">{{ row.workflowStatus === 'CREATING_REMOTE' ? '恢复重试' : '重试创建' }}</el-button></div></template></el-table-column>
        </el-table>
        </section>
        <div class="drawer-actions">
          <el-button v-if="hasPendingPublishReservation(selectedGroup)" type="warning" :loading="recoveringPublishId === selectedGroup.detail.batch.id" @click="recoverPublishReservation(selectedGroup)">恢复发布</el-button>
          <el-button v-else-if="selectedGroup.detail.batch.status === 'READY_TO_PUBLISH'" type="primary" @click="openPublishDialog(selectedGroup)">选择发布方式</el-button>
          <el-button v-if="selectedGroup.detail.batch.status === 'PUBLISHED' && selectedGroup.detail.batch.remotePublishTaskId" :loading="verifyingPublicationIds.has(String(selectedGroup.detail.batch.id))" @click="inspectPublication(selectedGroup)">{{ missingConfigurations(selectedGroup).length ? '处理缺失配置' : '查看核验结果' }}</el-button>
          <el-button v-if="(missingConfigurations(selectedGroup).length || isRepairing(selectedGroup)) && selectedGroup.detail.batch.importedCount > 0 && canExport" :loading="resolvingMissingBatchId === selectedGroup.detail.batch.id" @click="acceptAvailableCodes(selectedGroup)">仅下载已有兑换码</el-button>
          <el-button v-if="canCancelScheduledPublish(selectedGroup)" type="danger" :disabled="!canCancelScheduledPublish(selectedGroup)" :loading="cancellingPublishId === selectedGroup.detail.batch.id" @click="cancelScheduledPublish(selectedGroup)">撤销发布</el-button>
          <el-button v-if="canStartDownload(selectedGroup) && !isSuccess(selectedGroup)" type="primary" :loading="isProcessing(selectedGroup)" :disabled="downloadingTask" @click="requestDownload(selectedGroup, false)">{{ selectedGroup.detail.issues.some(issue => issue.remoteError) ? '重试下载' : '下载兑换码' }}</el-button>
          <el-button v-if="canStartDownload(selectedGroup) && canExport" type="primary" :icon="Download" :loading="exportingId === selectedGroup.detail.batch.id" :disabled="downloadingTask" @click="requestDownload(selectedGroup, true)">下载当前盘口 Excel</el-button>
        </div>
      </template>
    </article>
  </section>
</template>

<style scoped>

.task-detail-workspace { min-width: 0; }
.task-detail-heading, .task-detail-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.task-detail-heading { margin-bottom: 20px; }
.task-detail-heading h2 { margin: 8px 0 0; font-size: 24px; color: var(--theme-text-strong, var(--el-text-color-primary)); }
.task-detail-heading h2 { overflow-wrap: anywhere; }
.task-detail-heading h2 span { font-size: 16px; font-weight: 400; color: var(--el-text-color-secondary); }
.task-summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; padding: 16px; border: 1px solid var(--el-border-color); background: var(--el-bg-color); border-radius: 8px; }
.task-summary-strip > div { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; min-width: 0; }
.task-summary-strip span, .task-summary-strip small { color: var(--el-text-color-secondary); font-size: 12px; }
.task-summary-strip strong { font-size: 14px; font-weight: 600; color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
.task-parameters { margin: 12px 0 20px; }
.task-parameters summary { cursor: pointer; padding: 8px 0; color: var(--el-color-primary); font-size: 13px; }
.task-detail-views { display: flex; gap: 8px; margin-bottom: 16px; }
.task-detail-views :deep(.el-button + .el-button), .task-selection-bar :deep(.el-button + .el-button) { margin-left: 0; }
.task-config-filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.task-config-filters > .el-input { width: 300px; }
.task-config-filters > .el-select { width: 180px; }
.task-config-filters > span, .task-selection-bar > span { color: var(--el-text-color-secondary); font-size: 13px; }
.task-selection-bar { display: flex; align-items: center; gap: 12px; padding: 12px 0; }
.configuration-row-actions { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.configuration-row-actions :deep(.el-button + .el-button) { margin-left: 0; }
.configuration-expanded { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 24px; margin: 0; padding: 16px 24px; }
.configuration-expanded dt { color: var(--el-text-color-secondary); font-size: 12px; margin-bottom: 6px; }
.configuration-expanded dd { margin: 0; color: var(--el-text-color-primary); white-space: pre-wrap; overflow-wrap: anywhere; }
.configuration-code { font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px; overflow-wrap: anywhere; }
.group-detail-table :deep(.cell) { white-space: normal; overflow-wrap: anywhere; line-height: 1.55; }
.task-detail-workspace .repair-action-strip { flex-wrap: wrap; }
.task-detail-workspace .drawer-actions { flex-wrap: wrap; }
@media (max-width: 900px) {
  .task-summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .configuration-expanded { grid-template-columns: minmax(0, 1fr); padding: 16px; max-width: calc(100vw - 112px); box-sizing: border-box; }
  .task-detail-heading h2 { font-size: 20px; }
  .task-config-filters > .el-input, .task-config-filters > .el-select { width: 100%; }
  .task-detail-views { flex-wrap: wrap; }
  .task-detail-actions { justify-content: flex-start; }
  .task-detail-actions :deep(.el-button + .el-button) { margin-left: 0; }
  .task-selection-bar { flex-wrap: wrap; }
}

.publication-status-cell { display: flex; flex-direction: column; align-items: center; gap: 5px; }
.publication-status-cell small { color: var(--theme-text-muted, #65748b); }
.publication-status-cell .creation-status-summary { display: -webkit-box; overflow: hidden; max-width: 100%; color: var(--theme-warning, #9a3412); font-size: 12px; line-height: 15px; white-space: normal; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.redemption-alert { margin-bottom: 18px; }
.code-group-list { overflow: hidden; }
.code-group-list__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 19px 20px 16px; border-bottom: 1px solid var(--theme-border, #eaecf0); }
.code-group-list__heading h3 { margin: 0; color: var(--theme-text-strong, #101828); font-size: 15px; }
.code-group-list__heading p { margin: 5px 0 0; color: var(--theme-text-muted, #667085); font-size: 12px; }
.code-group-list__count { padding-top: 3px; color: var(--theme-text-muted, #667085); font-size: 12px; white-space: nowrap; }
.code-group-virtual-table { height: clamp(360px, calc(100vh - 320px), 640px); min-width: 0; }
.code-group-loading { min-height: 190px; }
.code-group-table { --el-table-header-bg-color: var(--theme-surface-muted, #f9fafb); --el-table-border-color: var(--theme-border, #eaecf0); --el-table-row-hover-bg-color: var(--theme-info-bg, #f8fbff); }
.code-group-table :deep(.el-table-v2__header-cell) { color: var(--theme-text-muted, #667085); font-size: 12px; font-weight: 600; }
.code-group-table :deep(.el-table-v2__row-cell) { padding: 0 12px; color: var(--theme-text, #475467); font-size: 12px; }
.code-group-list__pagination { display: flex; justify-content: flex-end; padding: 14px 20px; border-top: 1px solid var(--theme-border, #eaecf0); }
.group-name { display: grid; gap: 5px; }
.group-name strong { color: var(--theme-text-strong, #182230); font-size: 13px; }
.group-name span { overflow: hidden; color: var(--theme-text-muted, #98a2b3); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.virtual-cell { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.virtual-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px; width: 100%; }
.virtual-actions :deep(.el-button + .el-button) { margin-left: 0; }
.group-progress { color: var(--theme-text, #475467); font-size: 12px; white-space: nowrap; }
.code-group-form__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.code-group-form__grid--options { grid-template-columns: 1.15fr 1fr 1fr; }
.code-group-form__date-range { grid-column: 1 / -1; }
.code-group-form__validity { grid-column: 1 / -1; }
.code-group-form__code-type { grid-column: 1 / -1; }
.code-group-form__market { grid-column: 1 / -1; }
.date-presets { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.date-presets span { color: var(--theme-text-muted, #667085); font-size: 12px; }
.validity-editor { width: 100%; padding: 13px 14px; border: 1px solid var(--theme-border, #d0d5dd); border-radius: 9px; background: var(--theme-surface, #fff); }
.validity-editor__offsets { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.validity-editor__offsets label { display: grid; grid-template-columns: auto auto minmax(110px, 1fr) auto; align-items: center; gap: 8px; color: var(--theme-text, #475467); font-size: 13px; }
.validity-editor__formula { color: var(--theme-text-muted, #667085); white-space: nowrap; }
.validity-preview { display: grid; gap: 7px; margin-top: 12px; padding: 10px 12px; border-radius: 7px; background: var(--theme-info-bg, #f5f8ff); color: var(--theme-text, #344054); font-size: 12px; }
.validity-preview__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.validity-preview__heading strong { color: var(--theme-info, #175cd3); font-size: 13px; }
.validity-preview__heading span { color: var(--theme-text-muted, #667085); }
.validity-preview__row { display: grid; grid-template-columns: 90px minmax(150px, 1fr) auto minmax(150px, 1fr); align-items: center; gap: 8px; }
.validity-preview__row code { padding: 3px 6px; border: 1px solid var(--theme-info-border, #d1e0ff); border-radius: 4px; background: var(--theme-surface, #fff); color: var(--theme-info, #1849a9); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; text-align: center; }
.field-note { margin: 6px 0 0; color: var(--theme-text-muted, #667085); font-size: 12px; line-height: 1.5; }
.field-note strong { color: var(--theme-text, #344054); font-weight: 600; }
.field-note--danger { color: var(--theme-danger, #b42318); }
.field-unit { margin-left: 7px; color: var(--theme-text-muted, #667085); font-size: 13px; }
.tier-panel { margin: 10px 0 18px; padding: 15px; background: var(--theme-surface-muted, #f9fafb); border: 1px solid var(--theme-border, #eaecf0); border-radius: 10px; }
.tier-panel__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.tier-panel__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.tier-panel__heading strong { color: var(--theme-text, #344054); font-size: 14px; }
.tier-panel__heading p { margin: 5px 0 0; color: var(--theme-text-muted, #667085); font-size: 12px; }
.tier-panel__preset-copy { margin-left: 7px; }
.tier-editor { overflow: hidden; border: 1px solid var(--theme-border, #eaecf0); border-radius: 8px; background: var(--theme-surface, #fff); }
.tier-editor__header, .tier-editor__row { display: grid; grid-template-columns: minmax(132px, .72fr) minmax(300px, 1.8fr) minmax(138px, .82fr) minmax(138px, .82fr) 44px; align-items: center; gap: 10px; padding: 9px 11px; }
.tier-editor__header { color: var(--theme-text-muted, #667085); font-size: 12px; font-weight: 600; background: var(--theme-surface-muted, #f2f4f7); }
.tier-editor__row { border-top: 1px solid var(--theme-surface-muted, #f2f4f7); }
.tier-editor__all-users { min-height: 32px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 11px; color: var(--theme-text, #344054); border: 1px solid var(--theme-border, #d0d5dd); border-radius: 4px; background: var(--theme-surface-muted, #f9fafb); }
.tier-editor__all-users span { color: var(--theme-text-muted, #98a2b3); font-size: 12px; white-space: nowrap; }
.advanced-options { border-top: 1px solid var(--theme-border, #eaecf0); }
.advanced-options :deep(.el-collapse-item__header) { gap: 8px; color: var(--theme-text, #344054); font-weight: 600; }
.advanced-options__fixed { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 2px 0 14px; color: var(--theme-text-muted, #667085); font-size: 12px; }
.advanced-options__fixed span { padding: 5px 8px; border: 1px solid var(--theme-border, #eaecf0); border-radius: 6px; background: var(--theme-surface-muted, #f9fafb); }
.advanced-options__toggle-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.submit-hint { margin: 0; color: var(--theme-text-muted, #667085); font-size: 12px; }
.group-detail-summary { margin-bottom: 18px; }
.repair-action-strip { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; padding: 12px 14px; border: 1px solid var(--theme-warning-border, #fed7aa); border-radius: 8px; background: var(--theme-warning-bg, #fffbeb); color: var(--theme-warning, #9a3412); font-size: 13px; }
.group-detail-error { margin-bottom: 14px; }
.group-detail-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; color: var(--theme-text-muted, #667085); font-size: 13px; }
.group-detail-table { --el-table-header-bg-color: var(--theme-surface-muted, #f9fafb); --el-table-border-color: var(--theme-border, #eaecf0); }
.task-market-tabs { margin-bottom: 8px; }
.task-detail-note { margin: 0 0 14px; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 18px 0; }
</style>
