import axios, { AxiosError } from 'axios'
import type {
  AuditLog,
  AuditLogQuery,
  CalculationPreview,
  CurrentUser,
  DailyBalance,
  DownloadFile,
  ImportJob,
  ImportJobDetail,
  ImportJobRow,
  ImportPreview,
  ManagedUser,
  Operator,
  OperatorAccount,
  PeriodLock,
  PeriodLockIssue,
  PeriodLockValidation,
  ReportRow,
  RedemptionCampaign,
  RedemptionCampaignTier,
  RedemptionBatchDetail,
  RedemptionCodeGroupInput,
  RedemptionCodeBatch,
  RedemptionCodeIssue,
  RedemptionRemoteCreationOptions,
  RedemptionRemoteConnection,
  RedemptionRemoteMarket,
  RedemptionRemoteTag,
  RedemptionRewardTierPreset,
  Role,
  CreateUserInput,
  UpdateUserInput,
} from './types'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_ERP_COMPAT_API_BASE_URL || '/erp-api/api/v1',
  withCredentials: true,
  timeout: 15_000,
  headers: { 'X-Requested-With': 'XMLHttpRequest' },
  xsrfCookieName: 'XSRF-TOKEN',
  xsrfHeaderName: 'X-XSRF-TOKEN',
  paramsSerializer: {
    serialize(params) {
      const search = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null || value === '') continue
        if (Array.isArray(value)) value.forEach((item) => search.append(key, String(item)))
        else search.append(key, String(value))
      }
      return search.toString()
    },
  },
})

let csrfReady = false

async function ensureCsrf() {
  if (csrfReady) return
  await apiClient.get('/auth/csrf')
  csrfReady = true
}

apiClient.interceptors.request.use(async (config) => {
  const method = (config.method || 'get').toLowerCase()
  const url = config.url || ''
  const requiresCsrf = !['get', 'head', 'options'].includes(method) && !url.endsWith('/auth/login')
  if (requiresCsrf) await ensureCsrf()
  return config
})

export interface ApiProblem {
  code?: string
  message: string
  status?: number
  details?: Record<string, unknown>
}

export class ApiError extends Error implements ApiProblem {
  code?: string
  status?: number
  details?: Record<string, unknown>

  constructor(problem: ApiProblem) {
    super(problem.message)
    this.name = 'ApiError'
    this.code = problem.code
    this.status = problem.status
    this.details = problem.details
  }
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data
  }
  return payload as T
}

function paramsWithoutEmpty(params: object) {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '' && (!Array.isArray(value) || value.length > 0)))
}

async function request<T>(action: () => Promise<{ data: unknown }>): Promise<T> {
  try {
    return unwrap<T>((await action()).data)
  } catch (error) {
    if (error instanceof ApiError) throw error
    const axiosError = error as AxiosError<ApiProblem>
    const body = axiosError.response?.data
    throw new ApiError({
      code: body?.code,
      message: body?.message || axiosError.message || '请求服务失败，请稍后重试。',
      status: axiosError.response?.status,
      details: body?.details,
    })
  }
}

function readResponseHeader(headers: unknown, name: string) {
  const candidate = headers as { get?: (key: string) => unknown }
  const fromGetter = typeof candidate?.get === 'function' ? candidate.get(name) : undefined
  if (fromGetter !== undefined && fromGetter !== null) return String(fromGetter)
  const record = asRecord(headers)
  const fromRecord = record[name] ?? record[name.toLowerCase()]
  return fromRecord === undefined || fromRecord === null ? undefined : String(fromRecord)
}

