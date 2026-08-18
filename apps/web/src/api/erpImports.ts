import { api } from './client'
import type { ErpImportConflictStrategy, ErpImportJob, ErpImportPreview } from '../types'

export async function fetchErpImportJobs(): Promise<ErpImportJob[]> {
  return (await api.get<ErpImportJob[]>('/erp/imports')).data
}

export async function fetchErpImportJob(jobId: string): Promise<ErpImportPreview> {
  return (await api.get<ErpImportPreview>(`/erp/imports/${jobId}`)).data
}

export async function downloadErpImportArtifact(
  path: string,
  filename: string,
): Promise<void> {
  const response = await api.get<Blob>(path, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export async function previewErpPasteImport(payload: {
  text: string
  operatorLineId: string
  conflictStrategy: ErpImportConflictStrategy
  businessYear?: number
}): Promise<ErpImportPreview> {
  return (await api.post<ErpImportPreview>('/erp/imports/paste/preview', payload)).data
}

export async function previewErpExcelImport(payload: {
  file: File
  operatorLineId: string
  conflictStrategy: ErpImportConflictStrategy
  businessYear?: number
}): Promise<ErpImportPreview> {
  const form = new FormData()
  form.set('file', payload.file)
  form.set('operator_line_id', payload.operatorLineId)
  form.set('conflict_strategy', payload.conflictStrategy)
  if (payload.businessYear) form.set('business_year', String(payload.businessYear))
  return (await api.post<ErpImportPreview>('/erp/imports/excel/preview', form)).data
}

export async function commitErpImport(
  jobId: string,
  conflictStrategy: ErpImportConflictStrategy,
): Promise<void> {
  await api.post(`/erp/imports/${jobId}/commit`, { conflictStrategy })
}
