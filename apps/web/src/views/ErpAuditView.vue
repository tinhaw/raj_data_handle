<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchErpAuditLogs } from '../api/erpAudit'
import { fetchErpOperators } from '../api/erpOperators'
import type { ErpAuditLogEntry, ErpOperator } from '../types'

function localDate(offsetDays = 0): string {
  const value = new Date()
  value.setDate(value.getDate() + offsetDays)
  return value.toISOString().slice(0, 10)
}

function actionLabel(action: string): string {
  const labels: Record<string, string> = {
    'erp_daily_balance.create': '创建日结',
    'erp_daily_balance.update': '更新日结',
    'erp_daily_balance.confirm': '确认日结',
    'erp_daily_balance.reopen': '重开日结',
    'erp_period_lock.lock': '锁定期间',
    'erp_period_lock.unlock': '解锁期间',
    'erp_import.preview': '生成导入预览',
    'erp_import.commit': '提交导入',
    'erp_redemption_campaign.create': '创建兑换活动',
    'erp_redemption_batch.create': '创建兑换批次',
  }
  return labels[action] || action
}

const dateRange = ref<[string, string]>([localDate(-6), localDate()])
const action = ref('')
const operatorId = ref('')
const operators = ref<ErpOperator[]>([])
const rows = ref<ErpAuditLogEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const detailVisible = ref(false)
const selected = ref<ErpAuditLogEntry | null>(null)

async function load(nextPage = page.value): Promise<void> {
  loading.value = true
  try {
    page.value = nextPage
    const result = await fetchErpAuditLogs({
      dateFrom: dateRange.value[0],
      dateTo: dateRange.value[1],
      action: action.value.trim() || undefined,
      operatorId: operatorId.value || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    rows.value = []
    total.value = 0
    ElMessage.error(apiErrorMessage(error, '审计记录加载失败。'))
  } finally {
    loading.value = false
  }
}

function openDetail(row: ErpAuditLogEntry): void {
  selected.value = row
  detailVisible.value = true
}

onMounted(async () => {
  try {
    operators.value = await fetchErpOperators(true)
  } catch {
    operators.value = []
  }
  await load(1)
})
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div><span class="page-eyebrow">ERP audit trail</span><h1>审计日志</h1><p>查询本地 ERP 的追加式操作记录，默认显示最近 7 天；不包含远端业务会话或密钥。</p></div>
      <div class="header-actions"><el-button :icon="Refresh" :loading="loading" @click="load(1)">刷新</el-button></div>
    </header>

    <section class="surface-card audit-filter">
      <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" />
      <el-select v-model="operatorId" clearable placeholder="全部授权公司" style="width: 220px">
        <el-option v-for="operator in operators" :key="operator.id" :label="operator.name" :value="operator.id" />
      </el-select>
      <el-input v-model="action" clearable placeholder="操作代码（可选，如 erp_import.commit）" @keyup.enter="load(1)" />
      <el-button type="primary" @click="load(1)">查询</el-button>
    </section>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="该时间范围内没有 ERP 审计记录">
        <el-table-column label="时间" min-width="175"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column>
        <el-table-column label="操作" min-width="150"><template #default="{ row }">{{ actionLabel(row.action) }}</template></el-table-column>
        <el-table-column label="操作人" min-width="130"><template #default="{ row }">{{ row.actorDisplayName || '系统' }}</template></el-table-column>
        <el-table-column label="对象" min-width="160"><template #default="{ row }">{{ row.targetType || '—' }}<span v-if="row.targetId"> · {{ row.targetId }}</span></template></el-table-column>
        <el-table-column label="结果" width="100"><template #default="{ row }"><el-tag :type="row.result === 'success' ? 'success' : 'danger'">{{ row.result }}</el-tag></template></el-table-column>
        <el-table-column label="详情" width="90" fixed="right"><template #default="{ row }"><el-button text type="primary" @click="openDetail(row)">查看</el-button></template></el-table-column>
      </el-table>
      <el-pagination class="pagination" background layout="total, sizes, prev, pager, next" :total="total" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" @current-change="load" @size-change="() => load(1)" />
    </section>

    <el-dialog v-model="detailVisible" title="审计详情" width="640px">
      <el-descriptions v-if="selected" :column="1" border>
        <el-descriptions-item label="操作代码">{{ selected.action }}</el-descriptions-item>
        <el-descriptions-item label="对象">{{ selected.targetType || '—' }}<span v-if="selected.targetId"> · {{ selected.targetId }}</span></el-descriptions-item>
        <el-descriptions-item label="请求 ID">{{ selected.requestId || '—' }}</el-descriptions-item>
        <el-descriptions-item label="附加信息"><pre>{{ JSON.stringify(selected.metadata, null, 2) }}</pre></el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<style scoped>
.audit-filter { display: flex; align-items: center; gap: 12px; padding: 16px; }.audit-filter .el-input { width: min(360px, 38vw); }.table-card { padding: 20px; }.pagination { justify-content: flex-end; margin-top: 16px; }pre { max-height: 280px; margin: 0; overflow: auto; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 700px) { .audit-filter { align-items: stretch; flex-direction: column; }.audit-filter .el-input { width: 100%; } }
</style>
