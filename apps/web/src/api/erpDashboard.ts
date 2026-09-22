import { api } from './client'
import type { ErpDashboard } from '../types'

export async function fetchErpDashboard(businessDate: string): Promise<ErpDashboard> {
  return (await api.get<ErpDashboard>('/erp/dashboard', { params: { business_date: businessDate } })).data
}
