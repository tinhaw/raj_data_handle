<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Calendar, Delete, Download, Plus, Refresh, UploadFilled, Operation } from '@element-plus/icons-vue'
import { api, ApiError } from '@/api/client'
import type { CalculationBasis, CalculationPreview, DailyBalance, Operator, OperatorAccount, PeriodLock, PeriodLockIssue } from '@/api/types'
import MoneyText from '@/components/MoneyText.vue'
import StatusTag from '@/components/StatusTag.vue'
import { blankBalance, demoAccounts, demoBalanceRows, demoOperators } from '@/utils/demo-data'
import { formatMoney, percent, previewCalculation, toDecimal } from '@/utils/money'
import { demoEnabled } from '@/utils/runtime'
import { useSessionStore } from '@/stores/session'

type FeeKind = 'exchange' | 'service'
type FeeInputMode = 'AUTO' | 'MANUAL'

interface EntryDraftSnapshot {
  version: 2
  accountId: string
  operatorId: string
  month: string
  entryDate: string
  rows: DailyBalance[]
  dirtyDates: string[]
  savedAt: string
}

type StoredEntryDraft = Omit<EntryDraftSnapshot, 'version'> & { version: number }

const exchangeLossModePreferencePrefix = 'raj-erp:balance-ledger:exchange-loss-mode:v1:'
const entryDraftStoragePrefix = 'raj-erp:balance-ledger:workspace:v2:'
const legacyEntryDraftStoragePrefix = 'raj-erp:balance-ledger:draft:v1:'

const loading = ref(false)
const saving = ref(false)
const operators = ref<Operator[]>([])
const accounts = ref<OperatorAccount[]>([])
const selectedOperatorId = ref<string | number>('')
const selectedAccountId = ref<string | number>('')
const selectedMonth = ref('')
const entryDate = ref('')
const specifiedDateDialogVisible = ref(false)
const specifiedDate = ref('')
const rows = ref<DailyBalance[]>([])
const monthRecords = ref<DailyBalance[]>([])
const dirtyDates = ref(new Set<string>())
const usingDemo = ref(false)
const loadError = ref('')
const previewDrawer = ref(false)
const previewRow = ref<DailyBalance | null>(null)
const serverPreview = ref<CalculationPreview | null>(null)
const previewLoading = ref(false)
const periodLock = ref<PeriodLock | null>(null)
const periodLockLoading = ref(false)
const periodActionLoading = ref(false)
const periodLockIssues = ref<PeriodLockIssue[]>([])
const periodLockError = ref('')
const exchangeLossDefaultMode = ref<FeeInputMode>('MANUAL')
const serviceFeeDefaultMode = ref<FeeInputMode>('AUTO')
const exchangeLossHeaderDefaultDates = ref(new Set<string>())
const serviceFeeHeaderDefaultDates = ref(new Set<string>())
const session = useSessionStore()
let entryLoadVersion = 0
let restoringEntryDraft = false
let entryWorkspaceRestoreCount = 0

const basisOptions: Array<{ value: CalculationBasis; label: string }> = [
  { value: 'TRANSFER', label: '转 U' },
  { value: 'EFFECTIVE_TRANSFER', label: '有效转 U' },
  { value: 'SPEND', label: '消耗' },
  { value: 'MANUAL', label: '仅手工' },
]

const availableAccounts = computed(() => accounts.value.filter((account) => account.operatorId === selectedOperatorId.value && account.status === 'ACTIVE'))
const activeAccount = computed(() => accounts.value.find((account) => account.id === selectedAccountId.value) || null)
const dirtyCount = computed(() => dirtyDates.value.size)
const preview = (row: DailyBalance) => previewCalculation(row)
const periodDate = computed(() => selectedMonth.value ? `${selectedMonth.value}-01` : '')
const canConfirmBalances = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('BALANCE_CONFIRM') || user?.roles.includes('SUPER_ADMIN'))
})
const canManagePeriod = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('PERIOD_LOCK') || user?.roles.includes('SUPER_ADMIN'))
})
const canOverrideBalance = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('BALANCE_OVERRIDE') || user?.roles.includes('SUPER_ADMIN'))
})
const entryRows = computed(() => rows.value.filter((row) => Boolean(row.businessDate)))
const isPeriodLocked = computed(() => periodLock.value?.status === 'LOCKED' || entryRows.value.some((row) => Boolean(row.locked)))
const isEditable = (row: DailyBalance) => row.status === 'DRAFT' && !row.locked && !isPeriodLocked.value && !periodActionLoading.value
const isRowReady = (row: DailyBalance) => Boolean(row.businessDate)
const canEditRow = (row: DailyBalance) => isRowReady(row) && isEditable(row)
const hasUnsavedEditableRows = computed(() => rows.value.some((row) => !row.id && canEditRow(row)))
const canAddNextDay = computed(() => {
  const last = entryRows.value.at(-1)
  return Boolean(activeAccount.value && last?.businessDate && !loading.value && !saving.value && !isPeriodLocked.value && !periodActionLoading.value)
})
const canAddSpecifiedDate = computed(() => canAddNextDay.value)

const monthlyTotals = computed(() => {
  const all = entryRows.value
  const sum = (key: keyof DailyBalance) => all.reduce((total, row) => total.plus(toDecimal(row[key] as string)), toDecimal(0)).toString()
  const first = all[0]
  const last = all[all.length - 1]
  return {
    opening: first?.openingBalance || '0', transfer: sum('transferAmount'), effectiveTransfer: all.reduce((total, row) => total.plus(toDecimal(preview(row).effectiveTransferAmount)), toDecimal(0)).toString(),
    spend: sum('spendAmount'), exchange: all.reduce((total, row) => total.plus(toDecimal(preview(row).exchangeLossAmount)), toDecimal(0)).toString(),
    service: all.reduce((total, row) => total.plus(toDecimal(preview(row).serviceFeeAmount)), toDecimal(0)).toString(), reflux: sum('refluxAmount'), refund: sum('refundAmount'), other: sum('otherDeductionAmount'),
    closing: last ? preview(last).closingBalance : '0',
  }
})

function monthOf(date: string) {
  return date.slice(0, 7)
}

function nextBusinessDate(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day + 1)).toISOString().slice(0, 10)
}

