import { api } from './client'
import type { UserNotification } from '../types'

export async function fetchUnreadNotifications(): Promise<UserNotification[]> {
  return (await api.get<UserNotification[]>('/notifications', { params: { unread: true } })).data
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await api.post(`/notifications/${notificationId}/read`)
}
