<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowDown, ArrowUp, CircleCheck, WarningFilled } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import type { ReportRow } from '@/api/types'
import MoneyText from '@/components/MoneyText.vue'
import StatusTag from '@/components/StatusTag.vue'
import { demoDailyReport } from '@/utils/demo-data'
import { toDecimal } from '@/utils/money'
import { demoEnabled } from '@/utils/runtime'

const loading = ref(true)
const rows = ref<ReportRow[]>([])
const trendRows = ref<ReportRow[]>([])
const loadError = ref('')
const reportDate = '2026-07-01'

const totals = computed(() => rows.value.reduce((acc, row) => ({
  opening: acc.opening.plus(toDecimal(row.openingBalance)),
  transfer: acc.transfer.plus(toDecimal(row.transferAmount)),
  spend: acc.spend.plus(toDecimal(row.spendAmount)),
  deduction: acc.deduction.plus(toDecimal(row.exchangeLossAmount)).plus(toDecimal(row.serviceFeeAmount)).plus(toDecimal(row.refluxAmount)).plus(toDecimal(row.refundAmount)).plus(toDecimal(row.otherDeductionAmount)).plus(toDecimal(row.fraudFromBalance)),
  closing: acc.closing.plus(toDecimal(row.closingBalance)),
}), { opening: toDecimal(0), transfer: toDecimal(0), spend: toDecimal(0), deduction: toDecimal(0), closing: toDecimal(0) }))

const metrics = computed(() => [
  { label: '当前期初结余', value: totals.value.opening.toString(), note: '全部有权限投放公司', tone: 'neutral', icon: ArrowUp },
  { label: '本日转 U', value: totals.value.transfer.toString(), note: 'USDT / USDC 名义合计', tone: 'blue', icon: ArrowUp },
  { label: '本日消耗', value: totals.value.spend.toString(), note: '较前日 +8.6%', tone: 'orange', icon: ArrowDown },
  { label: '当前期末结余', value: totals.value.closing.toString(), note: '2 个投放公司 · 2 条投放线', tone: 'green', icon: CircleCheck },
])

