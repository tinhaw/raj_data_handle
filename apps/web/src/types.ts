export interface AuthUser {
  id: number
  username: string
  displayName: string
  role: 'admin' | 'user'
  expiresAt?: string | null
}

export interface Captcha {
  captchaId: string
  image: string
  expiresAt: string
}

export interface UserRecord {
  id: number
  username: string
  displayName: string
  role: 'admin' | 'user'
  isActive: boolean
  lastLoginAt: string | null
  createdAt: string
  updatedAt: string
}

export interface ErpRoleDefinition {
  code: string
  label: string
  permissions: string[]
}

export interface ErpUserAccess {
  userId: number
  roleGrants: string[]
  allOperators: boolean
  operatorIds: string[]
  effectivePermissions: string[]
}

export type UserLogEventType = 'login' | 'access'

export interface UserLogRecord {
  id: string
  userId: number
  username: string | null
  displayName: string | null
  eventType: UserLogEventType
  path: string | null
  occurredAt: string
}

export interface UserLogQueryResponse {
  items: UserLogRecord[]
  total: number
  page: number
  pageSize: number
}

export interface SourceConfig {
  sourceId: string
  displayName: string
  displayOrder: number
  baseUrl: string | null
  enabled: boolean
  businessTimezone: string
  currency: string
  configVersion: number
  credentialConfigured: boolean
  loginUsername: string | null
  credentialUpdatedAt: string | null
  scoringApiBaseUrl: string | null
  scoringApiKeyConfigured: boolean
  scoringApiKeyUpdatedAt: string | null
  scoringApiLastTestedAt: string | null
  scoringApiLastTestStatus: string | null
  initialReviewV1ApiBaseUrl: string | null
  initialReviewV1ApiKeyConfigured: boolean
  initialReviewV1ApiKeyUpdatedAt: string | null
  lastTestedAt: string | null
  lastTestStatus: string | null
  createdAt: string
  updatedAt: string
}

export interface RemoteAccountCapabilityDefinition {
  code: string
  label: string
}

export interface RemoteAccount {
  id: string
  sourceId: string
  sourceDisplayName: string
  sourceBaseUrl: string | null
  sourceEnabled: boolean
  loginUsername: string | null
  displayName: string
  enabled: boolean
  isDefault: boolean
  credentialMode: 'MANAGED' | 'LEGACY_SOURCE'
  credentialConfigured: boolean
  credentialUpdatedAt: string | null
  lastTestedAt: string | null
  lastTestStatus: string | null
  capabilities: Record<string, boolean>
  createdAt: string
  updatedAt: string
}

export interface RemoteTag {
  id: number
  name: string
}

export interface RemoteTagSnapshot {
  exists: boolean
  tags: RemoteTag[]
  source: string | null
  stale: boolean
  syncedAt: string | null
  updatedAt: string | null
  rowVersion: number | null
}

export interface RewardTierPresetTier {
  labelIds: number[]
  displayName: string
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount: string
}

export interface RewardTierPreset {
  exists: boolean
  stale: boolean
  tiers: RewardTierPresetTier[]
  tagSnapshot: RemoteTag[]
  savedAt: string | null
  rowVersion: number | null
}

export interface TotpAccount {
  id: string
  displayName: string
  accountName: string
  displayOrder: number
  enabled: boolean
  secretUpdatedAt: string
  createdAt: string
  updatedAt: string
}

export type TotpCodeStatus = 'available' | 'disabled' | 'invalid'

export interface TotpCodeItem {
  accountId: string
  displayName: string
  accountName: string
  enabled: boolean
  status: TotpCodeStatus
  code: string | null
  message: string | null
}

export interface TotpCodeList {
  generatedAt: string
  expiresAt: string
  periodSeconds: number
  items: TotpCodeItem[]
}

export type ErpOperatorType = 'COMPANY' | 'STUDIO' | 'INDIVIDUAL'
export type ErpRecordStatus = 'ACTIVE' | 'INACTIVE'
export type ErpAsset = 'USDT' | 'USDC'

export interface ErpOperator {
  id: string
  code: string
  name: string
  operatorType: ErpOperatorType
  status: ErpRecordStatus
  contactName: string | null
  contactValue: string | null
  remark: string | null
  rowVersion: number
  createdAt: string
  updatedAt: string
}

export interface ErpDeliveryLine {
  id: string
  operatorId: string
  operatorName: string
  displayName: string
  code: string
  name: string
  asset: ErpAsset
  network: string | null
  walletAddress: string | null
  startDate: string | null
  defaultExchangeLossRate: string
  defaultExchangeLossBasis: string
  defaultServiceFeeRate: string
  defaultServiceFeeBasis: string
  calculationScale: number
  status: ErpRecordStatus
  rowVersion: number
  createdAt: string
  updatedAt: string
}

