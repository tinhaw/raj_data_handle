import { api } from './client'
import type { TotpAccount, TotpCodeList } from '../types'

export async function generateTotpCodes(): Promise<TotpCodeList> {
  return (await api.post<TotpCodeList>('/settings/totp-codes/generate')).data
}

export async function createTotpAccount(
  payload: Record<string, unknown>,
): Promise<TotpAccount> {
  return (await api.post<TotpAccount>('/settings/totp-accounts', payload)).data
}

export async function updateTotpAccount(
  accountId: string,
  payload: Record<string, unknown>,
): Promise<TotpAccount> {
  return (await api.patch<TotpAccount>(`/settings/totp-accounts/${accountId}`, payload)).data
}

export async function deleteTotpAccount(accountId: string): Promise<void> {
  await api.delete(`/settings/totp-accounts/${accountId}`)
}
