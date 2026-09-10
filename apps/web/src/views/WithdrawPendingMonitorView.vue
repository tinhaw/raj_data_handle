<script setup lang="ts">
import { Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  fetchMonitorNotificationDestinations,
  fetchRemoteMarketMonitorOverview,
  testRemoteMarketMonitorTarget,
  updateRemoteMarketMonitorTarget,
} from '../api/remoteMarketMonitor'
import { isAdmin } from '../stores/auth'
import type {
  MonitorNotificationDestination,
  RemoteMarketMonitorMetricPolicy,
  RemoteMarketMonitorOverview,
  RemoteMarketMonitorTarget,
  RemoteMarketMonitorTargetUpdate,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const monitor = ref<RemoteMarketMonitorOverview | null>(null)
const destinations = ref<MonitorNotificationDestination[]>([])
const settingsVisible = ref(false)
const editingTarget = ref<RemoteMarketMonitorTarget | null>(null)
let refreshTimer: number | undefined

const form = reactive<RemoteMarketMonitorTargetUpdate>({
  enabled: false,
  checkIntervalSeconds: 60,
  queryWindowMode: 'business_today',
  previousDays: 1,
  sourceFailureConsecutiveChecks: null,
  sourceReminderIntervalMinutes: null,
  destinationIds: [],
  policies: [],
})

const deliveryLabel = computed(() =>
  monitor.value?.settings.deliveryMode === 'telegram' ? 'Telegram 投递' : '仅记录（灰度）',
)

function clearAutoRefresh(): void {
  if (refreshTimer) window.clearInterval(refreshTimer)
  refreshTimer = undefined
}

function scheduleAutoRefresh(): void {
  clearAutoRefresh()
  const interval = monitor.value?.settings.dashboardRefreshIntervalSeconds
  if (!interval) return
  refreshTimer = window.setInterval(() => void load(), interval * 1_000)
}

function healthTagType(health: string): 'success' | 'warning' | 'danger' | 'info' {
  if (health === 'healthy') return 'success'
  if (health === 'failing') return 'warning'
  if (health === 'unavailable') return 'danger'
  return 'info'
}

function healthLabel(health: string): string {
  if (health === 'healthy') return '正常'
  if (health === 'failing') return '读取异常中'
  if (health === 'unavailable') return '远端不可用'
  return '未开始'
}

function policyFor(target: RemoteMarketMonitorTarget, metric: string): RemoteMarketMonitorMetricPolicy {
  return target.policies.find((policy) => policy.metric === metric) ?? target.policies[0]!
}

function thresholdLabel(policy: RemoteMarketMonitorMetricPolicy): string {
  return `${policy.comparison === 'gt' ? '>' : '≥'} ${policy.threshold}`
}

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    monitor.value = await fetchRemoteMarketMonitorOverview()
    scheduleAutoRefresh()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端盘口监控加载失败。'))
  } finally {
    loading.value = false
  }
}

async function loadDestinations(): Promise<void> {
  if (!isAdmin.value) return
  try {
    destinations.value = await fetchMonitorNotificationDestinations()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'Telegram 通知目的地加载失败。'))
  }
}

function openSettings(target: RemoteMarketMonitorTarget): void {
  editingTarget.value = target
  form.enabled = target.enabled
  form.checkIntervalSeconds = target.checkIntervalSeconds
  form.queryWindowMode = target.queryWindowMode
  form.previousDays = target.previousDays
  form.sourceFailureConsecutiveChecks = target.sourceFailureConsecutiveChecks
  form.sourceReminderIntervalMinutes = target.sourceReminderIntervalMinutes
  form.destinationIds = [...target.destinationIds]
  form.policies = target.policies.map((policy) => ({ ...policy }))
  settingsVisible.value = true
}

async function saveTarget(): Promise<void> {
  if (!editingTarget.value) return
  saving.value = true
  try {
    await updateRemoteMarketMonitorTarget(editingTarget.value.sourceId, form)
    ElMessage.success('盘口监控策略已保存。')
    settingsVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口监控策略保存失败。'))
  } finally {
    saving.value = false
  }
}

async function testQuery(target: RemoteMarketMonitorTarget): Promise<void> {
  testing.value = true
  try {
    const result = await testRemoteMarketMonitorTarget(target.sourceId)
    if (result.status === 'ok') {
      ElMessage.success(`只读检查成功：待审核 ${result.pendingAuditCount}，待审查 ${result.pendingReviewCount}。`)
    } else {
      ElMessage.warning(result.safeErrorMessage || '只读检查未成功。')
    }
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '只读检查失败。'))
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  void Promise.all([load(), loadDestinations()])
})

