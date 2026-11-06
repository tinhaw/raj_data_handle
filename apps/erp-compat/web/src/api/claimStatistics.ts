export interface ClaimCell {
  count: number | null
  complete: boolean
  state: 'complete' | 'partial' | 'pending' | 'future' | 'notApplicable'
  asOf?: string
  error?: string
  coveredGroups?: number
  expectedGroups?: number
  configurationIds?: string[]
}
export interface ClaimColumn {
  key: string
  sourceId: string
  sourceName: string
  timezone: string
  currency: string
  tierName: string
  rewardMin: string
  rewardMax: string
  labels: number[]
}
export interface ClaimRow { date: string; cells: Record<string, ClaimCell>; total: ClaimCell }
export interface ClaimRun {
  id: string; taskId: string; status: string; trigger: string
  startedAt?: string; finishedAt?: string
  progress: { totalGroups?: number; completedGroups?: number; failedGroups?: number
    skippedGroups?: number; pages?: number; records?: number; backupGroups?: number
    accountUsage?: Array<{ sourceId: string; accountId: string; accountName: string; backup: boolean; groups: number }>
    errors?: Array<{ message: string; accountIds?: string[] }> }
}
export interface ClaimSchedule {
  enabled: boolean; intervalMinutes: number; rowVersion: number
  nextRunAt?: string; lastSucceededAt?: string; activeRun?: ClaimRun; lastRun?: ClaimRun
}
export interface ClaimStatistics {
  taskId: string; taskNumber: string; queryVersion: string; dateFrom: string; dateTo: string
  columns: ClaimColumn[]; rows: ClaimRow[]
  totals: Record<string, { count: number | null; complete: boolean }>
  schedule: ClaimSchedule
}
export interface ClaimCode {
  groupId: string; configurationId: string; description: string; claimDate: string
  code: string; count: number | null; complete: boolean; matched: boolean
}
export interface ClaimRecord { id: string; uid: string; code: string; receiveTime: string; amount: string }
export interface ClaimPage<T> { items: T[]; total: number; queryVersion: string }
export const claimIntervals = [
  { value: 30, label: '30 分钟' }, { value: 60, label: '1 小时' },
  { value: 120, label: '2 小时' }, { value: 180, label: '3 小时' },
  { value: 360, label: '6 小时' }, { value: 720, label: '12 小时' },
  { value: 1440, label: '24 小时' },
]
