import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import AppLayout from '@/layouts/AppLayout.vue'
import { useSessionStore } from '@/stores/session'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/modules/auth/LoginPage.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', redirect: { name: 'dashboard' } },
      { path: 'dashboard', name: 'dashboard', component: () => import('@/modules/dashboard/DashboardPage.vue'), meta: { title: '工作台' } },
      { path: 'balances', name: 'balances', component: () => import('@/modules/balances/BalanceLedgerPage.vue'), meta: { title: '输入台账' } },
      { path: 'reports', name: 'reports', component: () => import('@/modules/reports/ReportsPage.vue'), meta: { title: '汇总报表' } },
      { path: 'imports', name: 'imports', component: () => import('@/modules/imports/ImportCenterPage.vue'), meta: { title: '导入中心' } },
      { path: 'redemption', name: 'redemption', component: () => import('@/modules/redemption/RedemptionCampaignPage.vue'), meta: { title: '兑换码管理' } },
      { path: 'remote-connections', name: 'remote-connections', component: () => import('@/modules/redemption/RemoteConnectionsPage.vue'), meta: { title: '远端连接' } },
      { path: 'operators', name: 'operators', component: () => import('@/modules/operators/OperatorsPage.vue'), meta: { title: '投放公司管理' } },
      { path: 'users', name: 'users', component: () => import('@/modules/users/UsersPage.vue'), meta: { title: '用户与权限' } },
      { path: 'audit', name: 'audit', component: () => import('@/modules/audit/AuditPage.vue'), meta: { title: '审计日志' } },
      { path: 'settings', name: 'settings', component: () => import('@/modules/settings/SettingsPage.vue'), meta: { title: '系统设置' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (!session.ready) await session.restore()
  if (!to.meta.public && !session.loggedIn) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && session.loggedIn) return { name: 'dashboard' }
  return true
})

export default router
