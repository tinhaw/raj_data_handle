import { api } from './client'
import type { DataDictionaryEntry, WithdrawStatusSyncResult } from '../types'

export async function fetchPaymentChannelNames(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/payment-channel-names',
    {
      params: {
        source_id: params.sourceId,
        active: params.active,
      },
    },
  )
  return response.data
}

export async function fetchWithdrawStatuses(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/withdraw-statuses',
    {
      params: {
        source_id: params.sourceId,
        active: params.active,
      },
    },
  )
  return response.data
}

export async function createWithdrawStatus(payload: {
  sourceId: string
  entryCode: string
  entryLabel: string
  active: boolean
}): Promise<DataDictionaryEntry> {
  return (
    await api.post<DataDictionaryEntry>('/settings/data-dictionaries/withdraw-statuses', payload)
  ).data
}

export async function updateWithdrawStatus(
  entryId: number,
  payload: { entryLabel?: string; active?: boolean },
): Promise<DataDictionaryEntry> {
  return (
    await api.patch<DataDictionaryEntry>(
      `/settings/data-dictionaries/withdraw-statuses/${entryId}`,
      payload,
    )
  ).data
}

export async function syncWithdrawStatuses(sourceId: string): Promise<WithdrawStatusSyncResult> {
  return (
    await api.post<WithdrawStatusSyncResult>('/settings/data-dictionaries/withdraw-statuses/sync', {
      sourceId,
    })
  ).data
}
