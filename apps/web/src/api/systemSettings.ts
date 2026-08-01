import { api } from './client'
import type { RetentionSettings } from '../types'

export type RetentionSettingsUpdate = Pick<
  RetentionSettings,
  | 'uploadedFileRetentionDays'
  | 'resultRetentionDays'
  | 'remoteCacheRetentionDays'
  | 'withdrawOrderExportDateMode'
  | 'withdrawOrderExportSpecificDate'
  | 'withdrawOrderExportTime'
  | 'automaticSyncRetryLimit'
  | 'automaticSyncRetryIntervalMinutes'
  | 'chargeOrderExportDateMode'
  | 'chargeOrderExportSpecificDate'
  | 'chargeOrderExportTime'
  | 'spinOrderRefreshIntervalHours'
  | 'spinOrderRefreshPageSize'
  | 'spinOrderQueryRange'
  | 'sessionTtlDays'
>

export async function fetchRetentionSettings(): Promise<RetentionSettings> {
  const response = await api.get<RetentionSettings>('/system-settings/retention')
  return response.data
}

export async function updateRetentionSettings(
  payload: RetentionSettingsUpdate,
): Promise<RetentionSettings> {
  const response = await api.patch<RetentionSettings>(
    '/system-settings/retention',
    payload,
  )
  return response.data
}
