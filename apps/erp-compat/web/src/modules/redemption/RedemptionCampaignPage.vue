<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Download, Plus, Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import type {
  RedemptionBatchDetail,
  RedemptionCampaign,
  RedemptionCodeGroupInput,
  RedemptionCodeIssue,
  RedemptionCodeType,
  RedemptionRemoteConnection,
  RedemptionRemoteCreationOptions,
  RedemptionRemoteTag,
  RedemptionRewardTierPreset,
} from '@/api/types'
import { saveDownloadedFile } from '@/utils/download'
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
  tiers: CodeGroupTierDraft[]
  remoteOptions: RedemptionRemoteCreationOptions
}

interface MarketTierDraft {
  tiers: CodeGroupTierDraft[]
  remoteTags: RedemptionRemoteTag[]
  remoteTagsLoaded: boolean
  rewardTierPreset?: RedemptionRewardTierPreset
}

type PreviousDayProfile = 'WIN' | 'LUCK_SPIN'

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
const loading = ref(false)
const working = ref(false)
const exportingId = ref<string | number>()
const exportingGroupKey = ref<string>()
const remoteConnectionsLoading = ref(false)
const remoteTagsLoading = ref(false)
const remoteTagsLoaded = ref(false)
const rewardTierPresetLoading = ref(false)
const rewardTierPresetSaving = ref(false)
const codeGroupDialogVisible = ref(false)
const publishDialogVisible = ref(false)
const detailDrawerVisible = ref(false)
const advancedOptionsOpen = ref<string[]>([])
const publishOptionsOpen = ref<string[]>([])
const campaigns = ref<RedemptionCampaign[]>([])
const codeGroups = ref<CodeGroupRow[]>([])
const selectedTaskMembers = ref<CodeGroupRow[]>([])
const activeTaskBatchId = ref('')
const remoteConnections = ref<RedemptionRemoteConnection[]>([])
const remoteTags = ref<RedemptionRemoteTag[]>([])
const rewardTierPreset = ref<RedemptionRewardTierPreset>()
const marketTierDrafts = ref<Record<string, MarketTierDraft>>({})
const activeMarketTab = ref('')
const selectedGroup = ref<CodeGroupRow>()
const selectedTaskId = computed(() => selectedTaskMembers.value[0]?.detail.batch.taskId ?? selectedTaskMembers.value[0]?.detail.batch.id)
const publishTarget = ref<CodeGroupRow | CodeGroupTask>()
const publishing = ref(false)
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

const previousDayFallbackTags: RedemptionRemoteTag[] = [
  { id: 901991, name: '(901991)日充值200-999' },
  { id: 901993, name: '(901993)日充值1000-2999' },
  { id: 901996, name: '(901996)日充值3000-9999' },
  // Verified in both RajLuck and RajSpin remote consoles.
  { id: 901994, name: '(901994)日充值3000-9999' },
  { id: 901020, name: '(901020)日充值recharge today-10000+' },
]

const sevenDayTierProfiles: SevenDayTierProfile[] = [
  { fallbackLabelId: 901091, name: '近 7 天充值总金额 100–499', minDepositAmount: 100, maxDepositAmount: 499, bonusAmount: 1, bonusMaxAmount: 3 },
  { fallbackLabelId: 901092, name: '近 7 天充值总金额 500–1,999', minDepositAmount: 500, maxDepositAmount: 1999, bonusAmount: 5, bonusMaxAmount: 7 },
  { fallbackLabelId: 901093, name: '近 7 天充值总金额 2,000–4,999', minDepositAmount: 2000, maxDepositAmount: 4999, bonusAmount: 9, bonusMaxAmount: 11 },
  { fallbackLabelId: 901095, name: '近 7 天充值总金额 5,000–9,999', minDepositAmount: 5000, maxDepositAmount: 9999, bonusAmount: 17, bonusMaxAmount: 27 },
  { fallbackLabelId: 901094, name: '近 7 天充值总金额 10,000 以上', minDepositAmount: 10000, bonusAmount: 37, bonusMaxAmount: 57 },
]

const previousDayProfiles: Record<PreviousDayProfile, Array<Omit<TierProfile, 'id'> & { id?: number }>> = {
  WIN: [
    { id: undefined, name: '日充值 0（所有用户）', minDepositAmount: 0, bonusAmount: 1, bonusMaxAmount: 3 },
    { id: 901991, name: '日充值 200–999', minDepositAmount: 200, bonusAmount: 7, bonusMaxAmount: 9 },
    { id: 901993, name: '日充值 1,000–2,999', minDepositAmount: 1000, bonusAmount: 13, bonusMaxAmount: 17 },
    { id: 901996, name: '日充值 3,000–9,999', minDepositAmount: 3000, bonusAmount: 27, bonusMaxAmount: 37 },
    { id: 901020, name: '日充值 10,000+', minDepositAmount: 10000, bonusAmount: 57, bonusMaxAmount: 77 },
  ],
  LUCK_SPIN: [
    { id: undefined, name: '日充值 0（所有用户）', minDepositAmount: 0, bonusAmount: 1, bonusMaxAmount: 3 },
    { id: 901991, name: '日充值 200–999', minDepositAmount: 200, bonusAmount: 7, bonusMaxAmount: 9 },
    { id: 901993, name: '日充值 1,000–2,999', minDepositAmount: 1000, bonusAmount: 13, bonusMaxAmount: 17 },
    { id: 901994, name: '日充值 3,000–9,999', minDepositAmount: 3000, bonusAmount: 27, bonusMaxAmount: 37 },
    { id: 901020, name: '日充值 10,000+', minDepositAmount: 10000, bonusAmount: 57, bonusMaxAmount: 77 },
  ],
}

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
const failedRemoteCreationCount = computed(() => selectedGroup.value ? failedRemoteCreationIssues(selectedGroup.value).length : 0)
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
const previousDayTagOptions = computed(() => remoteTagsLoaded.value ? remoteTags.value : previousDayFallbackTags)
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
function previousDayProfileForMarket(marketId?: string | number): PreviousDayProfile | undefined {
  const identities = marketIdentities(marketId)
  if (identities.some((value) => value === 'rajwin')) return 'WIN'
  if (identities.some((value) => value === 'rajluck' || value === 'rajspin')) return 'LUCK_SPIN'
  return undefined
}
const previousDayProfile = computed(() => previousDayProfileForMarket(form.value.remoteMarketId))
const previousDayProfileLabel = computed(() => {
  if (previousDayProfile.value === 'WIN') return 'Win（RajWin）'
  if (previousDayProfile.value === 'LUCK_SPIN') return 'Luck Spin（RajLuck、RajSpin）'
  return '该盘口尚未配置日充值标签方案'
})

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

function previousDayTiers(profile: PreviousDayProfile): CodeGroupTierDraft[] {
  return previousDayProfiles[profile].map((tier) => ({
    userType: tier.id === undefined ? 'ALL_USERS' : 'LABEL_USERS',
    displayName: tier.name,
    minDepositAmount: tier.minDepositAmount,
    bonusAmount: tier.bonusAmount,
    bonusMaxAmount: tier.bonusMaxAmount,
    labelIds: tier.id === undefined ? [] : [tier.id],
  }))
}

