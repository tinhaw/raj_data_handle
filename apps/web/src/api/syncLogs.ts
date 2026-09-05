import { api } from './client'
import type {
  SyncLogQueryResponse,
  SyncRunBusinessType,
  SyncRunDetailResponse,
  SyncRunStatus,
  SyncRunTriggerType,
} from '../types'

export interface SyncLogQuery {
  sourceId?: string
  businessTypes?: SyncRunBusinessType[]
  triggerTypes?: SyncRunTriggerType[]
  statuses?: SyncRunStatus[]
  startedAt?: string
  endedAt?: string
  keyword?: string
  page: number
  pageSize: number
}

export async function querySyncLogs(payload: SyncLogQuery): Promise<SyncLogQueryResponse> {
  return (await api.post<SyncLogQueryResponse>('/sync-logs/query', payload)).data
}

export async function fetchSyncLogDetail(runId: string): Promise<SyncRunDetailResponse> {
  return (await api.get<SyncRunDetailResponse>(`/sync-logs/${encodeURIComponent(runId)}`)).data
}
