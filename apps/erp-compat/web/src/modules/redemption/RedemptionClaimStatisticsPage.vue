<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { claimStatisticsApi } from '@/api/client'
import { claimIntervals, type ClaimStatistics, type ClaimColumn, type ClaimCell, type ClaimCode, type ClaimRecord, type ClaimRun } from '@/api/claimStatistics'
import { useSessionStore } from '@/stores/session'
import { saveDownloadedFile } from '@/utils/download'
import RedemptionClaimTrend from './RedemptionClaimTrend.vue'
import ClaimConfigurationIds from './ClaimConfigurationIds.vue'

const route = useRoute(), router = useRouter(), session = useSessionStore()
const taskId = computed(() => String(route.params.taskId))
const compact = ref(window.innerWidth <= 640)
function measureViewport() { compact.value = window.innerWidth <= 640 }
const data = ref<ClaimStatistics>()
const loading = ref(false), error = ref(''), syncing = ref(false), exporting = ref(false)
const sourceId = ref(''), dates = ref<[string, string]>()
const displayedSourceId = ref('')
const sourceOptions = ref<Array<{ value: string; label: string }>>([])
const settingsOpen = ref(false), saving = ref(false), settingsLoading = ref(false)
const form = ref({ enabled: false, intervalMinutes: 30, rowVersion: 0 })
const detailOpen = ref(false), detailLoading = ref(false), detailError = ref('')
const selection = ref<{ date: string; column: ClaimColumn; version: string }>()
const selectedCode = ref<ClaimCode>()
const codeItems = ref<ClaimCode[]>([]), recordItems = ref<ClaimRecord[]>([])
const detailPage = ref(1), detailTotal = ref(0), activeRun = ref<ClaimRun>()
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0, disposed = false

