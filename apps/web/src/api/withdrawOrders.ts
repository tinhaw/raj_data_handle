import { api } from './client'
import type {
  WithdrawChannelSummaryResponse,
  WithdrawOperatorSummaryResponse,
  WithdrawOrderQueryResponse,
  WithdrawOrderRefreshResult,
  WithdrawOrderRefreshRange,
  WithdrawScoringSummaryResponse,
  ScoringReviewOperatorSummaryResponse,
  WithdrawScoringImportResult,
} from '../types'

export interface WithdrawOrderQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  uid?: string
  status?: string
  auditAdmin?: string
  orderNum?: string
  outTradeNo?: string
  payChannel?: string
  page: number
  pageSize: number
}

export async function queryWithdrawOrders(
  payload: WithdrawOrderQuery,
): Promise<WithdrawOrderQueryResponse> {
  return (await api.post<WithdrawOrderQueryResponse>('/withdraw-orders/query', payload)).data
}

export interface WithdrawOperatorSummaryQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  statuses?: string[]
  auditAdmin?: string
  page?: number
  pageSize?: number
}

export async function queryWithdrawOperatorSummary(
  payload: WithdrawOperatorSummaryQuery,
): Promise<WithdrawOperatorSummaryResponse> {
  return (await api.post<WithdrawOperatorSummaryResponse>('/withdraw-orders/operator-summary', payload)).data
}

export interface WithdrawChannelSummaryQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  payChannel?: string
  page?: number
  pageSize?: number
}

export async function queryWithdrawChannelSummary(
  payload: WithdrawChannelSummaryQuery,
): Promise<WithdrawChannelSummaryResponse> {
  return (await api.post<WithdrawChannelSummaryResponse>('/withdraw-orders/channel-summary', payload)).data
}

export interface ScoringReviewOperatorSummaryQuery {
  sourceId: string
  createTimeStart: string
  createTimeEnd: string
}

export async function queryScoringReviewOperatorSummary(
  payload: ScoringReviewOperatorSummaryQuery,
): Promise<ScoringReviewOperatorSummaryResponse> {
  return (await api.post<ScoringReviewOperatorSummaryResponse>(
    '/withdraw-orders/scoring-review-summary',
    payload,
  )).data
}

export interface WithdrawScoringSummaryQuery {
  sourceId: string
  createTimeStart: string
  createTimeEnd: string
}

export async function queryWithdrawScoringSummary(
  payload: WithdrawScoringSummaryQuery,
): Promise<WithdrawScoringSummaryResponse> {
  return (await api.post<WithdrawScoringSummaryResponse>('/withdraw-orders/scoring-summary', payload)).data
}

/**
 * Import one source's scoring-review workbook into the local supplemental
 * cache.  The service only joins existing withdrawal orders by case number;
 * it never creates a withdrawal order from a score row.
 */
export async function importScoringReviewedCases(
  sourceId: string,
  file: File,
): Promise<WithdrawScoringImportResult> {
  const form = new FormData()
  form.set('sourceId', sourceId)
  form.set('upload', file)
  return (
    await api.post<WithdrawScoringImportResult>('/withdraw-orders/scoring-review/import', form)
  ).data
}

export async function syncScoringReviewedCases(payload: {
  sourceId: string
  createTimeStart: string
  createTimeEnd: string
}): Promise<WithdrawScoringImportResult> {
  return (
    await api.post<WithdrawScoringImportResult>('/withdraw-orders/scoring-review/sync', payload)
  ).data
}

export async function startWithdrawOrderRefresh(payload: {
  sourceId?: string
  queryRange?: WithdrawOrderRefreshRange
} = {}): Promise<WithdrawOrderRefreshResult> {
  return (await api.post<WithdrawOrderRefreshResult>('/withdraw-orders/refresh', payload)).data
}
