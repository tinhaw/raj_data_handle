import { api } from './client'
import type {
  RemoteAccount,
  RemoteAccountCapabilityDefinition,
  RemoteTag,
  RemoteTagSnapshot,
  RewardTierPreset,
  RewardTierPresetTier,
} from '../types'

export async function fetchRemoteAccountCapabilities(): Promise<RemoteAccountCapabilityDefinition[]> {
  return (await api.get<RemoteAccountCapabilityDefinition[]>('/erp/remote-accounts/capabilities')).data
}

export async function fetchRemoteAccounts(): Promise<RemoteAccount[]> {
  return (await api.get<RemoteAccount[]>('/erp/remote-accounts')).data
}

export async function createRemoteAccount(payload: {
  sourceId: string
  loginUsername: string
  displayName: string
  enabled: boolean
  credentials: { password: string; totpSecret: string }
}): Promise<RemoteAccount> {
  return (await api.post<RemoteAccount>('/erp/remote-accounts', payload)).data
}

export async function updateRemoteAccount(
  accountId: string,
  payload: {
    loginUsername?: string
    displayName?: string
    enabled?: boolean
    credentials?: { password?: string; totpSecret?: string }
  },
): Promise<RemoteAccount> {
  return (await api.patch<RemoteAccount>(`/erp/remote-accounts/${accountId}`, payload)).data
}

export async function updateRemoteAccountCapabilities(
  accountId: string,
  capabilities: Record<string, boolean>,
): Promise<RemoteAccount> {
  return (
    await api.put<RemoteAccount>(`/erp/remote-accounts/${accountId}/capabilities`, {
      capabilities,
    })
  ).data
}

export async function fetchRemoteTagSnapshot(accountId: string): Promise<RemoteTagSnapshot> {
  return (await api.get<RemoteTagSnapshot>(`/erp/remote-accounts/${accountId}/tags`)).data
}

export async function saveRemoteTagSnapshot(
  accountId: string,
  tags: RemoteTag[],
): Promise<RemoteTagSnapshot> {
  return (await api.put<RemoteTagSnapshot>(`/erp/remote-accounts/${accountId}/tags/snapshot`, {
    tags,
    source: 'MIGRATED',
  })).data
}

export async function fetchRewardTierPreset(accountId: string): Promise<RewardTierPreset> {
  return (await api.get<RewardTierPreset>(`/erp/remote-accounts/${accountId}/reward-tier-preset`)).data
}

export async function saveRewardTierPreset(
  accountId: string,
  tiers: RewardTierPresetTier[],
  tagSnapshot: RemoteTag[],
): Promise<RewardTierPreset> {
  return (await api.put<RewardTierPreset>(`/erp/remote-accounts/${accountId}/reward-tier-preset`, {
    tiers,
    tagSnapshot,
  })).data
}