export type ErpDailyBalanceStatus = 'DRAFT' | 'CONFIRMED'
export type ErpBalanceMode = 'AUTO' | 'MANUAL'
export type ErpFraudDeductionSource = 'TRANSFER' | 'BALANCE'

export interface ErpDailyBalance {
  id: string
  operatorLineId: string
  businessDate: string
  suggestedOpeningBalance: string | null
  openingBalance: string
  openingMode: ErpBalanceMode
  openingOverrideReason: string | null
  transferAmount: string
  fraudLossAmount: string
  fraudDeductionSource: ErpFraudDeductionSource | null
  effectiveTransferAmount: string
  spendAmount: string
  exchangeLossRate: string
  exchangeLossBasis: string
  exchangeLossAutoAmount: string
  exchangeLossAmount: string
  exchangeLossMode: ErpBalanceMode
  exchangeLossOverrideReason: string | null
  serviceFeeRate: string
  serviceFeeBasis: string
  serviceFeeAutoAmount: string
  serviceFeeAmount: string
  serviceFeeMode: ErpBalanceMode
  serviceFeeOverrideReason: string | null
  refluxAmount: string
  refundAmount: string
  otherDeductionAmount: string
  otherReason: string | null
  closingBalance: string
  calculationScale: number
  status: ErpDailyBalanceStatus
  sourceType: 'MANUAL' | 'PASTE' | 'IMPORT'
  remark: string | null
  rowVersion: number
  createdAt: string
  updatedAt: string
  confirmedAt: string | null
}

export interface ErpDailyBalanceList {
  operatorLineId: string
  month: string
  records: ErpDailyBalance[]
}

export interface ErpBalanceImpactRecord {
  id: string
  businessDate: string
  previousOpeningBalance: string
  recalculatedOpeningBalance: string
  previousClosingBalance: string
  recalculatedClosingBalance: string
}

export interface ErpBalanceImpactPreview {
  current: {
    suggestedOpeningBalance: string | null
    openingBalance: string
    effectiveTransferAmount: string
    exchangeLossAutoAmount: string
    exchangeLossAmount: string
    serviceFeeAutoAmount: string
    serviceFeeAmount: string
    fraudFromTransfer: string
    fraudFromBalance: string
    closingBalance: string
  }
  impactedRecords: ErpBalanceImpactRecord[]
  blockingReasons: string[]
}

export type ErpPeriodLockStatus = 'LOCKED' | 'UNLOCKED'

export interface ErpPeriodLock {
  id: string
  operatorLineId: string
  monthStart: string
  status: ErpPeriodLockStatus
  lockedBy: number | null
  lockedAt: string | null
  unlockReason: string | null
  unlockedBy: number | null
  unlockedAt: string | null
  rowVersion: number
  createdAt: string
  updatedAt: string
}

export interface ErpPeriodLockIssue {
  operatorLineId: string
  businessDate: string | null
  code: string
  message: string
}

export interface ErpPeriodLockValidation {
  month: string
  canLock: boolean
  issues: ErpPeriodLockIssue[]
}

export interface ErpDashboardMetric {
  openingBalance: string
  transferAmount: string
  spendAmount: string
  closingBalance: string
  activeOperatorCount: number
  activeLineCount: number
}

export interface ErpDashboardTrendPoint {
  businessDate: string
  closingBalance: string
}

export interface ErpDashboardHealthItem {
  code: string
  severity: 'INFO' | 'WARNING' | 'DANGER'
  title: string
  description: string
  targetPath: string
  count: number
}

export interface ErpDashboardRecentBalance {
  id: string
  businessDate: string
  operatorName: string
  operatorLineName: string
  asset: string
  openingBalance: string
  transferAmount: string
  spendAmount: string
  closingBalance: string
  status: 'DRAFT' | 'CONFIRMED'
}

export interface ErpDashboard {
  businessDate: string
  metric: ErpDashboardMetric
  trend: ErpDashboardTrendPoint[]
  healthItems: ErpDashboardHealthItem[]
  recentBalances: ErpDashboardRecentBalance[]
}

export interface ErpAuditLogEntry {
  id: string
  action: string
  actorUserId: number | null
  actorDisplayName: string | null
  targetType: string | null
  targetId: string | null
  requestId: string | null
  result: string
  metadata: Record<string, unknown>
  createdAt: string
}

export interface ErpAuditLogList {
  items: ErpAuditLogEntry[]
  total: number
  page: number
  pageSize: number
}

export interface ErpReportRow {
  period: string
  asset: string
  openingBalance: string
  transferAmount: string
  fraudFromTransfer: string
  effectiveTransferAmount: string
  spendAmount: string
  exchangeLossAmount: string
  serviceFeeAmount: string
  refluxAmount: string
  refundAmount: string
  otherDeductionAmount: string
  fraudFromBalance: string
  closingBalance: string
  recordCount: number
  warnings: string[]
}

