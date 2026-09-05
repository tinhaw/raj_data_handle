import { api } from './client'
import type {
  ErpRedemptionBatch,
  ErpRedemptionBatchDetail,
  ErpRedemptionCampaign,
  ErpRedemptionRemoteExecution,
  ErpRedemptionRemotePlan,
  ErpRedemptionTask,
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

export async function downloadErpRedemptionTask(taskId: string): Promise<Blob> {
  return (await api.get(`/erp/redemption/tasks/${taskId}/export`, { responseType: 'blob' })).data
}

export async function fetchErpRedemptionTasks(campaignId?: string): Promise<ErpRedemptionTask[]> {
  return (
    await api.get<ErpRedemptionTask[]>('/erp/redemption/tasks', {
      params: { campaign_id: campaignId },
    })
  ).data
}

export async function createErpRedemptionTask(payload: {
  campaignId: string
  taskName?: string
  claimDateFrom: string
  claimDateTo: string
  remoteAccountIds: string[]
}): Promise<ErpRedemptionTask> {
  return (await api.post<ErpRedemptionTask>('/erp/redemption/tasks', payload)).data
}

export interface ErpRedemptionRemotePlanWrite {
  redemptionType: 'SEVEN_DAY_DEPOSIT' | 'PREVIOUS_DAY_DEPOSIT'
  publishEnvironment: 'test' | 'prod'
  flowTimes: number
  creationIntervalSeconds: number
  activityRecharge?: string
  activityRechargeCount?: number
  activityId?: number
  keyNumber: number
  singleUserLimit: number
  singleKeyLimit: number
  requireBindBankCard: boolean
  requireBindPhone: boolean
  checkUuid: boolean
  uuidRewardLimit: number
  checkLoginIp: boolean
  loginIpRewardLimit: number
  checkRegisterIp: boolean
  registerIpRewardLimit: number
  tierLabelIds: Record<string, number[]>
  rowVersion?: number
}

export async function fetchErpRedemptionRemotePlan(
  batchId: string,
): Promise<ErpRedemptionRemotePlan | null> {
  return (
    await api.get<ErpRedemptionRemotePlan | null>(
      `/erp/redemption/batches/${batchId}/remote-plan`,
    )
  ).data
}

export async function saveErpRedemptionRemotePlan(
  batchId: string,
  payload: ErpRedemptionRemotePlanWrite,
): Promise<ErpRedemptionRemotePlan> {
  return (
    await api.put<ErpRedemptionRemotePlan>(
      `/erp/redemption/batches/${batchId}/remote-plan`,
      payload,
    )
  ).data
}

export async function saveErpRedemptionTaskRemotePlans(
  taskId: string,
  payload: Omit<ErpRedemptionRemotePlanWrite, 'tierLabelIds' | 'rowVersion'>,
): Promise<ErpRedemptionRemotePlan[]> {
  return (
    await api.put<ErpRedemptionRemotePlan[]>(
      `/erp/redemption/tasks/${taskId}/remote-plans`,
      payload,
    )
  ).data
}

export async function saveErpRedemptionPublishPlan(
  batchId: string,
  payload: {
    mode: 'IMMEDIATE' | 'SCHEDULED'
    scheduledLocalAt?: string
    fallbackToScheduled: boolean
    note?: string
    rowVersion: number
  },
): Promise<ErpRedemptionRemotePlan> {
  return (
    await api.post<ErpRedemptionRemotePlan>(
      `/erp/redemption/batches/${batchId}/remote-plan/publish`,
      payload,
    )
  ).data
}

export async function cancelLocalErpRedemptionPublishSchedule(
  batchId: string,
  rowVersion: number,
  reason: string,
): Promise<ErpRedemptionRemotePlan> {
  return (
    await api.post<ErpRedemptionRemotePlan>(
      `/erp/redemption/batches/${batchId}/remote-plan/publish/cancel-local`,
      { rowVersion, reason },
    )
  ).data
}

export async function recoverErpRedemptionRemotePlan(
  batchId: string,
  rowVersion: number,
): Promise<ErpRedemptionRemotePlan> {
  return (
    await api.post<ErpRedemptionRemotePlan>(
      `/erp/redemption/batches/${batchId}/remote-plan/recover`,
      { rowVersion },
    )
  ).data
}

export async function fetchErpRedemptionRemoteExecutions(
  batchId: string,
): Promise<ErpRedemptionRemoteExecution[]> {
  return (
    await api.get<ErpRedemptionRemoteExecution[]>(
      `/erp/redemption/batches/${batchId}/remote-executions`,
    )
  ).data
}
