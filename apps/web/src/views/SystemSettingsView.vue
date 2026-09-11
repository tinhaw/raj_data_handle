<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  fetchRetentionSettings,
  updateRetentionSettings,
} from '../api/systemSettings'
import {
  createMonitorNotificationDestination,
  createMonitorNotificationTemplateSet,
  fetchMonitorNotificationDestinations,
  fetchMonitorNotificationTemplateSets,
} from '../api/remoteMarketMonitor'
import { isAdmin } from '../stores/auth'
import type {
  ChargeOrderExportDateMode,
  MonitorNotificationDestination,
  MonitorNotificationTemplateSet,
  RetentionSettings,
  SpinOrderQueryRange,
  SpinOrderRefreshIntervalHours,
  SpinOrderRefreshPageSize,
  WithdrawOrderExportDateMode,
  WithdrawPendingMonitorQueryRange,
  WithdrawPendingMonitorRefreshIntervalSeconds,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const current = ref<RetentionSettings | null>(null)
const notificationDestinations = ref<MonitorNotificationDestination[]>([])
const notificationTemplateSets = ref<MonitorNotificationTemplateSet[]>([])
const savingNotificationConfiguration = ref(false)
const destinationDraft = reactive({
  displayName: '', enabled: true, botToken: '', chatId: '', templateSetId: 'default-zh',
})

const templateDefinitions = [
  { key: 'threshold_opened', label: '超阈值首次告警', description: '连续超阈值达到设定次数时发送。' },
  { key: 'threshold_reminder', label: '超阈值重复告警', description: '告警未恢复时，按重复告警间隔发送。' },
  { key: 'threshold_recovered', label: '积压恢复通知', description: '数量连续恢复到恢复阈值后发送。' },
  { key: 'source_unavailable', label: '数据源异常告警', description: '远端查询连续失败达到设定次数时发送。' },
  { key: 'source_reminder', label: '数据源异常重复告警', description: '数据源持续不可用时，按异常提醒间隔发送。' },
  { key: 'source_recovered', label: '数据源恢复通知', description: '远端查询恢复成功后发送。' },
  { key: 'monitor_stale', label: '监控过期告警', description: '盘口超过预期时间未完成检查时使用。' },
  { key: 'monitor_recovered', label: '监控恢复通知', description: '过期的盘口监控恢复运行时使用。' },
  { key: 'test_message', label: '测试消息', description: '测试 Telegram 目的地时使用。' },
] as const
type MonitorTemplateKey = (typeof templateDefinitions)[number]['key']

const templatePlaceholders = [
  { token: '{source_display_name}', label: '盘口名称（必填）' },
  { token: '{source_id}', label: '盘口 ID' },
  { token: '{metric_label}', label: '指标名称' },
  { token: '{metric_name}', label: '指标代码' },
  { token: '{metric_count}', label: '当前数量' },
  { token: '{pending_audit_count}', label: '待审核数量' },
  { token: '{pending_review_count}', label: '待审查数量' },
  { token: '{comparison_label}', label: '比较符号' },
  { token: '{threshold}', label: '告警阈值' },
  { token: '{recovery_threshold}', label: '恢复阈值' },
  { token: '{checked_at_local}', label: '检查时间' },
  { token: '{query_range_local}', label: '查询范围' },
  { token: '{incident_id}', label: '事件编号' },
  { token: '{incident_started_at_local}', label: '事件开始时间' },
  { token: '{incident_duration}', label: '持续时间' },
  { token: '{peak_count}', label: '峰值数量' },
  { token: '{error_code}', label: '错误代码' },
  { token: '{safe_error_message}', label: '错误说明' },
] as const

function emptyTemplateMap(): Record<MonitorTemplateKey, string> {
  return Object.fromEntries(templateDefinitions.map((item) => [item.key, ''])) as Record<MonitorTemplateKey, string>
}

const templateDraft = reactive({
  id: '',
  displayName: '',
  activeKey: 'threshold_opened' as MonitorTemplateKey,
  templates: emptyTemplateMap(),
})
const templateTextareaRef = ref<{ textarea?: HTMLTextAreaElement } | null>(null)
const activeTemplateText = computed({
  get: () => templateDraft.templates[templateDraft.activeKey],
  set: (value: string) => { templateDraft.templates[templateDraft.activeKey] = value },
})
const activeTemplateDefinition = computed(
  () => templateDefinitions.find((item) => item.key === templateDraft.activeKey)!,
)
const form = reactive({
  uploadedFileRetentionDays: 3,
  resultRetentionDays: 30,
  remoteCacheRetentionDays: 30,
  syncLogRetentionDays: 30,
  withdrawPendingMonitorRefreshIntervalSeconds: 60 as WithdrawPendingMonitorRefreshIntervalSeconds,
  withdrawPendingMonitorQueryRange: 'india_today' as WithdrawPendingMonitorQueryRange,
  withdrawOrderExportDateMode: 'previous_day' as WithdrawOrderExportDateMode,
  withdrawOrderExportSpecificDate: null as string | null,
  withdrawOrderExportTime: '00:05:01',
  automaticSyncRetryLimit: 3,
  automaticSyncRetryIntervalMinutes: 5,
  remoteOrderSyncTimeoutSeconds: 180,
  chargeOrderExportDateMode: 'previous_day' as ChargeOrderExportDateMode,
  chargeOrderExportSpecificDate: null as string | null,
  chargeOrderExportTime: '00:00:01',
  spinOrderRefreshIntervalHours: 2 as SpinOrderRefreshIntervalHours,
  spinOrderRefreshPageSize: 100 as SpinOrderRefreshPageSize,
  spinOrderQueryRange: 'previous_business_day_to_completed_slot' as SpinOrderQueryRange,
  sessionTtlDays: 30,
})

function applySettings(settings: RetentionSettings): void {
  current.value = settings
  form.uploadedFileRetentionDays = settings.uploadedFileRetentionDays
  form.resultRetentionDays = settings.resultRetentionDays
  form.remoteCacheRetentionDays = settings.remoteCacheRetentionDays
  form.syncLogRetentionDays = settings.syncLogRetentionDays
  form.withdrawPendingMonitorRefreshIntervalSeconds =
    settings.withdrawPendingMonitorRefreshIntervalSeconds
  form.withdrawPendingMonitorQueryRange = settings.withdrawPendingMonitorQueryRange
  form.withdrawOrderExportDateMode = settings.withdrawOrderExportDateMode
  form.withdrawOrderExportSpecificDate = settings.withdrawOrderExportSpecificDate
  form.withdrawOrderExportTime = settings.withdrawOrderExportTime
  form.automaticSyncRetryLimit = settings.automaticSyncRetryLimit
  form.automaticSyncRetryIntervalMinutes = settings.automaticSyncRetryIntervalMinutes
  form.remoteOrderSyncTimeoutSeconds = settings.remoteOrderSyncTimeoutSeconds
  form.chargeOrderExportDateMode = settings.chargeOrderExportDateMode
  form.chargeOrderExportSpecificDate = settings.chargeOrderExportSpecificDate
  form.chargeOrderExportTime = settings.chargeOrderExportTime
  form.spinOrderRefreshIntervalHours = settings.spinOrderRefreshIntervalHours
  form.spinOrderRefreshPageSize = settings.spinOrderRefreshPageSize
  form.spinOrderQueryRange = settings.spinOrderQueryRange
  form.sessionTtlDays = settings.sessionTtlDays
}

async function load(): Promise<void> {
  loading.value = true
  try {
    applySettings(await fetchRetentionSettings())
    notificationDestinations.value = await fetchMonitorNotificationDestinations()
    notificationTemplateSets.value = await fetchMonitorNotificationTemplateSets()
    if (Object.values(templateDraft.templates).every((value) => !value)) {
      copyTemplateSet('default-zh', false)
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '系统配置加载失败。'))
  } finally {
    loading.value = false
  }
}