function allowed(permission: string) {
  return Boolean(session.user?.permissions.some(p => p === '*' || p === permission) || session.user?.roles.includes('SUPER_ADMIN'))
}
const canSync = computed(() => allowed('REDEMPTION_STATS_SYNC'))
const canExport = computed(() => allowed('REDEMPTION_EXPORT'))
const markets = computed(() => {
  const map = new Map<string, { id: string; name: string; timezone: string; columns: ClaimColumn[] }>()
  for (const column of data.value?.columns || []) {
    if (!map.has(column.sourceId)) map.set(column.sourceId, { id: column.sourceId, name: column.sourceName, timezone: column.timezone, columns: [] })
    map.get(column.sourceId)!.columns.push(column)
  }
  return [...map.values()]
})
const partial = computed(() => data.value?.rows.some(row => !row.total.complete && row.total.state !== 'future'))
const intervalLabel = computed(() => claimIntervals.find(i => i.value === data.value?.schedule.intervalMinutes)?.label || '30 分钟')
const runLabel = computed(() => {
  const run = activeRun.value
  if (!run) return '当前无同步任务'
  const progress = run.progress
  const names: Record<string, string> = { queued: '等待同步', running: '同步中', succeeded: '同步完成', partial: '部分同步失败', failed: '同步失败', cancelled: '已取消', superseded: '执行已替换' }
  const backup = progress.backupGroups ? ` · 备用账号完成 ${progress.backupGroups} 组` : ''
  return `${names[run.status] || run.status} · 已完成 ${progress.completedGroups || 0}/${progress.totalGroups || 0} 组 · 失败 ${progress.failedGroups || 0} 组${backup}`
})
function time(value?: string) { return value ? `${new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })} 北京时间` : '—' }
function count(cell?: { count: number | null; complete?: boolean; state?: string }) {
  if (!cell || cell.count === null) return cell?.state === 'future' ? '未到日期' : cell?.state === 'notApplicable' ? '无适用配置' : '待同步'
  return `${cell.count.toLocaleString()}${cell.complete ? '' : '（部分）'}`
}
function stopPolling() { if (timer) clearTimeout(timer); timer = undefined }
function poll(run: ClaimRun) {
  stopPolling(); activeRun.value = run
  if (!['queued', 'running'].includes(run.status) || disposed) return
  const current = generation
  timer = setTimeout(async () => {
    try {
      const next = await claimStatisticsApi.progress(run.id)
      if (disposed || current !== generation) return
      activeRun.value = next
      if (['queued', 'running'].includes(next.status)) poll(next)
      else await load()
    } catch (e) { if (!disposed) error.value = `同步进度读取失败：${(e as Error).message}` }
  }, 2000)
}
async function load(reset = false) {
  const current = ++generation
  stopPolling(); loading.value = true; error.value = ''
  if (reset) { data.value = undefined; sourceId.value = ''; dates.value = undefined; sourceOptions.value = []; activeRun.value = undefined }
  const requestedSourceId = sourceId.value
  try {
    const result = await claimStatisticsApi.statistics(taskId.value, { dateFrom: dates.value?.[0], dateTo: dates.value?.[1], sourceId: requestedSourceId || undefined })
    if (current !== generation || disposed) return
    data.value = result; dates.value = [result.dateFrom, result.dateTo]
    displayedSourceId.value = requestedSourceId
    for (const column of result.columns) if (!sourceOptions.value.some(s => s.value === column.sourceId)) sourceOptions.value.push({ value: column.sourceId, label: column.sourceName })
    activeRun.value = result.schedule.activeRun || result.schedule.lastRun
    if (result.schedule.activeRun) poll(result.schedule.activeRun)
  } catch (e) { if (current === generation) error.value = (e as Error).message }
  finally { if (current === generation) loading.value = false }
}
async function openSettings() {
  settingsOpen.value = true; settingsLoading.value = true
  try { const setting = await claimStatisticsApi.settings(taskId.value); form.value = { enabled: setting.enabled, intervalMinutes: setting.intervalMinutes, rowVersion: setting.rowVersion } }
  catch (e) { ElMessage.error((e as Error).message); settingsOpen.value = false }
  finally { settingsLoading.value = false }
}
async function saveSettings() {
  saving.value = true
  try {
    const setting = await claimStatisticsApi.saveSettings(taskId.value, form.value)
    if (data.value) data.value.schedule = setting
    settingsOpen.value = false; ElMessage.success('同步设置已保存')
    if (setting.activeRun) poll(setting.activeRun)
  } catch (e) { ElMessage.error((e as Error).message) }
  finally { saving.value = false }
}
async function syncNow() {
  syncing.value = true
  try { const run = await claimStatisticsApi.sync(taskId.value); poll(run); ElMessage.success('已安排后台同步，可继续查看现有结果') }
  catch (e) { ElMessage.error((e as Error).message) }
  finally { syncing.value = false }
}
async function drill(date: string, column: ClaimColumn) {
  selection.value = { date, column, version: data.value!.queryVersion }
  selectedCode.value = undefined; detailPage.value = 1; detailOpen.value = true
  await loadDetail()
}
async function showRecords(code: ClaimCode) { selectedCode.value = code; detailPage.value = 1; await loadDetail() }
async function backToCodes() { selectedCode.value = undefined; detailPage.value = 1; await loadDetail() }
async function loadDetail() {
  const target = selection.value
  if (!target) return
  detailLoading.value = true; detailError.value = ''
  try {
    const params = { claimDate: target.date, queryVersion: target.version, page: detailPage.value, pageSize: 50 }
    if (selectedCode.value) {
      const result = await claimStatisticsApi.records(taskId.value, { ...params, groupId: selectedCode.value.groupId, code: selectedCode.value.code })
      recordItems.value = result.items; detailTotal.value = result.total
    } else {
      const result = await claimStatisticsApi.codes(taskId.value, { ...params, columnKey: target.column.key })
      codeItems.value = result.items; detailTotal.value = result.total
    }
  } catch (e) { detailError.value = (e as Error).message; codeItems.value = []; recordItems.value = [] }
  finally { detailLoading.value = false }
}
async function exportData() {
  if (!data.value || loading.value || exporting.value) return
  const current = data.value
  exporting.value = true
  try { saveDownloadedFile(await claimStatisticsApi.export(taskId.value, { dateFrom: current.dateFrom, dateTo: current.dateTo, sourceId: displayedSourceId.value || undefined, queryVersion: current.queryVersion, layout: 'template' })) }
  catch (e) { ElMessage.error((e as Error).message) }
  finally { exporting.value = false }
}
function summaries({ columns }: { columns: Array<{ property: string }> }) {
  return columns.map((column, index) => index === 0 ? '区间合计' : count(data.value?.totals[column.property]))
}
function back() { router.push({ name: 'redemption', query: { page: route.query.returnPage, pageSize: route.query.returnPageSize, tableScroll: route.query.returnTableScroll } }) }
watch(taskId, () => load(true), { immediate: true })
onMounted(() => window.addEventListener('resize', measureViewport))
onUnmounted(() => { disposed = true; generation++; stopPolling(); window.removeEventListener('resize', measureViewport) })
</script>

