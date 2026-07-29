import { api } from './client'
import type { WithdrawOrderQueryResponse } from '../types'

export interface WithdrawOrderQuery {
  sourceId: string
  createTimeStart: string
  createTimeEnd: string
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
