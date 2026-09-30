import { api } from './client'
import type { ErpReportResponse } from '../types'

export interface ErpReportQuery {
  operatorIds?: string[]
  operatorLineIds?: string[]
  asset?: 'USDT' | 'USDC'
  includeDraft?: boolean
  nominalU?: boolean
}

export async function fetchErpDailyReport(
  dateFrom: string,
  dateTo: string,
  query: ErpReportQuery = {},
): Promise<ErpReportResponse> {
  return (
    await api.get<ErpReportResponse>('/erp/reports/daily', {
      params: {
        date_from: dateFrom,
        date_to: dateTo,
        operator_ids: query.operatorIds,
        operator_line_ids: query.operatorLineIds,
        asset: query.asset,
        include_draft: query.includeDraft,
        nominal_u: query.nominalU,
      },
    })
  ).data
}

export async function fetchErpMonthlyReport(
  monthFrom: string,
  monthTo: string,
  query: ErpReportQuery = {},
): Promise<ErpReportResponse> {
  return (
    await api.get<ErpReportResponse>('/erp/reports/monthly', {
      params: {
        month_from: monthFrom,
        month_to: monthTo,
        operator_ids: query.operatorIds,
        operator_line_ids: query.operatorLineIds,
        asset: query.asset,
        include_draft: query.includeDraft,
        nominal_u: query.nominalU,
      },
    })
  ).data
}

export async function downloadErpReport(
  type: 'daily' | 'monthly',
  range: { from: string; to: string },
  query: ErpReportQuery = {},
): Promise<Blob> {
  const path = type === 'daily' ? '/erp/reports/daily/export' : '/erp/reports/monthly/export'
  const params = type === 'daily'
    ? { date_from: range.from, date_to: range.to }
    : { month_from: range.from, month_to: range.to }
  Object.assign(params, {
    operator_ids: query.operatorIds,
    operator_line_ids: query.operatorLineIds,
    asset: query.asset,
    include_draft: query.includeDraft,
    nominal_u: query.nominalU,
  })
  return (await api.get(path, { params, responseType: 'blob' })).data
}
