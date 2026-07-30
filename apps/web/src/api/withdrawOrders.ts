import { api } from './client'
import type {
  WithdrawOperatorSummaryResponse,
  WithdrawOrderQueryResponse,
  WithdrawOrderRefreshResult,
} from '../types'

export interface WithdrawOrderQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  uid?: string
  status?: string
  auditAdmin?: string
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

export async function startWithdrawOrderRefresh(payload: {
  sourceId?: string
} = {}): Promise<WithdrawOrderRefreshResult> {
  return (await api.post<WithdrawOrderRefreshResult>('/withdraw-orders/refresh', payload)).data
}
