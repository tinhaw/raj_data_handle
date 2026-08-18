import { createRouter, createWebHistory } from 'vue-router'

import { recordPageAccess } from '../api/auth'
import { currentUser, ensureAuth, ensureErpAccess, hasErpPermission } from '../stores/auth'

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
      component: () => import('../views/ErpDashboardView.vue'),
      meta: {
        navKey: '/workspace',
        title: '工作台',
        erpPermission: 'ERP_WORKSPACE_VIEW',
      },
    },
    {
      path: '/erp/operators',
      component: () => import('../views/ErpOperatorsView.vue'),
      meta: {
        navKey: '/erp/operators',
        title: '投放公司与投放线',
        erpPermission: 'ERP_OPERATOR_VIEW',
      },
    },
    {
      path: '/erp/balances',
      component: () => import('../views/ErpBalancesView.vue'),
      meta: {
        navKey: '/erp/balances',
        title: '输入台账',
        erpPermission: 'ERP_LEDGER_VIEW',
      },
    },
    {
      path: '/erp/imports',
      component: () => import('../views/ErpImportsView.vue'),
      meta: {
        navKey: '/erp/imports',
        title: '导入中心',
        erpPermission: 'ERP_IMPORT',
      },
    },
    {
      path: '/erp/redemption',
      component: () => import('../views/ErpRedemptionView.vue'),
      meta: {
        navKey: '/erp/redemption',
        title: '兑换码管理',
        erpPermission: 'ERP_REDEMPTION_VIEW',
      },
    },
    {
      path: '/erp/reports',
      component: () => import('../views/ErpReportsView.vue'),
      meta: {
        navKey: '/erp/reports',
        title: '汇总报表',
        erpPermission: 'ERP_REPORT_VIEW',
      },
    },
    {
      path: '/erp/audit',
      component: () => import('../views/ErpAuditView.vue'),
      meta: {
        navKey: '/erp/audit',
        erpPermission: 'ERP_AUDIT_VIEW',
        title: '审计日志',
      },
    },
    {
      path: '/erp/remote-connections',
      component: () => import('../views/RemoteAccountsView.vue'),
      meta: {
        navKey: '/erp/remote-connections',
        erpPermission: 'ERP_REDEMPTION_VIEW',
        title: '远端账号与业务授权',
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
  await ensureErpAccess()
  if (to.meta.admin && user.role !== 'admin') {
    return '/workspace'
  }
  if (typeof to.meta.erpPermission === 'string' && !hasErpPermission(to.meta.erpPermission)) {
    return '/batches'
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
