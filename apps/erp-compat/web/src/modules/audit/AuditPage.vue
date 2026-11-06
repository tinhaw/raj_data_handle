<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { DocumentChecked, Lock, Refresh, View } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import type { AuditLog, Operator } from '@/api/types'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const loading = ref(false)
const loadError = ref('')
const logs = ref<AuditLog[]>([])
const operators = ref<Operator[]>([])
const action = ref('')
const operatorId = ref<string | number>('')
const selectedLog = ref<AuditLog | null>(null)
const detailDrawer = ref(false)

function defaultRange(): [Date, Date] {
  const end = new Date()
  const start = new Date(end)
  start.setDate(start.getDate() - 7)
  start.setHours(0, 0, 0, 0)
  return [start, end]
}

const dateRange = ref<[Date, Date] | null>(defaultRange())
const canViewAudit = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('AUDIT_VIEW') || user?.roles.includes('SUPER_ADMIN'))
})
const operatorNameById = computed(() => new Map(operators.value.map((operator) => [String(operator.id), operator.name])))

const actionOptions = [
  { value: 'LOGIN', label: '登录' },
  { value: 'PASSWORD_CHANGED', label: '修改密码' },
  { value: 'USER_CREATED', label: '创建用户' },
  { value: 'USER_UPDATED', label: '更新用户' },
  { value: 'USER_ROLES_UPDATED', label: '更新用户角色' },
  { value: 'USER_SCOPES_UPDATED', label: '更新用户范围' },
  { value: 'OPERATOR_CREATED', label: '创建投放公司' },
  { value: 'OPERATOR_UPDATED', label: '更新投放公司' },
  { value: 'OPERATOR_DISABLED', label: '停用投放公司' },
  { value: 'OPERATOR_ACCOUNT_CREATED', label: '创建投放线' },
  { value: 'OPERATOR_ACCOUNT_UPDATED', label: '更新投放线' },
  { value: 'OPERATOR_ACCOUNT_DISABLED', label: '停用投放线' },
  { value: 'DAILY_BALANCE_CREATED', label: '创建日结' },
  { value: 'DAILY_BALANCE_UPDATED', label: '更新日结' },
  { value: 'DAILY_BALANCE_CONFIRMED', label: '确认日结' },
  { value: 'DAILY_BALANCE_REOPENED', label: '重开日结' },
  { value: 'IMPORT_COMMITTED', label: '提交导入' },
  { value: 'REPORT_EXPORTED', label: '导出报表' },
  { value: 'PERIOD_LOCKED', label: '锁定期间' },
  { value: 'PERIOD_UNLOCKED', label: '解锁期间' },
]

function actionLabel(value: string) {
  return actionOptions.find((item) => item.value === value)?.label || value || '未命名动作'
}

function actionTagType(value: string): 'success' | 'warning' | 'danger' | 'info' | '' {
  if (value.includes('DISABLED') || value.includes('LOCKED')) return 'danger'
  if (value.includes('CONFIRMED') || value.includes('REOPENED') || value.includes('IMPORT')) return 'warning'
  if (value.includes('LOGIN') || value.includes('CREATED')) return 'success'
  return 'info'
}

function entityLabel(value: string) {
  const labels: Record<string, string> = {
    USER: '用户', OPERATOR: '投放公司', OPERATOR_ACCOUNT: '投放线', DAILY_BALANCE: '日结', IMPORT_JOB: '导入任务', ACCOUNTING_PERIOD: '会计期间',
  }
  return labels[value] || value || '—'
}

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Shanghai',
  }).format(date)
}