function dateValue(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function entryDraftStorageKey(accountId?: string | number, prefix = entryDraftStoragePrefix) {
  const userId = session.user?.id
  if (typeof window === 'undefined' || userId === undefined || userId === null || userId === '' || accountId === undefined || accountId === null || accountId === '') return null
  return `${prefix}${encodeURIComponent(String(userId))}:${encodeURIComponent(String(accountId))}`
}

function isValidEntryDraftSnapshot(snapshot: Partial<StoredEntryDraft>, account: OperatorAccount, version: number) {
  const snapshotRows = Array.isArray(snapshot.rows) ? snapshot.rows : []
  const validRows = snapshotRows.length > 0 && snapshotRows.every((row) => row && typeof row.businessDate === 'string')
  const businessRows = snapshotRows.filter((row) => Boolean(row.businessDate))
  const isEmptyWorkspace = businessRows.length === 0 && snapshot.month === '' && snapshot.entryDate === ''
  const isDatedWorkspace = /^\d{4}-(0[1-9]|1[0-2])$/.test(snapshot.month || '')
    && /^\d{4}-\d{2}-\d{2}$/.test(snapshot.entryDate || '')
    && businessRows.length > 0
    && businessRows.every((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.businessDate) && monthOf(row.businessDate) === snapshot.month)
  return snapshot.version === version && String(snapshot.accountId) === String(account.id) && String(snapshot.operatorId) === String(account.operatorId)
    && typeof snapshot.month === 'string' && typeof snapshot.entryDate === 'string' && validRows
    && Array.isArray(snapshot.dirtyDates) && snapshot.dirtyDates.every((date) => typeof date === 'string') && typeof snapshot.savedAt === 'string'
    && (isEmptyWorkspace || isDatedWorkspace)
}

function cachedEntryDraft(account: OperatorAccount) {
  const key = entryDraftStorageKey(account.id)
  if (!key) return null
  try {
    const raw = window.localStorage.getItem(key)
    if (raw) {
      const snapshot = JSON.parse(raw) as Partial<StoredEntryDraft>
      if (isValidEntryDraftSnapshot(snapshot, account, 2)) return snapshot as EntryDraftSnapshot
      window.localStorage.removeItem(key)
    }

    // 将仍在当前标签页中的旧版会话草稿无损迁移为持久工作面。
    const legacyKey = entryDraftStorageKey(account.id, legacyEntryDraftStoragePrefix)
    if (!legacyKey) return null
    const legacyRaw = window.sessionStorage.getItem(legacyKey)
    if (!legacyRaw) return null
    const legacySnapshot = JSON.parse(legacyRaw) as Partial<StoredEntryDraft>
    if (!isValidEntryDraftSnapshot(legacySnapshot, account, 1)) {
      window.sessionStorage.removeItem(legacyKey)
      return null
    }
    const migratedSnapshot = { ...legacySnapshot, version: 2 } as EntryDraftSnapshot
    window.localStorage.setItem(key, JSON.stringify(migratedSnapshot))
    window.sessionStorage.removeItem(legacyKey)
    return migratedSnapshot
  } catch {
    return null
  }
}

function clearEntryDraft(accountId = activeAccount.value?.id) {
  const key = entryDraftStorageKey(accountId)
  const legacyKey = entryDraftStorageKey(accountId, legacyEntryDraftStoragePrefix)
  if (!key) return
  try {
    window.localStorage.removeItem(key)
    if (legacyKey) window.sessionStorage.removeItem(legacyKey)
  } catch {
    // 浏览器禁用本地存储时不影响正常录入和保存。
  }
}

function persistEntryDraft() {
  const account = activeAccount.value
  if (restoringEntryDraft || entryWorkspaceRestoreCount > 0 || !account || !rows.value.length) return
  const key = entryDraftStorageKey(account.id)
  if (!key) return
  const snapshot: EntryDraftSnapshot = {
    version: 2,
    accountId: String(account.id),
    operatorId: String(account.operatorId),
    month: selectedMonth.value,
    entryDate: entryDate.value,
    rows: rows.value.map((row) => ({ ...row })),
    dirtyDates: Array.from(dirtyDates.value),
    savedAt: new Date().toISOString(),
  }
  try {
    window.localStorage.setItem(key, JSON.stringify(snapshot))
    const legacyKey = entryDraftStorageKey(account.id, legacyEntryDraftStoragePrefix)
    if (legacyKey) window.sessionStorage.removeItem(legacyKey)
  } catch {
    // 工作面保存失败不应阻断正式台账保存。
  }
}

function latestCachedEntryDraft(loadedAccounts: OperatorAccount[]) {
  let latest: { account: OperatorAccount; snapshot: EntryDraftSnapshot } | null = null
  for (const account of loadedAccounts) {
    if (account.status !== 'ACTIVE') continue
    const snapshot = cachedEntryDraft(account)
    if (!snapshot || (latest && snapshot.savedAt <= latest.snapshot.savedAt)) continue
    latest = { account, snapshot }
  }
  return latest
}

function createEmptyEntryRow(account: OperatorAccount) {
  const row = blankBalance(account, '', '0')
  row.openingMode = 'MANUAL'
  return row
}

function resetEntry(account = activeAccount.value) {
  entryLoadVersion += 1
  loading.value = false
  selectedMonth.value = ''
  entryDate.value = ''
  monthRecords.value = []
  dirtyDates.value = new Set()
  loadError.value = ''
  periodLock.value = null
  periodLockIssues.value = []
  periodLockError.value = ''
  if (account) {
    resetFeeColumnDefaults(account)
    rows.value = [createEmptyEntryRow(account)]
  } else {
    rows.value = []
  }
}

async function loadMonthRecords(account: OperatorAccount, month: string) {
  if (usingDemo.value) return demoBalanceRows(account, month)
  return api.balances.list(account.id, month)
}

async function createEntryDraft(account: OperatorAccount, businessDate: string, records: DailyBalance[]) {
  const existing = records.find((row) => row.businessDate === businessDate)
  if (existing?.id) return { ...existing }

  if (usingDemo.value) {
    const demoRow = records.find((row) => row.businessDate === businessDate)
    return demoRow ? { ...demoRow } : blankBalance(account, businessDate)
  }

  const draft = blankBalance(account, businessDate)
  try {
    const calculation = await api.balances.calculate(draft)
    draft.suggestedOpeningBalance = calculation.suggestedOpeningBalance
    draft.openingBalance = calculation.openingBalance
    draft.openingMode = calculation.suggestedOpeningBalance === undefined ? 'MANUAL' : 'AUTO'
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== 'OPENING_BALANCE_REQUIRED') throw error
    // 首次录入没有历史期末可承接，明确切换为手工期初。
    draft.openingMode = 'MANUAL'
    draft.openingBalance = '0'
    draft.suggestedOpeningBalance = undefined
  }
  return draft
}

async function loadEntryForDate(businessDate: string) {
  const account = activeAccount.value
  if (!account || !businessDate) return

  const loadVersion = ++entryLoadVersion
  const month = monthOf(businessDate)
  loading.value = true
  loadError.value = ''
  periodLock.value = null
  periodLockIssues.value = []
  periodLockError.value = ''
  resetFeeColumnDefaults(account)

  try {
    const records = await loadMonthRecords(account, month)
    if (loadVersion !== entryLoadVersion) return
    selectedMonth.value = month
    monthRecords.value = records
    const entry = await createEntryDraft(account, businessDate, records)
    if (loadVersion !== entryLoadVersion) return
    rows.value = [entry]
    entryDate.value = businessDate
    dirtyDates.value = new Set()
    await loadPeriodLock(account)
    if (loadVersion !== entryLoadVersion) return
    applyAccountManualFeeDefaults()
  } catch (error) {
    if (loadVersion !== entryLoadVersion) return
    selectedMonth.value = ''
    entryDate.value = ''
    monthRecords.value = []
    rows.value = [createEmptyEntryRow(account)]
    loadError.value = error instanceof Error ? error.message : '无法加载该投放线的日结数据。'
  } finally {
    if (loadVersion === entryLoadVersion) loading.value = false
  }
}

async function restoreEntryDraft(account: OperatorAccount, snapshot: EntryDraftSnapshot) {
  const restoreVersion = entryLoadVersion
  if (restoreVersion !== entryLoadVersion || String(activeAccount.value?.id) !== String(account.id)) return false

  restoringEntryDraft = true
  loading.value = true
  try {
    const hasBusinessRows = snapshot.rows.some((row) => Boolean(row.businessDate))
    if (!hasBusinessRows) {
      selectedMonth.value = ''
      monthRecords.value = []
      rows.value = snapshot.rows.map((row) => ({ ...row, accountId: account.id, operatorId: account.operatorId }))
      entryDate.value = ''
      dirtyDates.value = new Set(snapshot.dirtyDates)
      loadError.value = ''
      ElMessage.success('已恢复当前工作面。')
      return true
    }
    const records = await loadMonthRecords(account, snapshot.month)
    if (restoreVersion !== entryLoadVersion || String(activeAccount.value?.id) !== String(account.id)) return false
    const serverRows = new Map(records.map((row) => [row.businessDate, row]))
    const dirty = new Set(snapshot.dirtyDates)
    const conflictDates = snapshot.rows
      .filter((row) => dirty.has(row.businessDate))
      .filter((row) => {
        const latest = serverRows.get(row.businessDate)
        return Boolean((row.id && latest && String(row.rowVersion) !== String(latest.rowVersion)) || (!row.id && latest))
      })
    const restoredRows = snapshot.rows
      .filter((row) => row.businessDate && monthOf(row.businessDate) === snapshot.month)
      .map((row) => {
        const latest = serverRows.get(row.businessDate)
        if (row.id && !dirty.has(row.businessDate) && latest) return { ...latest }
        return { ...row, accountId: account.id, operatorId: account.operatorId }
    })
    if (!restoredRows.length) {
      return false
    }
    selectedMonth.value = snapshot.month
    monthRecords.value = records
    rows.value = restoredRows
    entryDate.value = snapshot.entryDate || restoredRows[0].businessDate
    dirtyDates.value = dirty
    loadError.value = ''
    await loadPeriodLock(account)
    if (restoreVersion !== entryLoadVersion || String(activeAccount.value?.id) !== String(account.id)) return false
    if (conflictDates.length) ElMessage.warning(`已恢复草稿，但 ${conflictDates.length} 条记录已有服务端更新；保存前请先核对。`)
    ElMessage.success('已恢复当前工作面。')
    return true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复工作面失败，原工作面仍保留在当前浏览器中。')
    return false
  } finally {
    restoringEntryDraft = false
    if (restoreVersion === entryLoadVersion && String(activeAccount.value?.id) === String(account.id)) loading.value = false
  }
}

async function loadOperators() {
  loading.value = true
  try {
    const loadedOperators = await api.operators.list()
    const loadedAccounts = (await Promise.all(loadedOperators.map((operator) => api.operators.accounts(operator.id)))).flat()
    operators.value = loadedOperators
    accounts.value = loadedAccounts
    usingDemo.value = false
    loadError.value = ''
    const cached = latestCachedEntryDraft(loadedAccounts)
    if (cached) {
      selectedOperatorId.value = cached.account.operatorId
      selectedAccountId.value = cached.account.id
    } else if (!selectedOperatorId.value || !loadedOperators.some((item) => item.id === selectedOperatorId.value)) {
      selectedOperatorId.value = loadedOperators.find((item) => item.status === 'ACTIVE')?.id || ''
    }
  } catch {
    if (demoEnabled) {
      operators.value = demoOperators.map((item) => ({ ...item }))
      accounts.value = demoAccounts.map((item) => ({ ...item }))
      usingDemo.value = true
      selectedOperatorId.value = 'op-aa'
      loadError.value = ''
    } else {
      operators.value = []
      accounts.value = []
      selectedOperatorId.value = ''
      selectedAccountId.value = ''
      rows.value = []
      usingDemo.value = false
      loadError.value = '无法连接投放公司或台账服务。请确认后端已启动、登录会话有效后刷新页面。'
    }
  } finally {
    loading.value = false
  }
}

