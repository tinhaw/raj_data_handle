import { api } from './client'
import type {
  ErpRedemptionBatch,
  ErpRedemptionBatchDetail,
  ErpRedemptionCampaign,
} from '../types'

export interface ErpRedemptionCampaignWrite {
  code: string
  name: string
  lookbackDays?: number
  description?: string
  tiers: Array<{
    displayName?: string
    minDepositAmount: string
    bonusAmount: string
    bonusMaxAmount?: string
    sortOrder?: number
  }>
}

export async function fetchErpRedemptionCampaigns(): Promise<ErpRedemptionCampaign[]> {
  return (await api.get<ErpRedemptionCampaign[]>('/erp/redemption/campaigns')).data
}

export async function createErpRedemptionCampaign(
  payload: ErpRedemptionCampaignWrite,
): Promise<ErpRedemptionCampaign> {
  return (await api.post<ErpRedemptionCampaign>('/erp/redemption/campaigns', payload)).data
}

export async function fetchErpRedemptionBatches(campaignId: string): Promise<ErpRedemptionBatch[]> {
  return (await api.get<ErpRedemptionBatch[]>(`/erp/redemption/campaigns/${campaignId}/batches`)).data
}

export async function createErpRedemptionBatch(payload: {
  campaignId: string
  claimDateFrom: string
  claimDateTo: string
}): Promise<ErpRedemptionBatchDetail> {
  return (await api.post<ErpRedemptionBatchDetail>('/erp/redemption/batches', payload)).data
}

export async function fetchErpRedemptionBatch(batchId: string): Promise<ErpRedemptionBatchDetail> {
  return (await api.get<ErpRedemptionBatchDetail>(`/erp/redemption/batches/${batchId}`)).data
}

export async function importErpRedemptionCodes(
  batchId: string,
  rows: Array<{ issueId: string; redemptionCode: string; localReference?: string; rowVersion: number }>,
): Promise<ErpRedemptionBatchDetail> {
  return (await api.post<ErpRedemptionBatchDetail>(`/erp/redemption/batches/${batchId}/codes`, { rows })).data
}

export async function publishErpRedemptionBatchLocal(
  batchId: string,
  rowVersion: number,
): Promise<ErpRedemptionBatchDetail> {
  return (await api.post<ErpRedemptionBatchDetail>(`/erp/redemption/batches/${batchId}/publish-local`, { rowVersion })).data
}

export async function downloadErpRedemptionBatch(batchId: string): Promise<Blob> {
  return (await api.get(`/erp/redemption/batches/${batchId}/export`, { responseType: 'blob' })).data
}
