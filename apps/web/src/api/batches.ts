import { api } from './client'
import type {
  BatchCharts,
  BatchList,
  BatchRecord,
  BatchSummary,
  OrderResultList,
  OperationalSummary,
} from '../types'

export async function fetchBatches(params: Record<string, unknown> = {}): Promise<BatchList> {
  return (await api.get<BatchList>('/order-reconciliation/batches', { params })).data
}

export async function fetchOperationalSummary(
  params: Record<string, unknown> = {},
): Promise<OperationalSummary> {
  return (await api.get<OperationalSummary>('/order-reconciliation/operational-summary', { params }))
    .data
}

export async function fetchBatch(batchId: string): Promise<BatchRecord> {
  return (await api.get<BatchRecord>(`/order-reconciliation/batches/${batchId}`)).data
}

export async function fetchBatchSummary(batchId: string): Promise<BatchSummary> {
  return (await api.get<BatchSummary>(`/order-reconciliation/batches/${batchId}/summary`)).data
}

export async function fetchBatchCharts(batchId: string): Promise<BatchCharts> {
  return (await api.get<BatchCharts>(`/order-reconciliation/batches/${batchId}/charts`)).data
}

export async function fetchBatchResults(
  batchId: string,
  params: Record<string, unknown> = {},
): Promise<OrderResultList> {
  return (
    await api.get<OrderResultList>(`/order-reconciliation/batches/${batchId}/results`, {
      params,
    })
  ).data
}

export async function createBatch(payload: {
  sourceId: string
  businessType: 'payin' | 'payout'
  file: File
  parameters?: Record<string, unknown>
}): Promise<{ batch: BatchRecord; duplicateOfExisting: boolean }> {
  const form = new FormData()
  form.set('sourceId', payload.sourceId)
  form.set('businessType', payload.businessType)
  form.set('parametersJson', JSON.stringify(payload.parameters || {}))
  form.set('upload', payload.file)
  return (
    await api.post<{ batch: BatchRecord; duplicateOfExisting: boolean }>(
      '/order-reconciliation/batches',
      form,
    )
  ).data
}

export async function rerunBatch(batchId: string): Promise<BatchRecord> {
  return (await api.post<BatchRecord>(`/order-reconciliation/batches/${batchId}/rerun`)).data
}

export async function confirmBatch(batchId: string): Promise<BatchRecord> {
  return (await api.post<BatchRecord>(`/order-reconciliation/batches/${batchId}/confirm`)).data
}

export async function cancelBatch(batchId: string, reason?: string): Promise<BatchRecord> {
  return (
    await api.post<BatchRecord>(`/order-reconciliation/batches/${batchId}/cancel`, {
      reason: reason || null,
    })
  ).data
}

export async function downloadBatchExport(
  batchId: string,
  format: 'csv' | 'xlsx',
): Promise<void> {
  const response = await api.get<Blob>(
    `/order-reconciliation/batches/${batchId}/export.${format}`,
    { responseType: 'blob' },
  )
  const url = URL.createObjectURL(response.data)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${batchId}.${format}`
  anchor.click()
  URL.revokeObjectURL(url)
}
