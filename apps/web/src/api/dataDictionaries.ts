import { api } from './client'
import type { DataDictionaryEntry } from '../types'

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