export interface ErpReportResponse {
  reportType: 'DAILY' | 'MONTHLY'
  nominalU: boolean
  rows: ErpReportRow[]
}

export type ErpImportConflictStrategy = 'SKIP_EXISTING' | 'UPDATE_DRAFT' | 'REJECT_ON_CONFLICT'

export interface ErpImportJob {
  id: string
  sourceType: string
  originalFilename: string | null
  sourceAvailable: boolean
  errorReportAvailable: boolean
  sourceSizeBytes: number | null
  status: 'PREVIEW_READY' | 'SUCCEEDED'
  conflictStrategy: ErpImportConflictStrategy
  totalRows: number
  validRows: number
  warningRows: number
  errorRows: number
  createdAt: string
  committedAt: string | null
}

export interface ErpImportRow {
  id: string
  sourceSheet: string | null
  sourceRow: number | null
  sourceJson: Record<string, unknown>
  operatorLineId: string | null
  businessDate: string | null
  severity: 'OK' | 'WARNING' | 'ERROR'
  errorCode: string | null
  errorMessage: string | null
  action: string | null
  targetDailyBalanceId: string | null
}

export interface ErpImportPreview {
  job: ErpImportJob
  rows: ErpImportRow[]
}

export interface ErpRedemptionTier {
  id: string
  displayName: string | null
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount: string
  sortOrder: number
  rowVersion: number
}

export interface ErpRedemptionCampaign {
  id: string
  code: string
  name: string
  status: 'DRAFT' | 'ACTIVE' | 'ARCHIVED'
  lookbackDays: number
  description: string | null
  tiers: ErpRedemptionTier[]
  plannedCodeCount: number
  importedCodeCount: number
  rowVersion: number
  createdAt: string
  updatedAt: string
}

export interface ErpRedemptionBatch {
  id: string
  campaignId: string
  taskId: string | null
  sourceId: string | null
  remoteAccountId: string | null
  executionOrder: number
  claimDateFrom: string
  claimDateTo: string
  lookbackDays: number
  expectedCodeCount: number
  importedCodeCount: number
  status: 'PLANNED' | 'READY_LOCAL' | 'PUBLISHED_LOCAL'
  publishedAt: string | null
  rowVersion: number
  createdAt: string
}

export interface ErpRedemptionIssue {
  id: string
  campaignId: string
  campaignTierId: string
  batchId: string
  claimDate: string
  depositWindowStart: string
  depositWindowEnd: string
  tierName: string | null
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount: string
  redemptionCode: string | null
  localReference: string | null
  workflowStatus: 'PENDING_LOCAL_CODE' | 'CODE_IMPORTED' | 'PUBLISHED_LOCAL'
  state: 'PENDING' | 'GENERATED'
  importedAt: string | null
  remoteWorkflowStatus:
    | 'NOT_STARTED'
    | 'RESERVED'
    | 'CREATING'
    | 'CREATED'
    | 'PUBLISHED'
    | 'DOWNLOADING'
    | 'DOWNLOADED'
    | 'FAILED'
  remoteConfigurationId: string | null
  remoteGroupKey: string | null
  remoteLabelIds: number[]
  remoteDescription: string | null
  remoteErrorCode: string | null
  remoteErrorMessage: string | null
  remoteCreatedAt: string | null
  remoteDownloadedAt: string | null
  rowVersion: number
}

export interface ErpRedemptionBatchDetail {
  batch: ErpRedemptionBatch
  issues: ErpRedemptionIssue[]
}

export interface ErpRedemptionTaskSubtask {
  batchId: string
  executionOrder: number
  sourceId: string
  sourceDisplayName: string
  remoteAccountId: string
  remoteAccountName: string
  expectedCodeCount: number
  importedCodeCount: number
  status: 'PLANNED' | 'READY_LOCAL' | 'PUBLISHED_LOCAL'
}

export interface ErpRedemptionTask {
  id: string
  campaignId: string
  taskName: string
  claimDateFrom: string
  claimDateTo: string
  lookbackDays: number
  exportGroupKey: string
  status: 'PLANNED' | 'READY_LOCAL' | 'PUBLISHED_LOCAL'
  expectedCodeCount: number
  importedCodeCount: number
  rowVersion: number
  createdAt: string
  subtasks: ErpRedemptionTaskSubtask[]
}

export type ErpRedemptionRemotePlanStatus =
  | 'AWAITING_CREATE_AUTHORIZATION'
  | 'CREATING'
  | 'CREATE_FAILED'
  | 'READY_TO_PUBLISH'
  | 'AWAITING_PUBLISH_AUTHORIZATION'
  | 'PUBLISHING'
  | 'PUBLISH_FAILED'
  | 'PUBLISH_SCHEDULED'
  | 'PUBLISHED'
  | 'DOWNLOADING'
  | 'DOWNLOAD_FAILED'
  | 'COMPLETED'
  | 'CANCEL_PENDING'
  | 'CANCEL_FAILED'
  | 'CANCELLED'

