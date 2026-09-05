<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import type { Operator, OperatorAccount, ReportRow } from '@/api/types'
import MoneyText from '@/components/MoneyText.vue'
import ReportMetricChart from './ReportMetricChart.vue'
import { demoAccounts, demoDailyReport, demoMonthlyReport, demoOperators } from '@/utils/demo-data'
import { useSessionStore } from '@/stores/session'
import { saveDownloadedFile } from '@/utils/download'
import { demoEnabled } from '@/utils/runtime'
import { toDecimal } from '@/utils/money'

type ReportMode = 'daily' | 'monthly'
type ChartType = 'bar' | 'line' | 'pie'
type ChartMetric = 'openingBalance' | 'transferAmount' | 'fraudFromTransfer' | 'effectiveTransferAmount' | 'spendAmount' | 'exchangeLossAmount' | 'serviceFeeAmount' | 'refluxAmount' | 'refundAmount' | 'otherDeductionAmount' | 'fraudFromBalance' | 'closingBalance'

const mode = ref<ReportMode>('daily')
const dailyRange = ref<[string, string]>(['2026-07-01', '2026-07-31'])
const monthlyRange = ref<[string, string]>(['2026-07', '2026-07'])
const operatorIds = ref<Array<string | number>>([])
const accountIds = ref<Array<string | number>>([])
const asset = ref<'ALL' | 'USDT' | 'USDC' | 'NOMINAL_U'>('ALL')
const status = ref<'ALL' | 'CONFIRMED'>('ALL')
const operators = ref<Operator[]>([])
const accounts = ref<OperatorAccount[]>([])
const rows = ref<ReportRow[]>([])
const loading = ref(false)
const exporting = ref(false)
const usingDemo = ref(false)
const loadError = ref('')
const loadedRangeLabel = ref('—')
const chartType = ref<ChartType>('bar')
const chartMetric = ref<ChartMetric>('closingBalance')
const chartAsset = ref('')
const session = useSessionStore()

const chartMetricOptions: Array<{ value: ChartMetric; label: string }> = [
  { value: 'closingBalance', label: '期末结余' },
  { value: 'openingBalance', label: '期初结余' },
  { value: 'transferAmount', label: '转 U' },
  { value: 'effectiveTransferAmount', label: '有效转 U' },
  { value: 'spendAmount', label: '消耗' },
  { value: 'exchangeLossAmount', label: '汇损' },
  { value: 'serviceFeeAmount', label: '服务费' },
  { value: 'refluxAmount', label: '回流' },
  { value: 'refundAmount', label: '退款' },
  { value: 'otherDeductionAmount', label: '其他' },
  { value: 'fraudFromTransfer', label: '欺诈扣转账' },
  { value: 'fraudFromBalance', label: '欺诈扣结余' },
]

const selectedOperatorLabel = computed(() => !operatorIds.value.length ? '全部有权限投放公司' : `已选择 ${operatorIds.value.length} 个投放公司`)
const selectedOperatorIdSet = computed(() => new Set(operatorIds.value.map((id) => String(id))))
const operatorNameById = computed(() => new Map(operators.value.map((operator) => [String(operator.id), operator.name])))
const availableAccounts = computed(() => {
  if (!operatorIds.value.length) return accounts.value
  return accounts.value.filter((account) => selectedOperatorIdSet.value.has(String(account.operatorId)))
})
const selectedLineLabel = computed(() => {
  if (!operatorIds.value.length) return '全部投放线'
  return accountIds.value.length ? `已选择 ${accountIds.value.length} 条投放线` : '所选投放公司下全部投放线'
})
const activeRows = computed(() => rows.value.filter((row) => asset.value === 'ALL' || row.asset === asset.value))
const chartAssetOptions = computed<string[]>(() => {
  const order = ['USDT', 'USDC', 'NOMINAL_U']
  return [...new Set(activeRows.value.map((row) => String(row.asset)))].sort((left, right) => order.indexOf(left) - order.indexOf(right))
})
const selectedChartAsset = computed(() => chartAssetOptions.value.includes(chartAsset.value) ? chartAsset.value : chartAssetOptions.value[0] || '')
const chartMetricLabel = computed(() => chartMetricOptions.find((item) => item.value === chartMetric.value)?.label || '期末结余')
const chartPoints = computed(() => activeRows.value
  .filter((row) => row.asset === selectedChartAsset.value)
  .sort((left, right) => periodOf(left).localeCompare(periodOf(right)))
  .map((row) => ({ label: periodOf(row), value: row[chartMetric.value] || '0' })))
