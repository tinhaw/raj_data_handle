import { api } from './client'
import type { AuthUser, Captcha, UserLogQueryResponse, UserRecord } from '../types'

export async function fetchCaptcha(): Promise<Captcha> {
  return (await api.get<Captcha>('/auth/captcha')).data
}

export async function login(payload: {
  username: string
  password: string
  captchaId: string
  captchaCode: string
}): Promise<AuthUser> {
  return (await api.post<AuthUser>('/auth/login', payload)).data
}

export async function fetchMe(): Promise<AuthUser> {
  return (await api.get<AuthUser>('/auth/me')).data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}

export async function recordPageAccess(path: string): Promise<void> {
  await api.post('/auth/user-logs/access', { path })
}

export async function queryUserLogs(payload: {
  userId?: number
  eventTypes?: Array<'login' | 'access'>
  startedAt?: string
  endedAt?: string
  page: number
  pageSize: number
}): Promise<UserLogQueryResponse> {
  return (await api.post<UserLogQueryResponse>('/auth/user-logs/query', payload)).data
}

export async function fetchUsers(): Promise<UserRecord[]> {
  return (await api.get<UserRecord[]>('/auth/users')).data
}

export async function createUser(payload: {
  username: string
  password: string
  displayName: string
  role: 'admin' | 'user'
}): Promise<UserRecord> {
  return (await api.post<UserRecord>('/auth/users', payload)).data
}

export async function updateUser(
  userId: number,
  payload: {
    displayName?: string
    role?: 'admin' | 'user'
    isActive?: boolean
    password?: string
  },
): Promise<UserRecord> {
  return (await api.patch<UserRecord>(`/auth/users/${userId}`, payload)).data
}
