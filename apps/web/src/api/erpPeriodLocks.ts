import { api } from './client'
import type {
  ErpPeriodLock,
  ErpPeriodLockValidation,
} from '../types'

export interface ErpPeriodLockWrite {
  month: string
  operatorIds?: string[]
  operatorLineIds?: string[]
}

export interface ErpPeriodUnlockWrite extends ErpPeriodLockWrite {
  reason: string
}

export async function fetchErpPeriodLocks(month: string): Promise<ErpPeriodLock[]> {
  return (await api.get<ErpPeriodLock[]>('/erp/period-locks', { params: { month } })).data
}

export async function validateErpPeriodLock(
  payload: ErpPeriodLockWrite,
): Promise<ErpPeriodLockValidation> {
  return (await api.post<ErpPeriodLockValidation>('/erp/period-locks/validate', payload)).data
}

export async function lockErpPeriod(payload: ErpPeriodLockWrite): Promise<ErpPeriodLock[]> {
  return (await api.post<ErpPeriodLock[]>('/erp/period-locks/lock', payload)).data
}

export async function unlockErpPeriod(payload: ErpPeriodUnlockWrite): Promise<ErpPeriodLock[]> {
  return (await api.post<ErpPeriodLock[]>('/erp/period-locks/unlock', payload)).data
}
