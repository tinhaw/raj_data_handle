import { api } from './client'
import type { SourceConfig } from '../types'

export async function fetchEnabledSources(): Promise<SourceConfig[]> {
  return (await api.get<SourceConfig[]>('/sources', { params: { enabled: true } })).data
}

export async function fetchAllSources(): Promise<SourceConfig[]> {
  return (await api.get<SourceConfig[]>('/settings/sources')).data
}

export async function createSource(payload: Record<string, unknown>): Promise<SourceConfig> {
  return (await api.post<SourceConfig>('/settings/sources', payload)).data
}

export async function updateSource(
  sourceId: string,
  payload: Record<string, unknown>,
): Promise<SourceConfig> {
  return (await api.patch<SourceConfig>(`/settings/sources/${sourceId}`, payload)).data
}

export async function testSourceConnection(
  sourceId: string,
): Promise<{ sourceId: string; status: string; requestId: string; message: string }> {
  return (
    await api.post<{ sourceId: string; status: string; requestId: string; message: string }>(
      `/settings/sources/${sourceId}/test-connection`,
    )
  ).data
}

export async function clearSourceCredentials(sourceId: string): Promise<SourceConfig> {
  return (await api.delete<SourceConfig>(`/settings/sources/${sourceId}/credentials`)).data
}

export async function deleteSource(sourceId: string): Promise<void> {
  await api.delete(`/settings/sources/${sourceId}`)
}
