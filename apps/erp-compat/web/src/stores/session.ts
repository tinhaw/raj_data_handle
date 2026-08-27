import { defineStore } from 'pinia'
import { api, ApiError, isServiceUnavailable } from '@/api/client'
import type { CurrentUser } from '@/api/types'
import { demoEnabled } from '@/utils/runtime'

const demoUser: CurrentUser = {
  id: 'demo-admin',
  username: 'admin',
  displayName: '演示管理员',
  roles: ['SUPER_ADMIN'],
  permissions: ['*'],
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    user: null as CurrentUser | null,
    ready: false,
    demoMode: false,
  }),
  getters: {
    loggedIn: (state) => Boolean(state.user),
  },
  actions: {
    async restore() {
      try {
        this.user = await api.auth.me()
        await api.auth.csrf()
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          this.demoMode = demoEnabled && isServiceUnavailable(error)
        }
      } finally {
        this.ready = true
      }
    },
    async login(username: string, password: string) {
      try {
        this.user = await api.auth.login(username, password)
        await api.auth.csrf()
        this.demoMode = false
      } catch (error) {
        if (!demoEnabled || !isServiceUnavailable(error)) throw error
        this.user = { ...demoUser, username: username || demoUser.username }
        this.demoMode = true
      }
    },
    async logout() {
      try {
        if (!this.demoMode) await api.auth.logout()
      } finally {
        this.user = null
        this.demoMode = false
      }
    },
  },
})
