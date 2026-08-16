import { api } from './client'
import type { ErpDeliveryLine, ErpOperator } from '../types'

export interface ErpOperatorWrite {
  name: string
  operatorType?: 'COMPANY' | 'STUDIO' | 'INDIVIDUAL'
  contactName?: string | null
  contactValue?: string | null
  remark?: string | null
  rowVersion?: number
}

export interface ErpDeliveryLineWrite {
  name: string
  asset?: 'USDT' | 'USDC'
  rowVersion?: number
}

export async function fetchErpOperators(
  includeInactive = true,
  search?: string,
): Promise<ErpOperator[]> {
  return (
    await api.get<ErpOperator[]>('/erp/operators', {
      params: { includeInactive, search: search || undefined },
    })
  ).data
}

export async function fetchErpOperatorLines(operatorId: string): Promise<ErpDeliveryLine[]> {
  return (await api.get<ErpDeliveryLine[]>(`/erp/operators/${operatorId}/lines`)).data
}

export async function createErpOperator(payload: ErpOperatorWrite): Promise<ErpOperator> {
  return (await api.post<ErpOperator>('/erp/operators', payload)).data
}

export async function updateErpOperator(
  operatorId: string,
  payload: ErpOperatorWrite,
): Promise<ErpOperator> {
  return (await api.patch<ErpOperator>(`/erp/operators/${operatorId}`, payload)).data
}

export async function disableErpOperator(
  operatorId: string,
  rowVersion: number,
): Promise<ErpOperator> {
  return (
    await api.post<ErpOperator>(`/erp/operators/${operatorId}/disable`, undefined, {
      params: { rowVersion },
    })
  ).data
}

export async function createErpDeliveryLine(
  operatorId: string,
  payload: ErpDeliveryLineWrite,
): Promise<ErpDeliveryLine> {
  return (await api.post<ErpDeliveryLine>(`/erp/operators/${operatorId}/lines`, payload)).data
}
