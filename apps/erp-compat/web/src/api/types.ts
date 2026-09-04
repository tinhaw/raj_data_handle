export type Asset = 'USDT' | 'USDC'
export type BalanceStatus = 'DRAFT' | 'CONFIRMED' | 'VOIDED'
export type FraudSource = 'TRANSFER' | 'BALANCE' | null
export type CalculationBasis = 'TRANSFER' | 'EFFECTIVE_TRANSFER' | 'SPEND' | 'MANUAL'

export interface CurrentUser {
  id: string | number
  username: string
  displayName: string
  roles: string[]
  permissions: string[]
  operatorIds?: Array<string | number>
  allOperators?: boolean
  mustChangePassword?: boolean
  rowVersion?: number
}

/** A user record returned by the administrator-only user-management APIs. */
export interface ManagedUser extends CurrentUser {
  enabled: boolean
  createdAt?: string
}

export interface Role {
  id: string | number
  code: string
  name: string
  description?: string
  permissions: string[]
}

export interface CreateUserInput {
  username: string
  password: string
  displayName: string
  enabled?: boolean
  roleCodes?: string[]
  allOperators?: boolean
  operatorIds?: Array<string | number>
}

export interface UpdateUserInput {
  displayName?: string
  enabled?: boolean
  rowVersion?: number
}

export interface AuditLog {
  id: string | number
  actorUserId?: string | number
  action: string
  entityType: string
  entityId?: string
  operatorId?: string | number
  requestId?: string
  ipAddress?: string
  reason?: string
  beforeJson?: string
  afterJson?: string
  createdAt: string
}

export interface AuditLogQuery {
  action?: string
  operatorId?: string | number
  from?: string
  to?: string
}

export interface Operator {
  id: string | number
  code: string
  name: string
  type: 'COMPANY' | 'STUDIO' | 'INDIVIDUAL'
  status: 'ACTIVE' | 'INACTIVE'
  contactName?: string
  contactValue?: string
  remark?: string
  rowVersion?: number
  accounts?: OperatorAccount[]
}

export interface OperatorAccount {
  id: string | number
  operatorId: string | number
  /** User-facing delivery-company context returned by the API. */
  companyName?: string
  /** `companyName · name`, for display wherever a line is listed on its own. */
  displayName?: string
  code: string
  name: string
  asset: Asset
  network?: string
  walletAddress?: string
  startDate?: string
  defaultExchangeLossRate: string
  defaultExchangeLossBasis: CalculationBasis
  defaultServiceFeeRate: string
  defaultServiceFeeBasis: CalculationBasis
  calculationScale: number
  status: 'ACTIVE' | 'INACTIVE'
  rowVersion?: number
}

export interface DailyBalance {
  id?: string | number
  accountId: string | number
  operatorId?: string | number
  businessDate: string
  openingBalance: string
  suggestedOpeningBalance?: string
  openingMode?: 'AUTO' | 'MANUAL'
  openingOverrideReason?: string
  transferAmount: string
  fraudLossAmount: string
  fraudDeductionSource: FraudSource
  effectiveTransferAmount?: string
  spendAmount: string
  exchangeLossRate: string
  exchangeLossBasis: CalculationBasis
  exchangeLossAutoAmount?: string
  exchangeLossAmount: string
  exchangeLossMode?: 'AUTO' | 'MANUAL'
  exchangeLossOverrideReason?: string
  serviceFeeRate: string
  serviceFeeBasis: CalculationBasis
  serviceFeeAutoAmount?: string
  serviceFeeAmount: string
  serviceFeeMode?: 'AUTO' | 'MANUAL'
  serviceFeeOverrideReason?: string
  refluxAmount: string
  refundAmount: string
  otherDeductionAmount: string
  otherReason?: string
  closingBalance?: string
  calculationScale?: number
  status: BalanceStatus
  locked?: boolean
  remark?: string
  rowVersion?: number
  sourceType?: 'MANUAL' | 'PASTE' | 'IMPORT'
}

export interface PeriodLock {
  id: string | number
  accountId: string | number
  month: string
  status: 'LOCKED' | 'UNLOCKED' | string
  lockedBy?: string | number
  lockedAt?: string
  unlockReason?: string
  unlockedBy?: string | number
  unlockedAt?: string
  rowVersion?: number
}