export interface ErpRedemptionRemotePlan {
  id: string
  batchId: string
  remoteAccountId: string
  remoteAccountName: string
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  redemptionType: 'SEVEN_DAY_DEPOSIT' | 'PREVIOUS_DAY_DEPOSIT'
  workflowStatus: ErpRedemptionRemotePlanStatus
  publishEnvironment: 'test' | 'prod'
  flowTimes: number
  creationIntervalSeconds: number
  activityRecharge: string | null
  activityRechargeCount: number | null
  activityId: number | null
  keyNumber: number
  singleUserLimit: number
  singleKeyLimit: number
  requireBindBankCard: boolean
  requireBindPhone: boolean
  checkUuid: boolean
  uuidRewardLimit: number
  checkLoginIp: boolean
  loginIpRewardLimit: number
  checkRegisterIp: boolean
  registerIpRewardLimit: number
  publishMode: 'IMMEDIATE' | 'SCHEDULED' | null
  scheduledPublishAt: string | null
  scheduledPublishLocalAt: string | null
  fallbackToScheduled: boolean
  publishNote: string | null
  remotePublishTaskId: string | null
  scheduleCancelledAt: string | null
  reservedOperation: 'CREATE' | 'PUBLISH' | 'DOWNLOAD' | 'CANCEL' | null
  errorCode: string | null
  errorMessage: string | null
  issueCount: number
  createdCount: number
  downloadedCount: number
  failedCount: number
  scheduleDue: boolean
  rowVersion: number
  createdAt: string
  updatedAt: string
}

export interface ErpRedemptionRemoteExecution {
  id: string
  planId: string
  issueId: string | null
  operation: 'CREATE' | 'PUBLISH' | 'DOWNLOAD' | 'CANCEL'
  triggerType: 'MANUAL' | 'SCHEDULED'
  status: 'RESERVED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
  attemptNumber: number
  scheduledFor: string | null
  remoteRequestId: string | null
  errorCode: string | null
  errorMessage: string | null
  resultMetadata: Record<string, unknown>
  requestedBy: number | null
  requestedAt: string
  startedAt: string | null
  finishedAt: string | null
}

export type WithdrawOrderQueryRange =
  | 'today'
  | 'last_1_hour'
  | 'last_2_hours'
  | 'last_3_hours'
  | 'last_6_hours'
  | 'last_12_hours'
  | 'last_24_hours'
  | 'last_48_hours'

export type WithdrawOrderRefreshPageSize = 10 | 20 | 30 | 50 | 100
export type WithdrawOrderRefreshRange = 'day_before_yesterday' | 'yesterday' | 'today'
export type ChargeOrderQueryRange = WithdrawOrderQueryRange
export type ChargeOrderRefreshPageSize = WithdrawOrderRefreshPageSize
export type ChargeOrderRefreshRange = 'day_before_yesterday' | 'yesterday' | 'today'
export type ChargeOrderExportDateMode = 'previous_day' | 'specific_date'
export type WithdrawOrderExportDateMode = 'previous_day' | 'specific_date'
export type SpinOrderRefreshIntervalHours = 1 | 2 | 3 | 4 | 6 | 8 | 12 | 24
export type SpinOrderRefreshPageSize = WithdrawOrderRefreshPageSize
export type SpinOrderQueryRange =
  | 'last_completed_slot'
  | 'business_day_to_completed_slot'
  | 'previous_business_day_to_completed_slot'
  | 'last_2_hours'
  | 'last_3_hours'
  | 'last_6_hours'
  | 'last_12_hours'
  | 'previous_day'

export interface RetentionSettings {
  uploadedFileRetentionDays: number
  resultRetentionDays: number
  remoteCacheRetentionDays: number
  syncLogRetentionDays: number
  withdrawOrderRefreshIntervalHours: number
  withdrawOrderRefreshPageSize: WithdrawOrderRefreshPageSize
  withdrawOrderQueryRange: WithdrawOrderQueryRange
  withdrawOrderExportDateMode: WithdrawOrderExportDateMode
  withdrawOrderExportSpecificDate: string | null
  withdrawOrderExportTime: string
  automaticSyncRetryLimit: number
  automaticSyncRetryIntervalMinutes: number
  remoteOrderSyncTimeoutSeconds: number
  chargeOrderRefreshIntervalHours: number
  chargeOrderRefreshPageSize: ChargeOrderRefreshPageSize
  chargeOrderQueryRange: ChargeOrderQueryRange
  chargeOrderExportDateMode: ChargeOrderExportDateMode
  chargeOrderExportSpecificDate: string | null
  chargeOrderExportTime: string
  spinOrderRefreshIntervalHours: SpinOrderRefreshIntervalHours
  spinOrderRefreshPageSize: SpinOrderRefreshPageSize
  spinOrderQueryRange: SpinOrderQueryRange
  sessionTtlDays: number
  configVersion: number
  updatedBy: number | null
  updatedAt: string
}