function jsonText(value?: string) {
  if (!value) return '—'
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

function operatorLabel(log: AuditLog) {
  if (log.operatorId === undefined) return '全局记录'
  return operatorNameById.value.get(String(log.operatorId)) || `投放公司 #${log.operatorId}`
}

async function loadOperators() {
  try {
    operators.value = await api.operators.list()
  } catch {
    // The audit response stays usable even if the user cannot load the optional name lookup.
    operators.value = []
  }
}

async function load() {
  if (!canViewAudit.value) return
  loading.value = true
  loadError.value = ''
  try {
    logs.value = await api.audit.list({
      action: action.value || undefined,
      operatorId: operatorId.value || undefined,
      from: dateRange.value?.[0]?.toISOString(),
      to: dateRange.value?.[1]?.toISOString(),
    })
  } catch (error) {
    logs.value = []
    loadError.value = error instanceof Error ? error.message : '无法加载审计日志，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  action.value = ''
  operatorId.value = ''
  dateRange.value = defaultRange()
  void load()
}

function openDetail(log: AuditLog) {
  selectedLog.value = log
  detailDrawer.value = true
}

onMounted(async () => {
  if (!canViewAudit.value) return
  await Promise.all([loadOperators(), load()])
})
</script>

<template>
  <section>
    <div class="page-title-row">
      <div><h2>审计日志</h2><p class="page-subtitle">记录登录、投放公司与投放线变更、台账录入、确认、导入、锁账与权限变更。审计记录只追加，不可由普通用户修改。</p></div>
      <div v-if="canViewAudit" class="page-actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button></div>
    </div>

    <template v-if="!canViewAudit">
      <div class="empty-panel access-denied"><div><el-icon class="empty-icon"><Lock /></el-icon><h3>无审计日志查看权限</h3><p>此功能需要 <code>AUDIT_VIEW</code> 权限。请联系超级管理员为你的账号分配审计/只读或其他具备该权限的角色。</p></div></div>
    </template>

    <template v-else>
      <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>

      <article class="panel panel--padded audit-rules"><div><el-icon><DocumentChecked /></el-icon><strong>完整变更留痕</strong><p>每条业务修改保留操作者、时间、对象、请求 ID 与变更前后数据；默认仅查询最近 7 天，避免无范围地加载历史记录。</p></div><div><el-icon><Lock /></el-icon><strong>按授权范围展示</strong><p>审计/只读角色只能查询已授权投放公司相关记录及自己的全局操作；超级管理员可查看全部记录。</p></div></article>

      <article class="panel panel--padded">
        <div class="filter-bar">
          <el-form-item label="发生时间"><el-date-picker v-model="dateRange" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" :clearable="true" style="width: 350px" /></el-form-item>
          <el-form-item label="动作"><el-select v-model="action" clearable filterable placeholder="全部动作" style="width: 190px"><el-option v-for="item in actionOptions" :key="item.value" :label="item.label" :value="item.value"><span>{{ item.label }}</span><span class="option-code">{{ item.value }}</span></el-option></el-select></el-form-item>
          <el-form-item label="投放公司"><el-select v-model="operatorId" clearable filterable placeholder="全部投放公司 / 全局" style="width: 215px"><el-option v-for="operator in operators" :key="operator.id" :label="operator.name" :value="operator.id" /></el-select></el-form-item>
          <el-button type="primary" @click="load">查询</el-button><el-button @click="resetFilters">重置</el-button>
        </div>
      </article>

      <article class="panel table-card audit-table">
        <div class="audit-table-title"><div><h3>查询结果</h3><p>共 {{ logs.length }} 条，按发生时间倒序排列；时间按 Asia/Shanghai 显示。</p></div><span class="hint">点击“详情”查看完整变更数据</span></div>
        <el-table v-loading="loading" :data="logs" border max-height="590" size="small" empty-text="当前筛选没有审计记录">
          <el-table-column label="发生时间" width="185" fixed="left"><template #default="{ row }"><strong>{{ formatTime(row.createdAt) }}</strong></template></el-table-column>
          <el-table-column label="动作" min-width="174"><template #default="{ row }"><div class="action-cell"><el-tag size="small" effect="light" :type="actionTagType(row.action)">{{ actionLabel(row.action) }}</el-tag><span>{{ row.action }}</span></div></template></el-table-column>
          <el-table-column label="对象" min-width="145"><template #default="{ row }"><strong>{{ entityLabel(row.entityType) }}</strong><span class="muted">{{ row.entityId ? `#${row.entityId}` : '—' }}</span></template></el-table-column>
          <el-table-column label="投放公司范围" min-width="170" show-overflow-tooltip><template #default="{ row }"><span :class="{ 'global-log': row.operatorId === undefined }">{{ operatorLabel(row) }}</span></template></el-table-column>
          <el-table-column label="操作者" width="110"><template #default="{ row }"><span>{{ row.actorUserId === undefined ? '系统 / 匿名' : `用户 #${row.actorUserId}` }}</span></template></el-table-column>
          <el-table-column label="请求 ID" min-width="145" show-overflow-tooltip><template #default="{ row }"><code class="request-id">{{ row.requestId || '—' }}</code></template></el-table-column>
          <el-table-column label="操作" width="86" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template></el-table-column>
        </el-table>
      </article>
    </template>

    <el-drawer v-model="detailDrawer" title="审计记录详情" size="620px">
      <template v-if="selectedLog">
        <div class="detail-heading"><el-tag effect="light" :type="actionTagType(selectedLog.action)">{{ actionLabel(selectedLog.action) }}</el-tag><code>{{ selectedLog.action }}</code></div>
        <div class="detail-meta"><span>发生时间</span><strong>{{ formatTime(selectedLog.createdAt) }}</strong><span>对象</span><strong>{{ entityLabel(selectedLog.entityType) }}{{ selectedLog.entityId ? ` #${selectedLog.entityId}` : '' }}</strong><span>投放公司范围</span><strong>{{ operatorLabel(selectedLog) }}</strong><span>操作者</span><strong>{{ selectedLog.actorUserId === undefined ? '系统 / 匿名' : `用户 #${selectedLog.actorUserId}` }}</strong><span>请求 ID</span><code>{{ selectedLog.requestId || '—' }}</code><span>来源 IP</span><code>{{ selectedLog.ipAddress || '—' }}</code></div>
        <el-alert v-if="selectedLog.reason" class="audit-reason" type="info" :closable="false" show-icon>操作原因：{{ selectedLog.reason }}</el-alert>
        <div class="payload-section"><h4>变更前</h4><pre>{{ jsonText(selectedLog.beforeJson) }}</pre></div>
        <div class="payload-section"><h4>变更后</h4><pre>{{ jsonText(selectedLog.afterJson) }}</pre></div>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.load-error { margin-bottom: 16px; }
.audit-rules { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
.audit-rules > div { display: grid; grid-template-columns: 32px 1fr; column-gap: 10px; }
.audit-rules .el-icon { grid-row: span 2; display: grid; place-items: center; width: 32px; height: 32px; color: #6941c6; font-size: 17px; background: #f4f3ff; border-radius: 8px; }
.audit-rules strong { color: #344054; font-size: 14px; }
.audit-rules p { margin: 5px 0 0; color: #667085; font-size: 12px; line-height: 1.65; }
.audit-table { overflow: hidden; }
.audit-table-title { display: flex; align-items: flex-start; justify-content: space-between; padding: 18px 20px 14px; }
.audit-table-title h3 { margin: 0; color: #101828; font-size: 15px; }
.audit-table-title p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }
.action-cell { display: grid; gap: 5px; }
.action-cell > span, .option-code { color: #98a2b3; font-size: 10px; letter-spacing: .02em; }
.option-code { float: right; margin-left: 18px; }
.global-log { color: #667085; }
.request-id { color: #667085; font-size: 11px; }
.detail-heading { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
.detail-heading code { color: #667085; font-size: 12px; }
.detail-meta { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 10px 14px; padding: 16px; color: #475467; font-size: 13px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 8px; }
.detail-meta > span { color: #98a2b3; }
.detail-meta strong, .detail-meta code { min-width: 0; overflow-wrap: anywhere; color: #344054; font-weight: 500; }
.detail-meta code { font-size: 12px; }
.audit-reason { margin-top: 16px; }
.payload-section { margin-top: 20px; }
.payload-section h4 { margin: 0 0 8px; color: #344054; font-size: 13px; }
.payload-section pre { max-height: 300px; margin: 0; padding: 14px; overflow: auto; color: #344054; font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 8px; }
.empty-icon { margin-bottom: 9px; color: #98a2b3; font-size: 36px; }
.access-denied h3 { margin: 4px 0; color: #344054; }
.access-denied p { max-width: 540px; margin: 0; line-height: 1.7; }
.access-denied code { padding: 1px 4px; color: #6941c6; background: #f4f3ff; border-radius: 4px; }
</style>