const chartHint = computed(() => chartType.value === 'pie'
  ? '饼图展示所选指标在各业务日/月的占比，用于查看构成，不表示趋势。'
  : '横轴为业务日/月；结余为各时点余额，发生额为各期金额。')
const canExportReports = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('REPORT_EXPORT') || user?.roles.includes('SUPER_ADMIN'))
})

function periodOf(row: ReportRow) {
  return row.businessDate || row.periodMonth || ''
}

function selectedRangeLabel() {
  const [from, to] = mode.value === 'daily' ? dailyRange.value : monthlyRange.value
  return from && to ? `${from} 至 ${to}` : '未设置查询范围'
}

/**
 * Opening and closing are balances at a point in time, not flow values.  Keep
 * currencies separate and take the first/last chronological group respectively;
 * only the in-range movement fields are accumulated.
 */
const totalsByAsset = computed(() => {
  const rowsByAsset = new Map<string, ReportRow[]>()
  for (const row of activeRows.value) {
    const current = rowsByAsset.get(row.asset) || []
    current.push(row)
    rowsByAsset.set(row.asset, current)
  }

  return [...rowsByAsset.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([unit, unitRows]) => {
    const chronologicalRows = [...unitRows].sort((left, right) => periodOf(left).localeCompare(periodOf(right)))
    const first = chronologicalRows[0]
    const last = chronologicalRows[chronologicalRows.length - 1]
    const flows = chronologicalRows.reduce((acc, row) => ({
      transfer: acc.transfer.plus(toDecimal(row.transferAmount)),
      fraudTransfer: acc.fraudTransfer.plus(toDecimal(row.fraudFromTransfer)),
      effective: acc.effective.plus(toDecimal(row.effectiveTransferAmount)),
      spend: acc.spend.plus(toDecimal(row.spendAmount)),
      exchange: acc.exchange.plus(toDecimal(row.exchangeLossAmount)),
      service: acc.service.plus(toDecimal(row.serviceFeeAmount)),
      reflux: acc.reflux.plus(toDecimal(row.refluxAmount)),
      refund: acc.refund.plus(toDecimal(row.refundAmount)),
      other: acc.other.plus(toDecimal(row.otherDeductionAmount)),
      fraudBalance: acc.fraudBalance.plus(toDecimal(row.fraudFromBalance)),
    }), {
      transfer: toDecimal(0), fraudTransfer: toDecimal(0), effective: toDecimal(0), spend: toDecimal(0), exchange: toDecimal(0), service: toDecimal(0), reflux: toDecimal(0), refund: toDecimal(0), other: toDecimal(0), fraudBalance: toDecimal(0),
    })
    return {
      asset: unit,
      opening: toDecimal(first?.openingBalance),
      closing: toDecimal(last?.closingBalance),
      ...flows,
    }
  })
})

function assetLabel(value: string) {
  return value === 'NOMINAL_U' ? '名义 U（1:1）' : value
}

function lineLabel(account: OperatorAccount) {
  return account.displayName || `${account.companyName || operatorNameById.value.get(String(account.operatorId)) || '未归属投放公司'} · ${account.name}`
}

function selectAllLinesForSelectedCompanies() {
  accountIds.value = operatorIds.value.length ? availableAccounts.value.map((account) => account.id) : []
}

async function loadReferences() {
  try {
    const items = await api.operators.list()
    operators.value = items
    accounts.value = (await Promise.all(items.map((operator) => api.operators.accounts(operator.id)))).flat()
    // Keep a restored company filter coherent if references are reloaded.
    selectAllLinesForSelectedCompanies()
    usingDemo.value = false
  } catch {
    if (demoEnabled) {
      operators.value = demoOperators
      accounts.value = demoAccounts
      usingDemo.value = true
    } else {
      operators.value = []
      accounts.value = []
    }
  }
}