function filenameFromDisposition(disposition: string | undefined, fallback: string) {
  if (!disposition) return fallback
  const encoded = disposition.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i)?.[1]
  const regular = disposition.match(/filename\s*=\s*([^;]+)/i)?.[1]
  const raw = (encoded || regular || '').trim().replace(/^['"]|['"]$/g, '')
  if (!raw) return fallback
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

async function requestDownload(action: () => Promise<{ data: Blob; headers: unknown }>, fallbackFilename: string): Promise<DownloadFile> {
  try {
    const response = await action()
    return {
      blob: response.data,
      filename: filenameFromDisposition(readResponseHeader(response.headers, 'content-disposition'), fallbackFilename),
    }
  } catch (error) {
    const axiosError = error as AxiosError<unknown>
    let body = axiosError.response?.data
    if (body instanceof Blob) {
      try {
        body = JSON.parse(await body.text()) as unknown
      } catch {
        body = undefined
      }
    }
    const problem = asRecord(body)
    throw new ApiError({
      code: problem.code ? String(problem.code) : undefined,
      message: problem.message ? String(problem.message) : axiosError.message || '文件下载失败，请稍后重试。',
      status: axiosError.response?.status,
      details: asRecord(problem.details),
    })
  }
}

type JsonRecord = Record<string, unknown>

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' ? value as JsonRecord : {}
}

function amount(value: unknown, fallback = '0') {
  return value === null || value === undefined ? fallback : String(value)
}

function optionalAmount(value: unknown) {
  return value === null || value === undefined ? undefined : String(value)
}

function stringArray(value: unknown) {
  return Array.isArray(value) ? value.map(String) : []
}

function normalizeUser(raw: unknown): CurrentUser {
  const value = asRecord(raw)
  return {
    id: value.id as string | number,
    username: String(value.username || ''),
    displayName: String(value.displayName || value.username || ''),
    roles: stringArray(value.roles),
    permissions: stringArray(value.permissions),
    operatorIds: Array.isArray(value.operatorIds) ? value.operatorIds as Array<string | number> : [],
    allOperators: Boolean(value.allOperators),
    mustChangePassword: Boolean(value.mustChangePassword),
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizeManagedUser(raw: unknown): ManagedUser {
  const value = asRecord(raw)
  return {
    ...normalizeUser(value),
    enabled: value.enabled !== false,
    createdAt: value.createdAt ? String(value.createdAt) : undefined,
  }
}

function normalizeRole(raw: unknown): Role {
  const value = asRecord(raw)
  return {
    id: value.id as string | number,
    code: String(value.code || ''),
    name: String(value.name || ''),
    description: value.description ? String(value.description) : undefined,
    permissions: stringArray(value.permissions),
  }
}

function normalizeAuditLog(raw: unknown): AuditLog {
  const value = asRecord(raw)
  const id = (input: unknown) => typeof input === 'string' || typeof input === 'number' ? input : undefined
  const text = (input: unknown) => input === null || input === undefined ? undefined : String(input)
  return {
    id: id(value.id) ?? '',
    actorUserId: id(value.actorUserId),
    action: String(value.action || ''),
    entityType: String(value.entityType || ''),
    entityId: text(value.entityId),
    operatorId: id(value.operatorId),
    requestId: text(value.requestId),
    ipAddress: text(value.ipAddress),
    reason: text(value.reason),
    beforeJson: text(value.beforeJson),
    afterJson: text(value.afterJson),
    createdAt: String(value.createdAt || ''),
  }
}

function normalizeOperator(raw: unknown): Operator {
  const value = asRecord(raw)
  return {
    id: value.id as string | number,
    code: String(value.code || ''),
    name: String(value.name || ''),
    type: String(value.operatorType || value.type || 'STUDIO') as Operator['type'],
    status: String(value.status || 'ACTIVE') as Operator['status'],
    contactName: value.contactName ? String(value.contactName) : undefined,
    contactValue: value.contactValue ? String(value.contactValue) : undefined,
    remark: value.remark ? String(value.remark) : undefined,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizeAccount(raw: unknown): OperatorAccount {
  const value = asRecord(raw)
  return {
    id: value.id as string | number,
    operatorId: value.operatorId as string | number,
    companyName: value.companyName ? String(value.companyName) : undefined,
    displayName: value.displayName ? String(value.displayName) : undefined,
    code: String(value.code || ''),
    name: String(value.name || ''),
    asset: String(value.asset || 'USDT') as OperatorAccount['asset'],
    network: value.network ? String(value.network) : undefined,
    walletAddress: value.walletAddress ? String(value.walletAddress) : undefined,
    startDate: value.startDate ? String(value.startDate) : undefined,
    defaultExchangeLossRate: amount(value.defaultExchangeLossRate),
    defaultExchangeLossBasis: String(value.defaultExchangeLossBasis || 'TRANSFER') as OperatorAccount['defaultExchangeLossBasis'],
    defaultServiceFeeRate: amount(value.defaultServiceFeeRate),
    defaultServiceFeeBasis: String(value.defaultServiceFeeBasis || 'TRANSFER') as OperatorAccount['defaultServiceFeeBasis'],
    calculationScale: Number(value.calculationScale ?? 2),
    status: String(value.status || 'ACTIVE') as OperatorAccount['status'],
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizeBalance(raw: unknown): DailyBalance {
  const value = asRecord(raw)
  return {
    id: value.id as string | number | undefined,
    accountId: (value.operatorAccountId ?? value.accountId) as string | number,
    businessDate: String(value.businessDate || ''),
    openingBalance: amount(value.openingBalance),
    suggestedOpeningBalance: optionalAmount(value.suggestedOpeningBalance),
    openingMode: String(value.openingMode || 'AUTO') as DailyBalance['openingMode'],
    openingOverrideReason: value.openingOverrideReason ? String(value.openingOverrideReason) : undefined,
    transferAmount: amount(value.transferAmount),
    fraudLossAmount: amount(value.fraudLossAmount),
    fraudDeductionSource: value.fraudDeductionSource ? String(value.fraudDeductionSource) as DailyBalance['fraudDeductionSource'] : null,
    effectiveTransferAmount: optionalAmount(value.effectiveTransferAmount),
    spendAmount: amount(value.spendAmount),
    exchangeLossRate: amount(value.exchangeLossRate),
    exchangeLossBasis: String(value.exchangeLossBasis || 'TRANSFER') as DailyBalance['exchangeLossBasis'],
    exchangeLossAutoAmount: optionalAmount(value.exchangeLossAutoAmount),
    exchangeLossAmount: amount(value.exchangeLossAmount),
    exchangeLossMode: String(value.exchangeLossMode || 'AUTO') as DailyBalance['exchangeLossMode'],
    exchangeLossOverrideReason: value.exchangeLossOverrideReason ? String(value.exchangeLossOverrideReason) : undefined,
    serviceFeeRate: amount(value.serviceFeeRate),
    serviceFeeBasis: String(value.serviceFeeBasis || 'TRANSFER') as DailyBalance['serviceFeeBasis'],
    serviceFeeAutoAmount: optionalAmount(value.serviceFeeAutoAmount),
    serviceFeeAmount: amount(value.serviceFeeAmount),
    serviceFeeMode: String(value.serviceFeeMode || 'AUTO') as DailyBalance['serviceFeeMode'],
    serviceFeeOverrideReason: value.serviceFeeOverrideReason ? String(value.serviceFeeOverrideReason) : undefined,
    refluxAmount: amount(value.refluxAmount),
    refundAmount: amount(value.refundAmount),
    otherDeductionAmount: amount(value.otherDeductionAmount),
    otherReason: value.otherReason ? String(value.otherReason) : undefined,
    closingBalance: optionalAmount(value.closingBalance),
    calculationScale: Number(value.calculationScale ?? 2),
    status: String(value.status || 'DRAFT') as DailyBalance['status'],
    locked: Boolean(value.locked),
    sourceType: value.sourceType ? String(value.sourceType) as DailyBalance['sourceType'] : undefined,
    remark: value.remark ? String(value.remark) : undefined,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizePeriodLock(raw: unknown): PeriodLock {
  const value = asRecord(raw)
  const optionalId = (input: unknown) => typeof input === 'string' || typeof input === 'number' ? input : undefined
  return {
    id: (value.id ?? '') as string | number,
    accountId: (value.accountId ?? value.operatorAccountId ?? '') as string | number,
    month: String(value.month || value.periodMonth || ''),
    status: String(value.status || 'LOCKED'),
    lockedBy: optionalId(value.lockedBy),
    lockedAt: value.lockedAt ? String(value.lockedAt) : undefined,
    unlockReason: value.unlockReason ? String(value.unlockReason) : undefined,
    unlockedBy: optionalId(value.unlockedBy),
    unlockedAt: value.unlockedAt ? String(value.unlockedAt) : undefined,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizePeriodLockIssue(raw: unknown): PeriodLockIssue {
  const value = asRecord(raw)
  return {
    accountId: (value.accountId ?? value.operatorAccountId) as string | number | undefined,
    businessDate: value.businessDate ? String(value.businessDate) : undefined,
    code: String(value.code || ''),
    message: String(value.message || ''),
  }
}

function normalizePeriodLockValidation(raw: unknown): PeriodLockValidation {
  const value = asRecord(raw)
  return {
    month: String(value.month || ''),
    canLock: Boolean(value.canLock),
    issues: (Array.isArray(value.issues) ? value.issues : []).map(normalizePeriodLockIssue),
  }
}

function numericIds(ids?: Array<string | number>) {
  const values = (ids || []).map(Number).filter((value) => Number.isFinite(value))
  return values.length ? values : undefined
}

function periodLockRequest(month: string, operatorIds?: Array<string | number>, accountIds?: Array<string | number>) {
  return {
    month,
    operatorIds: numericIds(operatorIds),
    accountIds: numericIds(accountIds),
  }
}

function balanceRequest(record: Partial<DailyBalance>) {
  return {
    operatorAccountId: record.accountId,
    businessDate: record.businessDate,
    openingBalance: record.openingBalance,
    openingMode: record.openingMode,
    openingOverrideReason: record.openingOverrideReason,
    transferAmount: record.transferAmount,
    fraudLossAmount: record.fraudLossAmount,
    fraudDeductionSource: record.fraudDeductionSource,
    spendAmount: record.spendAmount,
    exchangeLossRate: record.exchangeLossRate,
    exchangeLossBasis: record.exchangeLossBasis,
    exchangeLossMode: record.exchangeLossMode,
    exchangeLossAmount: record.exchangeLossAmount,
    exchangeLossOverrideReason: record.exchangeLossOverrideReason,
    serviceFeeRate: record.serviceFeeRate,
    serviceFeeBasis: record.serviceFeeBasis,
    serviceFeeMode: record.serviceFeeMode,
    serviceFeeAmount: record.serviceFeeAmount,
    serviceFeeOverrideReason: record.serviceFeeOverrideReason,
    refluxAmount: record.refluxAmount,
    refundAmount: record.refundAmount,
    otherDeductionAmount: record.otherDeductionAmount,
    otherReason: record.otherReason,
    calculationScale: record.calculationScale,
    sourceType: record.sourceType || 'MANUAL',
    remark: record.remark,
    rowVersion: record.rowVersion,
  }
}

function normalizeCalculation(raw: unknown): CalculationPreview {
  const value = asRecord(raw)
  return {
    suggestedOpeningBalance: optionalAmount(value.suggestedOpeningBalance),
    openingBalance: amount(value.openingBalance),
    effectiveTransferAmount: amount(value.effectiveTransferAmount),
    exchangeLossAutoAmount: amount(value.exchangeLossAutoAmount),
    exchangeLossAmount: amount(value.exchangeLossAmount),
    serviceFeeAutoAmount: amount(value.serviceFeeAutoAmount),
    serviceFeeAmount: amount(value.serviceFeeAmount),
    fraudFromTransfer: amount(value.fraudFromTransfer),
    fraudFromBalance: amount(value.fraudFromBalance),
    closingBalance: amount(value.closingBalance),
  }
}

function normalizeReport(raw: unknown, type: 'daily' | 'monthly'): ReportRow {
  const value = asRecord(raw)
  return {
    ...(type === 'daily' ? { businessDate: String(value.period || '') } : { periodMonth: String(value.period || '') }),
    asset: String(value.asset || 'USDT') as ReportRow['asset'],
    openingBalance: amount(value.openingBalance), transferAmount: amount(value.transferAmount), fraudFromTransfer: amount(value.fraudFromTransfer), effectiveTransferAmount: amount(value.effectiveTransferAmount), spendAmount: amount(value.spendAmount), exchangeLossAmount: amount(value.exchangeLossAmount), serviceFeeAmount: amount(value.serviceFeeAmount), refluxAmount: amount(value.refluxAmount), refundAmount: amount(value.refundAmount), otherDeductionAmount: amount(value.otherDeductionAmount), fraudFromBalance: amount(value.fraudFromBalance), closingBalance: amount(value.closingBalance), recordCount: Number(value.recordCount ?? 0),
  }
}

function normalizeImport(raw: unknown): ImportPreview {
  const value = asRecord(raw)
  const job = asRecord(value.job)
  const rawRows = Array.isArray(value.rows) ? value.rows : []
  return {
    jobId: String(job.id || ''),
    sourceType: String(job.sourceType || 'PASTE') as ImportPreview['sourceType'],
    totalRows: Number(job.totalRows ?? rawRows.length), validRows: Number(job.validRows ?? 0), warningRows: Number(job.warningRows ?? 0), errorRows: Number(job.errorRows ?? 0),
    rows: rawRows.map((item) => {
      const row = asRecord(item)
      const severity = String(row.severity || 'SUCCESS')
      return {
        sourceRow: Number(row.sourceRow ?? 0), businessDate: row.businessDate ? String(row.businessDate) : undefined, operatorName: row.operatorName ? String(row.operatorName) : undefined,
        accountName: row.operatorAccountId ? `投放线 #${row.operatorAccountId}` : undefined,
        action: String(row.action || (severity === 'ERROR' ? 'ERROR' : 'CREATE')) as ImportPreview['rows'][number]['action'],
        level: (severity === 'OK' ? 'SUCCESS' : severity === 'WARN' ? 'WARNING' : severity) as ImportPreview['rows'][number]['level'],
        message: row.errorMessage ? String(row.errorMessage) : row.errorCode ? String(row.errorCode) : undefined,
      }
    }),
  }
}

function normalizeImportJob(raw: unknown): ImportJob {
  const value = asRecord(raw)
  return {
    id: (value.id ?? '') as string | number,
    sourceType: String(value.sourceType || 'PASTE'),
    originalFilename: value.originalFilename ? String(value.originalFilename) : undefined,
    fileSha256: value.fileSha256 ? String(value.fileSha256) : undefined,
    status: String(value.status || 'PREVIEW_READY'),
    conflictStrategy: value.conflictStrategy ? String(value.conflictStrategy) : undefined,
    totalRows: Number(value.totalRows ?? 0),
    validRows: Number(value.validRows ?? 0),
    warningRows: Number(value.warningRows ?? 0),
    errorRows: Number(value.errorRows ?? 0),
    createdAt: value.createdAt ? String(value.createdAt) : undefined,
    committedAt: value.committedAt ? String(value.committedAt) : undefined,
    createdBy: value.createdBy as string | number | undefined,
  }
}

function normalizeImportJobRow(raw: unknown): ImportJobRow {
  const value = asRecord(raw)
  const severity = String(value.severity || 'OK').toUpperCase()
  return {
    id: value.id as string | number | undefined,
    sourceSheet: value.sourceSheet ? String(value.sourceSheet) : undefined,
    sourceRow: Number(value.sourceRow ?? 0),
    operatorName: value.operatorName ? String(value.operatorName) : undefined,
    operatorAccountId: value.operatorAccountId as string | number | undefined,
    businessDate: value.businessDate ? String(value.businessDate) : undefined,
    severity: severity === 'OK' ? 'SUCCESS' : severity === 'WARN' ? 'WARNING' : severity,
    errorCode: value.errorCode ? String(value.errorCode) : undefined,
    errorMessage: value.errorMessage ? String(value.errorMessage) : undefined,
    action: value.action ? String(value.action) : undefined,
    targetDailyBalanceId: value.targetDailyBalanceId as string | number | undefined,
    normalized: value.normalized && typeof value.normalized === 'object' ? value.normalized as Record<string, unknown> : undefined,
  }
}

function normalizeImportJobDetail(raw: unknown): ImportJobDetail {
  const value = asRecord(raw)
  return {
    job: normalizeImportJob(value.job),
    rows: (Array.isArray(value.rows) ? value.rows : []).map(normalizeImportJobRow),
  }
}

function normalizeRedemptionTier(raw: unknown): RedemptionCampaignTier {
  const value = asRecord(raw)
  return {
    id: value.id as string | number | undefined,
    displayName: value.displayName ? String(value.displayName) : undefined,
    minDepositAmount: amount(value.minDepositAmount),
    bonusAmount: amount(value.bonusAmount),
    bonusMaxAmount: optionalAmount(value.bonusMaxAmount),
    sortOrder: Number(value.sortOrder ?? 0),
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
  }
}

function normalizeRedemptionCampaign(raw: unknown): RedemptionCampaign {
  const value = asRecord(raw)
  return {
    id: value.id as string | number | undefined,
    code: String(value.code || ''),
    name: String(value.name || ''),
    status: String(value.status || 'DRAFT') as RedemptionCampaign['status'],
    lookbackDays: Number(value.lookbackDays ?? 7),
    description: value.description ? String(value.description) : undefined,
    tiers: (Array.isArray(value.tiers) ? value.tiers : []).map(normalizeRedemptionTier),
    generatedCodeCount: Number(value.generatedCodeCount ?? 0),
    failedCodeCount: Number(value.failedCodeCount ?? 0),
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
    createdAt: value.createdAt ? String(value.createdAt) : undefined,
    updatedAt: value.updatedAt ? String(value.updatedAt) : undefined,
  }
}

function normalizeRedemptionIssue(raw: unknown): RedemptionCodeIssue {
  const value = asRecord(raw)
  return {
    id: value.id as string | number,
    campaignId: value.campaignId as string | number,
    campaignTierId: value.campaignTierId as string | number,
    tierName: value.tierName ? String(value.tierName) : undefined,
    minDepositAmount: amount(value.minDepositAmount),
    bonusAmount: amount(value.bonusAmount),
    bonusMaxAmount: optionalAmount(value.bonusMaxAmount),
    claimDate: String(value.claimDate || ''),
    depositWindowStart: String(value.depositWindowStart || ''),
    depositWindowEnd: String(value.depositWindowEnd || ''),
    redemptionCode: value.redemptionCode ? String(value.redemptionCode) : undefined,
    state: String(value.state || 'PENDING') as RedemptionCodeIssue['state'],
    remoteReferenceId: value.remoteReferenceId ? String(value.remoteReferenceId) : undefined,
    remoteError: value.remoteError ? String(value.remoteError) : undefined,
    generatedAt: value.generatedAt ? String(value.generatedAt) : undefined,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
    batchId: value.batchId as string | number | undefined,
    workflowStatus: value.workflowStatus ? String(value.workflowStatus) as RedemptionCodeIssue['workflowStatus'] : undefined,
    remoteConfigurationId: value.remoteConfigurationId ? String(value.remoteConfigurationId) : undefined,
    remoteGroupKey: value.remoteGroupKey ? String(value.remoteGroupKey) : undefined,
    remoteLabelIds: Array.isArray(value.remoteLabelIds) ? value.remoteLabelIds as Array<string | number> : [],
  }
}

function normalizeRedemptionBatch(raw: unknown): RedemptionCodeBatch {
  const value = asRecord(raw)
  const options = value.remoteOptions ? asRecord(value.remoteOptions) : undefined
  return {
    id: value.id as string | number,
    taskId: value.taskId as string | number | undefined,
    taskNumber: value.taskNumber ? String(value.taskNumber) : undefined,
    subtaskNumber: value.subtaskNumber ? String(value.subtaskNumber) : undefined,
    operatorUsername: value.operatorUsername ? String(value.operatorUsername) : undefined,
    campaignId: value.campaignId as string | number,
    claimDateFrom: String(value.claimDateFrom || ''),
    claimDateTo: String(value.claimDateTo || ''),
    validFromDayOffset: Number(value.validFromDayOffset ?? 0),
    validToDayOffset: Number(value.validToDayOffset ?? 0),
    lookbackDays: Number(value.lookbackDays ?? 7),
    redemptionType: String(value.redemptionType || 'SEVEN_DAY_DEPOSIT') as RedemptionCodeBatch['redemptionType'],
    expectedCodeCount: Number(value.expectedCodeCount ?? 0),
    plannedCodeCount: Number(value.plannedCodeCount ?? Number(value.expectedCodeCount ?? 0) * Number(options?.keyNumber ?? 1)),
    importedCodeCount: Number(value.importedCodeCount ?? Number(value.importedCount ?? 0) * Number(options?.keyNumber ?? 1)),
    status: String(value.status || 'CREATING') as RedemptionCodeBatch['status'],
    pendingCreationCount: Number(value.pendingCreationCount ?? 0),
    createdCount: Number(value.createdCount ?? 0),
    publishedCount: Number(value.publishedCount ?? 0),
    importedCount: Number(value.importedCount ?? 0),
    publishedAt: value.publishedAt ? String(value.publishedAt) : undefined,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
    createdAt: value.createdAt ? String(value.createdAt) : undefined,
    remoteConnectionId: value.remoteConnectionId as string | number | undefined,
    remoteConnectionName: value.remoteConnectionName ? String(value.remoteConnectionName) : undefined,
    remoteMarketCode: value.remoteMarketCode ? String(value.remoteMarketCode) : undefined,
    remoteMarketName: value.remoteMarketName ? String(value.remoteMarketName) : undefined,
    exportGroupKey: value.exportGroupKey ? String(value.exportGroupKey) : undefined,
    remotePublishTaskId: value.remotePublishTaskId ? String(value.remotePublishTaskId) : undefined,
    remotePublishError: value.remotePublishError ? String(value.remotePublishError) : undefined,
    remotePublishMode: value.remotePublishMode as RedemptionCodeBatch['remotePublishMode'],
    remoteScheduledPublishAt: value.remoteScheduledPublishAt ? String(value.remoteScheduledPublishAt) : undefined,
    remotePublishNote: value.remotePublishNote ? String(value.remotePublishNote) : undefined,
    remotePublishCancelledAt: value.remotePublishCancelledAt ? String(value.remotePublishCancelledAt) : undefined,
    remoteOptions: options ? {
      publishEnvironment: String(options.publishEnvironment || 'test') as RedemptionRemoteCreationOptions['publishEnvironment'],
      flowTimes: Number(options.flowTimes ?? 5), creationIntervalSeconds: Number(options.creationIntervalSeconds ?? 5), keyNumber: Number(options.keyNumber ?? 1),
      activityRecharge: options.activityRecharge == null ? undefined : Number(options.activityRecharge),
      activityRechargeCount: options.activityRechargeCount == null ? undefined : Number(options.activityRechargeCount),
      activityId: options.activityId == null ? undefined : Number(options.activityId),
      singleUserLimit: Number(options.singleUserLimit ?? 1), singleKeyLimit: Number(options.singleKeyLimit ?? 2000),
      requireBindBankCard: Boolean(options.requireBindBankCard), requireBindPhone: options.requireBindPhone !== false,
      checkUuid: options.checkUuid !== false, uuidRewardLimit: Number(options.uuidRewardLimit ?? 1),
      checkLoginIp: options.checkLoginIp !== false, loginIpRewardLimit: Number(options.loginIpRewardLimit ?? 1),
      checkRegisterIp: options.checkRegisterIp !== false, registerIpRewardLimit: Number(options.registerIpRewardLimit ?? 1),
    } : undefined,
  }
}

function normalizeRemoteConnection(raw: unknown): RedemptionRemoteConnection {
  const value = asRecord(raw)
  return {
    id: value.id as string | number | undefined,
    username: String(value.username || ''), baseUrl: String(value.baseUrl || ''),
    marketId: value.marketId as string | number | undefined, marketCode: value.marketCode ? String(value.marketCode) : undefined,
    marketName: value.marketName ? String(value.marketName) : undefined, marketEnabled: value.marketEnabled !== false,
    hasPassword: Boolean(value.hasPassword), hasTotpSecret: Boolean(value.hasTotpSecret), hasActiveSession: Boolean(value.hasActiveSession),
    sessionExpiresAt: value.sessionExpiresAt ? String(value.sessionExpiresAt) : undefined,
    lastLoggedInAt: value.lastLoggedInAt ? String(value.lastLoggedInAt) : undefined,
    enabled: value.enabled !== false, lastCheckedAt: value.lastCheckedAt ? String(value.lastCheckedAt) : undefined,
    lastError: value.lastError ? String(value.lastError) : undefined, rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
    createdAt: value.createdAt ? String(value.createdAt) : undefined, updatedAt: value.updatedAt ? String(value.updatedAt) : undefined,
  }
}

function normalizeRemoteMarket(raw: unknown): RedemptionRemoteMarket {
  const value = asRecord(raw)
  return {
    id: value.id as string | number | undefined, code: String(value.code || ''), name: String(value.name || ''),
    baseUrl: String(value.baseUrl || ''), enabled: value.enabled !== false,
    rowVersion: typeof value.rowVersion === 'number' ? value.rowVersion : undefined,
    createdAt: value.createdAt ? String(value.createdAt) : undefined, updatedAt: value.updatedAt ? String(value.updatedAt) : undefined,
  }
}

function normalizeRewardTierPreset(raw: unknown): RedemptionRewardTierPreset {
  const value = asRecord(raw)
  return {
    exists: Boolean(value.exists),
    stale: Boolean(value.stale),
    tiers: (Array.isArray(value.tiers) ? value.tiers : []).map((rawTier) => {
      const tier = asRecord(rawTier)
      const labelIds = Array.isArray(tier.labelIds) ? tier.labelIds.map((id) => id as string | number) : []
      return {
        userType: tier.userType === 'ALL_USERS' || (!tier.userType && !labelIds.length) ? 'ALL_USERS' : 'LABEL_USERS',
        labelIds,
        displayName: String(tier.displayName || ''),
        minDepositAmount: amount(tier.minDepositAmount),
        bonusAmount: amount(tier.bonusAmount),
        bonusMaxAmount: amount(tier.bonusMaxAmount),
      }
    }),
    tagSnapshot: (Array.isArray(value.tagSnapshot) ? value.tagSnapshot : []).map((rawTag) => {
      const tag = asRecord(rawTag)
      return { id: tag.id as string | number, name: String(tag.name || '') }
    }),
    savedAt: value.savedAt ? String(value.savedAt) : undefined,
    lastSyncedAt: value.lastSyncedAt ? String(value.lastSyncedAt) : undefined,
  }
}

function remoteMarketRequest(market: Partial<RedemptionRemoteMarket>, patch = false) {
  const shared = { name: market.name, baseUrl: market.baseUrl, enabled: market.enabled }
  return patch ? { ...shared, rowVersion: market.rowVersion } : { code: market.code, ...shared }
}

function remoteConnectionRequest(connection: Partial<RedemptionRemoteConnection>, patch = false) {
  const shared = {
    username: connection.username, marketId: connection.marketId, password: connection.password, totpSecret: connection.totpSecret,
    enabled: connection.enabled,
  }
  return patch ? { ...shared, rowVersion: connection.rowVersion } : shared
}

function normalizeRedemptionBatchDetail(raw: unknown): RedemptionBatchDetail {
  const value = asRecord(raw)
  return { batch: normalizeRedemptionBatch(value.batch), issues: (Array.isArray(value.issues) ? value.issues : []).map(normalizeRedemptionIssue) }
}

function redemptionCampaignRequest(campaign: Partial<RedemptionCampaign>, patch = false) {
  const tiers = campaign.tiers?.map((tier, index) => ({
    displayName: tier.displayName,
    minDepositAmount: tier.minDepositAmount,
    bonusAmount: tier.bonusAmount,
    bonusMaxAmount: tier.bonusMaxAmount,
    sortOrder: tier.sortOrder ?? index + 1,
  }))
  const shared = { name: campaign.name, lookbackDays: campaign.lookbackDays, description: campaign.description, tiers }
  return patch ? { ...shared, status: campaign.status, rowVersion: campaign.rowVersion } : { code: campaign.code, ...shared }
}

function operatorRequest(operator: Partial<Operator>, patch = false) {
  const request = {
    name: operator.name,
    operatorType: operator.type,
    contactName: operator.contactName,
    contactValue: operator.contactValue,
    remark: operator.remark,
    rowVersion: operator.rowVersion,
  }
  // Company codes are generated by the server.  Keep operatorType only for
  // legacy patch compatibility; new companies are always delivery companies.
  return patch ? request : { name: operator.name, contactName: operator.contactName, contactValue: operator.contactValue, remark: operator.remark }
}

function accountRequest(account: Partial<OperatorAccount>, patch = false) {
  const shared = {
    name: account.name, network: account.network, walletAddress: account.walletAddress, startDate: account.startDate,
    defaultExchangeLossRate: account.defaultExchangeLossRate, defaultExchangeLossBasis: account.defaultExchangeLossBasis,
    defaultServiceFeeRate: account.defaultServiceFeeRate, defaultServiceFeeBasis: account.defaultServiceFeeBasis,
    calculationScale: account.calculationScale, rowVersion: account.rowVersion,
  }
  // A delivery line is created from only its name and currency.  The legacy
  // account code and calculation configuration remain server-side defaults.
  return patch ? shared : { name: account.name, asset: account.asset }
}

function createUserRequest(user: CreateUserInput) {
  return {
    username: user.username,
    password: user.password,
    displayName: user.displayName,
    enabled: user.enabled,
    roleCodes: user.roleCodes,
    allOperators: user.allOperators,
    operatorIds: user.operatorIds,
  }
}

function updateUserRequest(user: UpdateUserInput) {
  return {
    displayName: user.displayName,
    enabled: user.enabled,
    rowVersion: user.rowVersion,
  }
}

export const api = {
  auth: {
    me: async () => normalizeUser(await request<unknown>(() => apiClient.get('/auth/me'))),
    login: async (username: string, password: string) => {
      const response = await request<{ user: unknown }>(() => apiClient.post('/auth/login', { username, password }))
      return normalizeUser(response.user)
    },
    csrf: async () => {
      csrfReady = false
      await ensureCsrf()
    },
    logout: () => request<void>(() => apiClient.post('/auth/logout')),
  },
  operators: {
    list: async () => (await request<unknown>(() => apiClient.get('/operators', { params: { includeInactive: true } })) as unknown[]).map(normalizeOperator),
    create: async (operator: Partial<Operator>) => normalizeOperator(await request<unknown>(() => apiClient.post('/operators', operatorRequest(operator)))),
    update: async (id: string | number, operator: Partial<Operator>) => normalizeOperator(await request<unknown>(() => apiClient.patch(`/operators/${id}`, operatorRequest(operator, true)))),
    disable: async (id: string | number, rowVersion?: number, reason?: string) => normalizeOperator(await request<unknown>(() => apiClient.post(`/operators/${id}/disable`, { rowVersion, reason }))),
    remove: async (id: string | number, rowVersion?: number, purgeHistory = false) => request<void>(() => apiClient.delete(`/operators/${id}`, { data: { rowVersion, purgeHistory } })),
    accounts: async (operatorId: string | number) => (await request<unknown>(() => apiClient.get(`/operators/${operatorId}/accounts`)) as unknown[]).map(normalizeAccount),
    createAccount: async (operatorId: string | number, account: Partial<OperatorAccount>) => normalizeAccount(await request<unknown>(() => apiClient.post(`/operators/${operatorId}/accounts`, accountRequest(account)))),
    updateAccount: async (id: string | number, account: Partial<OperatorAccount>) => normalizeAccount(await request<unknown>(() => apiClient.patch(`/operator-accounts/${id}`, accountRequest(account, true)))),
  },
  balances: {
    list: async (accountId: string | number, month: string) => {
      const response = await request<{ records?: unknown[] }>(() => apiClient.get('/daily-balances', { params: { accountId, month } }))
      return (response.records || []).map(normalizeBalance)
    },
    calculate: async (record: Partial<DailyBalance>) => normalizeCalculation(await request<unknown>(() => apiClient.post('/daily-balances/calculation-preview', balanceRequest(record)))),
    save: async (record: Partial<DailyBalance>) => normalizeBalance(record.id
      ? await request<unknown>(() => apiClient.put(`/daily-balances/${record.id}`, balanceRequest(record)))
      : await request<unknown>(() => apiClient.post('/daily-balances', balanceRequest(record)))),
    // 服务端会按请求顺序处理，确保“前一天修改 + 后一天新增”的自动承接使用同一条连续链路。
    batch: async (records: Partial<DailyBalance>[]) => (await request<unknown[]>(() => apiClient.post('/daily-balances/batch', { records: records.map(balanceRequest) }))).map(normalizeBalance),
    confirm: async (id: string | number, rowVersion?: number) => normalizeBalance(await request<unknown>(() => apiClient.post(`/daily-balances/${id}/confirm`, { rowVersion }))),
    reopen: async (id: string | number, rowVersion: number | undefined, reason: string) => normalizeBalance(await request<unknown>(() => apiClient.post(`/daily-balances/${id}/reopen`, { rowVersion, reason }))),
  },
  periodLocks: {
    list: async (month: string, operatorIds?: Array<string | number>) => {
      const locks = await request<unknown[]>(() => apiClient.get('/period-locks', { params: paramsWithoutEmpty({ month, operatorIds: numericIds(operatorIds) }) }))
      return locks.map(normalizePeriodLock)
    },
    validate: async (month: string, operatorIds?: Array<string | number>, accountIds?: Array<string | number>) => normalizePeriodLockValidation(await request<unknown>(() => apiClient.post('/period-locks/validate', periodLockRequest(month, operatorIds, accountIds)))),
    lock: async (month: string, operatorIds?: Array<string | number>, accountIds?: Array<string | number>) => (await request<unknown[]>(() => apiClient.post('/period-locks/lock', periodLockRequest(month, operatorIds, accountIds)))).map(normalizePeriodLock),
    unlock: async (month: string, operatorIds: Array<string | number> | undefined, accountIds: Array<string | number> | undefined, reason: string) => (await request<unknown[]>(() => apiClient.post('/period-locks/unlock', { ...periodLockRequest(month, operatorIds, accountIds), reason }))).map(normalizePeriodLock),
  },
  imports: {
    previewPaste: async (text: string, accountId?: string | number, conflictStrategy?: string) => normalizeImport(await request<unknown>(() => apiClient.post('/imports/paste/preview', { text, accountId, conflictStrategy }))),
    previewExcel: (file: File, accountId?: string | number, conflictStrategy?: string, businessYear?: string | number) => {
      const form = new FormData()
      form.append('file', file)
      if (accountId !== undefined && accountId !== null && accountId !== '') form.append('accountId', String(accountId))
      if (conflictStrategy) form.append('conflictStrategy', conflictStrategy)
      if (businessYear !== undefined && businessYear !== null && businessYear !== '') form.append('businessYear', String(businessYear))
      return request<unknown>(() => apiClient.post('/imports/excel/preview', form)).then(normalizeImport)
    },
    commit: (jobId: string, conflictStrategy = 'SKIP_EXISTING') => request<void>(() => apiClient.post(`/imports/${jobId}/commit`, { conflictStrategy })),
    list: async () => (await request<unknown>(() => apiClient.get('/imports')) as unknown[]).map(normalizeImportJob),
    get: async (jobId: string | number) => normalizeImportJobDetail(await request<unknown>(() => apiClient.get(`/imports/${jobId}`))),
    rows: async (jobId: string | number) => (await request<unknown>(() => apiClient.get(`/imports/${jobId}/rows`)) as unknown[]).map(normalizeImportJobRow),
    downloadTemplate: () => requestDownload(() => apiClient.get<Blob>('/imports/template', { responseType: 'blob' }), 'import-template.xlsx'),
    downloadSource: (jobId: string | number) => requestDownload(() => apiClient.get<Blob>(`/imports/${jobId}/source`, { responseType: 'blob' }), `import-${jobId}-source.xlsx`),
    downloadErrorReport: (jobId: string | number) => requestDownload(() => apiClient.get<Blob>(`/imports/${jobId}/error-report`, { responseType: 'blob' }), `import-${jobId}-errors.xlsx`),
  },
  roles: {
    list: async () => (await request<unknown>(() => apiClient.get('/roles')) as unknown[]).map(normalizeRole),
  },
  users: {
    list: async () => (await request<unknown>(() => apiClient.get('/users')) as unknown[]).map(normalizeManagedUser),
    create: async (user: CreateUserInput) => normalizeManagedUser(await request<unknown>(() => apiClient.post('/users', createUserRequest(user)))),
    update: async (id: string | number, user: UpdateUserInput) => normalizeManagedUser(await request<unknown>(() => apiClient.patch(`/users/${id}`, updateUserRequest(user)))),
    assignRoles: async (id: string | number, roleCodes: string[]) => normalizeManagedUser(await request<unknown>(() => apiClient.put(`/users/${id}/roles`, { roleCodes }))),
    assignOperatorScopes: async (id: string | number, allOperators: boolean, operatorIds: Array<string | number>) => normalizeManagedUser(await request<unknown>(() => apiClient.put(`/users/${id}/operator-scopes`, { allOperators, operatorIds }))),
  },
  audit: {
    list: async (params: AuditLogQuery = {}) => (await request<unknown>(() => apiClient.get('/audit-logs', { params: paramsWithoutEmpty(params) })) as unknown[]).map(normalizeAuditLog),
  },
  reports: {
    daily: async (params: Record<string, unknown>) => {
      const response = await request<{ rows?: unknown[] }>(() => apiClient.get('/reports/daily', { params: paramsWithoutEmpty(params) }))
      return (response.rows || []).map((row) => normalizeReport(row, 'daily'))
    },
    monthly: async (params: Record<string, unknown>) => {
      const response = await request<{ rows?: unknown[] }>(() => apiClient.get('/reports/monthly', { params: paramsWithoutEmpty(params) }))
      return (response.rows || []).map((row) => normalizeReport(row, 'monthly'))
    },
    exportDaily: (params: Record<string, unknown>) => requestDownload(() => apiClient.get<Blob>('/reports/daily/export', { params: paramsWithoutEmpty(params), responseType: 'blob' }), 'daily-report.xlsx'),
    exportMonthly: (params: Record<string, unknown>) => requestDownload(() => apiClient.get<Blob>('/reports/monthly/export', { params: paramsWithoutEmpty(params), responseType: 'blob' }), 'monthly-report.xlsx'),
  },
  redemption: {
    list: async () => (await request<unknown>(() => apiClient.get('/redemption-campaigns')) as unknown[]).map(normalizeRedemptionCampaign),
    get: async (id: string | number) => normalizeRedemptionCampaign(await request<unknown>(() => apiClient.get(`/redemption-campaigns/${id}`))),
    create: async (campaign: Partial<RedemptionCampaign>) => normalizeRedemptionCampaign(await request<unknown>(() => apiClient.post('/redemption-campaigns', redemptionCampaignRequest(campaign)))),
    createGroup: async (group: RedemptionCodeGroupInput) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post('/redemption-campaigns/groups', {
      ...group,
      tiers: group.tiers.map((tier, index) => ({
        displayName: tier.displayName,
        minDepositAmount: tier.minDepositAmount,
        bonusAmount: tier.bonusAmount,
        bonusMaxAmount: tier.bonusMaxAmount,
        sortOrder: tier.sortOrder ?? index + 1,
      })),
    }))),
    update: async (id: string | number, campaign: Partial<RedemptionCampaign>) => normalizeRedemptionCampaign(await request<unknown>(() => apiClient.patch(`/redemption-campaigns/${id}`, redemptionCampaignRequest(campaign, true)))),
    issues: async (campaignId: string | number, claimDateFrom: string, claimDateTo: string) => (await request<unknown>(() => apiClient.get('/redemption-campaigns/codes', { params: { campaignId, claimDateFrom, claimDateTo } })) as unknown[]).map(normalizeRedemptionIssue),
    exportCodes: (campaignId: string | number, claimDateFrom: string, claimDateTo: string) => requestDownload(() => apiClient.get<Blob>('/redemption-campaigns/codes/export', { params: { campaignId, claimDateFrom, claimDateTo }, responseType: 'blob' }), 'redemption-codes.xlsx'),
    batches: async (campaignId: string | number) => (await request<unknown>(() => apiClient.get('/redemption-campaigns/batches', { params: { campaignId } })) as unknown[]).map(normalizeRedemptionBatch),
    batch: async (batchId: string | number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.get(`/redemption-campaigns/batches/${batchId}`))),
    createManualBatch: async (campaignId: string | number, claimDateFrom: string, claimDateTo: string, remoteConnectionId?: string | number, tierLabelIds?: Record<string, Array<string | number>>, remoteOptions?: RedemptionRemoteCreationOptions) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post('/redemption-campaigns/batches', { campaignId, claimDateFrom, claimDateTo, remoteConnectionId, tierLabelIds, remoteOptions }))),
    recordRemoteConfiguration: async (issueId: string | number, remoteConfigurationId: string, rowVersion?: number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/code-tasks/${issueId}/remote-configuration`, { remoteConfigurationId, rowVersion }))),
    createRemoteConfiguration: async (issueId: string | number, retryFailed = false) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/code-tasks/${issueId}/remote-create`, undefined, { params: { retryFailed } }))),
    downloadRemoteCode: async (issueId: string | number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/code-tasks/${issueId}/remote-download`))),
    publishBatch: async (batchId: string | number, rowVersion?: number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/batches/${batchId}/publish`, { rowVersion }))),
    publishRemoteBatch: async (batchId: string | number, rowVersion: number | undefined, mode: 'IMMEDIATE' | 'SCHEDULED' = 'IMMEDIATE', scheduledTime?: string, fallbackToScheduled = true) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/batches/${batchId}/remote-publish`, { rowVersion, mode, scheduledTime, fallbackToScheduled }))),
    cancelScheduledPublish: async (batchId: string | number, rowVersion?: number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/batches/${batchId}/remote-publish/cancel`, { rowVersion }))),
    recoverRemotePublish: async (batchId: string | number, rowVersion?: number) => normalizeRedemptionBatchDetail(await request<unknown>(() => apiClient.post(`/redemption-campaigns/batches/${batchId}/remote-publish/recover`, { rowVersion }))),
    importDownloadedCodes: async (batchId: string | number, rows: Array<{ remoteConfigurationId: string; redemptionCode: string }>) => {
      const value = asRecord(await request<unknown>(() => apiClient.post(`/redemption-campaigns/batches/${batchId}/codes/import`, { rows })))
      return { importedCount: Number(value.importedCount ?? 0), batch: normalizeRedemptionBatch(value.batch), issues: (Array.isArray(value.issues) ? value.issues : []).map(normalizeRedemptionIssue) }
    },
    exportBatch: (batchId: string | number) => requestDownload(() => apiClient.get<Blob>(`/redemption-campaigns/batches/${batchId}/export`, { responseType: 'blob' }), 'redemption-codes-batch.xlsx'),
    exportMultiMarketGroup: (exportGroupKey: string) => requestDownload(() => apiClient.get<Blob>(`/redemption-campaigns/batches/export-groups/${encodeURIComponent(exportGroupKey)}/export`, { responseType: 'blob' }), 'redemption-codes-multi-market.xlsx'),
  },
  redemptionRemoteConnections: {
    list: async () => (await request<unknown>(() => apiClient.get('/redemption-remote-connections')) as unknown[]).map(normalizeRemoteConnection),
    create: async (connection: RedemptionRemoteConnection) => normalizeRemoteConnection(await request<unknown>(() => apiClient.post('/redemption-remote-connections', remoteConnectionRequest(connection)))),
    update: async (id: string | number, connection: Partial<RedemptionRemoteConnection>) => normalizeRemoteConnection(await request<unknown>(() => apiClient.patch(`/redemption-remote-connections/${id}`, remoteConnectionRequest(connection, true)))),
    remove: async (id: string | number, rowVersion?: number) => request<void>(() => apiClient.delete(`/redemption-remote-connections/${id}`, { data: { rowVersion } })),
    check: async (id: string | number) => asRecord(await request<unknown>(() => apiClient.post(`/redemption-remote-connections/${id}/check`))),
    tags: async (id: string | number) => (await request<unknown>(() => apiClient.get(`/redemption-remote-connections/${id}/tags`)) as unknown[]).map((raw): RedemptionRemoteTag => {
      const value = asRecord(raw); return { id: value.id as string | number, name: String(value.name || '') }
    }),
    syncTags: async (id: string | number) => {
      const value = asRecord(await request<unknown>(() => apiClient.post(`/redemption-remote-connections/${id}/tags/sync`)))
      return {
        tags: (Array.isArray(value.tags) ? value.tags : []).map((raw): RedemptionRemoteTag => {
          const tag = asRecord(raw); return { id: tag.id as string | number, name: String(tag.name || '') }
        }),
        presetStale: Boolean(value.presetStale),
        syncedAt: value.syncedAt ? String(value.syncedAt) : undefined,
      }
    },
    rewardTierPreset: async (id: string | number, redemptionType = 'SEVEN_DAY_DEPOSIT') => {
      const value = asRecord(await request<unknown>(() => apiClient.get(`/redemption-remote-connections/${id}/reward-tier-preset`, { params: { redemptionType } })))
      return normalizeRewardTierPreset(value)
    },
    saveRewardTierPreset: async (id: string | number, preset: Pick<RedemptionRewardTierPreset, 'tiers' | 'tagSnapshot'>, redemptionType = 'SEVEN_DAY_DEPOSIT') => {
      const value = asRecord(await request<unknown>(() => apiClient.put(`/redemption-remote-connections/${id}/reward-tier-preset`, preset, { params: { redemptionType } })))
      return normalizeRewardTierPreset(value)
    },
  },
  redemptionRemoteMarkets: {
    list: async () => (await request<unknown>(() => apiClient.get('/redemption-remote-markets')) as unknown[]).map(normalizeRemoteMarket),
    create: async (market: RedemptionRemoteMarket) => normalizeRemoteMarket(await request<unknown>(() => apiClient.post('/redemption-remote-markets', remoteMarketRequest(market)))),
    update: async (id: string | number, market: Partial<RedemptionRemoteMarket>) => normalizeRemoteMarket(await request<unknown>(() => apiClient.patch(`/redemption-remote-markets/${id}`, remoteMarketRequest(market, true)))),
  },
}

export function isServiceUnavailable(error: unknown) {
  return error instanceof ApiError && (!error.status || error.status >= 500)
}
