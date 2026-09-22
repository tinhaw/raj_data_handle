<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { apiErrorMessage } from '../api/client'
import { fetchErpDashboard } from '../api/erpDashboard'
import type { ErpDashboard, ErpDashboardHealthItem } from '../types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function amount(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString()
}

const router = useRouter()
const businessDate = ref(today())
const dashboard = ref<ErpDashboard | null>(null)
const loading = ref(false)

const metrics = computed(() => dashboard.value ? [
  {
    label: '当前期初结余',
    value: amount(dashboard.value.metric.openingBalance),
    note: `${dashboard.value.metric.activeOperatorCount} 个投放公司`,
    tone: 'neutral',
  },
  {
    label: '当日转 U',
    value: amount(dashboard.value.metric.transferAmount),
    note: 'USDT / USDC 名义合计',
    tone: 'blue',
  },
  {
    label: '当日消耗',
    value: amount(dashboard.value.metric.spendAmount),
    note: '包含当前本地草稿',
    tone: 'orange',
  },
  {
    label: '当前期末结余',
    value: amount(dashboard.value.metric.closingBalance),
    note: `${dashboard.value.metric.activeLineCount} 条投放线`,
    tone: 'green',
  },
] : [])

const trendMax = computed(() => Math.max(
  1,
  ...((dashboard.value?.trend || []).map((item) => Math.abs(Number(item.closingBalance)))),
))

function trendHeight(value: string): string {
  return `${Math.max(8, Math.round((Math.abs(Number(value)) / trendMax.value) * 148))}px`
}

function healthType(item: ErpDashboardHealthItem): 'info' | 'warning' | 'danger' {
  if (item.severity === 'DANGER') return 'danger'
  if (item.severity === 'WARNING') return 'warning'
  return 'info'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    dashboard.value = await fetchErpDashboard(businessDate.value)
  } catch (error) {
    dashboard.value = null
    ElMessage.error(apiErrorMessage(error, '工作台加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
  }
}

watch(businessDate, () => void load())
onMounted(() => void load())
</script>

<template>
  <div class="page-stack erp-dashboard-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">ERP workbench</span>
        <h1>工作台</h1>
        <p>汇总本地日结、期间锁定和导入质量；不读取或操作远端 ERP 业务数据。</p>
      </div>
      <div class="header-actions">
        <el-date-picker v-model="businessDate" type="date" value-format="YYYY-MM-DD" />
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="router.push('/erp/balances')">新建日结</el-button>
      </div>
    </header>

    <section v-loading="loading" class="metric-grid">
      <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="`metric-card--${metric.tone}`">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.note }}</small>
      </article>
    </section>

    <section class="dashboard-grid">
      <article class="surface-card panel-card trend-card">
        <div class="panel-heading"><div><h2>近期结余趋势</h2><p>最近 7 个业务日 · 名义 U</p></div><el-tag effect="plain">含草稿</el-tag></div>
        <div class="trend-bars" aria-label="近期结余趋势">
          <div v-for="item in dashboard?.trend || []" :key="item.businessDate" class="trend-column">
            <span class="trend-value">{{ amount(item.closingBalance) }}</span>
            <div class="trend-track"><i :style="{ height: trendHeight(item.closingBalance) }" /></div>
            <small>{{ item.businessDate.slice(5).replace('-', '/') }}</small>
          </div>
        </div>
      </article>

      <article class="surface-card panel-card health-card">
        <div class="panel-heading"><div><h2>数据质量提醒</h2><p>需要优先处理的本地业务事项</p></div></div>
        <button
          v-for="item in dashboard?.healthItems || []"
          :key="item.code"
          class="health-item"
          type="button"
          @click="router.push(item.targetPath)"
        >
          <el-tag :type="healthType(item)" effect="light">{{ item.count }}</el-tag>
          <span><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
        </button>
      </article>
    </section>

    <section class="surface-card table-card">
      <div class="panel-heading"><div><h2>最近日结记录</h2><p>显示全部本地投放线的最近更新记录。</p></div><el-button text type="primary" @click="router.push('/erp/reports')">查看汇总报表</el-button></div>
      <el-table :data="dashboard?.recentBalances || []" row-key="id" empty-text="暂无本地 ERP 日结记录">
        <el-table-column prop="businessDate" label="业务日" width="115" />
        <el-table-column label="投放公司 / 线" min-width="210"><template #default="{ row }">{{ row.operatorName }} · {{ row.operatorLineName }}</template></el-table-column>
        <el-table-column prop="asset" label="币种" width="85" />
        <el-table-column label="期初" min-width="110" align="right"><template #default="{ row }">{{ amount(row.openingBalance) }}</template></el-table-column>
        <el-table-column label="转 U" min-width="110" align="right"><template #default="{ row }">{{ amount(row.transferAmount) }}</template></el-table-column>
        <el-table-column label="消耗" min-width="110" align="right"><template #default="{ row }">{{ amount(row.spendAmount) }}</template></el-table-column>
        <el-table-column label="期末" min-width="110" align="right"><template #default="{ row }"><strong>{{ amount(row.closingBalance) }}</strong></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.status === 'CONFIRMED' ? 'success' : 'warning'">{{ row.status === 'CONFIRMED' ? '已确认' : '草稿' }}</el-tag></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.metric-card { display: grid; gap: 8px; padding: 19px; border: 1px solid var(--el-border-color-lighter); border-radius: 12px; background: var(--el-bg-color); }
.metric-card--neutral { border-top: 3px solid #94a3b8; }.metric-card--blue { border-top: 3px solid #3b82f6; }.metric-card--orange { border-top: 3px solid #f59e0b; }.metric-card--green { border-top: 3px solid #10b981; }
.metric-card > span, .metric-card small, .panel-heading p { color: var(--ink-muted); font-size: 13px; }.metric-card strong { color: var(--ink-strong); font-size: 28px; line-height: 1.15; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(340px, 1fr); gap: 18px; }
.panel-card { padding: 20px; }.panel-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 16px; }.panel-heading h2 { margin: 0; font-size: 17px; }.panel-heading p { margin: 5px 0 0; }
.trend-bars { display: flex; align-items: end; justify-content: space-around; gap: 12px; min-height: 205px; padding: 8px 4px 0; background: repeating-linear-gradient(to bottom, transparent 0, transparent 46px, var(--el-border-color-lighter) 47px); }
.trend-column { display: grid; grid-template-rows: 20px 152px 20px; gap: 6px; min-width: 46px; color: var(--ink-muted); font-size: 11px; text-align: center; }.trend-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.trend-track { display: flex; align-items: end; justify-content: center; }.trend-track i { display: block; width: 28px; border-radius: 7px 7px 2px 2px; background: linear-gradient(#4f95ff, #2563eb); }.trend-column small { font-size: 11px; }
.health-card { display: flex; flex-direction: column; }.health-item { display: flex; align-items: flex-start; gap: 10px; width: 100%; padding: 13px 0; border: 0; border-top: 1px solid var(--el-border-color-lighter); background: transparent; cursor: pointer; color: inherit; text-align: left; }.health-item:first-of-type { border-top: 0; }.health-item > span:last-child { display: grid; gap: 4px; }.health-item strong { font-size: 13px; }.health-item small { color: var(--ink-muted); font-size: 12px; line-height: 1.45; }
.table-card { padding: 20px; }.table-card .panel-heading { margin-bottom: 10px; }
@media (max-width: 980px) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.dashboard-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .metric-grid { grid-template-columns: 1fr; }.header-actions { align-items: stretch; flex-direction: column; }.trend-column { min-width: 34px; }.trend-track i { width: 20px; } }
</style>
