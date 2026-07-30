import { api } from './client'
import type { WithdrawOrderQueryResponse, WithdrawOrderRefreshResult } from '../types'

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

export async function startWithdrawOrderRefresh(payload: {
  sourceId?: string
} = {}): Promise<WithdrawOrderRefreshResult> {
  return (await api.post<WithdrawOrderRefreshResult>('/withdraw-orders/refresh', payload)).data
}
