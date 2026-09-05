import { api } from './client'
import type {
  ErpBalanceImpactPreview,
  ErpDailyBalance,
  ErpDailyBalanceList,
} from '../types'

export interface ErpDailyBalanceWrite {
  operatorLineId: string
  businessDate: string
  openingBalance?: string
  openingMode?: 'AUTO' | 'MANUAL'
  openingOverrideReason?: string
  transferAmount?: string
  fraudLossAmount?: string
  fraudDeductionSource?: 'TRANSFER' | 'BALANCE'
  spendAmount?: string
  exchangeLossRate?: string
  exchangeLossBasis?: string
  exchangeLossMode?: 'AUTO' | 'MANUAL'
  exchangeLossAmount?: string
  exchangeLossOverrideReason?: string
  serviceFeeRate?: string
  serviceFeeBasis?: string
  serviceFeeMode?: 'AUTO' | 'MANUAL'
  serviceFeeAmount?: string
  serviceFeeOverrideReason?: string
  refluxAmount?: string
  refundAmount?: string
  otherDeductionAmount?: string
  otherReason?: string
  remark?: string
  rowVersion?: number
}

export async function fetchErpDailyBalances(
  operatorLineId: string,
  month: string,
): Promise<ErpDailyBalanceList> {
  return (
    await api.get<ErpDailyBalanceList>('/erp/daily-balances', {
      params: { operator_line_id: operatorLineId, month },
    })
  ).data
}

export async function createErpDailyBalance(
  payload: ErpDailyBalanceWrite,
): Promise<ErpDailyBalance> {
  return (await api.post<ErpDailyBalance>('/erp/daily-balances', payload)).data
}

export async function updateErpDailyBalance(
  balanceId: string,
  payload: ErpDailyBalanceWrite,
): Promise<ErpDailyBalance> {
  return (await api.put<ErpDailyBalance>(`/erp/daily-balances/${balanceId}`, payload)).data
}

export async function confirmErpDailyBalance(
  balanceId: string,
  rowVersion: number,
): Promise<ErpDailyBalance> {
  return (
    await api.post<ErpDailyBalance>(`/erp/daily-balances/${balanceId}/confirm`, undefined, {
      params: { rowVersion },
    })
  ).data
}

export async function reopenErpDailyBalance(
  balanceId: string,
  payload: { rowVersion: number; reason: string },
): Promise<ErpDailyBalance> {
  return (await api.post<ErpDailyBalance>(`/erp/daily-balances/${balanceId}/reopen`, payload)).data
}

export async function previewErpDailyBalanceImpact(
  payload: ErpDailyBalanceWrite,
): Promise<ErpBalanceImpactPreview> {
  return (await api.post<ErpBalanceImpactPreview>('/erp/daily-balances/impact-preview', payload)).data
}
