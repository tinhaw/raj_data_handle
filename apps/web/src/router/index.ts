import { createRouter, createWebHistory } from 'vue-router'

import { currentUser, ensureAuth } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true, layout: 'blank' },
    },
    {
      path: '/',
      redirect: '/batches',
    },
    {
      path: '/batches',
      component: () => import('../views/BatchListView.vue'),
      meta: { navKey: '/batches' },
    },
    {
      path: '/batches/new',
      component: () => import('../views/NewBatchView.vue'),
      meta: { navKey: '/batches' },
    },
    {
      path: '/batches/:batchId',
      component: () => import('../views/BatchDetailView.vue'),
      meta: { navKey: '/batches' },
    },
    {
      path: '/withdraw-orders',
      component: () => import('../views/WithdrawOrdersView.vue'),
      meta: { navKey: '/withdraw-orders' },
    },
    {
      path: '/spin-orders',
      component: () => import('../views/SpinOrdersView.vue'),
      meta: { navKey: '/spin-orders' },
    },
    {
      path: '/sync-logs',
      component: () => import('../views/SyncLogsView.vue'),
      meta: { navKey: '/sync-logs' },
    },
    {
      path: '/settings/system',
      component: () => import('../views/SystemSettingsView.vue'),
      meta: { navKey: '/settings/system' },
    },
    {
      path: '/settings/sources',
      component: () => import('../views/SourceSettingsView.vue'),
      meta: { navKey: '/settings/sources', admin: true },
    },
    {
      path: '/settings/data-dictionaries',
      component: () => import('../views/DataDictionaryView.vue'),
      meta: { navKey: '/settings/data-dictionaries', admin: true },
    },
    {
      path: '/settings/users',
      component: () => import('../views/UserManagementView.vue'),
      meta: { navKey: '/settings/users', admin: true },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/batches',
    },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.path === '/login' && (currentUser.value || (await ensureAuth()))) {
      return '/batches'
    }
    return true
  }
  const user = await ensureAuth()
  if (!user) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && user.role !== 'admin') {
    return '/batches'
  }
  return true
})

export default router
