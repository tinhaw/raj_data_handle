import { api } from './client'
import type { ErpAuditLogList } from '../types'

export async function fetchErpAuditLogs(params: {
  dateFrom: string
  dateTo: string
  action?: string
  operatorId?: string
  page?: number
  pageSize?: number
}): Promise<ErpAuditLogList> {
  return (
    await api.get<ErpAuditLogList>('/erp/audit-logs', {
      params: {
        date_from: params.dateFrom,
        date_to: params.dateTo,
        action: params.action,
        operator_id: params.operatorId,
        page: params.page,
        page_size: params.pageSize,
      },
    })
  ).data
}