<template>
  <section class="claim-statistics-page">
    <el-button link type="primary" class="back-link" @click="back">← 返回兑换码管理</el-button>
    <div class="page-header"><div><h2>兑换码领取统计</h2><p>任务 {{ data?.taskNumber || taskId }} · 按实际领取日期统计 · 单位：次</p></div><div class="page-actions"><el-button v-if="canSync" @click="openSettings">同步设置</el-button><el-button v-if="canSync" type="primary" :loading="syncing" @click="syncNow">立即同步</el-button><el-button v-if="canExport" :loading="exporting" :disabled="!data || loading" @click="exportData">导出</el-button></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><template v-if="data">当前保留上次查询结果，请重试查询。</template></el-alert>
    <div class="claim-filters"><label>实际领取日期<el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" /></label><label>盘口<el-select v-model="sourceId" placeholder="全部盘口" clearable><el-option label="全部盘口" value="" /><el-option v-for="item in sourceOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label><el-button :loading="loading" @click="load()">查询</el-button></div>
    <el-alert v-if="partial" title="部分配置尚未同步或更新失败；标注“部分”的数字及合计不代表完整数量。" type="warning" :closable="false" show-icon />
    <div v-if="data" class="claim-status-strip" aria-live="polite"><span>自动同步：{{ data.schedule.enabled ? `每 ${intervalLabel}` : '关闭' }}</span><span>最近成功轮次：{{ time(data.schedule.lastSucceededAt) }}</span><span>下次计划：{{ data.schedule.activeRun ? '本轮结束后安排' : time(data.schedule.nextRunAt) }}</span></div>
    <div v-if="activeRun" class="claim-run" role="status">{{ runLabel }}<span v-if="activeRun.progress.errors?.length"> · {{ activeRun.progress.errors[0]?.message }}</span></div>
    <el-table v-loading="loading" :data="data?.rows || []" row-key="date" border show-summary :summary-method="summaries" class="claim-matrix" empty-text="尚无领取统计，请先同步领取记录">
      <el-table-column prop="date" label="实际领取日" fixed :width="compact ? 110 : 125" />
      <el-table-column v-for="market in markets" :key="market.id" :label="`${market.name} · ${market.timezone}`" align="center">
        <el-table-column v-for="column in market.columns" :key="column.key" :prop="column.key" :min-width="160" align="right">
          <template #header><div class="claim-tier"><strong>{{ column.tierName }}</strong><small>奖励 {{ column.currency }} {{ column.rewardMin }}–{{ column.rewardMax }}</small><small v-if="column.labels.length">标签 {{ column.labels.join('、') }}</small></div></template>
          <template #default="{ row }">
            <div class="claim-count-cell">
              <el-tooltip :content="row.cells[column.key].error || (row.cells[column.key].asOf ? `完整数据截至 ${time(row.cells[column.key].asOf)}` : '尚未取得完整结果')" placement="top"><el-button link type="primary" :disabled="row.cells[column.key].count === null" @click="drill(row.date, column)">{{ count(row.cells[column.key] as ClaimCell) }}</el-button></el-tooltip>
              <ClaimConfigurationIds
                :ids="row.cells[column.key].configurationIds || []"
                :context="`${row.date} · ${column.sourceName} · ${column.tierName}`"
              />
            </div>
          </template>
        </el-table-column>
      </el-table-column>
      <el-table-column prop="total" label="当日合计" :fixed="compact ? false : 'right'" width="140" align="right"><template #default="{ row }">{{ count(row.total) }}</template></el-table-column>
    </el-table>
    <p class="claim-footnote">各盘口按其业务时区归日；今天的数据为截至同步时的数量。点击远端 ID 可查看此格涉及的全部配置；查询和筛选读取本地结果。</p>
    <RedemptionClaimTrend v-if="data" :key="taskId" :columns="data.columns" :rows="data.rows" :loading="loading" />

    <el-dialog v-model="settingsOpen" title="同步设置" width="440px" align-center><el-form v-loading="settingsLoading" label-width="100px"><el-form-item label="自动同步"><el-switch v-model="form.enabled" /></el-form-item><el-form-item label="同步间隔"><el-select v-model="form.intervalMinutes"><el-option v-for="option in claimIntervals" :key="option.value" :label="option.label" :value="option.value" /></el-select></el-form-item></el-form><p class="claim-footnote">作用于本任务全部盘口。本轮结束后间隔；首次开启立即安排同步，运行中修改间隔在本轮结束后生效。</p><template #footer><el-button @click="settingsOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="settingsLoading" @click="saveSettings">保存设置</el-button></template></el-dialog>
    <el-dialog v-model="detailOpen" :title="selectedCode ? `${selectedCode.code} · 领取记录` : '各兑换码当日领取次数'" width="min(960px, 94vw)" destroy-on-close><p class="claim-detail-context">{{ selection?.date }} · {{ selection?.column.sourceName }} · {{ selection?.column.tierName }} · {{ selection?.column.timezone }}</p><el-alert v-if="detailError" :title="detailError" type="error" :closable="false" /><el-button v-if="selectedCode" link type="primary" @click="backToCodes">← 返回各码领取次数</el-button>
      <p v-if="selectedCode" class="claim-detail-context">远端配置 ID：{{ selectedCode.configurationId || '—' }}</p>
      <el-table v-if="!selectedCode" v-loading="detailLoading" :data="codeItems" max-height="480"><el-table-column prop="configurationId" label="远端配置 ID" width="130" /><el-table-column prop="description" label="组描述" min-width="160" /><el-table-column prop="claimDate" label="计划开始兑换日" width="140" /><el-table-column prop="code" label="兑换码" min-width="150" /><el-table-column label="当日次数" width="130" align="right"><template #default="{ row }"><el-button link type="primary" :disabled="row.count === null" @click="showRecords(row)">{{ count(row) }}</el-button></template></el-table-column><el-table-column label="号码核对" width="110"><template #default="{ row }">{{ row.matched ? '已登记' : '待核对' }}</template></el-table-column></el-table>
      <el-table v-else v-loading="detailLoading" :data="recordItems" max-height="480"><el-table-column prop="id" label="领取记录 ID" min-width="120" /><el-table-column prop="uid" label="用户 UID" min-width="120" /><el-table-column prop="code" label="兑换码" min-width="130" /><el-table-column prop="receiveTime" label="领取时间" min-width="180" /><el-table-column prop="amount" label="金额" width="100" align="right" /></el-table>
      <el-pagination v-model:current-page="detailPage" :page-size="50" :total="detailTotal" layout="total, prev, pager, next" class="claim-pagination" @current-change="loadDetail" />
    </el-dialog>
  </section>
