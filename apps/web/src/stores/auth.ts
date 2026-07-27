import { computed, ref } from 'vue'

import { fetchMe, logout as logoutRequest } from '../api/auth'
import type { AuthUser } from '../types'

export const currentUser = ref<AuthUser | null>(null)
export const authReady = ref(false)
export const isAdmin = computed(() => currentUser.value?.role === 'admin')

let loadingPromise: Promise<AuthUser | null> | null = null

export async function ensureAuth(): Promise<AuthUser | null> {
  if (currentUser.value) {
    authReady.value = true
    return currentUser.value
  }
  if (!loadingPromise) {
    loadingPromise = fetchMe()
      .then((user) => {
        currentUser.value = user
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
}

export async function clearSession(): Promise<void> {
  try {
    await logoutRequest()
  } finally {
    currentUser.value = null
    authReady.value = true
  }
}
