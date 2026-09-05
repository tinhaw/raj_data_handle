import { api } from './client'
import type {
  SpinChannelSummaryResponse,
  SpinOrderQueryResponse,
  SpinOrderRefreshRange,
  SpinOrderRefreshResult,
} from '../types'

export interface SpinOrderQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  uid?: string
  status?: string
  spinConfigId?: string
  channelId?: string
  page: number
  pageSize: number
}

export async function querySpinOrders(payload: SpinOrderQuery): Promise<SpinOrderQueryResponse> {
  return (await api.post<SpinOrderQueryResponse>('/spin-orders/query', payload)).data
}

export interface SpinChannelSummaryQuery {
  sourceId: string
  createTimeStart?: string
  createTimeEnd?: string
  spinConfigId?: string
  channelId?: string
  page?: number
  pageSize?: number
}

export async function querySpinChannelSummary(
  payload: SpinChannelSummaryQuery,
): Promise<SpinChannelSummaryResponse> {
  return (await api.post<SpinChannelSummaryResponse>('/spin-orders/channel-summary', payload)).data
}

export async function startSpinOrderRefresh(payload: {
  sourceId?: string
  queryRange?: SpinOrderRefreshRange
} = {}): Promise<SpinOrderRefreshResult> {
  return (await api.post<SpinOrderRefreshResult>('/spin-orders/refresh', payload)).data
}