export type SyncRunBusinessType =
  | 'charge_orders'
  | 'withdraw_orders'
  | 'withdraw_scoring_import'
  | 'spin_orders'

export type SyncRunTriggerType = 'automatic' | 'manual' | 'upload'

export type SyncRunStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'superseded'
  | 'cancelled'

export interface SyncRunRecord {
  id: string
  sourceId: string | null
  sourceDisplayName: string
  businessTimezone: string | null
  sourceConfigVersion: number | null
  businessType: SyncRunBusinessType
  operationKind: 'remote_sync' | 'excel_import'
  triggerType: SyncRunTriggerType
  status: SyncRunStatus
  requestedByUserId: number | null
  requestedByDisplayName: string | null
  requestedAt: string
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  windowStartUtc: string | null
  windowEndUtc: string | null
  queryRange: string | null
  pageSize: number | null
  remoteTotal: number | null
  exportRowCount: number | null
  cachedTotal: number | null
  fetchedPages: number | null
  importedCount: number | null
  createdCount: number | null
  updatedCount: number | null
  duplicateCount: number | null
  matchedCount: number | null
  unmatchedCount: number | null
  resolvedUidCount: number | null
  unresolvedUidCount: number | null
  complete: boolean | null
  inputFilename: string | null
  inputSizeBytes: number | null
  errorCode: string | null
  errorMessage: string | null
  metadata: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

export interface SyncRunEvent {
  id: number
  eventType: string
  status: string | null
  message: string | null
  metadata: Record<string, unknown>
  occurredAt: string
}

export interface SyncRunDetailResponse {
  run: SyncRunRecord
  events: SyncRunEvent[]
}

export interface SyncLogSummary {
  total: number
  queuedCount: number
  runningCount: number
  succeededCount: number
  partialCount: number
  failedCount: number
  supersededCount: number
  cancelledCount: number
  inProgressCount: number
  last24HoursSucceededCount: number
  last24HoursProblemCount: number
  latestSucceededAt: string | null
}

export interface SyncLogTrendItem {
  bucketStart: string
  queuedCount: number
  runningCount: number
  succeededCount: number
  partialCount: number
  failedCount: number
}

export interface SyncLogQueryResponse {
  items: SyncRunRecord[]
  total: number
  page: number
  pageSize: number
  summary: SyncLogSummary
  trend: SyncLogTrendItem[]
}

export interface PaymentTemplate {
  id: number
  platformId: number
  platformKey: string
  platformDisplayName: string
  businessType: 'payin' | 'payout'
  version: number
  sheetNamePattern: string | null
  headerSignature: string[]
  columnMapping: Record<string, unknown>
  successStatusValues: string[]
  matchRules: Array<Record<string, unknown>>
  active: boolean
}

export interface TemplateDetection {
  status: 'matched' | 'unknown'
  fileName: string
  sourceSheet: string | null
  headerRow: number | null
  detectedHeaders: string[]
  headerCoverage: number
  template: PaymentTemplate | null
  message: string
}

export interface PaymentChannelBinding {
  id: number
  platformId: number
  platformKey: string
  sourceId: string
  businessType: 'payin' | 'payout'
  remoteChannelCode: string
  remoteChannelLabel: string
  merchantDiscriminator: string | null
  active: boolean
}

export type RemoteDataDictionaryType =
  | 'withdraw_status'
  | 'payment_channel'
  | 'payment_channel_name'
  | 'user_source_channel'

export interface DataDictionaryEntry {
  id: number
  sourceId: string
  sourceDisplayName: string
  dictionaryType:
    | 'charge_status'
    | 'payment_channel'
    | 'payment_channel_name'
    | 'spin_order_status'
    | 'user_source_channel'
    | 'withdraw_status'
  entryCode: string
  entryLabel: string
  active: boolean
  firstSeenAt: string
  lastSeenAt: string
  updatedAt: string
}

export interface DataDictionaryRefreshConfig {
  sourceId: string
  sourceDisplayName: string
  dictionaryType: RemoteDataDictionaryType
  enabled: boolean
  intervalMinutes: 15 | 30 | 60 | 180 | 360 | 720 | 1440
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  lastStartedAt: string | null
  lastSucceededAt: string | null
  lastFailedAt: string | null
  lastError: string | null
  nextRefreshAt: string | null
  updatedAt: string | null
}

export interface WithdrawStatusSyncResult {
  sourceId: string
  sourceDisplayName: string
  fetchedAt: string
  remoteTotal: number
  createdEntries: number
  refreshedEntries: number
  entries: DataDictionaryEntry[]
}

export interface UserSourceChannelSyncResult {
  sourceId: string
  sourceDisplayName: string
  fetchedAt: string
  remoteTotal: number
  replacedEntries: number
  entries: DataDictionaryEntry[]
}

export interface BatchRecord {
  id: string
  comparisonSeriesId: string
  runVersion: number
  rerunOfBatchId: string | null
  sourceId: string
  sourceDisplayName: string
  sourceConfigVersion: number
  sourceBusinessTimezone: string
  sourceCurrency: string
  businessType: 'payin' | 'payout'
  status: string
  isFinal: boolean
  uploadedFileName: string
  uploadedFileSha256: string
  parametersJson: Record<string, unknown>
  progressJson: Record<string, unknown>
  executionRequestedBy: number
  createdBy: number
  errorCategory: string | null
  errorMessage: string | null
  cancellationRequestedAt: string | null
  cancelledAt: string | null
  cancelledBy: number | null
  cancellationReason: string | null
  createdAt: string
  startedAt: string | null
  completedAt: string | null
  resultExpiresAt: string
  updatedAt: string
}

export interface BatchList {
  items: BatchRecord[]
  total: number
}

export interface OperationalSummary {
  executionStatusDistribution: Array<{ status: string; count: number }>
  executionCreatedTimeSeries: Array<{ date: string; count: number }>
  executionDurationBuckets: Array<{ bucket: string; count: number }>
  failureCategoryDistribution: Array<{ category: string; count: number }>
  aggregationVersion: string
}

export interface BatchSummary {
  batchId: string
  runVersion: number
  isFinal: boolean
  counts: Record<string, number>
  aggregationVersion: string
}

export interface BatchCharts {
  batchId: string
  runVersion: number
  isFinal: boolean
  resultStatusDistribution: Array<{ status: string; count: number }>
  paymentStatusResultMatrix: Array<Record<string, unknown>>
  timeSeries: Array<Record<string, unknown>>
  channelComparison: Array<Record<string, unknown>>
  aggregationVersion: string
}

export interface OrderResult {
  id: string
  batchId: string
  orderGroupId: string
  resultStatus: string
  paymentStatusRaw: string | null
  paymentStatusGroup: string
  merchantOrderNo: string | null
  platformOrderNo: string | null
  payloadJson: {
    platformKey?: string | null
    amount?: string | null
    currency?: string | null
    paymentTime?: string | null
    sourceSheet?: string | null
    sourceRowNumbers?: number[]
    duplicateCount?: number
    remoteOrder?: Record<string, unknown> | null
  }
  isFinal: boolean
  createdAt: string
}

export interface OrderResultList {
  items: OrderResult[]
  total: number
}

export interface UserNotification {
  id: string
  eventType: string
  batchId: string
  runVersion: number
  title: string
  summaryJson: Record<string, unknown>
  createdAt: string
  deliveredAt: string | null
  readAt: string | null
}

export interface WithdrawOrder {
  id: string
  uid: string
  orderNum: string | null
  outTradeNo: string | null
  payChannelName: string | null
  payChannel: string | null
  amount: string | null
  realAmount: string | null
  fee: string | null
  createTime: string | null
  updateTime: string | null
  submitTime: string | null
  auditAdmin: string | null
  status: string
  statusLabel: string | null
  isFirst: string | null
  channel: string | null
  /**
   * Optional score-review supplements, joined from the scoring workbook by
   * `案件号 -> 主键`.  These do not replace any canonical withdrawal fields.
   */
  scoringRecordImported: boolean
  scoringGlobalGate: string | null
  scoringSceneReview: string | null
  scoringScore: string | null
  scoringDecisionStage: string | null
  scoringFinalSuggestion: string | null
  scoringOperationResult: string | null
  scoringSummary: string | null
  scoringCurrentStatus: string | null
  scoringReviewedAt: string | null
  scoringReviewElapsed: string | null
  scoringQueueElapsed: string | null
  scoringQueueEnteredAt: string | null
  scoringQueueExitedAt: string | null
}

export interface WithdrawStatusSummary {
  status: string
  count: number
  amount: string
  realAmount: string
}

export interface WithdrawTimeSummary {
  bucket: string
  count: number
  amount: string
  realAmount: string
}

export interface WithdrawOrderSummary {
  orderCount: number
  amount: string
  realAmount: string
  averageAmount: string
  statusDistribution: WithdrawStatusSummary[]
  timeSeries: WithdrawTimeSummary[]
}

export interface WithdrawStatusDictionaryEntry {
  code: string
  label: string
  active: boolean
}

export interface WithdrawChannelDictionaryEntry {
  code: string
  label: string
}

export interface WithdrawOperatorStatusCount {
  status: string
  count: number
}

export interface WithdrawOperatorSummaryItem {
  auditAdmin: string
  auditAdminMissing: boolean
  statusCounts: WithdrawOperatorStatusCount[]
  selectedTotal: number
}

export interface WithdrawOperatorSummaryResponse {
  items: WithdrawOperatorSummaryItem[]
  total: number
  page: number
  pageSize: number
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  effectiveCreateTimeEnd: string
  fetchedAt: string
  localUpdatedAt: string | null
  statusColumns: string[]
  statusDictionary: WithdrawStatusDictionaryEntry[]
  selectedOrderTotal: number
}

export interface WithdrawOrderRefreshResult {
  status: 'queued'
  sourceIds: string[]
  requestedAt: string
  queryRange: WithdrawOrderRefreshRange | null
  message: string
}

export type WithdrawOrderRefreshStatus =
  | 'not_started'
  | 'idle'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'

export interface WithdrawOrderQueryResponse {
  items: WithdrawOrder[]
  total: number
  remoteTotal: number
  page: number
  pageSize: number
  fetchedPages: number
  complete: boolean
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  currency: string
  effectiveCreateTimeEnd: string
  fetchedAt: string
  localUpdatedAt: string | null
  lastRefreshedAt: string | null
  refreshStatus: WithdrawOrderRefreshStatus
  statusDictionary: WithdrawStatusDictionaryEntry[]
  channelDictionary: WithdrawChannelDictionaryEntry[]
  summary: WithdrawOrderSummary
}

export interface WithdrawChannelSummaryItem {
  date: string
  payChannel: string
  payChannelName: string
  orderCount: number
  successfulOrderCount: number
  successfulAmount: string
  successfulFee: string
  failedOrderCount: number
  submittedOrderCount: number
  rejectedOrderCount?: number
  successfulOrderShare: string
  successfulAmountShare: string
  stuckRate: string
  successRate: string
}

export interface WithdrawChannelSummaryResponse {
  items: WithdrawChannelSummaryItem[]
  total: number
  page: number
  pageSize: number
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  currency: string
  effectiveCreateTimeEnd: string
  fetchedAt: string
  localUpdatedAt: string | null
  channelDictionary: WithdrawChannelDictionaryEntry[]
}

/** Counts calculated from source-bound local withdrawal and score caches. */
export interface ScoringReviewSummaryCounts {
  totalCount: number
  /** Included in scoreLte30Count; it is intentionally not an additional score bucket. */
  notEnteredScoringCount: number
  scoreLte30Count: number
  score31To60Count: number
  scoreGte61Count: number
}

/**
 * Withdrawal summary restricted to local orders that have a matching scoring
 * review cache record.  Management-side orders without a scoring record are
 * reported separately and never enter the score buckets.
 */
export interface WithdrawScoringSummaryItem extends ScoringReviewSummaryCounts {
  auditAdmin: string
  auditAdminMissing: boolean
  statusCounts: WithdrawOperatorStatusCount[]
}

export interface WithdrawScoreDistributionItem {
  auditAdmin: string
  auditAdminMissing: boolean
  scoreLte30Count: number
  score31To60Count: number
  scoreGte61Count: number
}

export interface WithdrawScoringSummaryResponse {
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  startAt: string
  endAt: string
  generatedAt: string
  localUpdatedAt: string | null
  rows: WithdrawScoringSummaryItem[]
  totals: ScoringReviewSummaryCounts
  statusColumns: string[]
  statusDictionary: WithdrawStatusDictionaryEntry[]
  managementOrderCount: number
  scoringRecordOrderCount: number
  missingScoringRecordCount: number
  numericScoreOrderCount: number
  unscoredScoreRecordCount: number
  scoreDistribution: WithdrawScoreDistributionItem[]
}

export interface WithdrawScoringImportResult {
  sourceId: string
  sourceRowCount: number
  matchedCount: number
  createdCount: number
  updatedCount: number
  unmatchedCount: number
  syncedAt: string
}

export interface ChargeOrder {
  id: string
  uid: string
  orderNum: string | null
  chargeProductId: string | null
  productName: string | null
  outTradeNo: string | null
  payMethod: string | null
  payChannelName: string | null
  payType: string | null
  amount: string | null
  balance: string | null
  extra: string | null
  status: string
  createTime: string | null
  payTime: string | null
  updateTime: string | null
  firstPay: string | null
  notified: string | null
  chargeType: string | null
  fillOrderNum: string | null
  fillOrderAdmin: string | null
  channel: string | null
}

export interface ChargeOrderStatusDictionaryEntry {
  code: string
  label: string
}

export interface ChargeOrderChannelDictionaryEntry {
  code: string
  label: string
}

export interface ChargeOrderSummary {
  orderCount: number
  successfulOrderCount: number
  successfulAmount: string
  unpaidOrderCount: number
  noThirdPartyOrderCount: number
}

export interface ChargeOrderRefreshResult {
  status: 'queued'
  sourceIds: string[]
  requestedAt: string
  queryRange: ChargeOrderRefreshRange | null
  message: string
}

export interface ChargeOrderQueryResponse {
  items: ChargeOrder[]
  total: number
  remoteTotal: number
  page: number
  pageSize: number
  fetchedPages: number
  complete: boolean
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  currency: string
  effectiveCreateTimeEnd: string
  fetchedAt: string
  localUpdatedAt: string | null
  lastRefreshedAt: string | null
  refreshStatus: WithdrawOrderRefreshStatus
  statusDictionary: ChargeOrderStatusDictionaryEntry[]
  channelDictionary: ChargeOrderChannelDictionaryEntry[]
  channelNameDictionary: ChargeOrderChannelDictionaryEntry[]
  summary: ChargeOrderSummary
}

export interface ChargeChannelSummaryItem {
  payMethod: string
  payChannelName: string
  orderCount: number
  successfulOrderCount: number
  successfulAmount: string
  unpaidOrderCount: number
  noThirdPartyOrderCount: number
  successfulOrderShare: string
  successfulAmountShare: string
  successRate: string
}

export interface ChargeDenominationSummaryItem {
  amount: string
  successfulOrderCount: number
  successfulAmount: string
}

export interface ChargeChannelSummaryResponse {
  items: ChargeChannelSummaryItem[]
  denominationDistribution: ChargeDenominationSummaryItem[]
  total: number
  page: number
  pageSize: number
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  effectiveCreateTimeEnd: string
  fetchedAt: string
  localUpdatedAt: string | null
}

export type SpinOrderRefreshRange = 'day_before_yesterday' | 'yesterday' | 'today'
export type SpinOrderRefreshStatus =
  | 'not_started'
  | 'idle'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'

export interface SpinOrder {
  id: string
  uid: string
  vipLevel: string | null
  agentTotalCount: string | null
  amount: string | null
  spinConfigId: string
  spinConfigLabel: string
  roundNumber: string | null
  inviteCount: string | null
  status: string
  statusLabel: string
  createTime: string | null
  auditTime: string | null
  channelId: string | null
  channelName: string
}

export interface SpinStatusDictionaryEntry {
  code: string
  label: string
  active: boolean
}

export interface SpinChannelDictionaryEntry {
  code: string
  label: string
}

export interface SpinOrderStatusDistribution {
  status: string
  count: number
}

export interface SpinOrderSummary {
  orderCount: number
  passedOrderCount: number
  pendingOrderCount: number
  rejectedOrderCount: number
  suspendedOrderCount: number
  approvalRate: string
  winnerCount: number
  passedWinnerCount: number
  personApprovalRate: string
  statusDistribution: SpinOrderStatusDistribution[]
}

export interface SpinOrderQueryResponse {
  items: SpinOrder[]
  total: number
  page: number
  pageSize: number
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  fetchedAt: string
  localUpdatedAt: string | null
  lastRefreshedAt: string | null
  refreshStatus: SpinOrderRefreshStatus
  remoteTotal: number
  fetchedPages: number
  complete: boolean
  resolvedUidCount: number
  unresolvedUidCount: number
  statusDictionary: SpinStatusDictionaryEntry[]
  channelDictionary: SpinChannelDictionaryEntry[]
  summary: SpinOrderSummary
}

export interface SpinChannelSummaryItem {
  date: string
  spinConfigId: string
  spinConfigLabel: string
  channelId: string | null
  channelName: string
  applicationOrderCount: number
  passedOrderCount: number
  pendingOrderCount: number
  rejectedOrderCount: number
  suspendedOrderCount: number
  approvalRate: string
  winnerCount: number
  passedWinnerCount: number
  personApprovalRate: string
}

export interface SpinTwoHourSeriesItem {
  date: string
  bucket: string
  spinConfigId: string
  spinConfigLabel: string
  channelId: string | null
  channelName: string
  applicantCount: number
}

export interface SpinChannelSummaryResponse {
  items: SpinChannelSummaryItem[]
  total: number
  page: number
  pageSize: number
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  fetchedAt: string
  localUpdatedAt: string | null
  channelDictionary: SpinChannelDictionaryEntry[]
  timeSeries: SpinTwoHourSeriesItem[]
}

export interface SpinOrderRefreshResult {
  status: 'queued'
  sourceIds: string[]
  requestedAt: string
  queryRange: SpinOrderRefreshRange | null
  message: string
}
