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
  baseUrl: string | null
  enabled: boolean
  businessTimezone: string
  currency: string
  configVersion: number
  credentialConfigured: boolean
  credentialUpdatedAt: string | null
  lastTestedAt: string | null
  lastTestStatus: string | null
  createdAt: string
  updatedAt: string
}

export interface RetentionSettings {
  uploadedFileRetentionDays: number
  resultRetentionDays: number
  remoteCacheRetentionDays: number
  sessionTtlDays: number
  configVersion: number
  updatedBy: number | null
  updatedAt: string
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
  dictionaryType: 'payment_channel_name'
  entryCode: string
  entryLabel: string
  active: boolean
  firstSeenAt: string
  lastSeenAt: string
  updatedAt: string
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
