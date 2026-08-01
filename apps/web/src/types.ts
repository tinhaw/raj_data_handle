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
  credentialUpdatedAt: string | null
  scoringApiBaseUrl: string | null
  scoringApiKeyConfigured: boolean
  scoringApiKeyUpdatedAt: string | null
  scoringApiLastTestedAt: string | null
  scoringApiLastTestStatus: string | null
  lastTestedAt: string | null
  lastTestStatus: string | null
  createdAt: string
  updatedAt: string
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

export interface ScoringReviewOperatorSummaryItem extends ScoringReviewSummaryCounts {
  operator: string
}

export interface ScoringReviewOperatorSummaryResponse {
  sourceId: string
  sourceDisplayName: string
  businessTimezone: string
  startAt: string
  endAt: string
  generatedAt: string
  localUpdatedAt: string | null
  rows: ScoringReviewOperatorSummaryItem[]
  totals: ScoringReviewSummaryCounts
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