function currentReportParams() {
  const baseParams = {
    operatorIds: operatorIds.value,
    accountIds: accountIds.value.length ? accountIds.value : undefined,
    asset: asset.value === 'ALL' || asset.value === 'NOMINAL_U' ? undefined : asset.value,
    nominalU: asset.value === 'NOMINAL_U' || undefined,
    includeDraft: status.value !== 'CONFIRMED',
  }
  return mode.value === 'daily'
    ? { ...baseParams, from: dailyRange.value?.[0], to: dailyRange.value?.[1] }
    : { ...baseParams, from: monthlyRange.value?.[0], to: monthlyRange.value?.[1] }
}

async function load() {
  loading.value = true
  const params = currentReportParams()
  const requestedRangeLabel = selectedRangeLabel()
  try {
    rows.value = mode.value === 'daily' ? await api.reports.daily(params) : await api.reports.monthly(params)
    loadedRangeLabel.value = requestedRangeLabel
    loadError.value = ''
  } catch (error) {
    if (demoEnabled) {
      rows.value = mode.value === 'daily' ? demoDailyReport : demoMonthlyReport
      loadedRangeLabel.value = requestedRangeLabel
      usingDemo.value = true
      loadError.value = ''
    } else {
      rows.value = []
      loadError.value = error instanceof Error ? error.message : '报表服务暂不可用，请确认 API 后刷新。'
    }
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  operatorIds.value = []
  accountIds.value = []
  asset.value = 'ALL'
  status.value = 'ALL'
  void load()
}

async function exportReport() {
  if (!canExportReports.value) {
    ElMessage.warning('当前账号没有报表导出权限')
    return
  }
  exporting.value = true
  try {
    const file = mode.value === 'daily'
      ? await api.reports.exportDaily(currentReportParams())
      : await api.reports.exportMonthly(currentReportParams())
    saveDownloadedFile(file)
    ElMessage.success('报表已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出报表失败')
  } finally {
    exporting.value = false
  }
}

watch(mode, () => void load())
watch(operatorIds, selectAllLinesForSelectedCompanies, { deep: true })
watch(chartAssetOptions, (options) => {
  if (!options.includes(chartAsset.value)) chartAsset.value = options[0] || ''
}, { immediate: true })
onMounted(async () => {
  await loadReferences()
  await load()
})
</script>

<template>
  <section>
    <div class="page-title-row">
      <div>
        <h2>汇总报表</h2>
        <p class="page-subtitle">按日或按月汇总授权范围内的结余与发生额。期初、期末是时点余额，不会把每日结余重复相加。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-tooltip :disabled="canExportReports" content="当前账号没有报表导出权限，请联系管理员。">
          <span><el-button :icon="Download" type="primary" :loading="exporting" :disabled="!canExportReports" @click="exportReport">导出 Excel</el-button></span>
        </el-tooltip>
      </div>
    </div>

    <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>

    <article class="panel panel--padded report-filter-panel">
      <el-tabs v-model="mode" class="report-tabs"><el-tab-pane label="按日汇总" name="daily" /><el-tab-pane label="按月汇总" name="monthly" /></el-tabs>
      <div class="filter-bar">
        <el-form-item :label="mode === 'daily' ? '日期范围' : '月份范围'"><el-date-picker v-if="mode === 'daily'" v-model="dailyRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" style="width: 265px" /><el-date-picker v-else v-model="monthlyRange" type="monthrange" value-format="YYYY-MM" range-separator="至" start-placeholder="开始月份" end-placeholder="结束月份" style="width: 265px" /></el-form-item>
        <el-form-item label="投放公司"><el-select v-model="operatorIds" multiple collapse-tags collapse-tags-tooltip filterable clearable :placeholder="selectedOperatorLabel" style="width: 245px"><el-option v-for="operator in operators" :key="operator.id" :label="operator.name" :value="operator.id" /></el-select></el-form-item>
        <el-form-item label="投放线"><el-select v-model="accountIds" multiple collapse-tags collapse-tags-tooltip filterable clearable :placeholder="selectedLineLabel" style="width: 240px"><el-option v-for="account in availableAccounts" :key="account.id" :label="lineLabel(account)" :value="account.id" /></el-select></el-form-item>
        <el-form-item label="币种"><el-select v-model="asset" style="width: 130px"><el-option label="全部原币种" value="ALL" /><el-option label="USDT" value="USDT" /><el-option label="USDC" value="USDC" /><el-option label="名义 U 合计" value="NOMINAL_U" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="status" style="width: 130px"><el-option label="草稿 + 已确认" value="ALL" /><el-option label="仅已确认" value="CONFIRMED" /></el-select></el-form-item>
        <el-button type="primary" @click="load">查询</el-button><el-button @click="resetFilters">重置</el-button>
      </div>
      <el-alert class="nominal-note" type="info" :closable="false" show-icon>选择投放公司后会默认勾选其全部投放线；未指定投放公司时默认统计全部有权限投放公司。USDT 与 USDC 原币种分账；“名义 U 合计”仅按 1:1 展示，不代表法币估值。</el-alert>
    </article>

    <article v-loading="loading" class="panel report-overview">
      <div class="report-overview__title">
        <div>
          <h3>数据概览</h3>
          <p>当前查询范围：{{ loadedRangeLabel }} · {{ selectedOperatorLabel }}</p>
        </div>
        <span>期初、期末为范围起止时点余额；其余指标为范围内累计发生额</span>
      </div>
      <template v-if="totalsByAsset.length">
        <section v-for="item in totalsByAsset" :key="item.asset" class="report-overview__asset">
          <header>
            <strong>{{ assetLabel(item.asset) }}</strong>
            <span>原币种汇总</span>
          </header>
          <div class="report-overview__grid">
            <div class="overview-card overview-card--transfer"><span>转 U</span><MoneyText :value="item.transfer.toString()" /></div>
            <div class="overview-card overview-card--spend"><span>消耗</span><MoneyText :value="item.spend.toString()" /></div>
            <div class="overview-card overview-card--exchange"><span>汇损</span><MoneyText :value="item.exchange.toString()" /></div>
            <div class="overview-card overview-card--service"><span>服务费</span><MoneyText :value="item.service.toString()" /></div>
            <div class="overview-card"><span>回流</span><MoneyText :value="item.reflux.toString()" /></div>
            <div class="overview-card"><span>退款</span><MoneyText :value="item.refund.toString()" /></div>
            <div class="overview-card"><span>其他</span><MoneyText :value="item.other.toString()" /></div>
            <div class="overview-card overview-card--opening"><span>期初结余</span><MoneyText :value="item.opening.toString()" colorize /></div>
            <div class="overview-card overview-card--closing"><span>期末结余</span><MoneyText :value="item.closing.toString()" colorize /></div>
          </div>
        </section>
      </template>
      <div v-else class="report-overview__empty">当前筛选没有可展示的数据概览。</div>
    </article>

    <article v-loading="loading" class="panel report-chart-panel">
      <div class="report-chart-panel__title">
        <div>
          <h3>指标趋势</h3>
          <p>{{ loadedRangeLabel }} · {{ selectedChartAsset ? assetLabel(selectedChartAsset) : '暂无币种数据' }} · {{ chartMetricLabel }}</p>
        </div>
        <span>{{ chartHint }}</span>
      </div>
      <div class="report-chart-panel__controls">
        <el-form-item label="展示指标"><el-select v-model="chartMetric" style="width: 166px"><el-option v-for="item in chartMetricOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
        <el-form-item label="图表币种"><el-select v-model="chartAsset" style="width: 142px" :disabled="chartAssetOptions.length < 2"><el-option v-for="item in chartAssetOptions" :key="item" :label="assetLabel(item)" :value="item" /></el-select></el-form-item>
        <el-form-item label="图表形式"><el-radio-group v-model="chartType"><el-radio-button label="bar">柱状图</el-radio-button><el-radio-button label="line">折线图</el-radio-button><el-radio-button label="pie">饼图</el-radio-button></el-radio-group></el-form-item>
      </div>
      <ReportMetricChart :type="chartType" :points="chartPoints" :metric-label="chartMetricLabel" :asset-label="assetLabel(selectedChartAsset)" />
    </article>

    <article class="panel table-card report-table">
      <div class="report-table-title"><div><h3>{{ mode === 'daily' ? '日汇总结果' : '月汇总结果' }}</h3><p>{{ selectedOperatorLabel }} · {{ activeRows.length }} 个分组 · {{ usingDemo ? '演示数据' : '服务端数据' }}</p></div><span class="hint">点击展开可查看本行的汇总口径</span></div>
      <el-table v-loading="loading" :data="activeRows" border max-height="570" size="small">
        <el-table-column type="expand" width="42"><template #default="{ row }"><div class="report-expand"><span>投放线 / 投放公司：{{ row.operatorName || '汇总范围内投放线' }}{{ row.accountName ? ` · ${row.accountName}` : '' }}</span><span>期初为该时点各投放线最近一期余额之和；期末为截至该日/月的最新余额之和。</span><span>记录数：{{ row.recordCount ?? '—' }}</span></div></template></el-table-column>
        <el-table-column :label="mode === 'daily' ? '业务日' : '业务月份'" min-width="120" fixed="left"><template #default="{ row }"><strong>{{ row.businessDate || row.periodMonth }}</strong><span class="asset-label">{{ row.asset === 'NOMINAL_U' ? '名义 U' : row.asset }}</span></template></el-table-column>
        <el-table-column label="期初" width="115" align="right"><template #default="{ row }"><MoneyText :value="row.openingBalance" /></template></el-table-column>
        <el-table-column label="转 U" width="112" align="right"><template #default="{ row }"><MoneyText :value="row.transferAmount" /></template></el-table-column>
        <el-table-column label="欺诈扣转账" width="117" align="right"><template #default="{ row }"><MoneyText :value="row.fraudFromTransfer" /></template></el-table-column>
        <el-table-column label="有效转 U" width="112" align="right"><template #default="{ row }"><MoneyText :value="row.effectiveTransferAmount" /></template></el-table-column>
        <el-table-column label="消耗" width="112" align="right"><template #default="{ row }"><MoneyText :value="row.spendAmount" /></template></el-table-column>
        <el-table-column label="汇损" width="105" align="right"><template #default="{ row }"><MoneyText :value="row.exchangeLossAmount" /></template></el-table-column>
        <el-table-column label="服务费" width="105" align="right"><template #default="{ row }"><MoneyText :value="row.serviceFeeAmount" /></template></el-table-column>
        <el-table-column label="回流" width="105" align="right"><template #default="{ row }"><MoneyText :value="row.refluxAmount" /></template></el-table-column>
        <el-table-column label="退款" width="105" align="right"><template #default="{ row }"><MoneyText :value="row.refundAmount" /></template></el-table-column>
        <el-table-column label="其他" width="105" align="right"><template #default="{ row }"><MoneyText :value="row.otherDeductionAmount" /></template></el-table-column>
        <el-table-column label="欺诈扣结余" width="120" align="right"><template #default="{ row }"><MoneyText :value="row.fraudFromBalance" /></template></el-table-column>
        <el-table-column label="期末" width="122" fixed="right" align="right"><template #default="{ row }"><MoneyText :value="row.closingBalance" colorize /></template></el-table-column>
      </el-table>
      <div class="report-total">
        <strong>当前查询合计</strong>
        <template v-if="totalsByAsset.length">
          <div v-for="item in totalsByAsset" :key="item.asset" class="report-total-group">
            <b>{{ assetLabel(item.asset) }}</b>
            <span>期初 <MoneyText :value="item.opening.toString()" /></span>
            <span>转 U <MoneyText :value="item.transfer.toString()" /></span>
            <span>有效转 U <MoneyText :value="item.effective.toString()" /></span>
            <span>消耗 <MoneyText :value="item.spend.toString()" /></span>
            <span>全部扣减 <MoneyText :value="item.exchange.plus(item.service).plus(item.reflux).plus(item.refund).plus(item.other).plus(item.fraudTransfer).plus(item.fraudBalance).toString()" /></span>
            <span>期末 <MoneyText :value="item.closing.toString()" colorize /></span>
          </div>
        </template>
        <span v-else class="muted">当前筛选没有可汇总的数据</span>
      </div>
    </article>
  </section>
</template>

<style scoped>
.load-error { margin-bottom: 16px; }.report-filter-panel { padding-top: 7px; }.report-tabs { margin-bottom: 12px; }.report-tabs :deep(.el-tabs__header) { margin-bottom: 15px; }.nominal-note { margin-top: 16px; }.report-table { overflow: hidden; }.report-table-title { display: flex; justify-content: space-between; align-items: flex-start; padding: 18px 20px 14px; }.report-table-title h3 { margin: 0; color: #101828; font-size: 15px; }.report-table-title p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }.asset-label { display: block; margin-top: 3px; color: #98a2b3; font-size: 10px; }.report-expand { display: flex; gap: 42px; padding: 13px 18px; color: #667085; font-size: 12px; background: #f9fafb; }.report-total { display: flex; align-items: center; gap: 14px; min-width: max-content; padding: 13px 16px; color: #667085; font-size: 12px; border-top: 1px solid #eaecf0; overflow-x: auto; }.report-total > strong { align-self: flex-start; padding-top: 3px; color: #344054; white-space: nowrap; }.report-total-group { display: flex; align-items: center; gap: 16px; padding-left: 14px; white-space: nowrap; border-left: 1px solid #eaecf0; }.report-total-group b { color: #155eef; font-size: 12px; }.report-total-group span { white-space: nowrap; }
.report-overview { margin-top: 18px; overflow: hidden; }.report-overview__title { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 18px 20px 15px; border-bottom: 1px solid #eaecf0; }.report-overview__title h3 { margin: 0; color: #101828; font-size: 15px; }.report-overview__title p, .report-overview__title > span { margin: 5px 0 0; color: #667085; font-size: 12px; line-height: 1.5; }.report-overview__title > span { max-width: 410px; color: #98a2b3; text-align: right; }.report-overview__asset { padding: 16px 20px 18px; }.report-overview__asset + .report-overview__asset { border-top: 1px solid #eaecf0; }.report-overview__asset > header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }.report-overview__asset > header strong { color: #155eef; font-size: 13px; }.report-overview__asset > header span { color: #98a2b3; font-size: 12px; }.report-overview__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; }.overview-card { display: flex; flex-direction: column; gap: 8px; min-height: 76px; padding: 13px 14px; background: #fff; border: 1px solid #eaecf0; border-top: 3px solid #d0d5dd; border-radius: 8px; }.overview-card > span { color: #667085; font-size: 12px; }.overview-card :deep(.money) { color: #101828; font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }.overview-card :deep(.money--negative) { color: #d92d20; }.overview-card :deep(.money--positive) { color: #027a48; }.overview-card--transfer { border-top-color: #528bff; background: #f8faff; }.overview-card--spend { border-top-color: #f79009; background: #fffaf0; }.overview-card--exchange { border-top-color: #fdb022; background: #fffcf5; }.overview-card--service { border-top-color: #9e77ed; background: #fbfaff; }.overview-card--opening { border-top-color: #98a2b3; background: #fcfcfd; }.overview-card--closing { border-top-color: #12b76a; background: #f6fef9; }.report-overview__empty { padding: 28px 20px; color: #98a2b3; font-size: 13px; text-align: center; }.report-overview + .report-table { margin-top: 18px; }
.report-chart-panel { margin-top: 18px; overflow: hidden; }.report-chart-panel__title { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 18px 20px 13px; }.report-chart-panel__title h3 { margin: 0; color: #101828; font-size: 15px; }.report-chart-panel__title p, .report-chart-panel__title > span { margin: 5px 0 0; color: #667085; font-size: 12px; line-height: 1.5; }.report-chart-panel__title > span { max-width: 430px; color: #98a2b3; text-align: right; }.report-chart-panel__controls { display: flex; flex-wrap: wrap; align-items: center; gap: 0 18px; padding: 0 20px 14px; border-bottom: 1px solid #eaecf0; }.report-chart-panel__controls :deep(.el-form-item) { margin: 0; }.report-chart-panel + .report-table { margin-top: 18px; }
</style>