function isPreviousDayDeposit() { return form.value.redemptionType === 'PREVIOUS_DAY_DEPOSIT' }
function isAllUsersTier(tier: CodeGroupTierDraft) { return tier.userType === 'ALL_USERS' }
function redemptionTypeLabel(type: RedemptionCodeType) { return type === 'PREVIOUS_DAY_DEPOSIT' ? '日充值' : '近 7 天充值' }

function newCodeGroupForm(): CodeGroupForm {
  const range = futureRange(7)
  return {
    dateRange: range,
    validityMode: 'CLAIM_DAY',
    validFromDayOffset: 0,
    validToDayOffset: 0,
    remoteMarketIds: [],
    redemptionType: 'SEVEN_DAY_DEPOSIT',
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
  if (String(form.value.remoteMarketId) !== String(marketId)) saveActiveMarketDraft()
  form.value.remoteMarketId = marketId
  activeMarketTab.value = marketKey(marketId)
  if (restoreMarketDraft(marketId)) return
  form.value.tiers = []
  remoteTags.value = []
  remoteTagsLoaded.value = false
  rewardTierPreset.value = undefined
  if (isPreviousDayDeposit()) {
    resetPreviousDayTiers()
    saveActiveMarketDraft()
  } else {
    await loadMarketTierConfiguration()
  }
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
function indiaNowText() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date()).reduce<Record<string, string>>((result, part) => {
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
function isSuccess(row: CodeGroupRow) { return row.detail.batch.status === 'COMPLETED' }
function pendingRemoteCreationIssues(row: CodeGroupRow) {
  return row.detail.issues.filter((issue) => issue.workflowStatus === 'PENDING_CREATION')
}
function hasRemoteCreationInProgress(row: CodeGroupRow) {
  return row.detail.issues.some((issue) => issue.workflowStatus === 'CREATING_REMOTE')
}
function failedIssues(row: CodeGroupRow) {
  return row.detail.issues.filter((issue) => issue.workflowStatus === 'FAILED' || (issue.workflowStatus === 'PUBLISHED' && Boolean(issue.remoteError)))
}
function failedRemoteCreationIssues(row: CodeGroupRow) {
  return row.detail.issues.filter((issue) => issue.workflowStatus === 'FAILED')
}
function isFailedRemoteCreation(issue: RedemptionCodeIssue) {
  return issue.workflowStatus === 'FAILED'
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
  failedIssueTable.value?.clearSelection()
}
function groupFailureMessage(row: CodeGroupRow) {
  return row.detail.batch.remotePublishError || failedIssues(row)[0]?.remoteError
}
function groupRemark(row: CodeGroupRow) {
  const reasons = [row.detail.batch.remotePublishNote, row.detail.batch.remotePublishError, ...failedIssues(row).map((issue) => issue.remoteError)]
    .filter((reason): reason is string => Boolean(reason))
  return [...new Set(reasons)].join('；') || '—'
}
function groupStatus(row: CodeGroupRow) {
  if (groupFailureMessage(row)) return { text: '生成失败', type: 'danger' as const }
  if (isSuccess(row)) return { text: '生成成功', type: 'success' as const }
  if (hasScheduledPublishReached(row)) return { text: '待下载', type: 'info' as const }
  if (isScheduledPublish(row)) return { text: '定时发布中', type: 'warning' as const }
  if (row.detail.batch.status === 'PUBLISHED') return { text: '已发布', type: 'primary' as const }
  if (row.detail.batch.status === 'READY_TO_PUBLISH') return { text: '待发布', type: 'info' as const }
  if (hasRemoteCreationInProgress(row)) return { text: '生成中', type: 'warning' as const }
  if (pendingRemoteCreationIssues(row).length) return { text: '生成中', type: 'warning' as const }
  return { text: '生成中', type: 'warning' as const }
}
function groupProgress(row: CodeGroupRow) {
  const batch = row.detail.batch
  if (isSuccess(row)) return `${batch.importedCount} / ${batch.expectedCodeCount} 个兑换码已入库`
  if (batch.remotePublishError) return `远端发布失败：${batch.remotePublishError}`
  if (hasScheduledPublishReached(row)) return '定时发布已到时，可开始下载兑换码'
  if (isScheduledPublish(row)) return `定时发布：${formatIndiaDateTime(batch.remoteScheduledPublishAt)}`
  if (batch.status === 'PUBLISHED') return `${batch.publishedCount} / ${batch.expectedCodeCount} 条远端配置已发布，待下载兑换码`
  if (failedIssues(row).length) return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建，${failedIssues(row).length} 个任务失败`
  if (batch.status === 'READY_TO_PUBLISH') return `${batch.createdCount} / ${batch.expectedCodeCount} 条远端配置已创建，待发布`
  const pending = pendingRemoteCreationIssues(row).length
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
  return task.members.map((member) => `#${member.detail.batch.id}`).join('、')
}
function taskSummary(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return `执行批次 #${taskPrimary(task).detail.batch.id}`
  return `执行批次 ${taskBatchNumbers(task)} · 包含 ${task.members.length} 个盘口，按选择顺序串行执行`
}
function taskMemberLabel(member: CodeGroupRow) {
  return `${remoteMarketLabel(member)} · 批次 #${member.detail.batch.id}`
}
function taskMarkets(task: CodeGroupTask) {
  return task.members.map(remoteMarketLabel).filter((value, index, values) => values.indexOf(value) === index).join(' → ') || '—'
}
function taskAccounts(task: CodeGroupTask) {
  return task.members.map((member) => member.detail.batch.remoteConnectionName || '—')
    .filter((value, index, values) => values.indexOf(value) === index).join('、')
}
function taskLabels(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return labelsFor(taskPrimary(task))
  return task.members.map((member) => `${remoteMarketLabel(member)}：${labelsFor(member)}`).join('；')
}
function taskTiers(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return tiersFor(taskPrimary(task))
  return task.members.map((member) => `${remoteMarketLabel(member)}：${tiersFor(member)}`).join('；')
}
function taskStatus(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return groupStatus(taskPrimary(task))
  if (task.members.some(groupFailureMessage)) return { text: '部分生成失败', type: 'danger' as const }
  if (task.members.every(isSuccess)) return { text: '生成成功', type: 'success' as const }
  if (task.members.every((member) => member.detail.batch.status === 'PUBLISHED')) return { text: '已发布', type: 'primary' as const }
  if (task.members.every((member) => member.detail.batch.status === 'READY_TO_PUBLISH')) return { text: '待发布', type: 'info' as const }
  if (task.members.some(isScheduledPublish)) return { text: '发布中', type: 'warning' as const }
  if (task.members.some(hasRemoteCreationInProgress)) return { text: '生成中', type: 'warning' as const }
  if (task.members.some((member) => pendingRemoteCreationIssues(member).length > 0)) return { text: '生成中', type: 'warning' as const }
  return { text: '生成中', type: 'warning' as const }
}
function taskProgress(task: CodeGroupTask) {
  if (!isMultiMarketTask(task)) return groupProgress(taskPrimary(task))
  const expected = task.members.reduce((total, member) => total + member.detail.batch.expectedCodeCount, 0)
  const created = task.members.reduce((total, member) => total + member.detail.batch.createdCount, 0)
  const imported = task.members.reduce((total, member) => total + member.detail.batch.importedCount, 0)
  if (task.members.every(isSuccess)) return `${imported} / ${expected} 个兑换码已入库`
  if (task.members.every((member) => member.detail.batch.status === 'PUBLISHED')) {
    const published = task.members.reduce((total, member) => total + member.detail.batch.publishedCount, 0)
    return `${published} / ${expected} 条远端配置已发布，待下载兑换码`
  }
  const failed = task.members.reduce((total, member) => total + failedIssues(member).length, 0)
  if (failed) return `${created} / ${expected} 条远端配置已创建，${failed} 个失败`
  const pending = task.members.reduce((total, member) => total + pendingRemoteCreationIssues(member).length, 0)
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
function canExportMultiMarketTask(task: CodeGroupTask) {
  return Boolean(task.exportGroupKey) && isMultiMarketTask(task) && task.members.every(isSuccess)
}
function canPublishMultiMarketTask(task: CodeGroupTask) {
  return isMultiMarketTask(task) && task.members.every((member) => member.detail.batch.status === 'READY_TO_PUBLISH')
}
function isMultiMarketPublishTarget(target?: CodeGroupRow | CodeGroupTask): target is CodeGroupTask {
  return Boolean(target && 'members' in target)
}
function publishRows(target: CodeGroupRow | CodeGroupTask) {
  return isMultiMarketPublishTarget(target) ? target.members : [target]
}

function canCancelScheduledPublish(row: CodeGroupRow) {
  const scheduledTime = row.detail.batch.remoteScheduledPublishAt
  return isScheduledPublish(row) && Boolean(scheduledTime) && formatIndiaDateTime(scheduledTime) > indiaNow.value
}
function isScheduledPublish(row: CodeGroupRow) {
  const batch = row.detail.batch
  return batch.status === 'PUBLISHED' && batch.remotePublishMode === 'SCHEDULED' && !batch.remotePublishCancelledAt
}
function hasScheduledPublishReached(row: CodeGroupRow) {
  const scheduledTime = row.detail.batch.remoteScheduledPublishAt
  return isScheduledPublish(row) && Boolean(scheduledTime) && formatIndiaDateTime(scheduledTime) <= indiaNow.value
}
function canDownloadScheduledCodes(row: CodeGroupRow) {
  return hasScheduledPublishReached(row) && row.detail.issues.some((issue) => issue.workflowStatus === 'CREATED' || issue.workflowStatus === 'PUBLISHED')
}
function publishTime(row: CodeGroupRow) {
  const batch = row.detail.batch
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
  if (issue.workflowStatus === 'CODE_IMPORTED') return { text: '兑换码已下载', type: 'success' as const }
  if (issue.workflowStatus === 'FAILED') return { text: '生成失败', type: 'danger' as const }
  if (issue.workflowStatus === 'PUBLISHED' && issue.remoteError) return { text: '下载失败', type: 'danger' as const }
  if (issue.workflowStatus === 'PUBLISHED') return { text: '已发布', type: 'primary' as const }
  if (issue.workflowStatus === 'CREATED') return { text: '待发布', type: 'warning' as const }
  if (issue.workflowStatus === 'PENDING_CREATION') return { text: '待创建', type: 'info' as const }
  return { text: '生成中', type: 'info' as const }
}

function canRetryRemoteCreation(issue: RedemptionCodeIssue) {
  return !issue.remoteConfigurationId && (issue.workflowStatus === 'FAILED' || issue.workflowStatus === 'CREATING_REMOTE')
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
  remoteTagsLoading.value = true
  try {
    const result = await api.redemptionRemoteConnections.syncTags(connection.id!)
    remoteTags.value = result.tags
    remoteTagsLoaded.value = true
    if (rewardTierPreset.value?.exists && result.presetStale) {
      rewardTierPreset.value = { ...rewardTierPreset.value, stale: true, lastSyncedAt: result.syncedAt }
      ElMessage.warning(`已同步 ${result.tags.length} 个标签；奖励分档预设已过期，请确认后重新保存`)
    } else {
      ElMessage.success(`已同步 ${result.tags.length} 个标签`)
    }
    saveActiveMarketDraft()
  } catch (error) {
    remoteTags.value = []
    remoteTagsLoaded.value = false
    ElMessage.error(error instanceof Error ? error.message : '读取标签 ID 数组失败')
  } finally {
    remoteTagsLoading.value = false
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
  try {
    const [tags, preset] = await Promise.all([
      api.redemptionRemoteConnections.tags(connection.id!),
      api.redemptionRemoteConnections.rewardTierPreset(connection.id!),
    ])
    if (request !== marketConfigurationRequest) return
    remoteTags.value = tags
    remoteTagsLoaded.value = true
    rewardTierPreset.value = preset
    if (!isPreviousDayDeposit()) applyMarketTierDefaults()
    saveActiveMarketDraft()
  } catch (error) {
    if (request !== marketConfigurationRequest) return
    remoteTags.value = []
    remoteTagsLoaded.value = false
    rewardTierPreset.value = undefined
    if (!isPreviousDayDeposit()) applyMarketTierDefaults()
    saveActiveMarketDraft()
    ElMessage.error(error instanceof Error ? error.message : '读取当前盘口标签或奖励分档预设失败')
  } finally {
    if (request === marketConfigurationRequest) {
      remoteTagsLoading.value = false
      rewardTierPresetLoading.value = false
    }
  }
}

async function loadCodeGroups() {
  loading.value = true
  try {
    campaigns.value = await api.redemption.list()
    const groups = (await Promise.all(campaigns.value.filter((campaign) => campaign.id !== undefined).map(async (campaign) => {
      const batches = await api.redemption.batches(campaign.id!)
      return Promise.all(batches.map(async (batch) => ({ campaign, detail: await api.redemption.batch(batch.id) })))
    }))).flat()
    codeGroups.value = groups.sort((left, right) => String(right.detail.batch.createdAt || '').localeCompare(String(left.detail.batch.createdAt || '')))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '读取兑换码组任务失败')
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
  if (isPreviousDayDeposit()) {
    resetPreviousDayTiers()
    saveActiveMarketDraft()
  } else void loadMarketTierConfiguration()
}

function resetPreviousDayTiers() {
  const profile = previousDayProfile.value
  form.value.tiers = profile ? previousDayTiers(profile) : []
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
    minDepositAmount: Number(tier.minDepositAmount),
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

/** Applies a saved market preset when usable, otherwise that market's standard five tiers. */
function applyMarketTierDefaults() {
  const preset = rewardTierPreset.value
  if (preset?.exists && !preset.stale && savedPresetMatchesCurrentMarket(preset)) {
    form.value.tiers = tiersFromRewardPreset(preset)
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
  const matched = name.match(/(?:充值总金额|充值|deposit\s*>=?)\s*(\d[\d,]*)/i)
  if (!matched) return undefined
  const amount = Number(matched[1].replaceAll(',', ''))
  return Number.isFinite(amount) ? amount : undefined
}

function addTier() {
  const usedLabelIds = new Set(form.value.tiers.flatMap((tier) => tier.labelIds.map(String)))
  const options = isPreviousDayDeposit() ? previousDayTagOptions.value : tagOptions.value
  const availableTag = options.find((tag) => !usedLabelIds.has(String(tag.id)))
  if (!availableTag) {
    ElMessage.warning('所有可用标签都已添加为奖励档位')
    return
  }
  if (isPreviousDayDeposit()) {
    const tier: CodeGroupTierDraft = {
      userType: 'LABEL_USERS',
      displayName: availableTag.name.replace(/^\(\d+\)/, '').trim(),
      minDepositAmount: minimumDepositFromTag(availableTag.name) ?? 0,
      bonusAmount: 1,
      bonusMaxAmount: 3,
      labelIds: [availableTag.id],
    }
    form.value.tiers.push(tier)
  } else {
    form.value.tiers.push(draftTier(availableTag.id))
  }
}

function isLabelUsedByOtherTier(labelId: string | number, currentTier: CodeGroupTierDraft) {
  return form.value.tiers.some((tier) => tier !== currentTier && tier.labelIds.some((id) => String(id) === String(labelId)))
}

function restoreStandardTiers() {
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
  if (form.value.tiers.some((tier) => tier.userType === 'LABEL_USERS' && !tier.labelIds.length)) { ElMessage.warning('标签用户档位必须选择标签 ID'); return }
  if (form.value.tiers.some((tier) => tier.bonusMaxAmount < tier.bonusAmount)) { ElMessage.warning('兑换金额上下限不正确'); return }
  rewardTierPresetSaving.value = true
  try {
    rewardTierPreset.value = await api.redemptionRemoteConnections.saveRewardTierPreset(connection.id!, {
      tiers: form.value.tiers.map((tier) => ({
        userType: tier.userType,
        labelIds: tier.userType === 'ALL_USERS' ? [] : [...tier.labelIds],
        displayName: tier.displayName,
        minDepositAmount: String(tier.minDepositAmount),
        bonusAmount: String(tier.bonusAmount),
        bonusMaxAmount: String(tier.bonusMaxAmount),
      })),
      tagSnapshot: tagOptions.value.map((tag) => ({ id: tag.id, name: tag.name })),
    })
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
    if (isPreviousDayDeposit() && !previousDayProfileForMarket(marketId)) return `日充值目前不支持 ${label}`
    if (!draft?.tiers.length) return `${label} 请先配置至少一个充值档位`
    if (draft.tiers.some((tier) => tier.userType === 'LABEL_USERS' && !tier.labelIds.length)) return `${label} 的标签用户档位必须选择至少一个标签 ID`
    if (draft.tiers.some((tier) => tier.bonusAmount < 0 || tier.bonusMaxAmount < tier.bonusAmount)) return `${label} 的兑换金额上下限不正确`
  }
  return ''
}

async function createCodeGroup() {
  await ensureSelectedMarketDrafts()
  const message = validateForm()
  if (message) { ElMessage.warning(message); return }
  try {
    await ElMessageBox.confirm(
      `系统会将 ${form.value.remoteMarketIds.length} 个盘口汇总为一条任务，并按盘口顺序串行创建远端配置；兑换码生效规则为“${validityRuleSummary.value}”。后续发布仍按盘口分别执行全量发布，并可能发布该盘口所有待发布的兑换码配置，请确认各远端后台不存在不应发布的内容。`,
      '确认批量生成兑换码组',
      { type: 'warning', confirmButtonText: '确认并开始生成', cancelButtonText: '取消' },
    )
  } catch {
    return
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
        tierUserTypes: draft.tiers.map((tier) => tier.userType),
        tierLabelIds: draft.tiers.map((tier) => tier.userType === 'ALL_USERS' ? [] : tier.labelIds),
        remoteOptions: form.value.remoteOptions,
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
    for (const detail of created) await generateCodes(detail)
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

async function generateCodes(initial: RedemptionBatchDetail) {
  let detail = initial
  let failed = false
  markProcessing(detail.batch.id, true)
  try {
    const pendingIssues = detail.issues.filter((issue) => issue.workflowStatus === 'PENDING_CREATION')
    const intervalMs = Math.max(1, detail.batch.remoteOptions?.creationIntervalSeconds ?? form.value.remoteOptions.creationIntervalSeconds ?? 5) * 1000
    for (const [index, issue] of pendingIssues.entries()) {
      if (issue.workflowStatus !== 'PENDING_CREATION') continue
      const requestStartedAt = Date.now()
      try {
        detail = await api.redemption.createRemoteConfiguration(issue.id)
      } catch {
        failed = true
      }
      if (index < pendingIssues.length - 1) await wait(Math.max(0, intervalMs - (Date.now() - requestStartedAt)))
    }
    ElMessage[failed ? 'warning' : 'success'](failed ? '部分远端配置创建失败，请在任务列表中查看失败原因' : '远端配置已全部创建，请在任务列表中选择发布方式后发布')
  } finally {
    markProcessing(detail.batch.id, false)
    await loadCodeGroups()
    if (selectedGroup.value?.detail.batch.id === detail.batch.id) replaceCodeGroup({ campaign: selectedGroup.value.campaign, detail })
  }
}

function openPublishDialog(target: CodeGroupRow | CodeGroupTask) {
  publishTarget.value = target
  publishForm.value = { mode: 'IMMEDIATE', fallbackToScheduled: true }
  publishOptionsOpen.value = []
  publishDialogVisible.value = true
}

function hasPendingPublishReservation(row: CodeGroupRow) {
  return row.detail.batch.status === 'READY_TO_PUBLISH' && Boolean(row.detail.batch.remotePublishTaskId?.startsWith('PENDING:'))
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
  if (publishForm.value.mode === 'SCHEDULED' && !publishForm.value.scheduledTime) { ElMessage.warning('请选择定时发布时间（印度时间）'); return }
  const rows = publishRows(target)
  if (rows.some((row) => row.detail.batch.status !== 'READY_TO_PUBLISH')) {
    ElMessage.warning('仍有盘口尚未完成远端配置，请先处理完成后再统一发布')
    return
  }
  publishing.value = true
  try {
    const failures: string[] = []
    for (const row of rows) {
      try {
        const detail = await api.redemption.publishRemoteBatch(row.detail.batch.id, row.detail.batch.rowVersion, publishForm.value.mode, publishForm.value.scheduledTime, publishForm.value.fallbackToScheduled)
        const replacement = { campaign: row.campaign, detail }
        replaceCodeGroup(replacement)
        if (detail.batch.remotePublishMode !== 'SCHEDULED' && detail.batch.status === 'PUBLISHED') {
          await downloadPublishedCodes(replacement, false, true)
        }
      } catch (error) {
        failures.push(`${remoteMarketLabel(row)}：${error instanceof Error ? error.message : '发布失败'}`)
      }
    }
    publishDialogVisible.value = false
    const scheduled = publishForm.value.mode === 'SCHEDULED'
    ElMessage[failures.length ? 'warning' : 'success'](failures.length
      ? `${scheduled ? '定时发布' : '立即发布'}部分失败：${failures.join('；')}`
      : rows.length > 1
        ? (scheduled ? `已按盘口顺序提交 ${rows.length} 个定时发布任务` : `已按盘口顺序发布并下载 ${rows.length} 个盘口的兑换码`)
        : (scheduled ? '已提交定时发布' : '已立即发布并下载兑换码'))
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '远端发布失败') }
  finally { publishing.value = false }
}

async function downloadPublishedCodes(row: CodeGroupRow, activateScheduled = false, silent = false) {
  let detail = row.detail
  let failed = false
  markProcessing(detail.batch.id, true)
  try {
    const downloadableIssues = detail.issues.filter((item) => item.workflowStatus === 'PUBLISHED' || (activateScheduled && item.workflowStatus === 'CREATED'))
    for (const issue of downloadableIssues) try { detail = await api.redemption.downloadRemoteCode(issue.id) } catch { failed = true }
    replaceCodeGroup({ campaign: row.campaign, detail })
    if (!silent) ElMessage[failed ? 'warning' : 'success'](failed ? '部分兑换码下载失败，请查看任务备注' : '兑换码组生成成功，已可下载 Excel')
  } finally { markProcessing(detail.batch.id, false); await loadCodeGroups() }
}

async function cancelScheduledPublish(row: CodeGroupRow) {
  try { await ElMessageBox.confirm('撤销后该批次不会再自动进行后续定时发布尝试。', '撤销定时发布', { type: 'warning' }) } catch { return }
  cancellingPublishId.value = row.detail.batch.id
  try {
    const detail = await api.redemption.cancelScheduledPublish(row.detail.batch.id, row.detail.batch.rowVersion)
    replaceCodeGroup({ campaign: row.campaign, detail })
    ElMessage.success('已撤销定时发布')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '撤销定时发布失败') }
  finally { cancellingPublishId.value = undefined }
}

async function openGroupDetail(row: CodeGroupRow) {
  clearFailedIssueSelection()
  selectedTaskMembers.value = [{ campaign: row.campaign, detail: await api.redemption.batch(row.detail.batch.id) }]
  selectedGroup.value = selectedTaskMembers.value[0]
  activeTaskBatchId.value = String(selectedGroup.value.detail.batch.id)
  detailDrawerVisible.value = true
}

async function openTaskDetail(task: CodeGroupTask) {
  clearFailedIssueSelection()
  const members = await Promise.all(task.members.map(async (member) => ({
    campaign: member.campaign,
    detail: await api.redemption.batch(member.detail.batch.id),
  })))
  selectedTaskMembers.value = members
  selectedGroup.value = members[0]
  activeTaskBatchId.value = members[0] ? String(members[0].detail.batch.id) : ''
  detailDrawerVisible.value = true
}

function selectTaskMember(batchId: string | number) {
  const member = selectedTaskMembers.value.find((item) => String(item.detail.batch.id) === String(batchId))
  if (member) {
    clearFailedIssueSelection()
    selectedGroup.value = member
  }
}

function replaceCodeGroup(replacement: CodeGroupRow) {
  codeGroups.value = codeGroups.value.map((item) => item.detail.batch.id === replacement.detail.batch.id ? replacement : item)
  selectedTaskMembers.value = selectedTaskMembers.value.map((item) => item.detail.batch.id === replacement.detail.batch.id ? replacement : item)
  if (selectedGroup.value?.detail.batch.id === replacement.detail.batch.id) {
    selectedGroup.value = replacement
    clearFailedIssueSelection()
  }
}

async function retryRemoteCreation(issue: RedemptionCodeIssue) {
  const group = selectedGroup.value
  if (!group || !canRetryRemoteCreation(issue)) return
  if (issue.workflowStatus === 'CREATING_REMOTE') {
    try {
      await ElMessageBox.confirm('该任务已超过 2 分钟未完成。确认后会按原参数重新创建远端配置；请先确认远端后台不存在同名配置。', '恢复卡住的创建任务', { type: 'warning', confirmButtonText: '确认重试', cancelButtonText: '取消' })
    } catch {
      return
    }
  }
  retryingIssueId.value = issue.id
  try {
    const detail = await api.redemption.createRemoteConfiguration(issue.id, true)
    const replacement = { campaign: group.campaign, detail }
    replaceCodeGroup(replacement)
    ElMessage.success('已重新创建远端兑换码配置')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重试创建远端配置失败')
  } finally {
    retryingIssueId.value = undefined
  }
}

async function retrySelectedFailedRemoteCreations() {
  const group = selectedGroup.value
  if (!group) return
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
    for (const [index, { row, issue }] of targets.entries()) {
      const requestStartedAt = Date.now()
      try {
        const detail = await api.redemption.createRemoteConfiguration(issue.id, true)
        replaceCodeGroup({ campaign: row.campaign, detail })
        succeeded += 1
      } catch (error) {
        failures.push(`${remoteMarketLabel(row)} · ${formatDate(issue.claimDate)}：${error instanceof Error ? error.message : '重试失败'}`)
      }
      if (index < targets.length - 1) {
        const intervalMs = Math.max(1, row.detail.batch.remoteOptions?.creationIntervalSeconds ?? form.value.remoteOptions.creationIntervalSeconds ?? 5) * 1000
        await wait(Math.max(0, intervalMs - (Date.now() - requestStartedAt)))
      }
    }
    ElMessage[failures.length ? 'warning' : 'success'](failures.length
      ? `${succeeded} 条已选任务重试成功，${failures.length} 条仍失败：${failures.join('；')}`
      : `${succeeded} 条已选失败任务已全部重新创建，请选择发布方式后发布`)
  } finally {
    retryingSelectedFailedTasks.value = false
    markProcessing(group.detail.batch.id, false)
    clearFailedIssueSelection()
    await loadCodeGroups()
  }
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

onMounted(async () => {
  indiaNow.value = indiaNowText()
  indiaClock = window.setInterval(() => { indiaNow.value = indiaNowText() }, 15_000)
  await Promise.all([loadCodeGroups(), loadRemoteConnections()])
})

onUnmounted(() => {
  if (indiaClock) window.clearInterval(indiaClock)
})
</script>

<template>
  <section class="redemption-page">
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
      系统将为每个开始兑换日 × 用户类型/标签档位创建远端配置，并为每条兑换码自动写入独立的描述和备注。远端生效时间默认是开始兑换日当天，也可在生成时设置相对有效期。配置全部创建后，请在任务行选择发布方式。
    </el-alert>

    <article class="panel code-group-list">
      <header class="code-group-list__heading">
        <div>
          <h3>批量生成兑换码组任务</h3>
          <p>状态会显示为生成中、生成失败或生成成功；成功的兑换码组支持下载 Excel。</p>
        </div>
        <span class="code-group-list__count">共 {{ codeGroupTasks.length }} 个兑换码组任务</span>
      </header>

      <el-table v-if="codeGroupTasks.length" v-loading="loading" :data="codeGroupTasks" class="code-group-table">
        <el-table-column label="任务批次号" width="118" align="center">
          <template #default="{ row }">#{{ row.taskId }}</template>
        </el-table-column>
        <el-table-column label="兑换码组" min-width="210">
          <template #default="{ row }">
            <div class="group-name">
              <strong>{{ taskName(row) }}</strong>
              <span>{{ taskSummary(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="开始兑换日期" min-width="175">
          <template #default="{ row }">{{ formatDate(taskPrimary(row).detail.batch.claimDateFrom) }} 至 {{ formatDate(taskPrimary(row).detail.batch.claimDateTo) }}</template>
        </el-table-column>
        <el-table-column label="远端账号" min-width="135" show-overflow-tooltip>
          <template #default="{ row }">{{ taskAccounts(row) }}</template>
        </el-table-column>
        <el-table-column label="盘口" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ taskMarkets(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="112">
          <template #default="{ row }"><el-tag :type="taskStatus(row).type" effect="light">{{ taskStatus(row).text }}</el-tag></template>
        </el-table-column>
        <el-table-column label="用户类型 / 标签 ID" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ taskLabels(row) }}</template>
        </el-table-column>
        <el-table-column label="兑换码类型" width="128"><template #default="{ row }">{{ redemptionTypeLabel(taskPrimary(row).detail.batch.redemptionType) }}</template></el-table-column>
        <el-table-column label="充值档位 · 兑换金额" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">{{ taskTiers(row) }}</template>
        </el-table-column>
        <el-table-column label="生成进度" min-width="180">
          <template #default="{ row }"><span class="group-progress">{{ taskProgress(row) }}</span></template>
        </el-table-column>
        <el-table-column label="发布时间" min-width="205" show-overflow-tooltip>
          <template #default="{ row }">{{ taskPublishTime(row) }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="250" show-overflow-tooltip>
          <template #default="{ row }">{{ taskRemark(row) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatDateTime(taskCreatedAt(row)) }}</template></el-table-column>
        <el-table-column label="操作" width="228" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="row.members.some(isProcessing)" @click="isMultiMarketTask(row) ? openTaskDetail(row) : openGroupDetail(taskPrimary(row))">查看任务</el-button>
            <template v-if="!isMultiMarketTask(row)">
              <el-button v-if="hasPendingPublishReservation(taskPrimary(row))" link type="warning" :loading="recoveringPublishId === taskPrimary(row).detail.batch.id" @click="recoverPublishReservation(taskPrimary(row))">恢复发布</el-button>
              <el-button v-else-if="taskPrimary(row).detail.batch.status === 'READY_TO_PUBLISH'" link type="primary" @click="openPublishDialog(taskPrimary(row))">选择发布方式</el-button>
              <el-button v-if="isScheduledPublish(taskPrimary(row))" link type="danger" :disabled="!canCancelScheduledPublish(taskPrimary(row))" :loading="cancellingPublishId === taskPrimary(row).detail.batch.id" @click="cancelScheduledPublish(taskPrimary(row))">撤销发布</el-button>
              <el-button v-if="canDownloadScheduledCodes(taskPrimary(row))" link type="primary" :loading="isProcessing(taskPrimary(row))" @click="downloadPublishedCodes(taskPrimary(row), true)">下载兑换码</el-button>
              <template v-if="isSuccess(taskPrimary(row)) && canExport">
                <el-button link type="primary" :icon="Download" :loading="exportingId === taskPrimary(row).detail.batch.id" @click="exportGroup(taskPrimary(row))">下载 Excel</el-button>
              </template>
            </template>
            <el-button v-if="canPublishMultiMarketTask(row)" link type="primary" :loading="publishing" @click="openPublishDialog(row)">选择发布方式</el-button>
            <el-button v-if="canExportMultiMarketTask(row) && canExport" link type="primary" :icon="Download" :loading="exportingGroupKey === row.exportGroupKey" @click="exportMultiMarketGroup(row)">下载 Excel</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else v-loading="loading" :image-size="68" description="还没有兑换码组，点击右上角“批量生成兑换码组”开始创建" />
    </article>

    <el-dialog v-model="codeGroupDialogVisible" title="批量生成兑换码组" width="1040px" destroy-on-close>
      <el-form label-position="top" class="code-group-form">
        <div class="code-group-form__grid">
          <el-form-item class="code-group-form__date-range" label="开始兑换日期范围（表格列）" required>
            <el-date-picker v-model="form.dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :disabled-date="(date: Date) => date < new Date(`${todayIso()}T00:00:00`)" style="width: 100%" />
            <div class="date-presets"><span>快捷选择</span><el-button size="small" @click="applyFutureRange(7)">未来 7 天</el-button><el-button size="small" @click="applyFutureRange(30)">未来 30 天</el-button></div>
            <p class="field-note">范围内每一天对应表格中的一列；系统按照“开始兑换日 × 用户类型/标签档位”生成独立兑换码组，例如 <strong>{{ isPreviousDayDeposit() ? 'NEW-818存款200' : 'NEW-808到814存款100' }}</strong>。</p>
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
            </el-radio-group>
            <p class="field-note">日充值类型只核验开始兑换日前一天的充值金额；兑换码实际有效期以上方生效时间规则为准。</p>
          </el-form-item>
          <el-form-item v-if="isPreviousDayDeposit() && form.remoteMarketId" class="code-group-form__code-type" label="当前编辑盘口的日充值标签方案">
            <el-tag type="info">{{ previousDayProfileLabel }}</el-tag>
            <p class="field-note">标签方案由盘口自动决定：RajWin 使用 Win 的 3,000 档默认标签 ID 901996；RajLuck、RajSpin 使用 Luck Spin 的 901994。充值 0 档为所有用户，仍请同步当前盘口标签后确认。</p>
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
          <div><strong>{{ marketLabel(form.remoteMarketId) }} · 用户类型与兑换金额</strong><p>每个档位先选择用户类型。“标签用户”必须选择标签 ID；“全部用户”不会向远端发送标签数组。切换顶部盘口标签页可独立编辑各盘口。</p><p v-if="isPreviousDayDeposit()" class="field-note">日充值默认保留充值 0 档为全部用户，其余档位为标签用户；远端描述和备注会命名为“{{ 'NEW-818存款200' }}”格式。</p><template v-else><p v-if="rewardTierPresetLoading" class="field-note">正在读取 {{ marketLabel(form.remoteMarketId) }} 的用户类型、标签与奖励分档预设…</p><p v-else-if="rewardTierPreset?.exists" class="field-note"><el-tag size="small" :type="rewardTierPreset.stale ? 'warning' : 'success'">{{ rewardTierPreset.stale ? '预设待重新保存' : '已保存预设' }}</el-tag><span class="tier-panel__preset-copy">{{ rewardTierPreset.stale ? '标签已同步，请确认当前奖励分档后重新保存。' : `保存于 ${formatDateTime(rewardTierPreset.savedAt)}` }}</span></p><p v-else class="field-note">当前盘口尚未另存预设，已按现有标签加载标准五档。</p></template></div>
            <div class="tier-panel__actions"><el-button plain :icon="Refresh" :loading="remoteTagsLoading" @click="loadRemoteTags">同步当前盘口标签</el-button><template v-if="!isPreviousDayDeposit()"><el-button plain :disabled="!rewardTierPreset?.exists || rewardTierPreset.stale" @click="applyRewardTierPreset">重新应用预设</el-button><el-button plain type="primary" :loading="rewardTierPresetSaving" @click="saveRewardTierPreset">另存当前预设</el-button><el-button plain @click="restoreStandardTiers">恢复该盘口标准五档</el-button></template><el-button plain :icon="Plus" @click="addTier">添加档位</el-button></div>
          </div>
          <div class="tier-editor">
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
              <el-form-item label="兑换码数量"><el-input-number v-model="form.remoteOptions.keyNumber" :min="1" :max="1" controls-position="right" disabled /></el-form-item>
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
        <p v-if="form.remoteMarketIds.length" class="submit-hint">已选择 {{ form.remoteMarketIds.length }} 个盘口；每个盘口会自动选择自己的远端账号并使用其独立标签配置，共创建 {{ expectedTaskCount() }} 条远端兑换码任务。远端生效时间：{{ validityRuleSummary }}。全部创建完成后，可在任务列表按盘口分别选择发布方式。</p>
      </el-form>
      <template #footer><el-button @click="codeGroupDialogVisible = false">取消</el-button><el-button type="primary" :loading="working" @click="createCodeGroup">开始生成</el-button></template>
    </el-dialog>

    <el-dialog v-model="publishDialogVisible" title="选择发布方式" width="560px" destroy-on-close>
      <p class="field-note publish-dialog__intro">{{ isMultiMarketPublishTarget(publishTarget) ? '将按盘口顺序串行执行；每个盘口仍仅发布其远端后台的待发布配置。' : '默认会立即发布，并在失败时自动回退为定时发布；如需调整，请展开下方设置。' }}</p>
      <el-collapse v-model="publishOptionsOpen" class="advanced-options publish-options">
        <el-collapse-item name="publish">
          <template #title><el-icon><Setting /></el-icon><span>发布相关设置（默认：立即发布，开启自动回退）</span></template>
          <el-form label-width="112px">
            <el-form-item label="发布方式"><el-radio-group v-model="publishForm.mode"><el-radio value="IMMEDIATE">立即发布（默认）</el-radio><el-radio value="SCHEDULED">定时发布</el-radio></el-radio-group></el-form-item>
            <el-form-item v-if="publishForm.mode === 'SCHEDULED'" label="发布时间" required><el-date-picker v-model="publishForm.scheduledTime" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" placeholder="选择印度时间" style="width: 100%" /><p class="field-note">远端按印度时间（Asia/Kolkata）执行；撤销必须早于该时间。</p></el-form-item>
            <el-form-item v-if="publishForm.mode === 'IMMEDIATE'" label="失败自动回退"><el-switch v-model="publishForm.fallbackToScheduled" inline-prompt active-text="开" inactive-text="关" /><p class="field-note">默认开启。关闭后，立即发布失败将直接记录失败原因，不再创建定时发布任务。</p></el-form-item>
            <el-alert v-if="publishForm.mode === 'IMMEDIATE' && publishForm.fallbackToScheduled" type="info" :closable="false" title="立即发布冲突时，系统会依次尝试 15、30、60 分钟后的定时发布，再尝试最早领取日期 00:00:00（印度时间）。" />
          </el-form>
        </el-collapse-item>
      </el-collapse>
      <template #footer><el-button @click="publishDialogVisible = false">取消</el-button><el-button type="primary" :loading="publishing" @click="submitPublish">确认发布</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailDrawerVisible" :title="selectedTaskMembers.length > 1 ? `任务 #${selectedTaskId} · 多盘口兑换码组任务明细` : (selectedGroup ? `任务 #${selectedTaskId} · ${selectedGroup.campaign.name} · 任务明细` : '兑换码组任务明细')" size="720px">
      <template v-if="selectedGroup">
        <el-tabs v-if="selectedTaskMembers.length > 1" v-model="activeTaskBatchId" class="task-market-tabs" @tab-change="selectTaskMember">
          <el-tab-pane v-for="member in selectedTaskMembers" :key="member.detail.batch.id" :name="String(member.detail.batch.id)" :label="taskMemberLabel(member)" />
        </el-tabs>
        <p v-if="selectedTaskMembers.length > 1" class="field-note task-detail-note">各盘口保留独立的远端创建、发布与下载进度；系统会按盘口顺序完成创建，所有盘口完成后可在任务列表下载同一份多 Sheet Excel。</p>
        <el-descriptions :column="2" border class="group-detail-summary">
          <el-descriptions-item label="任务编号">#{{ selectedGroup.detail.batch.taskId || selectedGroup.detail.batch.id }}</el-descriptions-item>
          <el-descriptions-item label="执行批次">#{{ selectedGroup.detail.batch.id }}</el-descriptions-item>
          <el-descriptions-item label="开始兑换日期">{{ formatDate(selectedGroup.detail.batch.claimDateFrom) }} 至 {{ formatDate(selectedGroup.detail.batch.claimDateTo) }}</el-descriptions-item>
          <el-descriptions-item label="任务状态"><el-tag :type="groupStatus(selectedGroup).type">{{ groupStatus(selectedGroup).text }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="远端账号">{{ selectedGroup.detail.batch.remoteConnectionName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="盘口">{{ remoteMarketLabel(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="兑换码类型">{{ redemptionTypeLabel(selectedGroup.detail.batch.redemptionType) }}</el-descriptions-item>
          <el-descriptions-item label="用户类型 / 标签 ID">{{ labelsFor(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item label="远端生效规则" :span="2">{{ batchValidityRuleLabel(selectedGroup.detail.batch) }}</el-descriptions-item>
          <el-descriptions-item label="发布时间" :span="2">{{ publishTime(selectedGroup) }}</el-descriptions-item>
          <el-descriptions-item v-if="groupRemark(selectedGroup) !== '—'" label="备注" :span="2">{{ groupRemark(selectedGroup) }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="selectedGroup.detail.batch.remotePublishError" class="group-detail-error" type="error" :closable="false" show-icon>{{ selectedGroup.detail.batch.remotePublishError }}</el-alert>
        <div v-if="failedRemoteCreationCount" class="group-detail-toolbar">
          <span>当前盘口有 {{ failedRemoteCreationCount }} 条远端配置生成失败；勾选后可批量重试。</span>
          <el-button type="warning" :disabled="!selectedFailedIssueCount" :loading="retryingSelectedFailedTasks" @click="retrySelectedFailedRemoteCreations">批量重试已选（{{ selectedFailedIssueCount }}）</el-button>
        </div>
        <el-table ref="failedIssueTable" :data="selectedGroup.detail.issues" row-key="id" class="group-detail-table" @selection-change="updateSelectedFailedIssues">
          <el-table-column type="selection" width="48" :selectable="isFailedRemoteCreation" />
          <el-table-column label="开始兑换日" width="118"><template #default="{ row }">{{ formatDate(row.claimDate) }}</template></el-table-column>
          <el-table-column label="远端生效日期" min-width="220"><template #default="{ row }">{{ issueValidityLabel(selectedGroup.detail.batch, row.claimDate) }}</template></el-table-column>
          <el-table-column label="充值档位" min-width="150"><template #default="{ row }">{{ row.tierName || `充值 ≥ ${formatAmount(row.minDepositAmount)}` }}</template></el-table-column>
          <el-table-column label="兑换金额" width="128"><template #default="{ row }">{{ formatAmount(row.bonusAmount) }}–{{ formatAmount(row.bonusMaxAmount || row.bonusAmount) }}</template></el-table-column>
          <el-table-column label="状态" width="116"><template #default="{ row }"><el-tag :type="issueStatus(row).type" size="small">{{ issueStatus(row).text }}</el-tag></template></el-table-column>
          <el-table-column label="兑换码 / 备注" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ row.redemptionCode || row.remoteError || '—' }}</template></el-table-column>
          <el-table-column label="操作" width="96"><template #default="{ row }"><el-button v-if="canRetryRemoteCreation(row)" link type="primary" :loading="retryingIssueId === row.id" :disabled="retryingSelectedFailedTasks" @click="retryRemoteCreation(row)">{{ row.workflowStatus === 'CREATING_REMOTE' ? '恢复重试' : '重试创建' }}</el-button></template></el-table-column>
        </el-table>
        <div class="drawer-actions">
          <el-button v-if="hasPendingPublishReservation(selectedGroup)" type="warning" :loading="recoveringPublishId === selectedGroup.detail.batch.id" @click="recoverPublishReservation(selectedGroup)">恢复发布</el-button>
          <el-button v-else-if="selectedGroup.detail.batch.status === 'READY_TO_PUBLISH'" type="primary" @click="openPublishDialog(selectedGroup)">选择发布方式</el-button>
          <el-button v-if="isScheduledPublish(selectedGroup)" type="danger" :disabled="!canCancelScheduledPublish(selectedGroup)" :loading="cancellingPublishId === selectedGroup.detail.batch.id" @click="cancelScheduledPublish(selectedGroup)">撤销发布</el-button>
          <el-button v-if="canDownloadScheduledCodes(selectedGroup)" type="primary" :loading="isProcessing(selectedGroup)" @click="downloadPublishedCodes(selectedGroup, true)">下载兑换码</el-button>
          <el-button v-if="isSuccess(selectedGroup) && canExport" type="primary" :icon="Download" :loading="exportingId === selectedGroup.detail.batch.id" @click="exportGroup(selectedGroup)">下载当前盘口 Excel</el-button>
        </div>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.redemption-alert { margin-bottom: 18px; }
.code-group-list { overflow: hidden; }
.code-group-list__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 19px 20px 16px; border-bottom: 1px solid #eaecf0; }
.code-group-list__heading h3 { margin: 0; color: #101828; font-size: 15px; }
.code-group-list__heading p { margin: 5px 0 0; color: #667085; font-size: 12px; }
.code-group-list__count { padding-top: 3px; color: #667085; font-size: 12px; white-space: nowrap; }
.code-group-table { --el-table-header-bg-color: #f9fafb; --el-table-border-color: #eaecf0; --el-table-row-hover-bg-color: #f8fbff; }
.group-name { display: grid; gap: 5px; }
.group-name strong { color: #182230; font-size: 13px; }
.group-name span { color: #98a2b3; font-size: 11px; }
.group-progress { color: #475467; font-size: 12px; white-space: nowrap; }
.code-group-form__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.code-group-form__grid--options { grid-template-columns: 1.15fr 1fr 1fr; }
.code-group-form__date-range { grid-column: 1 / -1; }
.code-group-form__validity { grid-column: 1 / -1; }
.code-group-form__code-type { grid-column: 1 / -1; }
.code-group-form__market { grid-column: 1 / -1; }
.date-presets { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.date-presets span { color: #667085; font-size: 12px; }
.validity-editor { width: 100%; padding: 13px 14px; border: 1px solid #d0d5dd; border-radius: 9px; background: #fff; }
.validity-editor__offsets { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.validity-editor__offsets label { display: grid; grid-template-columns: auto auto minmax(110px, 1fr) auto; align-items: center; gap: 8px; color: #475467; font-size: 13px; }
.validity-editor__formula { color: #667085; white-space: nowrap; }
.validity-preview { display: grid; gap: 7px; margin-top: 12px; padding: 10px 12px; border-radius: 7px; background: #f5f8ff; color: #344054; font-size: 12px; }
.validity-preview__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.validity-preview__heading strong { color: #175cd3; font-size: 13px; }
.validity-preview__heading span { color: #667085; }
.validity-preview__row { display: grid; grid-template-columns: 90px minmax(150px, 1fr) auto minmax(150px, 1fr); align-items: center; gap: 8px; }
.validity-preview__row code { padding: 3px 6px; border: 1px solid #d1e0ff; border-radius: 4px; background: #fff; color: #1849a9; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; text-align: center; }
.field-note { margin: 6px 0 0; color: #667085; font-size: 12px; line-height: 1.5; }
.field-note strong { color: #344054; font-weight: 600; }
.field-note--danger { color: #b42318; }
.field-unit { margin-left: 7px; color: #667085; font-size: 13px; }
.tier-panel { margin: 10px 0 18px; padding: 15px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 10px; }
.tier-panel__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.tier-panel__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.tier-panel__heading strong { color: #344054; font-size: 14px; }
.tier-panel__heading p { margin: 5px 0 0; color: #667085; font-size: 12px; }
.tier-panel__preset-copy { margin-left: 7px; }
.tier-editor { overflow: hidden; border: 1px solid #eaecf0; border-radius: 8px; background: #fff; }
.tier-editor__header, .tier-editor__row { display: grid; grid-template-columns: minmax(132px, .72fr) minmax(300px, 1.8fr) minmax(138px, .82fr) minmax(138px, .82fr) 44px; align-items: center; gap: 10px; padding: 9px 11px; }
.tier-editor__header { color: #667085; font-size: 12px; font-weight: 600; background: #f2f4f7; }
.tier-editor__row { border-top: 1px solid #f2f4f7; }
.tier-editor__all-users { min-height: 32px; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 11px; color: #344054; border: 1px solid #d0d5dd; border-radius: 4px; background: #f9fafb; }
.tier-editor__all-users span { color: #98a2b3; font-size: 12px; white-space: nowrap; }
.advanced-options { border-top: 1px solid #eaecf0; }
.advanced-options :deep(.el-collapse-item__header) { gap: 8px; color: #344054; font-weight: 600; }
.advanced-options__fixed { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 2px 0 14px; color: #667085; font-size: 12px; }
.advanced-options__fixed span { padding: 5px 8px; border: 1px solid #eaecf0; border-radius: 6px; background: #f9fafb; }
.advanced-options__toggle-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.submit-hint { margin: 0; color: #667085; font-size: 12px; }
.group-detail-summary { margin-bottom: 18px; }
.group-detail-error { margin-bottom: 14px; }
.group-detail-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; color: #667085; font-size: 13px; }
.group-detail-table { --el-table-header-bg-color: #f9fafb; --el-table-border-color: #eaecf0; }
.task-market-tabs { margin-bottom: 8px; }
.task-detail-note { margin: 0 0 14px; }
.drawer-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 18px 0; }
</style>