async function load() {
  loading.value = true
  try {
    const [summary, trend] = await Promise.all([
      api.reports.daily({ from: reportDate, to: reportDate, includeDraft: true }),
      api.reports.daily({ from: '2026-06-25', to: reportDate, includeDraft: true }),
    ])
    rows.value = summary
    trendRows.value = trend
    loadError.value = ''
  } catch {
    rows.value = demoEnabled ? demoDailyReport.filter((row) => row.businessDate === reportDate) : []
    trendRows.value = demoEnabled ? demoDailyReport : []
    loadError.value = demoEnabled ? '' : '无法连接数据服务，概览数据暂不可用。请确认 API 已启动后刷新。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title-row">
      <div>
        <h2>工作台</h2>
        <p class="page-subtitle">围绕数据录入、核对与异常处理安排本日工作。业务数据以 {{ reportDate }} 为例展示。</p>
      </div>
      <div class="page-actions">
        <el-button plain @click="load">刷新工作台</el-button>
        <el-button type="primary" @click="$router.push('/balances')">新建台账</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>

    <div class="metric-grid" v-loading="loading">
      <article v-for="metric in metrics" :key="metric.label" class="metric-card" :class="`metric-card--${metric.tone}`">
        <div class="metric-card__head"><span>{{ metric.label }}</span><el-icon><component :is="metric.icon" /></el-icon></div>
        <MoneyText class="metric-card__value" :value="metric.value" :digits="2" />
        <small>{{ metric.note }}</small>
      </article>
    </div>

    <div class="dashboard-grid">
      <article class="panel panel--padded trend-card">
        <div class="panel-title"><div><h3>近期结余趋势</h3><p>期末结余 · 名义 U</p></div><el-tag type="info" effect="plain">近 3 个业务日</el-tag></div>
        <div class="chart-placeholder">
          <div class="chart-y"><span>1,000</span><span>750</span><span>500</span><span>250</span><span>0</span></div>
          <div class="bar-group" v-for="row in trendRows" :key="row.businessDate">
            <div class="bar-wrap"><div class="bar" :style="{ height: `${Math.max(12, Number(row.closingBalance) / 10)}px` }"></div></div>
            <span>{{ row.businessDate?.slice(5).replace('-', '/') }}</span>
          </div>
        </div>
        <div class="trend-legend"><span><i class="dot dot--blue"></i>期末结余</span><span>数据以服务端汇总口径为准</span></div>
      </article>

      <article class="panel panel--padded health-card">
        <div class="panel-title"><div><h3>数据质量提醒</h3><p>需要财务管理员关注的事项</p></div></div>
        <div class="health-item"><span class="health-icon health-icon--warning"><el-icon><WarningFilled /></el-icon></span><div><strong>1 条草稿等待确认</strong><p>示例投放公司 · 主投放线 · 2026-07-02</p></div><el-button link type="primary" @click="$router.push('/balances')">处理</el-button></div>
        <div class="health-item"><span class="health-icon health-icon--success"><el-icon><CircleCheck /></el-icon></span><div><strong>当月公式校验通过</strong><p>期末结余与月度发生额一致</p></div></div>
        <div class="health-item"><span class="health-icon health-icon--neutral">0</span><div><strong>负结余投放线</strong><p>暂无需要预警的投放线</p></div></div>
      </article>
    </div>

    <article class="panel table-card recent-card">
      <div class="table-title"><div><h3>最近日结记录</h3><p>显示当前授权范围内的最新业务记录</p></div><el-button link type="primary" @click="$router.push('/reports')">查看全部报表 →</el-button></div>
      <el-table :data="rows" size="small">
        <el-table-column prop="businessDate" label="业务日" min-width="110" />
        <el-table-column label="期初" align="right"><template #default="{ row }"><MoneyText :value="row.openingBalance" /></template></el-table-column>
        <el-table-column label="转 U" align="right"><template #default="{ row }"><MoneyText :value="row.transferAmount" /></template></el-table-column>
        <el-table-column label="消耗" align="right"><template #default="{ row }"><MoneyText :value="row.spendAmount" /></template></el-table-column>
        <el-table-column label="期末" align="right"><template #default="{ row }"><MoneyText :value="row.closingBalance" colorize /></template></el-table-column>
        <el-table-column label="记录" width="80" align="center"><template #default="{ row }"><StatusTag :status="row.recordCount ? 'CONFIRMED' : 'DRAFT'" /></template></el-table-column>
      </el-table>
    </article>
  </section>
</template>

<style scoped>
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-bottom: 18px; }
.metric-card { padding: 18px; background: #fff; border: 1px solid #eaecf0; border-radius: 12px; }
.metric-card--blue { border-top: 3px solid #528bff; }.metric-card--orange { border-top: 3px solid #f79009; }.metric-card--green { border-top: 3px solid #12b76a; }.metric-card--neutral { border-top: 3px solid #98a2b3; }
.metric-card__head { display: flex; justify-content: space-between; color: #667085; font-size: 13px; }.metric-card__head .el-icon { font-size: 17px; }
.metric-card__value { display: block; margin: 15px 0 4px; color: #101828; font-size: 26px; font-weight: 680; letter-spacing: -.03em; }.metric-card small { color: #98a2b3; font-size: 12px; }
.dashboard-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .95fr); gap: 18px; }
.panel-title, .table-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.panel-title h3, .table-title h3 { margin: 0; color: #101828; font-size: 15px; }.panel-title p, .table-title p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }
.chart-placeholder { display: flex; align-items: flex-end; gap: 26px; height: 220px; margin-top: 24px; padding: 8px 18px 0 39px; background: repeating-linear-gradient(to bottom, transparent 0, transparent 43px, #f2f4f7 44px); }.chart-y { display: flex; flex-direction: column; justify-content: space-between; align-self: stretch; margin-left: -34px; color: #98a2b3; font-size: 11px; }.bar-group { display: grid; grid-template-rows: 1fr 22px; gap: 8px; width: 54px; height: 100%; color: #98a2b3; font-size: 11px; text-align: center; }.bar-wrap { display: flex; align-items: end; justify-content: center; }.bar { width: 30px; max-height: 178px; border-radius: 6px 6px 2px 2px; background: linear-gradient(#528bff, #155eef); }.trend-legend { display: flex; justify-content: space-between; margin-top: 16px; color: #98a2b3; font-size: 12px; }.dot { display: inline-block; width: 8px; height: 8px; margin-right: 5px; border-radius: 50%; }.dot--blue { background: #155eef; }
.health-card { padding-bottom: 8px; }.health-item { display: flex; align-items: center; gap: 10px; padding: 16px 0; border-bottom: 1px solid #f2f4f7; }.health-item:last-child { border: 0; }.health-item > div:nth-child(2) { flex: 1; }.health-item strong { color: #344054; font-size: 13px; }.health-item p { margin: 4px 0 0; color: #98a2b3; font-size: 12px; }.health-icon { display: grid; place-items: center; flex: 0 0 auto; width: 30px; height: 30px; border-radius: 50%; }.health-icon--warning { color: #dc6803; background: #fffaeb; }.health-icon--success { color: #027a48; background: #ecfdf3; }.health-icon--neutral { color: #475467; font-size: 12px; font-weight: 650; background: #f2f4f7; }
.recent-card { margin-top: 18px; }.table-title { padding: 18px 20px 14px; }
.load-error { margin-bottom: 16px; }
</style>