async function loadBalances() {
  const account = activeAccount.value
  if (!account) {
    resetEntry()
    return
  }
  if (!entryDate.value) {
    resetEntry(account)
    return
  }
  if (dirtyCount.value) {
    ElMessage.warning('当前有未保存修改，请先保存后再刷新。')
    return
  }
  await loadEntryForDate(entryDate.value)
}

async function clearCurrentWorkspace() {
  const account = activeAccount.value
  if (!account) return
  try {
    await ElMessageBox.confirm(
      `将清除“${account.displayName || account.name}”当前工作面中的日期与未保存输入；已保存到服务端的台账不会受影响。是否继续？`,
      '清除当前工作面',
      {
        type: 'warning',
        confirmButtonText: '确认清除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  // 用新的空工作面覆盖原记录，保留当前投放线选择，但不保留日期与输入内容。
  clearEntryDraft(account.id)
  resetEntry(account)
  await nextTick()
  persistEntryDraft()
  ElMessage.success('已清除当前工作面。')
}

async function loadPeriodLock(account = activeAccount.value) {
  periodLockError.value = ''
  if (!account || !periodDate.value || usingDemo.value) {
    if (!account || usingDemo.value) periodLock.value = null
    return
  }
  periodLockLoading.value = true
  try {
    const locks = await api.periodLocks.list(periodDate.value, [account.operatorId])
    periodLock.value = locks.find((lock) => String(lock.accountId) === String(account.id)) || null
  } catch (error) {
    periodLock.value = null
    periodLockError.value = error instanceof Error ? error.message : '无法读取本月锁账状态。'
  } finally {
    periodLockLoading.value = false
  }
}

watch(selectedOperatorId, (operatorId) => {
  if (accounts.value.some((account) => account.operatorId === operatorId && account.id === selectedAccountId.value && account.status === 'ACTIVE')) return
  const firstAccount = accounts.value.find((account) => account.operatorId === operatorId && account.status === 'ACTIVE')
  selectedAccountId.value = firstAccount?.id || ''
})

watch(selectedAccountId, () => {
  const account = activeAccount.value
  const snapshot = account ? cachedEntryDraft(account) : null
  if (account && snapshot) entryWorkspaceRestoreCount += 1
  resetEntry(account)
  if (account && snapshot) {
    void restoreEntryDraft(account, snapshot).finally(() => {
      entryWorkspaceRestoreCount -= 1
      persistEntryDraft()
    })
  }
})

watch(rows, () => {
  persistEntryDraft()
}, { deep: true })

watch(dirtyDates, () => {
  persistEntryDraft()
})

async function onEntryDateChanged(value: string | null | undefined) {
  const businessDate = value || ''
  const previousDate = rows.value[0]?.businessDate || ''
  if (!businessDate) {
    entryDate.value = previousDate
    return
  }
  if (businessDate === previousDate) return
  if (dirtyCount.value) {
    ElMessage.warning('当前工作面有未保存输入。请先保存，或手动清除当前工作面后再切换业务日期。')
    entryDate.value = previousDate
    return
  }
  await loadEntryForDate(businessDate)
}

async function addNextDay() {
  const account = activeAccount.value
  const last = entryRows.value.at(-1)
  if (!account || !last?.businessDate) {
    ElMessage.warning('请先选择首个业务日期。')
    return
  }
  if (isPeriodLocked.value) {
    ElMessage.warning('本月已锁定，不能新增日结。')
    return
  }

  const businessDate = nextBusinessDate(last.businessDate)
  const nextMonth = monthOf(businessDate)
  if (nextMonth !== selectedMonth.value) {
    if (dirtyCount.value || entryRows.value.some((row) => !row.id)) {
      ElMessage.warning('跨月前请先保存当前月份的日结，避免两个月的数据混在同一次提交中，并确保期初能正确承接。')
      return
    }
    try {
      await ElMessageBox.confirm(`下一天是 ${businessDate}，将切换到 ${nextMonth} 的输入台账。当前月份数据不会被删除，是否继续？`, '进入下一个月份', {
        type: 'warning',
        confirmButtonText: '进入新月份',
        cancelButtonText: '留在当前月份',
      })
    } catch {
      return
    }
    await loadEntryForDate(businessDate)
    return
  }

  loading.value = true
  try {
    const saved = monthRecords.value.find((row) => row.businessDate === businessDate && Boolean(row.id))
    const next = saved ? { ...saved } : blankBalance(account, businessDate, preview(last).closingBalance)
    if (!saved) {
      next.openingMode = 'AUTO'
      next.suggestedOpeningBalance = next.openingBalance
    }
    rows.value = [...rows.value, next]
    if (!saved) applyAccountManualFeeDefaults()
  } finally {
    loading.value = false
  }
}

function openSpecifiedDateDialog() {
  if (!canAddSpecifiedDate.value) {
    ElMessage.warning('请先选择首个业务日期，且确保当前月份可编辑。')
    return
  }
  specifiedDate.value = ''
  specifiedDateDialogVisible.value = true
}

function isSpecifiedDateDisabled(date: Date) {
  const businessDate = dateValue(date)
  const lastBusinessDate = entryRows.value.at(-1)?.businessDate
  return !selectedMonth.value
    || monthOf(businessDate) !== selectedMonth.value
    || entryRows.value.some((row) => row.businessDate === businessDate)
    || Boolean(lastBusinessDate && businessDate <= lastBusinessDate)
}

async function addSpecifiedDate() {
  const account = activeAccount.value
  const businessDate = specifiedDate.value
  if (!account || !businessDate) {
    ElMessage.warning('请选择要新增的业务日期。')
    return
  }
  if (monthOf(businessDate) !== selectedMonth.value) {
    ElMessage.warning('指定日期需位于当前录入月份。')
    return
  }
  const last = entryRows.value.at(-1)
  if (!last?.businessDate || businessDate <= last.businessDate) {
    ElMessage.warning('为保证期初自动承接，请选择当前最后一条录入之后的日期。')
    return
  }

  loading.value = true
  try {
    const saved = monthRecords.value.find((row) => row.businessDate === businessDate && Boolean(row.id))
    const next = saved ? { ...saved } : blankBalance(account, businessDate, preview(last).closingBalance)
    if (!saved) {
      next.openingMode = 'AUTO'
      next.suggestedOpeningBalance = next.openingBalance
    }
    rows.value = [...entryRows.value, next]
    if (!saved) applyAccountManualFeeDefaults()
    specifiedDateDialogVisible.value = false
    ElMessage.success(saved ? `已加入 ${businessDate} 的已保存台账。` : `已新增 ${businessDate} 的录入行。`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '新增指定日期失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

function markDirty(date: string) {
  if (!date) return
  const next = new Set(dirtyDates.value)
  next.add(date)
  dirtyDates.value = next
}

function updateFollowingOpening(index: number) {
  let preceding = preview(rows.value[index]).closingBalance
  for (let nextIndex = index + 1; nextIndex < rows.value.length; nextIndex += 1) {
    const next = rows.value[nextIndex]
    if (!canEditRow(next) || next.openingMode === 'MANUAL') break
    if (next.openingBalance !== preceding) {
      next.openingBalance = preceding
      markDirty(next.businessDate)
    }
    preceding = preview(next).closingBalance
  }
}

function updateFollowingUnsavedOpening(index: number) {
  let preceding = preview(rows.value[index]).closingBalance
  for (let nextIndex = index + 1; nextIndex < rows.value.length; nextIndex += 1) {
    const next = rows.value[nextIndex]
    // 表头默认值不能影响已保存草稿；遇到历史记录、人工期初或不可编辑行即停止联动。
    if (next.id || !canEditRow(next) || next.openingMode === 'MANUAL') break
    if (next.openingBalance !== preceding) {
      next.openingBalance = preceding
      markDirty(next.businessDate)
    }
    preceding = preview(next).closingBalance
  }
}

function onEdited(row: DailyBalance, index: number) {
  if (!canEditRow(row)) return
  onInputEdited(row)
  updateFollowingOpening(index)
}

function onInputEdited(row: DailyBalance) {
  if (!canEditRow(row)) return
  markDirty(row.businessDate)
  persistEntryDraft()
}

function setOpeningMode(row: DailyBalance, index: number, mode: 'AUTO' | 'MANUAL') {
  if (!canEditRow(row)) return
  row.openingMode = mode
  if (mode === 'AUTO' && index > 0) row.openingBalance = preview(rows.value[index - 1]).closingBalance
  onEdited(row, index)
}

function setFeeMode(row: DailyBalance, index: number, fee: 'exchange' | 'service', mode: 'AUTO' | 'MANUAL') {
  if (!canEditRow(row)) return
  clearFeeHeaderDefault(row, fee)
  if (fee === 'exchange') {
    row.exchangeLossMode = mode
    if (mode === 'AUTO') row.exchangeLossAmount = preview(row).exchangeLossAutoAmount
  } else {
    row.serviceFeeMode = mode
    if (mode === 'AUTO') row.serviceFeeAmount = preview(row).serviceFeeAutoAmount
  }
  onEdited(row, index)
}

function feeLabel(fee: FeeKind) {
  return fee === 'exchange' ? '汇损' : '服务费'
}

function feeModeLabel(mode: FeeInputMode) {
  return mode === 'MANUAL' ? '人工填写' : '自动计算'
}

function exchangeLossModePreferenceKey() {
  const userId = session.user?.id
  if (userId === undefined || userId === null || userId === '') return null
  return `${exchangeLossModePreferencePrefix}${encodeURIComponent(String(userId))}`
}

function readExchangeLossModePreference() {
  const key = exchangeLossModePreferenceKey()
  if (!key || typeof window === 'undefined') return null
  try {
    const value = window.localStorage.getItem(key)
    return value === 'AUTO' || value === 'MANUAL' ? value : null
  } catch {
    return null
  }
}

function saveExchangeLossModePreference(mode: FeeInputMode) {
  const key = exchangeLossModePreferenceKey()
  if (!key || typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, mode)
  } catch {
    // 浏览器禁用本地存储时，保留本次页面内设置，不影响台账录入。
  }
}

function resolveExchangeLossDefaultMode(account: OperatorAccount): FeeInputMode {
  const preference = readExchangeLossModePreference() || 'MANUAL'
  // 投放线的既有计算规则为“仅手工”时，不允许用户的自动偏好绕过该限制。
  if (preference === 'AUTO' && account.defaultExchangeLossBasis === 'MANUAL') return 'MANUAL'
  // 没有手工覆盖权限时，自动计算可用的投放线只能以自动模式展示和录入。
  if (preference === 'MANUAL' && !canOverrideBalance.value && account.defaultExchangeLossBasis !== 'MANUAL') return 'AUTO'
  return preference
}

function calculationBasisLabel(basis?: CalculationBasis) {
  return basisOptions.find((item) => item.value === basis)?.label || '转 U'
}

function feeDefaultBasisHint(fee: FeeKind) {
  const account = activeAccount.value
  const basis = fee === 'exchange' ? account?.defaultExchangeLossBasis : account?.defaultServiceFeeBasis
  return basis === 'MANUAL' ? '仅手工' : `按${calculationBasisLabel(basis)}`
}

function feeAutoSummary(rate: string, basis?: CalculationBasis) {
  return `${percent(rate)}% · 按${calculationBasisLabel(basis)}`
}

function feeDefaultedDates(fee: FeeKind) {
  return fee === 'exchange' ? exchangeLossHeaderDefaultDates : serviceFeeHeaderDefaultDates
}

function setFeeHeaderDefault(row: DailyBalance, fee: FeeKind, enabled: boolean) {
  const dates = new Set(feeDefaultedDates(fee).value)
  if (enabled) dates.add(row.businessDate)
  else dates.delete(row.businessDate)
  feeDefaultedDates(fee).value = dates
}

function clearFeeHeaderDefault(row: DailyBalance, fee: FeeKind) {
  if (feeDefaultedDates(fee).value.has(row.businessDate)) setFeeHeaderDefault(row, fee, false)
}

function isFeeAutoAvailable(fee: FeeKind) {
  const account = activeAccount.value
  if (!account) return false
  return fee === 'exchange' ? account.defaultExchangeLossBasis !== 'MANUAL' : account.defaultServiceFeeBasis !== 'MANUAL'
}

function feeHeaderTooltip(fee: FeeKind) {
  if (!isFeeAutoAvailable(fee)) return `${feeLabel(fee)}投放线默认计算基数为“仅手工”，不能使用自动计算。`
  const basisHint = `当前新行自动${feeDefaultBasisHint(fee)}。`
  if (!canOverrideBalance.value) return `${basisHint} 仅作为当前未保存录入行的默认值；人工填写需要 BALANCE_OVERRIDE 权限。`
  return `${basisHint} 仅作为当前未保存录入行的默认值；不会改写已保存、已确认或已锁定行。`
}

function resetFeeColumnDefaults(account: OperatorAccount) {
  exchangeLossDefaultMode.value = resolveExchangeLossDefaultMode(account)
  serviceFeeDefaultMode.value = account.defaultServiceFeeBasis === 'MANUAL' ? 'MANUAL' : 'AUTO'
  exchangeLossHeaderDefaultDates.value = new Set()
  serviceFeeHeaderDefaultDates.value = new Set()
}

function hasFeeBusinessData(row: DailyBalance) {
  return ['transferAmount', 'spendAmount', 'refluxAmount', 'refundAmount', 'otherDeductionAmount', 'fraudLossAmount']
    .some((key) => !toDecimal(row[key as keyof DailyBalance] as string).eq(0))
}

function isPristineUnsavedFeeRow(row: DailyBalance, fee: FeeKind) {
  if (row.id || !canEditRow(row) || hasFeeBusinessData(row)) return false
  const amount = fee === 'exchange' ? row.exchangeLossAmount : row.serviceFeeAmount
  const mode = fee === 'exchange' ? row.exchangeLossMode : row.serviceFeeMode
  // 已通过单行控件设为人工的记录视为用户输入，表头默认不能再覆盖。
  if (mode === 'MANUAL' && !feeDefaultedDates(fee).value.has(row.businessDate)) return false
  return toDecimal(amount).eq(0)
}

function onFeeRuleEdited(row: DailyBalance, index: number, fee: FeeKind) {
  clearFeeHeaderDefault(row, fee)
  onEdited(row, index)
}

function applyAccountManualFeeDefaults() {
  if (exchangeLossDefaultMode.value === 'MANUAL' && canOverrideBalance.value) setFeeColumnDefault('exchange', 'MANUAL', false)
  if (serviceFeeDefaultMode.value === 'MANUAL') setFeeColumnDefault('service', 'MANUAL', false)
}

function canChangeExchangeLossDefault() {
  return canOverrideBalance.value || isFeeAutoAvailable('exchange')
}

function setFeeColumnDefault(fee: FeeKind, value: string, announce = true) {
  if (value !== 'AUTO' && value !== 'MANUAL') return
  const mode: FeeInputMode = value
  if (mode === 'MANUAL' && !canOverrideBalance.value) {
    if (announce) ElMessage.warning('人工填写汇损或服务费需要 BALANCE_OVERRIDE 权限。')
    return
  }
  if (mode === 'AUTO' && !isFeeAutoAvailable(fee)) {
    if (announce) ElMessage.warning(`${feeLabel(fee)}投放线默认基数为“仅手工”，不能切换为自动计算。`)
    return
  }
  const defaultMode = fee === 'exchange' ? exchangeLossDefaultMode : serviceFeeDefaultMode
  defaultMode.value = mode
  // 仅在用户主动从表头选择时写入偏好；投放线限制导致的页面内回退不能覆盖原偏好。
  if (fee === 'exchange' && announce) saveExchangeLossModePreference(mode)

  let applied = 0
  let firstChangedIndex = -1
  rows.value.forEach((row, index) => {
    // 表头设置只为还没有业务或手工费用数据的新行设默认值，不能重写用户已录入的数据。
    if (!isPristineUnsavedFeeRow(row, fee)) return

    if (fee === 'exchange') {
      if (row.exchangeLossMode === mode) return
      row.exchangeLossMode = mode
      if (mode === 'MANUAL') {
        row.exchangeLossAmount = '0'
        row.exchangeLossOverrideReason = undefined
        setFeeHeaderDefault(row, fee, true)
      } else {
        row.exchangeLossAmount = preview(row).exchangeLossAutoAmount
        row.exchangeLossOverrideReason = undefined
        setFeeHeaderDefault(row, fee, false)
      }
    } else {
      if (row.serviceFeeMode === mode) return
      row.serviceFeeMode = mode
      if (mode === 'MANUAL') {
        row.serviceFeeAmount = '0'
        row.serviceFeeOverrideReason = undefined
        setFeeHeaderDefault(row, fee, true)
      } else {
        row.serviceFeeAmount = preview(row).serviceFeeAutoAmount
        row.serviceFeeOverrideReason = undefined
        setFeeHeaderDefault(row, fee, false)
      }
    }
    applied += 1
    if (firstChangedIndex < 0) firstChangedIndex = index
  })

  // 若未保存行中已经录入了金额，切换默认模式会改变其期末；仅同步连续的未保存自动期初。
  if (firstChangedIndex >= 0) updateFollowingUnsavedOpening(firstChangedIndex)

  if (!announce) return
  const scope = '仅影响当前未录入数据的未保存行，已录入、已保存、已确认和已锁定行保持不变。'
  if (!applied) {
    ElMessage.info(`${feeLabel(fee)}默认已设为${feeModeLabel(mode)}；${scope}`)
    return
  }
  const manualHint = mode === 'MANUAL' ? '手工金额已初始化为 0。' : ''
  ElMessage.success(`${feeLabel(fee)}默认已设为${feeModeLabel(mode)}，已应用到 ${applied} 条未保存日结。${manualHint}`)
}

function openPreview(row: DailyBalance) {
  previewRow.value = row
  serverPreview.value = null
  previewDrawer.value = true
}

async function requestServerPreview() {
  if (!previewRow.value) return
  previewLoading.value = true
  try {
    serverPreview.value = await api.balances.calculate(previewRow.value)
    ElMessage.success('已获取服务端计算预览')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '服务端试算失败')
  } finally {
    previewLoading.value = false
  }
}

function validationErrors(changes: DailyBalance[]) {
  const errors: string[] = []
  for (const row of changes) {
    if (row.fraudDeductionSource === 'TRANSFER' && toDecimal(row.fraudLossAmount).gt(toDecimal(row.transferAmount))) errors.push(`${row.businessDate}：从转账扣除的欺诈损失不能大于转 U`)
    if (toDecimal(row.otherDeductionAmount).gt(0) && !row.otherReason?.trim()) errors.push(`${row.businessDate}：填写“其他”金额时必须补充原因`)
  }
  return errors
}

async function saveChanges() {
  if (isPeriodLocked.value) {
    ElMessage.warning('本月已锁定，不能继续修改日结。')
    return
  }
  const changes = rows.value
    .filter((row) => isRowReady(row) && dirtyDates.value.has(row.businessDate))
    .sort((left, right) => left.businessDate.localeCompare(right.businessDate))
  if (!changes.length) {
    ElMessage.info('没有待保存的修改')
    return
  }
  const errors = validationErrors(changes)
  if (errors.length) {
    await ElMessageBox.alert(errors.join('<br/>'), '请先修正以下数据', { dangerouslyUseHTMLString: true, type: 'error' })
    return
  }
  saving.value = true
  try {
    const saved = await api.balances.batch(changes)
    if (saved.length) {
      const savedByDate = new Map(saved.map((row) => [row.businessDate, row]))
      rows.value = rows.value.map((row) => savedByDate.get(row.businessDate) || row)
      monthRecords.value = Array.from(new Map([...monthRecords.value, ...saved].map((row) => [row.businessDate, row])).values())
    }
    dirtyDates.value = new Set()
    persistEntryDraft()
    ElMessage.success(`已保存 ${changes.length} 条日结记录；期末金额以服务端重算结果为准。`)
  } catch (error) {
    if (usingDemo.value && demoEnabled) {
      dirtyDates.value = new Set()
      persistEntryDraft()
      ElMessage.warning('演示模式不会写入正式账本，修改仅保留在当前页面。')
    } else {
      ElMessage.error(error instanceof Error ? error.message : '保存失败，请稍后重试')
    }
  } finally {
    saving.value = false
  }
}

async function confirmRow(row: DailyBalance) {
  if (!canConfirmBalances.value) {
    ElMessage.warning('当前账号没有确认日结的权限')
    return
  }
  if (isPeriodLocked.value || row.locked) {
    ElMessage.warning('本月已锁定，不能确认日结')
    return
  }
  if (!row.id) {
    ElMessage.warning('请先保存该日结记录，再执行确认')
    return
  }
  try {
    await ElMessageBox.confirm(`确认 ${row.businessDate} 的日结后，录入员将不能直接修改。是否继续？`, '确认日结', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' })
  } catch {
    return
  }
  try {
    const saved = await api.balances.confirm(row.id, row.rowVersion)
    Object.assign(row, saved)
    ElMessage.success('日结已确认')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '确认失败')
  }
}

async function reopenRow(row: DailyBalance) {
  if (!canConfirmBalances.value) {
    ElMessage.warning('当前账号没有重开日结的权限')
    return
  }
  if (isPeriodLocked.value || row.locked) {
    ElMessage.warning('本月已锁定，请先由有权限的人员解锁后再重开日结')
    return
  }
  if (!row.id) return
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(`请说明重开 ${row.businessDate} 日结的原因。该说明会写入审计记录。`, '重开日结', {
      confirmButtonText: '重开',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：更正转账金额',
      inputValidator: (value) => value.trim().length > 0 || '请填写重开原因',
    })
    reason = result.value.trim()
  } catch {
    return
  }
  try {
    const saved = await api.balances.reopen(row.id, row.rowVersion, reason)
    Object.assign(row, saved)
    ElMessage.success('日结已重开，可以继续编辑并再次确认')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重开日结失败')
  }
}

function selectCurrentPeriodLock(locks: PeriodLock[], account: OperatorAccount) {
  return locks.find((lock) => String(lock.accountId) === String(account.id)) || null
}

async function lockPeriod() {
  if (!canManagePeriod.value) {
    ElMessage.warning('当前账号没有锁账权限')
    return
  }
  const account = activeAccount.value
  if (!account || !periodDate.value) return
  periodActionLoading.value = true
  periodLockIssues.value = []
  try {
    const validation = await api.periodLocks.validate(periodDate.value, undefined, [account.id])
    if (!validation.canLock) {
      periodLockIssues.value = validation.issues
      ElMessage.warning(validation.issues.length ? `本月有 ${validation.issues.length} 项未完成，暂不能锁定` : '本月暂不能锁定')
      return
    }
    try {
      await ElMessageBox.confirm(`锁定 ${selectedMonth.value} 后，该投放线本月的日结将全部只读，导入、修改和重开都会被阻止。是否继续？`, '锁定本月', {
        type: 'warning',
        confirmButtonText: '确认锁定',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    const locks = await api.periodLocks.lock(periodDate.value, undefined, [account.id])
    periodLock.value = selectCurrentPeriodLock(locks, account)
    await loadBalances()
    ElMessage.success(`${selectedMonth.value} 已锁定`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '锁定本月失败')
  } finally {
    periodActionLoading.value = false
  }
}

async function unlockPeriod() {
  if (!canManagePeriod.value) {
    ElMessage.warning('当前账号没有解锁权限')
    return
  }
  const account = activeAccount.value
  if (!account || !periodDate.value) return
  let reason = ''
  try {
    const result = await ElMessageBox.prompt(`请填写解锁 ${selectedMonth.value} 的原因。该说明会写入审计记录。`, '解锁本月', {
      confirmButtonText: '确认解锁',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：已发现并需要修正已确认数据',
      inputValidator: (value) => value.trim().length > 0 || '解锁原因不能为空',
    })
    reason = result.value.trim()
  } catch {
    return
  }
  periodActionLoading.value = true
  try {
    const locks = await api.periodLocks.unlock(periodDate.value, undefined, [account.id], reason)
    periodLock.value = selectCurrentPeriodLock(locks, account)
    await loadBalances()
    ElMessage.success(`${selectedMonth.value} 已解锁`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '解锁本月失败')
  } finally {
    periodActionLoading.value = false
  }
}

function formatDay(value: string) {
  if (!value) return ''
  return `${Number(value.slice(8))}日`
}

function amountsChanged(row: DailyBalance) {
  return ['transferAmount', 'spendAmount', 'refluxAmount', 'refundAmount', 'otherDeductionAmount', 'fraudLossAmount'].some((key) => !toDecimal(row[key as keyof DailyBalance] as string).eq(0))
}

function ledgerRowClass({ row }: { row: DailyBalance }) {
  return isRowReady(row) && !isEditable(row) ? 'locked-row' : ''
}

onMounted(() => {
  window.addEventListener('pagehide', persistEntryDraft)
  void loadOperators()
})

onBeforeUnmount(() => {
  persistEntryDraft()
  window.removeEventListener('pagehide', persistEntryDraft)
})
</script>

<template>
  <section class="ledger-page">
    <div class="page-title-row">
      <div>
        <h2>输入台账</h2>
        <p class="page-subtitle">先选择首个业务日期，再按天连续录入。系统会承接上一日结余；月份由日期自动识别，用于锁账和汇总。当前工作面会自动保存在此浏览器，只有手动清除才会移除。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="UploadFilled" @click="$router.push('/imports')">导入数据</el-button>
        <el-button :icon="Download" disabled>导出当前台账</el-button>
        <el-button :icon="Delete" type="danger" plain :disabled="!activeAccount || loading || saving" @click="clearCurrentWorkspace">清除当前工作面</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadBalances">刷新</el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirtyCount || isPeriodLocked" @click="saveChanges">保存修改<span v-if="dirtyCount">（{{ dirtyCount }}）</span></el-button>
      </div>
    </div>

    <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>

    <article class="panel panel--padded">
      <div class="filter-bar">
        <el-form-item label="投放公司"><el-select v-model="selectedOperatorId" filterable style="width: 230px" placeholder="选择投放公司"><el-option v-for="operator in operators.filter((item) => item.status === 'ACTIVE')" :key="operator.id" :label="operator.name" :value="operator.id" /></el-select></el-form-item>
        <el-form-item label="投放线"><el-select v-model="selectedAccountId" style="width: 270px" placeholder="选择投放线"><el-option v-for="account in availableAccounts" :key="account.id" :label="account.displayName || account.name" :value="account.id"><span>{{ account.displayName || account.name }}</span><span class="option-meta">{{ account.asset }}</span></el-option></el-select></el-form-item>
        <div v-if="activeAccount" class="account-context"><el-tag effect="plain">{{ activeAccount.asset }}</el-tag><span>{{ activeAccount.displayName || activeAccount.name }}</span></div>
        <div v-if="selectedMonth" class="entry-month-context"><span>当前录入月份</span><strong>{{ selectedMonth }}</strong></div>
        <div v-if="activeAccount && selectedMonth" class="period-lock-context">
          <StatusTag :status="isPeriodLocked ? 'LOCKED' : 'UNLOCKED'" />
          <span>{{ isPeriodLocked ? '本月日结已锁定，只读' : '本月可编辑' }}</span>
          <el-tooltip :disabled="canManagePeriod" content="需要 PERIOD_LOCK 权限才能锁定或解锁月份。">
            <span>
              <el-button v-if="isPeriodLocked" size="small" type="warning" plain :loading="periodActionLoading" :disabled="!canManagePeriod || periodLockLoading" @click="unlockPeriod">解锁本月</el-button>
              <el-button v-else size="small" type="danger" plain :loading="periodActionLoading" :disabled="!canManagePeriod || periodLockLoading" @click="lockPeriod">锁定本月</el-button>
            </span>
          </el-tooltip>
        </div>
      </div>
      <el-alert v-if="periodLockError" class="period-lock-alert" type="warning" :closable="false" show-icon>{{ periodLockError }}</el-alert>
      <el-alert v-if="periodLockIssues.length" class="period-lock-alert" type="warning" title="本月暂不能锁定" :closable="false" show-icon>
        <ul class="lock-issues"><li v-for="issue in periodLockIssues" :key="`${issue.accountId}-${issue.businessDate}-${issue.code}`">{{ issue.businessDate || selectedMonth }}：{{ issue.message || issue.code }}</li></ul>
      </el-alert>
    </article>

    <article v-if="activeAccount" class="panel table-card ledger-table">
      <div class="ledger-guide"><span><i class="legend legend--auto"></i> 自动计算</span><span><i class="legend legend--manual"></i> 允许手工覆盖</span><span><i class="legend legend--negative"></i> 负结余预警</span><span class="ledger-guide__right">先选择日期后才能输入；表头默认仅影响当前未保存录入行</span></div>
      <el-table v-loading="loading" :data="rows" border max-height="570" size="small" :row-class-name="ledgerRowClass">
        <el-table-column label="业务日期" width="158" fixed="left">
          <template #default="{ row, $index }">
            <el-date-picker v-if="$index === 0" v-model="entryDate" type="date" value-format="YYYY-MM-DD" size="small" :clearable="false" placeholder="先选择日期" :disabled="loading || periodActionLoading || rows.length > 1" @change="onEntryDateChanged" />
            <template v-else><strong>{{ formatDay(row.businessDate) }}</strong><span class="date-sub">{{ row.businessDate.slice(5) }}</span></template>
          </template>
        </el-table-column>
        <el-table-column label="昨日结余" width="152" fixed="left">
          <template #default="{ row, $index }"><div class="opening-cell" :class="{ 'opening-cell--negative': toDecimal(row.openingBalance).isNegative() }"><el-input v-model="row.openingBalance" size="small" :disabled="!canEditRow(row) || row.openingMode === 'AUTO'" @input="onInputEdited(row)" @change="onEdited(row, $index)" /><el-dropdown trigger="click" :disabled="!canEditRow(row)" @command="(value) => setOpeningMode(row, $index, value)"><button class="cell-mode" :class="{ 'cell-mode--disabled': !canEditRow(row) }" type="button" :disabled="!canEditRow(row)" :aria-label="`切换昨日结余录入方式，当前为${row.openingMode === 'MANUAL' ? '手工期初' : '自动承接'}`"><el-icon class="cell-mode__icon"><Refresh /></el-icon><span>{{ row.openingMode === 'MANUAL' ? '手工' : '自动' }}</span></button><template #dropdown><el-dropdown-menu><el-dropdown-item command="AUTO">自动承接</el-dropdown-item><el-dropdown-item command="MANUAL">手工期初</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></template>
        </el-table-column>
        <el-table-column label="转 U" width="112" align="right"><template #default="{ row, $index }"><el-input v-model="row.transferAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /></template></el-table-column>
        <el-table-column label="有效转 U" width="108" align="right"><template #default="{ row }"><span class="auto-value">{{ formatMoney(preview(row).effectiveTransferAmount) }}</span></template></el-table-column>
        <el-table-column label="消耗" width="112" align="right"><template #default="{ row, $index }"><el-input v-model="row.spendAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /></template></el-table-column>
        <el-table-column width="145" align="right">
          <template #header>
            <div class="fee-column-header">
              <span>汇损</span>
              <el-tooltip :content="feeHeaderTooltip('exchange')" placement="top">
                <span>
                  <el-dropdown trigger="click" :disabled="!hasUnsavedEditableRows || !canChangeExchangeLossDefault()" @command="(value) => setFeeColumnDefault('exchange', String(value))">
                    <button class="fee-header-mode" :class="{ 'fee-header-mode--auto': exchangeLossDefaultMode === 'AUTO', 'fee-header-mode--manual': exchangeLossDefaultMode === 'MANUAL' }" type="button" :disabled="!hasUnsavedEditableRows || !canChangeExchangeLossDefault()" :aria-label="`设置汇损默认模式，当前为${feeModeLabel(exchangeLossDefaultMode)}`">
                      <span class="fee-header-mode__label">默认</span>
                      <strong>{{ feeModeLabel(exchangeLossDefaultMode) }}</strong>
                      <el-icon class="fee-header-mode__icon"><ArrowDown /></el-icon>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="AUTO" :disabled="!isFeeAutoAvailable('exchange')">自动计算</el-dropdown-item>
                        <el-dropdown-item command="MANUAL" :disabled="!canOverrideBalance">人工填写（默认 0）</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </el-tooltip>
            </div>
          </template>
          <template #default="{ row, $index }">
            <el-popover placement="bottom" :width="330" trigger="click">
              <template #reference><button class="fee-cell" :disabled="!canEditRow(row)"><span>{{ formatMoney(preview(row).exchangeLossAmount) }}</span><small>{{ row.exchangeLossMode === 'MANUAL' ? '手工填写' : `${percent(row.exchangeLossRate)}%` }}</small></button></template>
              <div class="rule-popover">
                <strong>汇损规则</strong>
                <el-form label-position="top">
                  <div class="rule-grid">
                    <el-form-item label="费率"><el-input v-model="row.exchangeLossRate" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onFeeRuleEdited(row, $index, 'exchange')"><template #append>小数</template></el-input><span class="field-note">当前 {{ percent(row.exchangeLossRate) }}%</span></el-form-item>
                    <el-form-item label="计算基数"><el-select v-model="row.exchangeLossBasis" :disabled="!canEditRow(row)" @change="onFeeRuleEdited(row, $index, 'exchange')"><el-option v-for="item in basisOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                  </div>
                  <el-form-item label="金额模式"><el-radio-group :model-value="row.exchangeLossMode" :disabled="!canEditRow(row)" @change="setFeeMode(row, $index, 'exchange', $event)"><el-radio-button value="AUTO">自动</el-radio-button><el-radio-button value="MANUAL">手工</el-radio-button></el-radio-group></el-form-item>
                  <template v-if="row.exchangeLossMode === 'MANUAL'"><el-form-item label="手工汇损金额"><el-input v-model="row.exchangeLossAmount" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onFeeRuleEdited(row, $index, 'exchange')" /></el-form-item></template>
                  <p class="rule-result">自动结果：{{ formatMoney(preview(row).exchangeLossAutoAmount) }}</p>
                </el-form>
              </div>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column width="145" align="right">
          <template #header>
            <div class="fee-column-header">
              <span class="fee-header-title">服务费 <small class="fee-header-basis">新行{{ feeDefaultBasisHint('service') }}</small></span>
              <el-tooltip :content="feeHeaderTooltip('service')" placement="top">
                <span>
                  <el-dropdown trigger="click" :disabled="!hasUnsavedEditableRows || !isFeeAutoAvailable('service')" @command="(value) => setFeeColumnDefault('service', String(value))">
                    <button class="fee-header-mode" :class="{ 'fee-header-mode--auto': serviceFeeDefaultMode === 'AUTO', 'fee-header-mode--manual': serviceFeeDefaultMode === 'MANUAL' }" type="button" :disabled="!hasUnsavedEditableRows || !isFeeAutoAvailable('service')" :aria-label="`设置服务费默认模式，当前为${feeModeLabel(serviceFeeDefaultMode)}`">
                      <span class="fee-header-mode__label">默认</span>
                      <strong>{{ feeModeLabel(serviceFeeDefaultMode) }}</strong>
                      <el-icon class="fee-header-mode__icon"><ArrowDown /></el-icon>
                    </button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="AUTO">自动计算</el-dropdown-item>
                        <el-dropdown-item command="MANUAL" :disabled="!canOverrideBalance">人工填写（默认 0）</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </el-tooltip>
            </div>
          </template>
          <template #default="{ row, $index }">
            <el-popover placement="bottom" :width="330" trigger="click">
              <template #reference><button class="fee-cell" :disabled="!canEditRow(row)"><span>{{ formatMoney(preview(row).serviceFeeAmount) }}</span><small>{{ row.serviceFeeMode === 'MANUAL' ? '手工填写' : feeAutoSummary(row.serviceFeeRate, row.serviceFeeBasis) }}</small></button></template>
              <div class="rule-popover">
                <strong>服务费规则</strong>
                <el-form label-position="top">
                  <div class="rule-grid">
                    <el-form-item label="费率"><el-input v-model="row.serviceFeeRate" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onFeeRuleEdited(row, $index, 'service')"><template #append>小数</template></el-input><span class="field-note">当前 {{ percent(row.serviceFeeRate) }}%</span></el-form-item>
                    <el-form-item label="计算基数"><el-select v-model="row.serviceFeeBasis" :disabled="!canEditRow(row)" @change="onFeeRuleEdited(row, $index, 'service')"><el-option v-for="item in basisOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
                  </div>
                  <el-form-item label="金额模式"><el-radio-group :model-value="row.serviceFeeMode" :disabled="!canEditRow(row)" @change="setFeeMode(row, $index, 'service', $event)"><el-radio-button value="AUTO">自动</el-radio-button><el-radio-button value="MANUAL">手工</el-radio-button></el-radio-group></el-form-item>
                  <template v-if="row.serviceFeeMode === 'MANUAL'"><el-form-item label="手工服务费金额"><el-input v-model="row.serviceFeeAmount" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onFeeRuleEdited(row, $index, 'service')" /></el-form-item></template>
                  <p class="rule-result">自动结果：{{ formatMoney(preview(row).serviceFeeAutoAmount) }}</p>
                </el-form>
              </div>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column label="回流" width="105" align="right"><template #default="{ row, $index }"><el-input v-model="row.refluxAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /></template></el-table-column>
        <el-table-column label="退款" width="105" align="right"><template #default="{ row, $index }"><el-input v-model="row.refundAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /></template></el-table-column>
        <el-table-column label="其他" width="142" align="right"><template #default="{ row, $index }"><el-input v-model="row.otherDeductionAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /><el-input v-if="toDecimal(row.otherDeductionAmount).gt(0)" v-model="row.otherReason" class="reason-input" size="small" placeholder="扣减原因（必填）" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /></template></el-table-column>
        <el-table-column label="欺诈损失" width="164"><template #default="{ row, $index }"><el-input v-model="row.fraudLossAmount" size="small" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /><el-select v-if="toDecimal(row.fraudLossAmount).gt(0)" v-model="row.fraudDeductionSource" class="fraud-source" size="small" :disabled="!canEditRow(row)" placeholder="承担方式" @change="onEdited(row, $index)"><el-option label="从转账扣除" value="TRANSFER" /><el-option label="从结余扣除" value="BALANCE" /></el-select></template></el-table-column>
        <el-table-column label="当日结余" width="122" fixed="right" align="right"><template #default="{ row }"><button class="closing-value" :class="{ 'closing-value--negative': toDecimal(preview(row).closingBalance).isNegative() }" :disabled="!isRowReady(row)" @click="openPreview(row)">{{ formatMoney(preview(row).closingBalance) }}<el-icon><Operation /></el-icon></button></template></el-table-column>
        <el-table-column label="状态" width="86" fixed="right" align="center"><template #default="{ row }"><StatusTag :status="row.locked ? 'LOCKED' : row.status" /></template></el-table-column>
        <el-table-column label="备注 / 操作" width="180" fixed="right"><template #default="{ row, $index }"><el-input v-model="row.remark" size="small" placeholder="备注" :disabled="!canEditRow(row)" @input="onInputEdited(row)" @change="onEdited(row, $index)" /><el-button v-if="canConfirmBalances && row.status === 'DRAFT' && row.id && !row.locked && !isPeriodLocked" class="confirm-button" link type="primary" @click="confirmRow(row)">确认日结</el-button><el-button v-else-if="canConfirmBalances && row.status === 'CONFIRMED' && row.id && !row.locked && !isPeriodLocked" class="confirm-button" link type="warning" @click="reopenRow(row)">重开日结</el-button><span v-else-if="!isRowReady(row)" class="muted">请先选择日期</span><span v-else-if="row.locked || isPeriodLocked" class="muted">本月已锁定</span><span v-else-if="!amountsChanged(row)" class="muted">无发生额</span></template></el-table-column>
      </el-table>
      <div class="ledger-entry-actions">
        <span v-if="!entryDate">请选择首个业务日期后开始录入。</span>
        <span v-else>已录入 {{ entryRows.length }} 天；可连续新增或按指定日期补录。</span>
        <div class="ledger-entry-actions__buttons">
          <el-button class="ledger-entry-action" text :disabled="!canAddNextDay" @click="addNextDay"><el-icon><Plus /></el-icon><span>新增下一天</span></el-button>
          <el-button class="ledger-entry-action" text :disabled="!canAddSpecifiedDate" @click="openSpecifiedDateDialog"><el-icon><Calendar /></el-icon><span>新增指定日期</span></el-button>
        </div>
        <span aria-hidden="true"></span>
      </div>
      <div v-if="entryRows.length" class="ledger-total"><strong>当前输入序列试算</strong><span>期初 <MoneyText :value="monthlyTotals.opening" /></span><span>转 U <MoneyText :value="monthlyTotals.transfer" /></span><span>有效转 U <MoneyText :value="monthlyTotals.effectiveTransfer" /></span><span>消耗 <MoneyText :value="monthlyTotals.spend" /></span><span>汇损 <MoneyText :value="monthlyTotals.exchange" /></span><span>服务费 <MoneyText :value="monthlyTotals.service" /></span><span>期末 <MoneyText :value="monthlyTotals.closing" colorize /></span><em>保存后以服务端汇总为准</em></div>
    </article>

    <div v-else class="empty-panel"><div><h3>请选择可用投放线</h3><p>先在投放公司管理中创建投放公司和 USDT / USDC 投放线，再录入每日结余。</p></div></div>

    <el-drawer v-model="previewDrawer" title="计算预览" size="440px">
      <template v-if="previewRow">
        <div class="calc-title"><span>{{ previewRow.businessDate }} · {{ activeAccount?.name }}</span><el-button :loading="previewLoading" size="small" type="primary" plain @click="requestServerPreview">服务端试算</el-button></div>
        <el-alert type="info" :closable="false" show-icon>浏览器试算用于即时反馈；提交时服务端会使用保存的费率、基数、精度和公式版本重新计算。</el-alert>
        <div class="calculation-list"><div><span>昨日结余</span><MoneyText :value="previewRow.openingBalance" /></div><div class="plus"><span>转 U</span><MoneyText :value="previewRow.transferAmount" /></div><div v-if="preview(previewRow).fraudFromTransfer !== '0.00'" class="minus"><span>转账型欺诈损失</span><MoneyText :value="preview(previewRow).fraudFromTransfer" /></div><div class="result-line"><span>有效转 U</span><MoneyText :value="preview(previewRow).effectiveTransferAmount" /></div><div class="minus"><span>消耗</span><MoneyText :value="previewRow.spendAmount" /></div><div class="minus"><span>汇损</span><MoneyText :value="preview(previewRow).exchangeLossAmount" /></div><div class="minus"><span>服务费</span><MoneyText :value="preview(previewRow).serviceFeeAmount" /></div><div class="minus"><span>回流 / 退款 / 其他</span><MoneyText :value="toDecimal(previewRow.refluxAmount).plus(toDecimal(previewRow.refundAmount)).plus(toDecimal(previewRow.otherDeductionAmount)).toString()" /></div><div v-if="preview(previewRow).fraudFromBalance !== '0.00'" class="minus"><span>结余型欺诈损失</span><MoneyText :value="preview(previewRow).fraudFromBalance" /></div><div class="closing-line"><span>当日结余</span><MoneyText :value="preview(previewRow).closingBalance" colorize /></div></div>
        <div v-if="serverPreview" class="server-preview"><span>服务端期末</span><MoneyText :value="serverPreview.closingBalance" colorize /><el-tag type="success" size="small">已由服务端计算</el-tag></div>
      </template>
    </el-drawer>

    <el-dialog v-model="specifiedDateDialogVisible" title="新增指定日期" width="420px" :close-on-click-modal="false">
      <p class="specified-date-dialog__hint">仅可选择当前录入月份中最后一条录入之后的日期；新增后会自动承接前一条结余。</p>
      <el-date-picker v-model="specifiedDate" type="date" value-format="YYYY-MM-DD" style="width: 100%" :clearable="false" :disabled-date="isSpecifiedDateDisabled" placeholder="选择业务日期" />
      <template #footer>
        <el-button @click="specifiedDateDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!specifiedDate" :loading="loading" @click="addSpecifiedDate">确认新增</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.load-error { margin-bottom: 16px; }.option-meta { float: right; margin-left: 24px; color: #98a2b3; font-size: 12px; }.account-context, .period-lock-context { display: flex; align-items: center; gap: 8px; padding-bottom: 5px; color: #667085; font-size: 12px; }.period-lock-context { margin-left: auto; }.period-lock-alert { margin-top: 10px; }.lock-issues { margin: 6px 0 0; padding-left: 18px; line-height: 1.65; }.ledger-table { min-width: 0; }.ledger-guide { display: flex; align-items: center; gap: 17px; padding: 12px 16px; color: #667085; font-size: 12px; border-bottom: 1px solid #eaecf0; }.ledger-guide__right { margin-left: auto; }.legend { display: inline-block; width: 8px; height: 8px; margin-right: 5px; border-radius: 50%; }.legend--auto { background: #528bff; }.legend--manual { background: #f79009; }.legend--negative { background: #f04438; }.date-sub { display: block; margin-top: 3px; color: #98a2b3; font-size: 10px; }.opening-cell { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px; align-items: center; }.opening-cell--negative :deep(.el-input__wrapper) { background: #fff1f0; box-shadow: inset 0 0 0 1px #fecdca; }.opening-cell--negative :deep(.el-input__inner) { color: #d92d20; font-weight: 650; -webkit-text-fill-color: #d92d20; }.cell-mode { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-height: 26px; padding: 0 7px; color: #b54708; font-size: 12px; font-weight: 700; line-height: 1; cursor: pointer; background: #fffaeb; border: 1px solid #fec84b; border-radius: 5px; box-shadow: 0 1px 2px rgb(180 83 9 / 12%); transition: color .16s ease, background-color .16s ease, border-color .16s ease, box-shadow .16s ease; }.cell-mode:hover:not(:disabled) { color: #93370d; background: #fef0c7; border-color: #f79009; box-shadow: 0 1px 3px rgb(180 83 9 / 22%); }.cell-mode:focus-visible { outline: 2px solid #fdb022; outline-offset: 1px; }.cell-mode__icon { font-size: 14px; }.cell-mode--disabled, .cell-mode:disabled { color: #98a2b3; cursor: default; background: #f9fafb; border-color: #eaecf0; box-shadow: none; }.reason-input { margin-top: 4px; }.auto-value { color: #667085; font-variant-numeric: tabular-nums; }.fee-column-header { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }.fee-header-mode { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-height: 23px; padding: 2px 6px; font-size: 11px; line-height: 1.2; cursor: pointer; border: 1px solid transparent; border-radius: 5px; box-shadow: 0 1px 1px rgb(16 24 40 / 4%); transition: color .16s ease, background-color .16s ease, border-color .16s ease, box-shadow .16s ease; }.fee-header-mode__label { font-size: 10px; font-weight: 500; opacity: .8; }.fee-header-mode--auto { color: #175cd3; background: #eff8ff; border-color: #b2ddff; }.fee-header-mode--manual { color: #b54708; background: #fffaeb; border-color: #fedf89; }.fee-header-mode:hover:not(:disabled) { box-shadow: 0 1px 2px rgb(16 24 40 / 12%); }.fee-header-mode--auto:hover:not(:disabled) { color: #004eeb; background: #d1e9ff; border-color: #84caff; }.fee-header-mode--manual:hover:not(:disabled) { color: #93370d; background: #fef0c7; border-color: #fec84b; }.fee-header-mode:focus-visible { outline: 2px solid #84adff; outline-offset: 1px; }.fee-header-mode:disabled { color: #98a2b3; cursor: default; background: #f9fafb; border-color: #eaecf0; box-shadow: none; }.fee-cell { display: grid; width: 100%; padding: 0; color: #344054; text-align: right; cursor: pointer; background: transparent; border: 0; }.fee-cell:disabled { color: #667085; cursor: default; }.fee-cell small { color: #98a2b3; font-size: 10px; }.rule-popover > strong { display: block; margin-bottom: 10px; color: #182230; }.rule-popover :deep(.el-form-item) { margin-bottom: 11px; }.rule-grid { display: grid; grid-template-columns: 1fr 1.25fr; gap: 12px; }.rule-result { margin: 4px 0 0; color: #667085; font-size: 12px; }.fraud-source { width: 100%; margin-top: 4px; }.closing-value { display: inline-flex; align-items: center; justify-content: flex-end; gap: 4px; width: 100%; padding: 0; color: #027a48; font-weight: 700; font-variant-numeric: tabular-nums; cursor: pointer; background: transparent; border: 0; }.closing-value:hover { color: #155eef; }.closing-value--negative { color: #d92d20; }.confirm-button { margin-top: 4px; }.locked-row :deep(.el-input__wrapper) { background: #f9fafb; }.ledger-total { display: flex; align-items: center; gap: 18px; min-width: max-content; padding: 13px 16px; color: #667085; font-size: 12px; border-top: 1px solid #eaecf0; overflow-x: auto; }.ledger-total strong { color: #344054; }.ledger-total em { color: #98a2b3; font-style: normal; }.calc-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 15px; color: #344054; font-size: 13px; font-weight: 650; }.calculation-list { margin-top: 16px; }.calculation-list > div { display: flex; justify-content: space-between; padding: 9px 0; color: #475467; font-size: 13px; border-bottom: 1px solid #f2f4f7; }.calculation-list .plus span::before { margin-right: 6px; color: #027a48; content: '+'; }.calculation-list .minus span::before { margin-right: 6px; color: #d92d20; content: '−'; }.calculation-list .result-line { color: #155eef; background: #eff4ff; }.calculation-list .closing-line { margin-top: 8px; padding: 14px 0; color: #101828; font-size: 16px; font-weight: 700; border-top: 1px solid #d0d5dd; border-bottom: 0; }.server-preview { display: flex; align-items: center; gap: 9px; margin-top: 18px; padding: 12px; color: #027a48; background: #ecfdf3; border-radius: 8px; }.server-preview span:first-child { flex: 1; }
.fee-header-mode strong { font-weight: 700; }
.fee-header-mode__icon { width: 11px; height: 11px; margin-left: 1px; }
.opening-cell--negative :deep(.el-input.is-disabled .el-input__wrapper) { background: #fff1f0; box-shadow: inset 0 0 0 1px #fecdca; }
.opening-cell--negative :deep(.el-input.is-disabled .el-input__inner) { color: #d92d20; font-weight: 650; -webkit-text-fill-color: #d92d20; }
.fee-header-title { display: inline-flex; align-items: baseline; gap: 5px; }
.fee-header-basis { color: #667085; font-size: 10px; font-weight: 500; }
.entry-month-context { display: inline-flex; align-items: center; gap: 7px; padding: 5px 9px; color: #475467; font-size: 12px; background: #f8fafc; border: 1px solid #e4e7ec; border-radius: 6px; }
.entry-month-context strong { color: #155eef; font-variant-numeric: tabular-nums; }
.ledger-entry-actions { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 16px; padding: 12px 16px; color: #667085; font-size: 12px; border-top: 1px solid #eaecf0; }
.ledger-entry-actions__buttons { display: inline-flex; align-items: center; justify-content: center; gap: 22px; }
.ledger-entry-action { --el-button-text-color: #039855; --el-button-hover-text-color: #027a48; --el-button-active-text-color: #05603a; min-height: 28px; padding: 0; color: #039855; font-weight: 650; background: transparent !important; border: 0 !important; box-shadow: none !important; }
.ledger-entry-action:hover, .ledger-entry-action:focus, .ledger-entry-action:active { background: transparent !important; }
.ledger-entry-action :deep(.el-icon) { margin-right: 5px; font-size: 15px; }
.ledger-entry-action.is-disabled { color: #98a2b3; }
.specified-date-dialog__hint { margin: 0 0 16px; color: #667085; line-height: 1.6; }
.closing-value:disabled { color: #98a2b3; cursor: default; }
</style>