onBeforeUnmount(clearAutoRefresh)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Remote market monitor</span>
        <h1>远端盘口监控</h1>
        <p>后台持续读取各盘口待审核与待审查数量；页面关闭后监控仍会继续运行。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
    </header>

    <el-alert
      title="远端只读监控"
      description="每次有效检查同时读取待审核（状态 0）和待审查（状态 4）的可信汇总数量；不下载或保存订单明细。"
      type="info"
      show-icon
      :closable="false"
    />

    <section v-if="monitor" class="surface-card monitor-summary">
      <div><span>全局监控</span><strong>{{ monitor.settings.monitorEnabled ? '已启用' : '未启用' }}</strong></div>
      <div><span>通知模式</span><strong>{{ deliveryLabel }}</strong></div>
      <div><span>开放事件</span><strong>{{ monitor.openIncidentCount }}</strong></div>
      <div><span>待投递消息</span><strong>{{ monitor.pendingOutboxCount }}</strong></div>
      <div><span>状态刷新</span><strong>每 {{ monitor.settings.dashboardRefreshIntervalSeconds }} 秒</strong></div>
    </section>

    <section class="surface-card monitor-sources-card" v-loading="loading && !monitor">
      <div class="section-heading">
        <div><h2>盘口策略与实时状态</h2><p>每个盘口独立检查、独立阈值、独立告警状态与 Telegram 群路由。</p></div>
        <el-tag v-if="monitor" type="info">{{ monitor.targets.length }} 个盘口</el-tag>
      </div>

      <el-empty v-if="monitor && !monitor.targets.length" description="暂无已配置后台地址的盘口。" />
      <div v-else-if="monitor" class="source-card-grid">
        <article v-for="target in monitor.targets" :key="target.sourceId" class="source-card" :class="{ 'source-card--disabled': !target.enabled }">
          <header class="source-card__header">
            <div><h3>{{ target.sourceDisplayName }}</h3><span>{{ target.sourceId }} · {{ target.businessTimezone }}</span></div>
            <el-tag :type="healthTagType(target.sourceHealth)">{{ target.enabled ? healthLabel(target.sourceHealth) : '监控未启用' }}</el-tag>
          </header>
          <div class="source-card__metrics">
            <div><span>待审核</span><strong>{{ target.lastPendingAuditCount ?? '—' }}</strong><small>告警 {{ thresholdLabel(policyFor(target, 'pending_audit')) }}</small></div>
            <div><span>待审查</span><strong>{{ target.lastPendingReviewCount ?? '—' }}</strong><small>告警 {{ thresholdLabel(policyFor(target, 'pending_review')) }}</small></div>
          </div>
          <div class="source-card__details">
            <span>检查周期：每 {{ target.checkIntervalSeconds }} 秒</span>
            <span>最后成功：{{ formatDateTime(target.lastSuccessAt) }}</span>
            <span>下次检查：{{ formatDateTime(target.nextCheckAt) }}</span>
          </div>
          <p v-if="target.lastSafeErrorMessage" class="source-card__message">{{ target.lastErrorCode }}：{{ target.lastSafeErrorMessage }}</p>
          <footer v-if="isAdmin" class="source-card__actions">
            <el-button link type="primary" :loading="testing" @click="testQuery(target)">只读检查</el-button>
            <el-button link type="primary" :icon="Setting" @click="openSettings(target)">配置策略</el-button>
          </footer>
        </article>
      </div>
    </section>

    <el-dialog v-model="settingsVisible" :title="`${editingTarget?.sourceDisplayName || ''} · 监控策略`" width="760px" destroy-on-close>
      <el-alert title="三个时间间隔相互独立" description="远端查询间隔决定多久取一次数量；重复告警间隔决定异常持续时多久再发一次 Telegram；页面刷新间隔只更新界面。当前全局模式为仅记录时不会发送 Telegram。" type="warning" show-icon :closable="false" />
      <el-form label-position="top" class="monitor-form">
        <div class="form-grid">
          <el-form-item label="启用该盘口监控"><el-switch v-model="form.enabled" /></el-form-item>
          <el-form-item label="远端查询间隔（秒）"><el-input-number v-model="form.checkIntervalSeconds" :min="30" :max="3600" /><span class="field-help">后台按此周期读取状态 0 和 4 的数量。</span></el-form-item>
          <el-form-item label="查询范围"><el-select v-model="form.queryWindowMode"><el-option label="盘口业务日当天" value="business_today" /><el-option label="当天及前 N 天" value="business_today_and_previous_days" /></el-select></el-form-item>
          <el-form-item v-if="form.queryWindowMode === 'business_today_and_previous_days'" label="回查天数"><el-input-number v-model="form.previousDays" :min="1" :max="7" /></el-form-item>
          <el-form-item label="源异常连续次数（留空继承全局）"><el-input-number v-model="form.sourceFailureConsecutiveChecks" :min="1" :max="20" clearable /></el-form-item>
          <el-form-item label="数据源异常重复告警间隔（分钟，留空继承全局）"><el-input-number v-model="form.sourceReminderIntervalMinutes" :min="1" :max="1440" clearable /></el-form-item>
        </div>
        <el-form-item label="Telegram 通知群">
          <el-select v-model="form.destinationIds" multiple placeholder="选择系统设置中已配置的目的地"><el-option v-for="destination in destinations.filter((item) => item.enabled)" :key="destination.id" :label="destination.displayName" :value="destination.id" /></el-select>
          <span class="field-help">群组和密钥引用在系统设置中管理；此处只绑定已配置目的地。</span>
        </el-form-item>
        <section v-for="policy in form.policies" :key="policy.metric" class="metric-policy">
          <h3>{{ policy.metric === 'pending_audit' ? '待审核（状态 0）' : '待审查（状态 4）' }}</h3>
          <div class="form-grid">
            <el-form-item label="启用该指标告警"><el-switch v-model="policy.enabled" /></el-form-item>
            <el-form-item label="比较方式"><el-select v-model="policy.comparison"><el-option label="大于（>）" value="gt" /><el-option label="大于等于（≥）" value="gte" /></el-select></el-form-item>
            <el-form-item label="告警阈值"><el-input-number v-model="policy.threshold" :min="0" /></el-form-item>
            <el-form-item label="恢复阈值"><el-input-number v-model="policy.recoveryThreshold" :min="0" :max="policy.threshold" /></el-form-item>
            <el-form-item label="连续超阈值次数"><el-input-number v-model="policy.breachConsecutiveChecks" :min="1" :max="20" /></el-form-item>
            <el-form-item label="连续恢复次数"><el-input-number v-model="policy.recoveryConsecutiveChecks" :min="1" :max="20" /></el-form-item>
            <el-form-item label="超阈值重复告警间隔（分钟，留空继承全局）"><el-input-number v-model="policy.reminderIntervalMinutes" :min="1" :max="1440" clearable /></el-form-item>
          </div>
        </section>
      </el-form>
      <template #footer><el-button @click="settingsVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveTarget">保存策略</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.monitor-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; padding: 18px 22px; }
