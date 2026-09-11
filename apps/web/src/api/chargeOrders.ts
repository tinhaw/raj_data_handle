import { api } from './client'
import type {
  ChargeChannelSummaryResponse,
  ChargeOrderQueryResponse,
  ChargeOrderRefreshResult,
  ChargeOrderRefreshRange,
} from '../types'

export interface ChargeOrderQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  uid?: string
  status?: string
  payMethod?: string
  orderNum?: string
  page: number
  pageSize: number
}

export async function queryChargeOrders(
  payload: ChargeOrderQuery,
): Promise<ChargeOrderQueryResponse> {
  return (await api.post<ChargeOrderQueryResponse>('/charge-orders/query', payload)).data
}

export async function queryChargeChannelSummary(
  payload: ChargeOrderQuery,
): Promise<ChargeChannelSummaryResponse> {
  return (await api.post<ChargeChannelSummaryResponse>('/charge-orders/channel-summary', payload)).data
}

export async function startChargeOrderRefresh(payload: {
  sourceId?: string
  queryRange?: ChargeOrderRefreshRange
} = {}): Promise<ChargeOrderRefreshResult> {
  return (await api.post<ChargeOrderRefreshResult>('/charge-orders/refresh', payload)).data
}
