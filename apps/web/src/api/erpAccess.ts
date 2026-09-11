import { api } from './client'
import type { ErpRoleDefinition, ErpUserAccess } from '../types'

export async function fetchErpRoles(): Promise<ErpRoleDefinition[]> {
  return (await api.get<ErpRoleDefinition[]>('/erp/access/roles')).data
}

export async function fetchMyErpAccess(): Promise<ErpUserAccess> {
  return (await api.get<ErpUserAccess>('/erp/access/me')).data
}

export async function fetchErpUserAccess(userId: number): Promise<ErpUserAccess> {
  return (await api.get<ErpUserAccess>(`/erp/access/users/${userId}`)).data
}

export async function updateErpUserAccess(
  userId: number,
  payload: {
    roleGrants: string[]
    allOperators: boolean
    operatorIds: string[]
  },
): Promise<ErpUserAccess> {
  return (await api.put<ErpUserAccess>(`/erp/access/users/${userId}`, payload)).data
}
