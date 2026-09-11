<script setup lang="ts">
import { Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  downloadErpReport,
  fetchErpDailyReport,
  fetchErpMonthlyReport,
} from '../api/erpReports'
import type { ErpReportRow } from '../types'

type ReportMode = 'daily' | 'monthly'

function dateText(offsetDays = 0): string {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  return value.toISOString().slice(0, 10)
}

function monthText(): string {
  return dateText().slice(0, 7)
}

function amount(value: string): string {
  return Number(value).toLocaleString()
}

const mode = ref<ReportMode>('daily')
const dailyRange = ref<[string, string]>([dateText(-6), dateText()])
const monthlyRange = ref<[string, string]>([monthText(), monthText()])
const asset = ref<'ALL' | 'USDT' | 'USDC' | 'NOMINAL_U'>('ALL')
const includeDraft = ref(true)
const loading = ref(false)
const exporting = ref(false)
const rows = ref<ErpReportRow[]>([])
const errorMessage = ref('')

const reportQuery = computed(() => ({
  asset: asset.value === 'USDT' || asset.value === 'USDC' ? asset.value : undefined,
  nominalU: asset.value === 'NOMINAL_U',
  includeDraft: includeDraft.value,
}))

async function load(): Promise<void> {
  const range = mode.value === 'daily' ? dailyRange.value : monthlyRange.value
  if (!range?.[0] || !range?.[1]) return
  loading.value = true
  try {
    const response = mode.value === 'daily'
      ? await fetchErpDailyReport(range[0], range[1], reportQuery.value)
      : await fetchErpMonthlyReport(range[0], range[1], reportQuery.value)
    rows.value = response.rows
    errorMessage.value = ''
  } catch (error) {
    rows.value = []
    errorMessage.value = apiErrorMessage(error, '汇总报表加载失败。')
  } finally {
    loading.value = false
  }
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function exportReport(): Promise<void> {
  const range = mode.value === 'daily' ? dailyRange.value : monthlyRange.value
  if (!range?.[0] || !range?.[1]) return
  exporting.value = true
  try {
    const blob = await downloadErpReport(mode.value, { from: range[0], to: range[1] }, reportQuery.value)
    saveBlob(blob, `erp-${mode.value}-report-${range[0]}_to_${range[1]}.xlsx`)
    ElMessage.success('本地 ERP 报表已导出。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '报表导出失败。'))
  } finally {
    exporting.value = false
  }
}

watch([mode, asset, includeDraft], () => void load())
onMounted(() => void load())
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">ERP local reporting</span>
        <h1>汇总报表</h1>
        <p>按日或按月汇总本地 ERP 日结数据；期初与期末为时点结余，不会重复累加。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Download" :loading="exporting" @click="exportReport">导出 Excel</el-button>
      </div>
    </header>

    <el-alert
      title="只读本地汇总"
      description="报表仅查询当前项目的本地 ERP 日结表。导出会记录本地审计日志，不会访问或修改任何远端业务系统。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card report-filter">
      <el-radio-group v-model="mode"><el-radio-button label="daily">按日</el-radio-button><el-radio-button label="monthly">按月</el-radio-button></el-radio-group>
      <el-date-picker v-if="mode === 'daily'" v-model="dailyRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-date-picker v-else v-model="monthlyRange" type="monthrange" value-format="YYYY-MM" range-separator="至" start-placeholder="开始月份" end-placeholder="结束月份" />
      <el-select v-model="asset" style="width: 145px"><el-option label="全部币种" value="ALL" /><el-option label="USDT" value="USDT" /><el-option label="USDC" value="USDC" /><el-option label="名义 U（1:1）" value="NOMINAL_U" /></el-select>
      <el-checkbox v-model="includeDraft">包含草稿</el-checkbox>
    </section>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="rows" row-key="period" empty-text="当前范围内暂无本地日结数据">
        <el-table-column prop="period" label="期间" width="120" fixed="left" />
        <el-table-column prop="asset" label="币种" width="100" />
        <el-table-column label="期初" min-width="110" align="right"><template #default="{ row }">{{ amount(row.openingBalance) }}</template></el-table-column>
        <el-table-column label="转 U" min-width="108" align="right"><template #default="{ row }">{{ amount(row.transferAmount) }}</template></el-table-column>
        <el-table-column label="有效转 U" min-width="118" align="right"><template #default="{ row }">{{ amount(row.effectiveTransferAmount) }}</template></el-table-column>
        <el-table-column label="消耗" min-width="100" align="right"><template #default="{ row }">{{ amount(row.spendAmount) }}</template></el-table-column>
        <el-table-column label="汇损 / 服务费" min-width="165" align="right"><template #default="{ row }">{{ amount(row.exchangeLossAmount) }} / {{ amount(row.serviceFeeAmount) }}</template></el-table-column>
        <el-table-column label="回流 / 退款 / 其他" min-width="185" align="right"><template #default="{ row }">{{ amount(row.refluxAmount) }} / {{ amount(row.refundAmount) }} / {{ amount(row.otherDeductionAmount) }}</template></el-table-column>
        <el-table-column label="期末" min-width="110" align="right"><template #default="{ row }"><strong>{{ amount(row.closingBalance) }}</strong></template></el-table-column>
        <el-table-column prop="recordCount" label="记录" width="82" align="right" />
        <el-table-column label="校验提示" min-width="230"><template #default="{ row }"><span v-if="row.warnings.length" class="report-warning">{{ row.warnings.join('；') }}</span><span v-else class="muted">—</span></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.report-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; padding: 16px; }
.report-warning { color: var(--el-color-warning); font-size: 12px; }
@media (max-width: 680px) { .report-filter { align-items: stretch; flex-direction: column; } }
</style>