</template>

<style scoped>
.claim-count-cell { display: grid; justify-items: end; gap: 2px; }
:global(body:has(.claim-statistics-page)){min-width:320px}
:global(body:has(.claim-statistics-page) .app-shell > .el-container){min-width:0}
:global(body:has(.claim-statistics-page) .app-main){min-width:0}
@media(max-width:760px){:global(body:has(.claim-statistics-page) .app-aside){display:none}:global(body:has(.claim-statistics-page) .app-header){padding:12px 16px}:global(body:has(.claim-statistics-page) .business-time){display:none}:global(body:has(.claim-statistics-page) .app-main){padding:20px 12px}}
.claim-statistics-page{min-width:0}.back-link{margin-bottom:16px}.page-header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:20px}.page-header h2{margin:0;color:var(--theme-text-strong);font-size:22px}.page-header p,.claim-footnote,.claim-detail-context{color:var(--theme-text-muted);font-size:12px;line-height:1.6}.page-actions{display:flex;gap:8px;flex-wrap:wrap}.page-actions .el-button+.el-button{margin-left:0}.claim-filters{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:20px 0}.claim-filters label{display:grid;gap:8px;color:var(--theme-text-muted);font-size:12px}.claim-filters .el-select{width:220px}.claim-status-strip{display:flex;gap:12px 24px;flex-wrap:wrap;margin:16px 0;color:var(--theme-text-muted);font-size:12px}.claim-run{margin:12px 0;color:var(--theme-text);font-size:13px}.claim-matrix{width:100%;font-variant-numeric:tabular-nums}.claim-tier{display:grid;gap:3px;text-align:right}.claim-tier strong{color:var(--theme-text-strong);font-weight:600}.claim-tier small{font-size:11px;color:var(--theme-text-muted);font-weight:400}.claim-pagination{margin-top:16px;justify-content:flex-end}.claim-detail-context{margin-top:0}.claim-statistics-page :deep(.el-alert){margin:12px 0}@media(max-width:640px){.claim-filters label{width:100%}.claim-filters :deep(.el-date-editor){width:100%!important}.claim-filters .el-select{width:100%}.claim-status-strip{display:grid;gap:8px}}
</style>