function copyTemplateSet(templateSetId: string, showMessage = true): void {
  const templateSet = notificationTemplateSets.value.find((item) => item.id === templateSetId)
  if (!templateSet) return
  for (const definition of templateDefinitions) {
    templateDraft.templates[definition.key] = templateSet.templates[definition.key] || ''
  }
  templateDraft.activeKey = 'threshold_opened'
  if (showMessage) ElMessage.success(`已载入“${templateSet.displayName}”，请填写新模板集 ID 和名称。`)
}

async function insertTemplatePlaceholder(token: string): Promise<void> {
  const textarea = templateTextareaRef.value?.textarea
  const value = activeTemplateText.value
  const start = textarea?.selectionStart ?? value.length
  const end = textarea?.selectionEnd ?? start
  activeTemplateText.value = `${value.slice(0, start)}${token}${value.slice(end)}`
  await nextTick()
  templateTextareaRef.value?.textarea?.focus()
  templateTextareaRef.value?.textarea?.setSelectionRange(start + token.length, start + token.length)
}

async function saveNotificationDestination(): Promise<void> {
  savingNotificationConfiguration.value = true
  try {
    await createMonitorNotificationDestination(destinationDraft)
    Object.assign(destinationDraft, { displayName: '', botToken: '', chatId: '' })
    notificationDestinations.value = await fetchMonitorNotificationDestinations()
    ElMessage.success('Telegram 通知目的地已添加。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'Telegram 通知目的地保存失败。'))
  } finally {
    savingNotificationConfiguration.value = false
  }
}

async function saveTemplateSet(): Promise<void> {
  const emptyDefinition = templateDefinitions.find(
    (definition) => !templateDraft.templates[definition.key].trim(),
  )
  if (emptyDefinition) {
    templateDraft.activeKey = emptyDefinition.key
    ElMessage.error(`“${emptyDefinition.label}”不能为空。`)
    return
  }
  const missingMarketDefinition = templateDefinitions.find(
    (definition) => !templateDraft.templates[definition.key].includes('{source_display_name}'),
  )
  if (missingMarketDefinition) {
    templateDraft.activeKey = missingMarketDefinition.key
    ElMessage.error(`“${missingMarketDefinition.label}”必须包含盘口名称占位符。`)
    return
  }
  const templates = Object.fromEntries(
    templateDefinitions.map((definition) => [definition.key, templateDraft.templates[definition.key]]),
  )
  savingNotificationConfiguration.value = true
  try {
    await createMonitorNotificationTemplateSet({ id: templateDraft.id, displayName: templateDraft.displayName, templates })
    Object.assign(templateDraft, { id: '', displayName: '', activeKey: 'threshold_opened', templates: emptyTemplateMap() })
    notificationTemplateSets.value = await fetchMonitorNotificationTemplateSets()
    copyTemplateSet('default-zh', false)
    ElMessage.success('通知模板集已创建。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '通知模板集保存失败。'))
  } finally {
    savingNotificationConfiguration.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    applySettings(await updateRetentionSettings({ ...form }))
    ElMessage.success('系统配置已更新；后续登录、同步与监控刷新会使用新的规则。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '保留策略保存失败。'))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">System settings</span>
        <h1>系统配置</h1>
        <p>当前配置对所有用户可见；只有超级管理员可以修改。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert
      title="保留策略的生效范围"
      description="修改文件、批次及订单级结果的默认值不会追溯改变已有数据；充值、提现和转盘订单本地缓存按当前缓存保留天数清理。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card settings-card">
      <div class="settings-heading"><div><h2>ERP 业务基准</h2><p>与原 ERP 当前云端版本一致；敏感参数继续由部署环境管理。</p></div><el-tag type="success">已融合</el-tag></div>
      <div class="form-grid">
        <el-form-item label="业务时区"><el-input model-value="Asia/Shanghai" disabled /></el-form-item>
        <el-form-item label="默认计算精度"><el-input model-value="2 位小数" disabled /></el-form-item>
        <el-form-item label="舍入方式"><el-input model-value="四舍五入（HALF_UP）" disabled /></el-form-item>
        <el-form-item label="台账导入"><el-input model-value=".xlsx · 最大 10 MB · 最大 20,000 行" disabled /></el-form-item>
      </div>
    </section>

    <el-alert
      title="登录有效期从成功登录时开始计时"
      description="会话不会因访问页面自动续期；修改时长只影响之后的新登录，不会追溯改变现有会话。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section v-loading="loading" class="surface-card settings-card">
      <div class="settings-heading">
        <div>
          <h2>全局配置</h2>
          <p>登录、充值订单、提现订单、转盘订单、同步日志与数据保留策略集中维护。</p>
        </div>
        <el-tag v-if="current" type="info">配置版本 V{{ current.configVersion }}</el-tag>
      </div>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>登录与会话</h2>
          <p>超级管理员可调整后续登录会话的最长有效期。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="登录有效时长（天）">
              <el-input-number
                v-model="form.sessionTtlDays"
                :min="1"
                :max="365"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；到期后需重新登录。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>远端订单同步超时</h2>
          <p>适用于充值、提现、转盘和评分审核订单的远端读取与 Excel 下载；不影响盘口连接测试。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="请求超时（秒）">
              <el-input-number
                v-model="form.remoteOrderSyncTimeoutSeconds"
                :min="30"
                :max="600"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 180 秒；连接建立仍最多等待 10 秒。新同步任务会使用保存后的值。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>自动同步失败重试</h2>
          <p>适用于充值、提现和转盘订单的自动任务；不影响管理员手动刷新。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="失败后最大重试次数">
              <el-input-number
                v-model="form.automaticSyncRetryLimit"
                :min="0"
                :max="10"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">不包含首次自动同步；设为 0 表示当天窗口失败后不再自动重试。</span>
            </el-form-item>
            <el-form-item label="重试间隔（分钟）">
              <el-input-number
                v-model="form.automaticSyncRetryIntervalMinutes"
                :min="1"
                :max="1440"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认每 5 分钟重试一次；达到次数上限后，等待下一个自动同步窗口。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>转盘订单远端同步</h2>
          <p>自动同步只读取远端数据，转盘订单页展示本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动刷新间隔（小时）">
              <el-select v-model="form.spinOrderRefreshIntervalHours" :disabled="!isAdmin">
                <el-option
                  v-for="hours in [1, 2, 3, 4, 6, 8, 12, 24]"
                  :key="hours"
                  :label="`每 ${hours} 小时`"
                  :value="hours"
                />
              </el-select>
              <span class="field-help">默认每 2 小时；每个时段开始 5 分钟后读取已完成时段的数据。</span>
            </el-form-item>
            <el-form-item label="自动查询时间范围">
              <el-select v-model="form.spinOrderQueryRange" :disabled="!isAdmin">
                <el-option label="仅上一完整时段" value="last_completed_slot" />
                <el-option label="最近 2 小时" value="last_2_hours" />
                <el-option label="最近 3 小时" value="last_3_hours" />
                <el-option label="最近 6 小时" value="last_6_hours" />
                <el-option label="最近 12 小时" value="last_12_hours" />
                <el-option label="前一天" value="previous_day" />
                <el-option
                  label="本业务日 00:00 至上一完整时段"
                  value="business_day_to_completed_slot"
                />
                <el-option
                  label="前一业务日 00:00 至上一完整时段（默认）"
                  value="previous_business_day_to_completed_slot"
                />
              </el-select>
              <span class="field-help">按各盘口业务时区计算；最近 N 小时截至上一完整时段，回查范围越长越能覆盖延迟审核状态。</span>
            </el-form-item>
            <el-form-item label="远端分页大小">
              <el-select v-model="form.spinOrderRefreshPageSize" :disabled="!isAdmin">
                <el-option
                  v-for="size in [10, 20, 30, 50, 100]"
                  :key="size"
                  :label="`${size} 条 / 页`"
                  :value="size"
                />
              </el-select>
              <span class="field-help">默认 100 条 / 页；数值越小，远端请求次数越多。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>充值订单 Excel 导出同步</h2>
          <p>按盘口业务时区每天导出一个自然日；充值订单页只查询本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动导出时间（盘口业务时区）">
              <el-time-picker
                v-model="form.chargeOrderExportTime"
                value-format="HH:mm:ss"
                format="HH:mm:ss"
                :clearable="false"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">每天按各盘口业务时区的该时刻开始导出；工作进程每 30 秒轮询，会自动补跑。</span>
            </el-form-item>
            <el-form-item label="自动导出日期">
              <el-select v-model="form.chargeOrderExportDateMode" :disabled="!isAdmin">
                <el-option
                  label="前一天"
                  value="previous_day"
                />
                <el-option label="指定日期（仅执行一次）" value="specific_date" />
              </el-select>
              <span class="field-help">
                默认导出前一天 00:00:00 至 23:59:59；指定日期成功导出后不会在下一天重复执行。
              </span>
            </el-form-item>
            <el-form-item
              v-if="form.chargeOrderExportDateMode === 'specific_date'"
              label="指定导出日期（盘口业务时区）"
            >
              <el-date-picker
                v-model="form.chargeOrderExportSpecificDate"
                type="date"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">仅导出该自然日的充值订单，需填写后才可保存。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>旧版提现汇总查询（兼容）</h2>
          <p>仅保留给旧版接口和已打开的旧页面；新的远端盘口监控不读取此处配置。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动刷新间隔（秒）">
              <el-select
                v-model="form.withdrawPendingMonitorRefreshIntervalSeconds"
                :disabled="!isAdmin"
              >
                <el-option
                  v-for="seconds in [5, 10, 15, 20, 25, 30, 60, 120, 300]"
                  :key="seconds"
                  :label="`每 ${seconds} 秒`"
                  :value="seconds"
                />
              </el-select>
              <span class="field-help">首次打开会立即查询；手动刷新不受此间隔限制。</span>
            </el-form-item>
            <el-form-item label="查询时间范围">
              <el-select v-model="form.withdrawPendingMonitorQueryRange" :disabled="!isAdmin">
                <el-option label="印度时间今天全天" value="india_today" />
                <el-option
                  label="印度时间昨天全天＋今天全天"
                  value="india_yesterday_today"
                />
              </el-select>
              <span class="field-help">统一按 Asia/Kolkata 的自然日计算，再查询待审核与待审查订单数量。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading"><h2>Telegram 通知目的地与模板</h2><p>Bot Token 和 Chat ID 由管理员直接填写，服务端加密保存且永不回显明文。模板按消息类型分别编辑，可点击插入占位符。</p></div>
        <div class="notification-config-grid">
          <section>
            <h3>已配置目的地</h3>
            <el-empty v-if="!notificationDestinations.length" description="尚未配置 Telegram 通知目的地" :image-size="72" />
            <div v-for="destination in notificationDestinations" :key="destination.id" class="notification-config-item"><strong>{{ destination.displayName }}</strong><span>{{ destination.enabled ? '已启用' : '已停用' }} · 模板：{{ destination.templateSetId }}</span><span>Bot Token {{ destination.botTokenConfigured ? '已配置' : '未配置' }} · Chat ID {{ destination.chatIdConfigured ? '已配置' : '未配置' }}</span></div>
            <el-form v-if="isAdmin" label-position="top" class="notification-draft">
              <el-form-item label="目的地名称"><el-input v-model="destinationDraft.displayName" placeholder="例如：运营告警群" /></el-form-item>
              <el-form-item label="Bot Token"><el-input v-model="destinationDraft.botToken" type="password" show-password autocomplete="new-password" placeholder="例如：123456789:AA..." /><span class="field-help">仅在保存时提交，之后只显示“已配置”。</span></el-form-item>
              <el-form-item label="Chat ID"><el-input v-model="destinationDraft.chatId" placeholder="例如：-1001234567890" /></el-form-item>
              <el-form-item label="通知模板集"><el-select v-model="destinationDraft.templateSetId"><el-option v-for="templateSet in notificationTemplateSets" :key="templateSet.id" :label="templateSet.displayName" :value="templateSet.id" /></el-select></el-form-item>
              <el-button type="primary" :loading="savingNotificationConfiguration" @click="saveNotificationDestination">添加通知目的地</el-button>
            </el-form>
          </section>
          <section>
            <h3>模板集</h3>
            <div v-for="templateSet in notificationTemplateSets" :key="templateSet.id" class="notification-config-item"><strong>{{ templateSet.displayName }}</strong><span>{{ templateSet.id }} · {{ templateSet.isBuiltin ? '内置只读' : '自定义' }}</span><el-button v-if="isAdmin" link type="primary" @click="copyTemplateSet(templateSet.id)">以此模板创建副本</el-button></div>
            <el-form v-if="isAdmin" label-position="top" class="notification-draft">
              <el-form-item label="新模板集 ID"><el-input v-model="templateDraft.id" placeholder="ops-zh" /></el-form-item>
              <el-form-item label="新模板集名称"><el-input v-model="templateDraft.displayName" placeholder="运营中文模板" /></el-form-item>
              <el-form-item label="消息类型">
                <el-select v-model="templateDraft.activeKey">
                  <el-option v-for="definition in templateDefinitions" :key="definition.key" :label="definition.label" :value="definition.key" />
                </el-select>
                <span class="field-help">{{ activeTemplateDefinition.description }}</span>
              </el-form-item>
              <el-form-item :label="activeTemplateDefinition.label">
                <el-input ref="templateTextareaRef" v-model="activeTemplateText" type="textarea" :rows="8" placeholder="输入要发送到 Telegram 的消息内容，并从下方插入占位符。" />
              </el-form-item>
              <div class="template-placeholder-panel">
                <strong>可用占位符</strong>
                <p>点击后插入到当前光标位置，发送时会替换为实际数据；每个消息模板都必须保留“盘口名称”。</p>
                <div class="template-placeholder-list">
                  <el-button v-for="placeholder in templatePlaceholders" :key="placeholder.token" size="small" plain @click="insertTemplatePlaceholder(placeholder.token)">
                    {{ placeholder.label }} <code>{{ placeholder.token }}</code>
                  </el-button>
                </div>
              </div>
              <el-button type="primary" :loading="savingNotificationConfiguration" @click="saveTemplateSet">创建模板集</el-button>
            </el-form>
          </section>
        </div>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>提现订单 Excel 导出同步</h2>
          <p>按盘口业务时区每天导出一个自然日；提现订单页只查询本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动导出时间（盘口业务时区）">
              <el-time-picker
                v-model="form.withdrawOrderExportTime"
                value-format="HH:mm:ss"
                format="HH:mm:ss"
                :clearable="false"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">每天按各盘口业务时区的该时刻开始导出；若对应盘口的评分审核 API 已配置并测试通过，完成后会继续同步评分审核 Excel。</span>
            </el-form-item>
            <el-form-item label="自动导出日期">
              <el-select v-model="form.withdrawOrderExportDateMode" :disabled="!isAdmin">
                <el-option label="前一天" value="previous_day" />
                <el-option label="指定日期（仅执行一次）" value="specific_date" />
              </el-select>
              <span class="field-help">
                默认导出前一天 00:00:00 至 23:59:59；指定日期成功导出后不会在下一天重复执行。
              </span>
            </el-form-item>
            <el-form-item
              v-if="form.withdrawOrderExportDateMode === 'specific_date'"
              label="指定导出日期（盘口业务时区）"
            >
              <el-date-picker
                v-model="form.withdrawOrderExportSpecificDate"
                type="date"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">仅导出该自然日的提现订单，需填写后才可保存。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>数据保留策略</h2>
          <p>允许范围为 1–3650 天。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="上传与导出文件">
              <el-input-number
                v-model="form.uploadedFileRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 3 天；最后一个有效引用过期后才清理物理文件。</span>
            </el-form-item>
            <el-form-item label="批次与订单级结果">
              <el-input-number
                v-model="form.resultRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；到期后不再保留订单级业务明细。</span>
            </el-form-item>
            <el-form-item label="远端订单缓存">
              <el-input-number
                v-model="form.remoteCacheRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；活跃批次引用的数据不会被清理。</span>
            </el-form-item>
            <el-form-item label="同步运行日志">
              <el-input-number
                v-model="form.syncLogRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；保留同步、导入、失败和部分完成的执行记录，不保留远端请求内容或原始 Excel。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <footer class="settings-footer">
        <span v-if="current">最后更新：{{ formatDateTime(current.updatedAt) }}</span>
        <el-button v-if="isAdmin" type="primary" :loading="saving" @click="save">
          保存配置
        </el-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.settings-card {
  padding: 24px;
}

.settings-heading,
.settings-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.settings-heading {
  margin-bottom: 22px;
}

.settings-heading h2,
.settings-heading p,
.settings-section-heading h2,
.settings-section-heading p {
  margin: 0;
}

.settings-heading p,
.settings-section-heading p,
.settings-footer,
.field-help {
  color: var(--ink-muted);
}

.settings-heading p,
.settings-section-heading p,
.field-help {
  font-size: 13px;
}

.settings-section {
  padding: 20px 0;
  border-top: 1px solid var(--border);
}

.settings-section + .settings-section {
  margin-top: 4px;
}

.settings-section-heading {
  margin-bottom: 16px;
}

.field-help {
  display: block;
  margin-top: 8px;
  line-height: 1.5;
}

.settings-card :deep(.el-select) {
  width: 100%;
}

.notification-config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 28px;
}

.notification-config-grid h3 {
  margin: 0 0 12px;
  font-size: 15px;
}

.notification-config-item {
  display: grid;
  gap: 4px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.notification-config-item span {
  color: var(--ink-muted);
  font-size: 12px;
}

.notification-draft {
  margin-top: 16px;
}

.template-placeholder-panel {
  margin: -2px 0 18px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-muted);
}

.template-placeholder-panel > strong {
  font-size: 13px;
}

.template-placeholder-panel > p {
  margin: 4px 0 10px;
  color: var(--ink-muted);
  font-size: 12px;
}

.template-placeholder-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.template-placeholder-list .el-button {
  margin: 0;
}

.template-placeholder-list code {
  margin-left: 4px;
  font-size: 11px;
}

@media (max-width: 900px) {
  .notification-config-grid {
    grid-template-columns: 1fr;
  }
}

.settings-footer {
  margin-top: 8px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
</style>
