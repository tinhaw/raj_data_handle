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
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/workspace',
        title: '工作台',
        erpPermission: 'ERP_WORKSPACE_VIEW',
        erpCompatComponent: '../../../erp-compat/web/src/modules/dashboard/DashboardPage.vue',
      },
    },
    {
      path: '/erp/operators',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/operators',
        title: '投放公司与投放线',
        erpPermission: 'ERP_OPERATOR_VIEW',
        erpCompatComponent: '../../../erp-compat/web/src/modules/operators/OperatorsPage.vue',
      },
    },
    {
      path: '/erp/balances',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/balances',
        title: '输入台账',
        erpPermission: 'ERP_LEDGER_VIEW',
        erpCompatComponent: '../../../erp-compat/web/src/modules/balances/BalanceLedgerPage.vue',
      },
    },
    {
      path: '/erp/imports',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/imports',
        title: '导入中心',
        erpPermission: 'ERP_IMPORT',
        erpCompatComponent: '../../../erp-compat/web/src/modules/imports/ImportCenterPage.vue',
      },
    },
    {
      path: '/erp/redemption',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/redemption',
        title: '兑换码管理',
        erpPermission: 'ERP_REDEMPTION_VIEW',
        erpCompatComponent: '../../../erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue',
      },
    },
    {
      path: '/erp/reports',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/reports',
        title: '汇总报表',
        erpPermission: 'ERP_REPORT_VIEW',
        erpCompatComponent: '../../../erp-compat/web/src/modules/reports/ReportsPage.vue',
      },
    },
    {
      path: '/erp/audit',
      component: () => import('../components/ErpCompatibilityModule.vue'),
      meta: {
        navKey: '/erp/audit',
        erpPermission: 'ERP_AUDIT_VIEW',
        title: '审计日志',
        erpCompatComponent: '../../../erp-compat/web/src/modules/audit/AuditPage.vue',
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
    // Preserve links embedded in the deployed ERP source while keeping the
    // merged application's canonical navigation under /workspace and /erp/*.
    { path: '/dashboard', redirect: '/workspace' },
    { path: '/operators', redirect: '/erp/operators' },
    { path: '/balances', redirect: '/erp/balances' },
    { path: '/imports', redirect: '/erp/imports' },
    { path: '/redemption', redirect: '/erp/redemption' },
    { path: '/reports', redirect: '/erp/reports' },
    { path: '/audit', redirect: '/erp/audit' },
    {
      path: '/erp-preview',
      component: () => import('../components/ErpCompatibilityFrame.vue'),
      children: [
        {
          path: '',
          redirect: '/erp-preview/dashboard',
        },
        {
          path: 'dashboard',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/workspace', title: '工作台 · 原版预览', erpPermission: 'ERP_WORKSPACE_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/dashboard/DashboardPage.vue' },
        },
        {
          path: 'operators',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/operators', title: '投放公司与投放线 · 原版预览', erpPermission: 'ERP_OPERATOR_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/operators/OperatorsPage.vue' },
        },
        {
          path: 'balances',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/balances', title: '输入台账 · 原版预览', erpPermission: 'ERP_LEDGER_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/balances/BalanceLedgerPage.vue' },
        },
        {
          path: 'imports',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/imports', title: '导入中心 · 原版预览', erpPermission: 'ERP_IMPORT', erpCompatComponent: '../../../erp-compat/web/src/modules/imports/ImportCenterPage.vue' },
        },
        {
          path: 'redemption',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/redemption', title: '兑换码管理 · 原版预览', erpPermission: 'ERP_REDEMPTION_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue' },
        },
        {
          path: 'reports',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/reports', title: '汇总报表 · 原版预览', erpPermission: 'ERP_REPORT_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/reports/ReportsPage.vue' },
        },
        {
          path: 'audit',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/audit', title: '审计日志 · 原版预览', erpPermission: 'ERP_AUDIT_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/audit/AuditPage.vue' },
        },
        {
          path: 'remote-connections',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/erp/remote-connections', title: '远端连接 · 原版预览', erpPermission: 'ERP_REDEMPTION_VIEW', erpCompatComponent: '../../../erp-compat/web/src/modules/redemption/RemoteConnectionsPage.vue' },
        },
        {
          path: 'users',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/settings/users', title: '用户与权限 · 原版预览', admin: true, erpPermission: 'ERP_ACCESS_MANAGE', erpCompatComponent: '../../../erp-compat/web/src/modules/users/UsersPage.vue' },
        },
        {
          path: 'settings',
          component: () => import('../components/ErpCompatibilityModule.vue'),
          meta: { navKey: '/settings/system', title: '系统设置 · 原版预览', admin: true, erpCompatComponent: '../../../erp-compat/web/src/modules/settings/SettingsPage.vue' },
        },
      ],
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
