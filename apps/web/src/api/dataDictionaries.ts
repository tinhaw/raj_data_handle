import { api } from './client'
import type {
  DataDictionaryEntry,
  DataDictionaryRefreshConfig,
  RemoteDataDictionaryType,
  UserSourceChannelSyncResult,
  WithdrawStatusSyncResult,
} from '../types'

export async function fetchDataDictionaryRefreshConfig(
  dictionaryType: RemoteDataDictionaryType,
  sourceId: string,
): Promise<DataDictionaryRefreshConfig> {
  return (
    await api.get<DataDictionaryRefreshConfig>(
      `/settings/data-dictionaries/${dictionaryType}/auto-refresh`,
      { params: { source_id: sourceId } },
    )
  ).data
}

export async function updateDataDictionaryRefreshConfig(
  dictionaryType: RemoteDataDictionaryType,
  payload: {
    sourceId: string
    enabled: boolean
    intervalMinutes: DataDictionaryRefreshConfig['intervalMinutes']
  },
): Promise<DataDictionaryRefreshConfig> {
  return (
    await api.put<DataDictionaryRefreshConfig>(
      `/settings/data-dictionaries/${dictionaryType}/auto-refresh`,
      payload,
    )
  ).data
}

export async function fetchChargeStatuses(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/charge-statuses',
    {
      params: {
        source_id: params.sourceId,
        active: params.active,
      },
    },
  )
  return response.data
}

export async function createChargeStatus(payload: {
  sourceId: string
  entryCode: string
  entryLabel: string
  active: boolean
}): Promise<DataDictionaryEntry> {
  return (
    await api.post<DataDictionaryEntry>('/settings/data-dictionaries/charge-statuses', payload)
  ).data
}

export async function updateChargeStatus(
  entryId: number,
  payload: { entryLabel?: string; active?: boolean },
): Promise<DataDictionaryEntry> {
  return (
    await api.patch<DataDictionaryEntry>(
      `/settings/data-dictionaries/charge-statuses/${entryId}`,
      payload,
    )
  ).data
}

export async function fetchPaymentChannels(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/payment-channels',
    {
      params: {
        source_id: params.sourceId,
        active: params.active,
      },
    },
  )
  return response.data
}

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

export async function fetchSpinOrderStatuses(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/spin-order-statuses',
    { params: { source_id: params.sourceId, active: params.active } },
  )
  return response.data
}

export async function fetchUserSourceChannels(params: {
  sourceId?: string
  active?: boolean
} = {}): Promise<DataDictionaryEntry[]> {
  const response = await api.get<DataDictionaryEntry[]>(
    '/settings/data-dictionaries/user-source-channels',
    { params: { source_id: params.sourceId, active: params.active } },
  )
  return response.data
}

export async function refreshUserSourceChannels(
  sourceId: string,
): Promise<UserSourceChannelSyncResult> {
  return (
    await api.post<UserSourceChannelSyncResult>(
      '/settings/data-dictionaries/user-source-channels/refresh',
      { sourceId },
    )
  ).data
}