.monitor-summary div, .source-card__metrics > div { display: grid; gap: 5px; }
.monitor-summary span, .source-card__header span, .source-card__metrics span, .source-card__metrics small, .source-card__details, .field-help { color: var(--ink-muted); font-size: 13px; }
.monitor-summary strong { font-size: 16px; color: var(--ink); }
.monitor-sources-card { padding: 24px; }
.section-heading, .source-card__header, .source-card__actions { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.section-heading { margin-bottom: 18px; }
.section-heading h2, .section-heading p, .source-card h3, .metric-policy h3 { margin: 0; }
.section-heading p { color: var(--ink-muted); font-size: 13px; margin-top: 6px; }
.source-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.source-card { border: 1px solid var(--border); border-top: 3px solid var(--el-color-success); border-radius: 12px; padding: 18px; background: var(--surface); }
.source-card--disabled { border-top-color: var(--ink-muted); opacity: .8; }
.source-card__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 18px 0; }
.source-card__metrics > div { padding: 13px; border-radius: 9px; background: var(--surface-muted); }
.source-card__metrics strong { font-size: 26px; color: var(--ink); }
.source-card__details { display: grid; gap: 5px; padding-top: 12px; border-top: 1px solid var(--border); }
.source-card__message { margin: 12px 0 0; color: var(--el-color-danger); font-size: 13px; line-height: 1.5; }
.source-card__actions { margin-top: 14px; align-items: center; }
.monitor-form { margin-top: 18px; }
.metric-policy { border-top: 1px solid var(--border); margin-top: 12px; padding-top: 18px; }
.metric-policy h3 { margin-bottom: 14px; font-size: 15px; }
.monitor-form :deep(.el-select), .monitor-form :deep(.el-input-number) { width: 100%; }
.field-help { display: block; margin-top: 6px; }
@media (max-width: 900px) { .monitor-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