export interface PeriodLockIssue {
  accountId?: string | number
  businessDate?: string
  code: string
  message: string
}

export interface PeriodLockValidation {
  month: string
  canLock: boolean
  issues: PeriodLockIssue[]
}

export interface CalculationPreview {
  /** The server-provided carry-forward value, when an earlier daily record exists. */
  suggestedOpeningBalance?: string
  /** The effective opening value after the server applies the carry-forward rule. */
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

export interface ReportRow {
  businessDate?: string
  periodMonth?: string
  operatorId?: string | number
  operatorName?: string
  accountId?: string | number
  accountName?: string
  asset: Asset | 'NOMINAL_U'
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
  recordCount?: number
}

export interface ImportRowPreview {
  sourceRow: number
  businessDate?: string
  operatorName?: string
  accountName?: string
  action: 'CREATE' | 'UPDATE' | 'SKIP' | 'ERROR'
  level: 'SUCCESS' | 'WARNING' | 'ERROR'
  message?: string
  raw?: Record<string, string>
}

export interface ImportPreview {
  jobId: string
  sourceType: 'PASTE' | 'XLSX_STANDARD' | 'XLSX_LEGACY'
  totalRows: number
  validRows: number
  warningRows: number
  errorRows: number
  rows: ImportRowPreview[]
}

export interface ImportJob {
  id: string | number
  sourceType: 'PASTE' | 'XLSX_STANDARD' | 'XLSX_LEGACY' | string
  originalFilename?: string
  fileSha256?: string
  status: string
  conflictStrategy?: string
  totalRows: number
  validRows: number
  warningRows: number
  errorRows: number
  createdAt?: string
  committedAt?: string
  createdBy?: string | number
}

export interface ImportJobRow {
  id?: string | number
  sourceSheet?: string
  sourceRow: number
  operatorName?: string
  operatorAccountId?: string | number
  businessDate?: string
  severity: 'SUCCESS' | 'WARNING' | 'ERROR' | string
  errorCode?: string
  errorMessage?: string
  action?: string
  targetDailyBalanceId?: string | number
  normalized?: Record<string, unknown>
}

export interface ImportJobDetail {
  job: ImportJob
  rows: ImportJobRow[]
}

export interface DownloadFile {
  blob: Blob
  filename: string
}

export type RedemptionCampaignStatus = 'DRAFT' | 'ACTIVE' | 'ARCHIVED'
export type RedemptionCodeState = 'PENDING' | 'GENERATED' | 'FAILED'
export type RedemptionWorkflowStatus = 'PENDING_CREATION' | 'CREATING_REMOTE' | 'CREATED' | 'PUBLISHED' | 'CODE_IMPORTED' | 'FAILED'
export type RedemptionBatchStatus = 'CREATING' | 'READY_TO_PUBLISH' | 'PUBLISHED' | 'COMPLETED'
export type RedemptionCodeType = 'SEVEN_DAY_DEPOSIT' | 'PREVIOUS_DAY_DEPOSIT'

export interface RedemptionCampaignTier {
  id?: string | number
  displayName?: string
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount?: string
  sortOrder?: number
  rowVersion?: number
}

export interface RedemptionCampaign {
  id?: string | number
  code: string
  name: string
  status: RedemptionCampaignStatus
  lookbackDays: number
  description?: string
  tiers: RedemptionCampaignTier[]
  generatedCodeCount?: number
  failedCodeCount?: number
  rowVersion?: number
  createdAt?: string
  updatedAt?: string
}

export interface RedemptionCodeIssue {
  id: string | number
  campaignId: string | number
  campaignTierId: string | number
  tierName?: string
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount?: string
  claimDate: string
  depositWindowStart: string
  depositWindowEnd: string
  redemptionCode?: string
  state: RedemptionCodeState
  remoteReferenceId?: string
  remoteError?: string
  generatedAt?: string
  rowVersion?: number
  batchId?: string | number
  workflowStatus?: RedemptionWorkflowStatus
  remoteConfigurationId?: string
  remoteGroupKey?: string
  remoteLabelIds?: Array<string | number>
}

export interface RedemptionCodeBatch {
  id: string | number
  /** Operator-facing task ID shared by every market in one multi-market request. */
  taskId?: string | number
  campaignId: string | number
  claimDateFrom: string
  claimDateTo: string
  /** Day offsets from each generated claim date used for remote valid_time. */
  validFromDayOffset: number
  validToDayOffset: number
  lookbackDays: number
  redemptionType: RedemptionCodeType
  expectedCodeCount: number
  /** Number of individual codes; expectedCodeCount remains the configuration count. */
  plannedCodeCount: number
  importedCodeCount: number
  status: RedemptionBatchStatus
  pendingCreationCount: number
  createdCount: number
  publishedCount: number
  importedCount: number
  publishedAt?: string
  rowVersion?: number
  createdAt?: string
  remoteConnectionId?: string | number
  remoteConnectionName?: string
  remoteMarketCode?: string
  remoteMarketName?: string
  /** Links the separate market batches created in one multi-market request. */
  exportGroupKey?: string
  remotePublishTaskId?: string
  remotePublishError?: string
  remotePublishMode?: 'IMMEDIATE' | 'SCHEDULED'
  remoteScheduledPublishAt?: string
  remotePublishNote?: string
  remotePublishCancelledAt?: string
  remoteOptions?: RedemptionRemoteCreationOptions
}

export interface RedemptionBatchDetail {
  batch: RedemptionCodeBatch
  issues: RedemptionCodeIssue[]
}

export interface RedemptionCodeGroupInput {
  code: string
  name: string
  claimDateFrom: string
  claimDateTo: string
  /** Defaults to 0/0: each configuration is valid on its claim date only. */
  validFromDayOffset: number
  validToDayOffset: number
  lookbackDays: number
  description?: string
  tiers: RedemptionCampaignTier[]
  remoteMarketId: string | number
  exportGroupKey?: string
  redemptionType: RedemptionCodeType
  /** Each entry declares whether the same-indexed tier targets all users or label users. */
  tierUserTypes: Array<'ALL_USERS' | 'LABEL_USERS'>
  /** Each entry corresponds to the same-indexed recharge tier. */
  tierLabelIds: Array<Array<string | number>>
  remoteOptions: RedemptionRemoteCreationOptions
}

/** These options are selected when establishing a batch and are snapshotted with that batch. */
export interface RedemptionRemoteCreationOptions {
  publishEnvironment: 'test' | 'prod'
  flowTimes: number
  /** Minimum time between starting two remote configuration-create requests. */
  creationIntervalSeconds: number
  /** Optional remote activity eligibility gates. Omit them when no activity is associated. */
  activityRecharge?: number
  activityRechargeCount?: number
  activityId?: number
  /** Codes generated per remote configuration (key_number), default 1. */
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
}

export interface RedemptionRemoteConnection {
  id?: string | number
  /** The remote-admin login name. It is unique; no second account code is needed. */
  username: string
  marketId?: string | number
  marketCode?: string
  marketName?: string
  marketEnabled?: boolean
  /** Read-only endpoint snapshot; select a market instead of editing this on an account. */
  baseUrl: string
  hasPassword?: boolean
  hasTotpSecret?: boolean
  hasActiveSession?: boolean
  sessionExpiresAt?: string
  lastLoggedInAt?: string
  /** Request-only encrypted-at-rest credentials; the server never returns their plaintext. */
  password?: string
  totpSecret?: string
  enabled: boolean
  lastCheckedAt?: string
  lastError?: string
  rowVersion?: number
  createdAt?: string
  updatedAt?: string
}

export interface RedemptionRemoteMarket {
  id?: string | number
  code: string
  name: string
  baseUrl: string
  enabled: boolean
  rowVersion?: number
  createdAt?: string
  updatedAt?: string
}

export interface RedemptionRemoteTag { id: string | number; name: string }

export interface RedemptionRewardTierPresetTier {
  userType?: 'ALL_USERS' | 'LABEL_USERS'
  labelIds: Array<string | number>
  displayName: string
  minDepositAmount: string
  bonusAmount: string
  bonusMaxAmount: string
}

export interface RedemptionRewardTierPreset {
  exists: boolean
  stale: boolean
  tiers: RedemptionRewardTierPresetTier[]
  tagSnapshot: RedemptionRemoteTag[]
  savedAt?: string
  lastSyncedAt?: string
}

export interface RedemptionRemoteTagSyncResult {
  tags: RedemptionRemoteTag[]
  presetStale: boolean
  syncedAt?: string
}

export interface PageResult<T> {
  content: T[]
  totalElements?: number
}
