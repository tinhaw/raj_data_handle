import { computed, ref } from 'vue'

import { fetchMe, logout as logoutRequest } from '../api/auth'
import { fetchMyErpAccess } from '../api/erpAccess'
import type { AuthUser, ErpUserAccess } from '../types'

export const currentUser = ref<AuthUser | null>(null)
export const authReady = ref(false)
export const isAdmin = computed(() => currentUser.value?.role === 'admin')
export const erpAccess = ref<ErpUserAccess | null>(null)
export const erpPermissions = computed(() => new Set(erpAccess.value?.effectivePermissions || []))

export function hasErpPermission(permission: string): boolean {
  return erpPermissions.value.has(permission)
}

let loadingPromise: Promise<AuthUser | null> | null = null
let erpAccessPromise: Promise<ErpUserAccess | null> | null = null

export async function ensureErpAccess(): Promise<ErpUserAccess | null> {
  if (erpAccess.value) return erpAccess.value
  if (!currentUser.value) return null
  if (!erpAccessPromise) {
    erpAccessPromise = fetchMyErpAccess()
      .then((access) => {
        erpAccess.value = access
        return access
      })
      .catch(() => null)
      .finally(() => {
        erpAccessPromise = null
      })
  }
  return erpAccessPromise
}

export async function ensureAuth(): Promise<AuthUser | null> {
  if (currentUser.value) {
    await ensureErpAccess()
    authReady.value = true
    return currentUser.value
  }
  if (!loadingPromise) {
    loadingPromise = fetchMe()
      .then(async (user) => {
        currentUser.value = user
        await ensureErpAccess()
        return user
      })
      .catch(() => null)
      .finally(() => {
        authReady.value = true
        loadingPromise = null
      })
  }
  return loadingPromise
}

export function setCurrentUser(user: AuthUser): void {
  currentUser.value = user
  authReady.value = true
  void ensureErpAccess()
}

export async function clearSession(): Promise<void> {
  try {
    await logoutRequest()
  } finally {
    currentUser.value = null
    erpAccess.value = null
    authReady.value = true
  }
}
