import { createRouter, createWebHistory } from 'vue-router'

import { recordPageAccess } from '../api/auth'
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
      redirect: '/workspace',
    },
    {
      path: '/workspace',
      component: () => import('../views/ErpMigrationView.vue'),
      meta: {
        navKey: '/workspace',
        title: '工作台',
        migrationDescription: '统一工作台将汇总 ERP 业务进度与数据对账状态。',
      },
    },
    {
      path: '/erp/operators',
      component: () => import('../views/ErpOperatorsView.vue'),
      meta: {
        navKey: '/erp/operators',
        title: '投放公司与投放线',
      },
    },
    {
      path: '/erp/balances',
      component: () => import('../views/ErpBalancesView.vue'),
      meta: {
        navKey: '/erp/balances',
        title: '输入台账',
      },
    },
    {
      path: '/erp/imports',
      component: () => import('../views/ErpImportsView.vue'),
      meta: {
        navKey: '/erp/imports',
        title: '导入中心',
      },
    },
    {
      path: '/erp/redemption',
      component: () => import('../views/ErpRedemptionView.vue'),
      meta: {
        navKey: '/erp/redemption',
        title: '兑换码管理',
      },
    },
    {
      path: '/erp/reports',
      component: () => import('../views/ErpReportsView.vue'),
      meta: {
        navKey: '/erp/reports',
        title: '汇总报表',
      },
    },
    {
      path: '/erp/remote-connections',
      component: () => import('../views/ErpMigrationView.vue'),
      meta: {
        navKey: '/erp/remote-connections',
        admin: true,
        title: 'ERP 业务授权',
        migrationDescription: '在统一的远端账号体系中，为已配置账号授予 ERP 兑换业务能力。',
      },
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
      path: '/settings/totp-codes',
      component: () => import('../views/TotpCodesView.vue'),
      meta: { navKey: '/settings/totp-codes', admin: true },
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
      path: '/settings/user-logs',
      component: () => import('../views/UserLogsView.vue'),
      meta: { navKey: '/settings/user-logs', admin: true },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/workspace',
    },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.path === '/login' && (currentUser.value || (await ensureAuth()))) {
      return '/workspace'
    }
    return true
  }
  const user = await ensureAuth()
  if (!user) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && user.role !== 'admin') {
    return '/workspace'
  }
  return true
})

router.afterEach((to, _from, failure) => {
  if (failure || to.meta.public) return
  void recordPageAccess(to.path).catch(() => {
    // A failed audit write must not interrupt normal page navigation.
  })
})

export default router
