<script setup lang="ts">
import { Download, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  cancelLocalErpRedemptionPublishSchedule,
  createErpRedemptionBatch,
  createErpRedemptionCampaign,
  createErpRedemptionTask,
  downloadErpRedemptionBatch,
  downloadErpRedemptionTask,
  fetchErpRedemptionBatch,
  fetchErpRedemptionBatches,
  fetchErpRedemptionCampaigns,
  fetchErpRedemptionRemoteExecutions,
  fetchErpRedemptionRemotePlan,
  fetchErpRedemptionTasks,
  importErpRedemptionCodes,
  publishErpRedemptionBatchLocal,
  recoverErpRedemptionRemotePlan,
  saveErpRedemptionPublishPlan,
  saveErpRedemptionRemotePlan,
  saveErpRedemptionTaskRemotePlans,
} from '../api/erpRedemption'
import { fetchRemoteAccounts, fetchRewardTierPreset } from '../api/remoteAccounts'
import { hasErpPermission } from '../stores/auth'
import type {
  ErpRedemptionBatch,
  ErpRedemptionBatchDetail,
  ErpRedemptionCampaign,
  ErpRedemptionRemoteExecution,
  ErpRedemptionRemotePlan,
  ErpRedemptionTask,
  RemoteAccount,
  RewardTierPreset,
} from '../types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

const loading = ref(false)
const saving = ref(false)
const campaigns = ref<ErpRedemptionCampaign[]>([])
const selectedCampaignId = ref('')
const batches = ref<ErpRedemptionBatch[]>([])
const tasks = ref<ErpRedemptionTask[]>([])
const remoteAccounts = ref<RemoteAccount[]>([])
const selectedBatch = ref<ErpRedemptionBatchDetail | null>(null)
const campaignDialog = ref(false)
const batchDialog = ref(false)
const taskDialog = ref(false)
const taskPlanDialog = ref(false)
const taskPlanTarget = ref<ErpRedemptionTask | null>(null)
const remotePlanDialog = ref(false)
const publishPlanDialog = ref(false)
const remotePlan = ref<ErpRedemptionRemotePlan | null>(null)
const remoteExecutions = ref<ErpRedemptionRemoteExecution[]>([])
const codeDrafts = reactive<Record<string, string>>({})
const tierLabelDrafts = reactive<Record<string, string>>({})

const campaignForm = reactive({
  code: '', name: '', lookbackDays: 7, description: '',
  tiers: [{ displayName: '基础档位', minDepositAmount: '0', bonusAmount: '0', bonusMaxAmount: '0' }],
})
const batchDateRange = ref<[string, string]>([today(), today()])
const taskDateRange = ref<[string, string]>([today(), today()])
const taskForm = reactive({ taskName: '', remoteAccountIds: [] as string[] })
const remotePlanForm = reactive({
  redemptionType: 'SEVEN_DAY_DEPOSIT' as 'SEVEN_DAY_DEPOSIT' | 'PREVIOUS_DAY_DEPOSIT',
  publishEnvironment: 'test' as 'test' | 'prod',
  flowTimes: 5,
  creationIntervalSeconds: 5,
  activityRecharge: '',
  activityRechargeCount: undefined as number | undefined,
  activityId: undefined as number | undefined,
  keyNumber: 1,
  singleUserLimit: 1,
  singleKeyLimit: 2000,
  requireBindBankCard: false,
  requireBindPhone: true,
  checkUuid: true,
  uuidRewardLimit: 1,
  checkLoginIp: true,
  loginIpRewardLimit: 1,
  checkRegisterIp: true,
  registerIpRewardLimit: 1,
})
const publishPlanForm = reactive({
  mode: 'SCHEDULED' as 'IMMEDIATE' | 'SCHEDULED',
  scheduledLocalAt: '',
  fallbackToScheduled: true,
  note: '',
})

const selectedCampaign = computed(() => campaigns.value.find((campaign) => campaign.id === selectedCampaignId.value))
const readyForLocalPublish = computed(() => selectedBatch.value?.batch.status === 'READY_LOCAL')

async function loadCampaigns(): Promise<void> {
  campaigns.value = await fetchErpRedemptionCampaigns()
  if (!selectedCampaignId.value && campaigns.value[0]) selectedCampaignId.value = campaigns.value[0].id
}

async function loadBatches(): Promise<void> {
  if (!selectedCampaignId.value) {
    batches.value = []
    selectedBatch.value = null
    remotePlan.value = null
    remoteExecutions.value = []
    return
  }
  batches.value = await fetchErpRedemptionBatches(selectedCampaignId.value)
  if (selectedBatch.value && !batches.value.some((batch) => batch.id === selectedBatch.value?.batch.id)) {
    selectedBatch.value = null
  }
}

async function loadTasks(): Promise<void> {
  tasks.value = selectedCampaignId.value
    ? await fetchErpRedemptionTasks(selectedCampaignId.value)
    : []
}

async function load(): Promise<void> {
  loading.value = true
  try {
    await loadCampaigns()
    await Promise.all([
      loadBatches(),
      loadTasks(),
      hasErpPermission('ERP_REDEMPTION_VIEW') ? fetchRemoteAccounts().then((items) => { remoteAccounts.value = items }) : Promise.resolve(),
    ])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码管理加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
  }
}

function openTaskDialog(): void {
  taskForm.taskName = ''
  taskForm.remoteAccountIds = remoteAccounts.value.filter((item) => item.enabled).map((item) => item.id)
  taskDateRange.value = [today(), today()]
  taskDialog.value = true
}

async function saveTask(): Promise<void> {
  if (!selectedCampaignId.value || !taskForm.remoteAccountIds.length) {
    ElMessage.warning('请选择至少一个远端账号作为本地子任务。')
    return
  }
  saving.value = true
  try {
    await createErpRedemptionTask({
      campaignId: selectedCampaignId.value,
      taskName: taskForm.taskName || undefined,
      claimDateFrom: taskDateRange.value[0],
      claimDateTo: taskDateRange.value[1],
      remoteAccountIds: taskForm.remoteAccountIds,
    })
    taskDialog.value = false
    ElMessage.success('本地多盘口任务组已创建。')
    await Promise.all([loadTasks(), loadBatches()])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '任务组创建失败。'))
  } finally {
    saving.value = false
  }
}

function resetRemotePlanForm(): void {
  Object.assign(remotePlanForm, {
    redemptionType: 'SEVEN_DAY_DEPOSIT',
    publishEnvironment: 'test',
    flowTimes: 5,
    creationIntervalSeconds: 5,
    activityRecharge: '',
    activityRechargeCount: undefined,
    activityId: undefined,
    keyNumber: 1,
    singleUserLimit: 1,
    singleKeyLimit: 2000,
    requireBindBankCard: false,
    requireBindPhone: true,
    checkUuid: true,
    uuidRewardLimit: 1,
    checkLoginIp: true,
    loginIpRewardLimit: 1,
    checkRegisterIp: true,
    registerIpRewardLimit: 1,
  })
}

function openTaskPlanDialog(task: ErpRedemptionTask): void {
  taskPlanTarget.value = task
  resetRemotePlanForm()
  taskPlanDialog.value = true
}

async function saveTaskPlans(): Promise<void> {
  if (!taskPlanTarget.value) return
  saving.value = true
  try {
    const plans = await saveErpRedemptionTaskRemotePlans(taskPlanTarget.value.id, {
      redemptionType: remotePlanForm.redemptionType,
      publishEnvironment: remotePlanForm.publishEnvironment,
      flowTimes: remotePlanForm.flowTimes,
      creationIntervalSeconds: remotePlanForm.creationIntervalSeconds,
      activityRecharge: remotePlanForm.activityRecharge || undefined,
      activityRechargeCount: remotePlanForm.activityRechargeCount,
      activityId: remotePlanForm.activityId,
      keyNumber: remotePlanForm.keyNumber,
      singleUserLimit: remotePlanForm.singleUserLimit,
      singleKeyLimit: remotePlanForm.singleKeyLimit,
      requireBindBankCard: remotePlanForm.requireBindBankCard,
      requireBindPhone: remotePlanForm.requireBindPhone,
      checkUuid: remotePlanForm.checkUuid,
      uuidRewardLimit: remotePlanForm.uuidRewardLimit,
      checkLoginIp: remotePlanForm.checkLoginIp,
      loginIpRewardLimit: remotePlanForm.loginIpRewardLimit,
      checkRegisterIp: remotePlanForm.checkRegisterIp,
      registerIpRewardLimit: remotePlanForm.registerIpRewardLimit,
    })
    taskPlanDialog.value = false
    ElMessage.success(`已为 ${plans.length} 个盘口子任务生成本地参数快照。`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '任务组批量配置失败，请先完善各远端账号的档位预设。'))
  } finally {
    saving.value = false
  }
}

function openCampaignDialog(): void {
  campaignForm.code = ''
  campaignForm.name = ''
  campaignForm.lookbackDays = 7
  campaignForm.description = ''
  campaignForm.tiers = [{ displayName: '基础档位', minDepositAmount: '0', bonusAmount: '0', bonusMaxAmount: '0' }]
  campaignDialog.value = true
}

function addTier(): void {
  campaignForm.tiers.push({ displayName: '', minDepositAmount: '', bonusAmount: '', bonusMaxAmount: '' })
}

async function saveCampaign(): Promise<void> {
  if (!campaignForm.code.trim() || !campaignForm.name.trim()) {
    ElMessage.warning('请填写活动编码和名称。')
    return
  }
  if (campaignForm.tiers.some((tier) => !tier.minDepositAmount || !tier.bonusAmount)) {
    ElMessage.warning('请完整填写每个充值档位的门槛和赠金。')
    return
  }
  saving.value = true
  try {
    const campaign = await createErpRedemptionCampaign({
      code: campaignForm.code,
      name: campaignForm.name,
      lookbackDays: campaignForm.lookbackDays,
      description: campaignForm.description || undefined,
      tiers: campaignForm.tiers.map((tier, index) => ({ ...tier, sortOrder: index + 1 })),
    })
    selectedCampaignId.value = campaign.id
    campaignDialog.value = false
    ElMessage.success('本地兑换码活动已创建。')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '活动创建失败。'))
  } finally {
    saving.value = false
  }
}

async function saveBatch(): Promise<void> {
  if (!selectedCampaignId.value) return
  saving.value = true
  try {
    selectedBatch.value = await createErpRedemptionBatch({
      campaignId: selectedCampaignId.value,
      claimDateFrom: batchDateRange.value[0],
      claimDateTo: batchDateRange.value[1],
    })
    batchDialog.value = false
    ElMessage.success('本地兑换码任务批次已创建。')
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批次创建失败。'))
  } finally {
    saving.value = false
  }
}

async function selectBatch(batchId: string): Promise<void> {
  try {
    selectedBatch.value = await fetchErpRedemptionBatch(batchId)
    for (const issue of selectedBatch.value.issues) codeDrafts[issue.id] = issue.redemptionCode || ''
    if (selectedBatch.value.batch.remoteAccountId) {
      remotePlan.value = await fetchErpRedemptionRemotePlan(batchId)
      remoteExecutions.value = remotePlan.value
        ? await fetchErpRedemptionRemoteExecutions(batchId)
        : []
    } else {
      remotePlan.value = null
      remoteExecutions.value = []
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码任务加载失败。'))
  }
}

function remoteStatusLabel(status: ErpRedemptionRemotePlan['workflowStatus']): string {
  return {
    AWAITING_CREATE_AUTHORIZATION: '等待远端创建授权',
    CREATING: '正在创建',
    CREATE_FAILED: '创建失败',
    READY_TO_PUBLISH: '待安排发布',
    AWAITING_PUBLISH_AUTHORIZATION: '等待发布授权',
    PUBLISHING: '正在发布',
    PUBLISH_FAILED: '发布失败',
    PUBLISH_SCHEDULED: '远端定时已提交',
    PUBLISHED: '已远端发布',
    DOWNLOADING: '正在下载',
    DOWNLOAD_FAILED: '下载失败',
    COMPLETED: '远端流程完成',
    CANCEL_PENDING: '正在取消',
    CANCEL_FAILED: '取消失败',
    CANCELLED: '远端发布已取消',
  }[status]
}

async function openRemotePlanDialog(): Promise<void> {
  if (!selectedBatch.value?.batch.remoteAccountId) {
    ElMessage.warning('兼容旧单批次没有统一远端账号，不能配置远端编排。')
    return
  }
  const plan = remotePlan.value
  remotePlanForm.redemptionType = plan?.redemptionType || 'SEVEN_DAY_DEPOSIT'
  remotePlanForm.publishEnvironment = plan?.publishEnvironment || 'test'
  remotePlanForm.flowTimes = plan?.flowTimes ?? 5
  remotePlanForm.creationIntervalSeconds = plan?.creationIntervalSeconds ?? 5
  remotePlanForm.activityRecharge = plan?.activityRecharge || ''
  remotePlanForm.activityRechargeCount = plan?.activityRechargeCount ?? undefined
  remotePlanForm.activityId = plan?.activityId ?? undefined
  remotePlanForm.keyNumber = plan?.keyNumber ?? 1
  remotePlanForm.singleUserLimit = plan?.singleUserLimit ?? 1
  remotePlanForm.singleKeyLimit = plan?.singleKeyLimit ?? 2000
  remotePlanForm.requireBindBankCard = plan?.requireBindBankCard ?? false
  remotePlanForm.requireBindPhone = plan?.requireBindPhone ?? true
  remotePlanForm.checkUuid = plan?.checkUuid ?? true
  remotePlanForm.uuidRewardLimit = plan?.uuidRewardLimit ?? 1
  remotePlanForm.checkLoginIp = plan?.checkLoginIp ?? true
  remotePlanForm.loginIpRewardLimit = plan?.loginIpRewardLimit ?? 1
  remotePlanForm.checkRegisterIp = plan?.checkRegisterIp ?? true
  remotePlanForm.registerIpRewardLimit = plan?.registerIpRewardLimit ?? 1
  let preset: RewardTierPreset | null = null
  if (!plan) {
    try {
      preset = await fetchRewardTierPreset(selectedBatch.value.batch.remoteAccountId)
    } catch {
      // A missing preset is valid; the operator can enter label IDs manually.
    }
  }
  for (const tier of selectedCampaign.value?.tiers || []) {
    const issue = selectedBatch.value.issues.find((item) => item.campaignTierId === tier.id)
    const savedTier = preset?.tiers.find((item) =>
      (tier.displayName && item.displayName === tier.displayName)
      || Number(item.minDepositAmount) === Number(tier.minDepositAmount),
    )
    tierLabelDrafts[tier.id] = issue?.remoteLabelIds.join(', ')
      || savedTier?.labelIds.join(', ')
      || ''
  }
  if (preset?.stale) ElMessage.warning('账号档位预设基于旧标签快照，请核对标签 ID。')
  remotePlanDialog.value = true
}

async function saveRemotePlan(): Promise<void> {
  if (!selectedBatch.value) return
  const tierLabelIds: Record<string, number[]> = {}
  for (const tier of selectedCampaign.value?.tiers || []) {
    const values = (tierLabelDrafts[tier.id] || '')
      .split(/[，,\s]+/)
      .filter(Boolean)
      .map(Number)
    if (
      (remotePlanForm.redemptionType === 'SEVEN_DAY_DEPOSIT' && !values.length)
      || values.some((value) => !Number.isInteger(value) || value < 1)
    ) {
      ElMessage.warning(`请为“${tier.displayName || tier.minDepositAmount}”填写有效标签 ID。`)
      return
    }
    tierLabelIds[tier.id] = [...new Set(values)]
  }
  saving.value = true
  try {
    remotePlan.value = await saveErpRedemptionRemotePlan(selectedBatch.value.batch.id, {
      ...remotePlanForm,
      activityRecharge: remotePlanForm.activityRecharge || undefined,
      activityRechargeCount: remotePlanForm.activityRechargeCount,
      activityId: remotePlanForm.activityId,
      tierLabelIds,
      rowVersion: remotePlan.value?.rowVersion,
    })
    remotePlanDialog.value = false
    ElMessage.success('远端编排参数快照已保存；尚未执行任何远端操作。')
    await selectBatch(selectedBatch.value.batch.id)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端编排参数保存失败。'))
  } finally {
    saving.value = false
  }
}

function openPublishPlanDialog(): void {
  if (!remotePlan.value) return
  publishPlanForm.mode = remotePlan.value.publishMode || 'SCHEDULED'
  publishPlanForm.scheduledLocalAt = remotePlan.value.scheduledPublishLocalAt?.slice(0, 19) || ''
  publishPlanForm.fallbackToScheduled = remotePlan.value.fallbackToScheduled
  publishPlanForm.note = remotePlan.value.publishNote || ''
  publishPlanDialog.value = true
}

async function savePublishPlan(): Promise<void> {
  if (!selectedBatch.value || !remotePlan.value) return
  if (publishPlanForm.mode === 'SCHEDULED' && !publishPlanForm.scheduledLocalAt) {
    ElMessage.warning('请选择盘口业务时区的定时发布时间。')
    return
  }
  saving.value = true
  try {
    remotePlan.value = await saveErpRedemptionPublishPlan(selectedBatch.value.batch.id, {
      mode: publishPlanForm.mode,
      scheduledLocalAt: publishPlanForm.mode === 'SCHEDULED'
        ? publishPlanForm.scheduledLocalAt
        : undefined,
      fallbackToScheduled: publishPlanForm.fallbackToScheduled,
      note: publishPlanForm.note || undefined,
      rowVersion: remotePlan.value.rowVersion,
    })
    publishPlanDialog.value = false
    ElMessage.success('发布计划已保存在本地；到期后仍需单独获得远端发布授权。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '发布计划保存失败。'))
  } finally {
    saving.value = false
  }
}

async function cancelLocalSchedule(): Promise<void> {
  if (!selectedBatch.value || !remotePlan.value) return
  try {
    const result = await ElMessageBox.prompt(
      '此操作只取消尚未提交远端的本地定时计划，请填写原因。',
      '取消本地计划',
      { inputPattern: /\S+/, inputErrorMessage: '必须填写取消原因。' },
    )
    remotePlan.value = await cancelLocalErpRedemptionPublishSchedule(
      selectedBatch.value.batch.id,
      remotePlan.value.rowVersion,
      result.value,
    )
    ElMessage.success('本地定时发布计划已取消。')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '取消本地计划失败。'))
  }
}

async function recoverRemotePlan(): Promise<void> {
  if (!selectedBatch.value || !remotePlan.value) return
  try {
    await ElMessageBox.confirm(
      '恢复只会清除已取消的发布占位并回到待编排状态，不会重新提交远端。',
      '恢复远端编排',
      { type: 'warning' },
    )
    remotePlan.value = await recoverErpRedemptionRemotePlan(
      selectedBatch.value.batch.id,
      remotePlan.value.rowVersion,
    )
    ElMessage.success('远端编排已恢复为待处理状态。')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '恢复远端编排失败。'))
  }
}

async function saveCodes(): Promise<void> {
  if (!selectedBatch.value) return
  const changed = selectedBatch.value.issues.filter((issue) => {
    const draft = codeDrafts[issue.id]?.trim() || ''
    return draft && draft !== issue.redemptionCode
  })
  if (!changed.length) {
    ElMessage.info('没有需要登记的新兑换码。')
    return
  }
  saving.value = true
  try {
    selectedBatch.value = await importErpRedemptionCodes(
      selectedBatch.value.batch.id,
      changed.map((issue) => ({
        issueId: issue.id,
        redemptionCode: (codeDrafts[issue.id] || '').trim(),
        rowVersion: issue.rowVersion,
      })),
    )
    ElMessage.success('兑换码已登记到本地任务。')
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码登记失败。'))
  } finally {
    saving.value = false
  }
}

async function publishLocal(): Promise<void> {
  if (!selectedBatch.value) return
  try {
    await ElMessageBox.confirm(
      '此操作仅将本地任务标记为“已本地发布”，不会向任何远端系统发布。是否继续？',
      '标记本地发布',
      { type: 'warning', confirmButtonText: '标记', cancelButtonText: '取消' },
    )
    selectedBatch.value = await publishErpRedemptionBatchLocal(
      selectedBatch.value.batch.id,
      selectedBatch.value.batch.rowVersion,
    )
    ElMessage.success('批次已标记为本地发布。')
    await loadBatches()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '本地发布标记失败。'))
  }
}

async function exportBatch(): Promise<void> {
  if (!selectedBatch.value) return
  try {
    saveBlob(
      await downloadErpRedemptionBatch(selectedBatch.value.batch.id),
      `erp-redemption-${selectedBatch.value.batch.id}.xlsx`,
    )
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码导出失败。'))
  }
}

async function exportTask(task: ErpRedemptionTask): Promise<void> {
  try {
    saveBlob(
      await downloadErpRedemptionTask(task.id),
      `erp-redemption-task-${task.id}.xlsx`,
    )
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '任务组联合导出失败。'))
  }
}

watch(selectedCampaignId, () => {
  void loadBatches()
  void loadTasks()
})
onMounted(() => void load())
</script>

<template>
  <div class="page-stack redemption-page">
    <header class="page-header">
      <div><span class="page-eyebrow">ERP local redemption</span><h1>兑换码管理</h1><p>维护本地活动、兑换码任务和已取得代码的登记记录；远端创建、发布、下载始终未启用。</p></div>
      <div class="header-actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_MANAGE')" type="primary" :icon="Plus" @click="openCampaignDialog">新建活动</el-button></div>
    </header>

    <el-alert title="远端执行门控保持关闭" description="现在可以配置远端参数快照和发布计划，但页面仍不读取密码、会话或 TOTP，也没有远端执行入口。创建、发布、取消和下载必须分别获得账号能力与本次明确授权。" type="warning" show-icon :closable="false" />

    <section class="surface-card redemption-filter"><el-select v-model="selectedCampaignId" filterable placeholder="选择兑换活动"><el-option v-for="campaign in campaigns" :key="campaign.id" :value="campaign.id" :label="`${campaign.code} · ${campaign.name}`" /></el-select><span v-if="selectedCampaign">档位 {{ selectedCampaign.tiers.length }} 个 · 已登记 {{ selectedCampaign.importedCodeCount }} / {{ selectedCampaign.plannedCodeCount }} 个代码</span><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && selectedCampaign" type="primary" plain @click="openTaskDialog">新建任务组</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && selectedCampaign" @click="batchDialog = true">兼容旧单批次</el-button></section>

    <section class="surface-card table-card"><div class="section-heading"><div><h2>多盘口任务组</h2><p>按选择顺序拆分为盘口/账号子任务；批量配置只生成本地参数快照。</p></div></div><el-table v-loading="loading" :data="tasks" row-key="id" empty-text="当前活动暂无多盘口任务组"><el-table-column prop="taskName" label="任务组" min-width="185" /><el-table-column label="领取日期" min-width="180"><template #default="{ row }">{{ row.claimDateFrom }} 至 {{ row.claimDateTo }}</template></el-table-column><el-table-column label="子任务" width="90" align="right"><template #default="{ row }">{{ row.subtasks.length }}</template></el-table-column><el-table-column label="已登记 / 总数" min-width="130" align="right"><template #default="{ row }">{{ row.importedCodeCount }} / {{ row.expectedCodeCount }}</template></el-table-column><el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="row.status === 'PUBLISHED_LOCAL' ? 'success' : row.status === 'READY_LOCAL' ? 'warning' : 'info'">{{ row.status }}</el-tag></template></el-table-column><el-table-column label="子任务" min-width="230"><template #default="{ row }"><el-button v-for="item in row.subtasks" :key="item.batchId" text type="primary" @click="selectBatch(item.batchId)">{{ item.executionOrder }}. {{ item.sourceDisplayName }} · {{ item.remoteAccountName }}</el-button></template></el-table-column><el-table-column label="操作" width="220" fixed="right"><template #default="{ row }"><div class="task-actions"><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE')" text type="primary" @click="openTaskPlanDialog(row)">批量配置</el-button><el-button text type="primary" :icon="Download" @click="exportTask(row)">联合导出</el-button></div></template></el-table-column></el-table></section>

    <section class="surface-card table-card"><div class="section-heading"><div><h2>本地任务批次</h2><p>每个领取日期 × 充值档位生成一条本地代码登记任务。</p></div></div><el-table v-loading="loading" :data="batches" row-key="id" empty-text="当前活动暂无任务批次"><el-table-column label="领取日期" min-width="180"><template #default="{ row }">{{ row.claimDateFrom }} 至 {{ row.claimDateTo }}</template></el-table-column><el-table-column prop="expectedCodeCount" label="任务数" width="90" align="right" /><el-table-column label="已登记" width="100" align="right"><template #default="{ row }">{{ row.importedCodeCount }}</template></el-table-column><el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="row.status === 'PUBLISHED_LOCAL' ? 'success' : row.status === 'READY_LOCAL' ? 'warning' : 'info'">{{ row.status }}</el-tag></template></el-table-column><el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button text type="primary" @click="selectBatch(row.id)">查看</el-button></template></el-table-column></el-table></section>

    <section v-if="selectedBatch?.batch.remoteAccountId" class="surface-card remote-plan-card">
      <div class="redemption-detail-heading">
        <div><h2>远端作业编排</h2><p>这里只保存参数、发布意图和状态历史；不会执行远端创建、发布、取消或下载。</p></div>
        <div class="header-actions"><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE')" @click="openRemotePlanDialog">{{ remotePlan ? '编辑参数' : '配置参数' }}</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && remotePlan" type="primary" plain @click="openPublishPlanDialog">安排发布</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && remotePlan?.publishMode === 'SCHEDULED' && !remotePlan.remotePublishTaskId" type="danger" plain @click="cancelLocalSchedule">取消本地计划</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && (remotePlan?.workflowStatus === 'CANCELLED' || remotePlan?.workflowStatus === 'CANCEL_FAILED')" @click="recoverRemotePlan">恢复编排</el-button></div>
      </div>
      <el-empty v-if="!remotePlan" description="尚未配置远端编排参数" :image-size="72" />
      <template v-else>
        <div class="remote-plan-summary">
          <div><span>盘口 / 账号</span><strong>{{ remotePlan.sourceDisplayName }} · {{ remotePlan.remoteAccountName }}</strong></div>
          <div><span>状态</span><strong><el-tag :type="remotePlan.workflowStatus === 'COMPLETED' ? 'success' : remotePlan.errorCode ? 'danger' : 'warning'">{{ remoteStatusLabel(remotePlan.workflowStatus) }}</el-tag></strong></div>
          <div><span>创建进度</span><strong>{{ remotePlan.createdCount }} / {{ remotePlan.issueCount }}</strong></div>
          <div><span>下载进度</span><strong>{{ remotePlan.downloadedCount }} / {{ remotePlan.issueCount }}</strong></div>
          <div><span>发布环境</span><strong>{{ remotePlan.publishEnvironment }}</strong></div>
          <div><span>业务时区</span><strong>{{ remotePlan.businessTimezone }}</strong></div>
          <div><span>发布方式</span><strong>{{ remotePlan.publishMode || '未安排' }}</strong></div>
          <div><span>计划时间</span><strong>{{ remotePlan.scheduledPublishLocalAt || '—' }}</strong></div>
        </div>
        <el-alert v-if="remotePlan.errorMessage" :title="remotePlan.errorCode || '编排失败'" :description="remotePlan.errorMessage" type="error" show-icon :closable="false" />
        <el-alert v-else title="尚未授权执行" description="计划即使到期也只会显示为待授权，不会由后台自动调用远端。" type="info" show-icon :closable="false" />
        <el-table v-if="remoteExecutions.length" :data="remoteExecutions" row-key="id" class="execution-table">
          <el-table-column prop="operation" label="操作" width="100" />
          <el-table-column prop="attemptNumber" label="尝试" width="72" align="right" />
          <el-table-column prop="triggerType" label="触发" width="100" />
          <el-table-column prop="status" label="状态" width="110" />
          <el-table-column prop="requestedAt" label="请求时间" min-width="180" />
          <el-table-column prop="errorMessage" label="错误" min-width="220"><template #default="{ row }">{{ row.errorMessage || '—' }}</template></el-table-column>
        </el-table>
      </template>
    </section>

    <section v-if="selectedBatch" class="surface-card table-card"><div class="redemption-detail-heading"><div><h2>代码登记：{{ selectedBatch.batch.claimDateFrom }} 至 {{ selectedBatch.batch.claimDateTo }}</h2><p>将已经取得的兑换码逐行登记到本地任务；不会自动下载或生成代码。</p></div><div><el-button v-if="hasErpPermission('ERP_REDEMPTION_EXPORT')" :icon="Download" @click="exportBatch">导出</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && readyForLocalPublish" type="success" @click="publishLocal">标记本地发布</el-button><el-button v-if="hasErpPermission('ERP_REDEMPTION_GENERATE') && selectedBatch.batch.status !== 'PUBLISHED_LOCAL'" type="primary" :loading="saving" @click="saveCodes">保存兑换码</el-button></div></div><el-table :data="selectedBatch.issues" row-key="id" max-height="520"><el-table-column prop="claimDate" label="领取日期" width="112" /><el-table-column label="充值窗口" min-width="180"><template #default="{ row }">{{ row.depositWindowStart }} 至 {{ row.depositWindowEnd }}</template></el-table-column><el-table-column label="档位" min-width="150"><template #default="{ row }">{{ row.tierName || '—' }} · ≥ {{ row.minDepositAmount }} / 奖励 {{ row.bonusAmount }}</template></el-table-column><el-table-column label="兑换码" min-width="220"><template #default="{ row }"><el-input v-model="codeDrafts[row.id]" :disabled="selectedBatch?.batch.status === 'PUBLISHED_LOCAL'" placeholder="手工登记取得的兑换码" /></template></el-table-column><el-table-column prop="workflowStatus" label="本地状态" width="155" /></el-table></section>

    <el-dialog v-model="remotePlanDialog" title="远端兑换参数快照" width="860px">
      <el-form label-position="top">
        <div class="remote-options-grid">
          <el-form-item label="兑换码类型"><el-select v-model="remotePlanForm.redemptionType"><el-option value="SEVEN_DAY_DEPOSIT" label="近 7 天充值" /><el-option value="PREVIOUS_DAY_DEPOSIT" label="日充值" /></el-select></el-form-item>
          <el-form-item label="发布环境"><el-select v-model="remotePlanForm.publishEnvironment"><el-option value="test" label="test" /><el-option value="prod" label="prod" /></el-select></el-form-item>
          <el-form-item label="流水倍数"><el-input-number v-model="remotePlanForm.flowTimes" :min="0" :max="1000" /></el-form-item>
          <el-form-item label="串行间隔（秒）"><el-input-number v-model="remotePlanForm.creationIntervalSeconds" :min="1" :max="60" /></el-form-item>
          <el-form-item label="活动累计充值"><el-input v-model="remotePlanForm.activityRecharge" placeholder="可选" /></el-form-item>
          <el-form-item label="活动充值次数"><el-input-number v-model="remotePlanForm.activityRechargeCount" :min="0" :max="100000" /></el-form-item>
          <el-form-item label="远端活动 ID"><el-input-number v-model="remotePlanForm.activityId" :min="1" /></el-form-item>
          <el-form-item label="单用户领取次数"><el-input-number v-model="remotePlanForm.singleUserLimit" :min="1" :max="100" /></el-form-item>
          <el-form-item label="单码领取上限"><el-input-number v-model="remotePlanForm.singleKeyLimit" :min="1" :max="100000" /></el-form-item>
        </div>
        <h3>充值档位标签</h3>
        <div class="tier-label-grid"><el-form-item v-for="tier in selectedCampaign?.tiers || []" :key="tier.id" :label="`${tier.displayName || '档位'} · ≥ ${tier.minDepositAmount}`"><el-input v-model="tierLabelDrafts[tier.id]" :placeholder="remotePlanForm.redemptionType === 'PREVIOUS_DAY_DEPOSIT' ? '可留空表示全部用户' : '标签 ID，使用逗号分隔'" /></el-form-item></div>
        <h3>领取限制</h3>
        <div class="remote-switch-grid">
          <el-checkbox v-model="remotePlanForm.requireBindBankCard">要求绑定银行卡</el-checkbox>
          <el-checkbox v-model="remotePlanForm.requireBindPhone">要求绑定手机号</el-checkbox>
          <span><el-checkbox v-model="remotePlanForm.checkUuid">检查设备 UUID</el-checkbox><el-input-number v-model="remotePlanForm.uuidRewardLimit" :min="1" :max="100" /></span>
          <span><el-checkbox v-model="remotePlanForm.checkLoginIp">检查登录 IP</el-checkbox><el-input-number v-model="remotePlanForm.loginIpRewardLimit" :min="1" :max="100" /></span>
          <span><el-checkbox v-model="remotePlanForm.checkRegisterIp">检查注册 IP</el-checkbox><el-input-number v-model="remotePlanForm.registerIpRewardLimit" :min="1" :max="100" /></span>
        </div>
        <el-alert title="仅保存本地快照" description="保存不会检测连接、同步标签、登录远端或创建兑换码。" type="warning" :closable="false" />
      </el-form>
      <template #footer><el-button @click="remotePlanDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRemotePlan">保存参数</el-button></template>
    </el-dialog>
    <el-dialog v-model="publishPlanDialog" title="安排远端发布计划" width="560px">
      <el-form label-position="top">
        <el-form-item label="发布方式"><el-radio-group v-model="publishPlanForm.mode"><el-radio-button value="IMMEDIATE">立即发布意图</el-radio-button><el-radio-button value="SCHEDULED">定时发布意图</el-radio-button></el-radio-group></el-form-item>
        <el-form-item v-if="publishPlanForm.mode === 'SCHEDULED'" :label="`发布时间（${remotePlan?.businessTimezone || '盘口业务时区'}）`"><el-date-picker v-model="publishPlanForm.scheduledLocalAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item><el-checkbox v-model="publishPlanForm.fallbackToScheduled">立即发布失败时允许回退到定时方案</el-checkbox></el-form-item>
        <el-form-item label="备注"><el-input v-model="publishPlanForm.note" type="textarea" :rows="3" /></el-form-item>
        <el-alert title="计划不会自动执行" description="计划到期只进入待授权队列；本阶段没有后台远端执行器。" type="warning" :closable="false" />
      </el-form>
      <template #footer><el-button @click="publishPlanDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="savePublishPlan">保存计划</el-button></template>
    </el-dialog>
    <el-dialog v-model="campaignDialog" title="新建本地兑换活动" width="760px"><el-form label-position="top"><div class="campaign-grid"><el-form-item label="活动编码"><el-input v-model="campaignForm.code" placeholder="例如 AUG-2026" /></el-form-item><el-form-item label="活动名称"><el-input v-model="campaignForm.name" /></el-form-item><el-form-item label="回看天数"><el-input-number v-model="campaignForm.lookbackDays" :min="1" :max="60" /></el-form-item></div><el-form-item label="说明"><el-input v-model="campaignForm.description" type="textarea" :rows="2" /></el-form-item><div class="tier-heading"><h3>充值档位</h3><el-button text type="primary" @click="addTier">添加档位</el-button></div><div v-for="(tier, index) in campaignForm.tiers" :key="index" class="tier-grid"><el-input v-model="tier.displayName" placeholder="档位名称" /><el-input v-model="tier.minDepositAmount" placeholder="充值门槛" /><el-input v-model="tier.bonusAmount" placeholder="赠金" /><el-input v-model="tier.bonusMaxAmount" placeholder="最大奖金" /><el-button v-if="campaignForm.tiers.length > 1" text type="danger" @click="campaignForm.tiers.splice(index, 1)">移除</el-button></div></el-form><template #footer><el-button @click="campaignDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCampaign">创建活动</el-button></template></el-dialog>
    <el-dialog v-model="batchDialog" title="新建本地代码任务批次" width="500px"><el-form label-position="top"><el-form-item label="领取日期范围"><el-date-picker v-model="batchDateRange" type="daterange" value-format="YYYY-MM-DD" /></el-form-item><p class="muted">请选择范围后创建。每个领取日期会按活动的所有充值档位生成本地任务。</p></el-form><template #footer><el-button @click="batchDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveBatch">创建批次</el-button></template></el-dialog>
    <el-dialog v-model="taskDialog" title="新建多盘口兑换任务组" width="600px"><el-form label-position="top"><el-form-item label="任务名称"><el-input v-model="taskForm.taskName" placeholder="不填则按活动和日期自动命名" /></el-form-item><el-form-item label="领取日期范围"><el-date-picker v-model="taskDateRange" type="daterange" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="远端账号（仅用于本地子任务归属）"><el-checkbox-group v-model="taskForm.remoteAccountIds"><el-checkbox v-for="account in remoteAccounts.filter((item) => item.enabled)" :key="account.id" :value="account.id">{{ account.sourceDisplayName }} · {{ account.displayName }}</el-checkbox></el-checkbox-group></el-form-item><el-alert title="不会执行远端操作" description="创建后只生成本地子任务与代码登记行。实际远端创建、下载、发布仍需分别授权。" type="warning" :closable="false" /></el-form><template #footer><el-button @click="taskDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveTask">创建任务组</el-button></template></el-dialog>
    <el-dialog v-model="taskPlanDialog" :title="`批量配置：${taskPlanTarget?.taskName || ''}`" width="760px">
      <el-form label-position="top">
        <div class="remote-options-grid">
          <el-form-item label="兑换码类型"><el-select v-model="remotePlanForm.redemptionType"><el-option value="SEVEN_DAY_DEPOSIT" label="近 7 天充值" /><el-option value="PREVIOUS_DAY_DEPOSIT" label="日充值（全部用户）" /></el-select></el-form-item>
          <el-form-item label="发布环境"><el-select v-model="remotePlanForm.publishEnvironment"><el-option value="test" label="test" /><el-option value="prod" label="prod" /></el-select></el-form-item>
          <el-form-item label="流水倍数"><el-input-number v-model="remotePlanForm.flowTimes" :min="0" :max="1000" /></el-form-item>
          <el-form-item label="串行间隔（秒）"><el-input-number v-model="remotePlanForm.creationIntervalSeconds" :min="1" :max="60" /></el-form-item>
          <el-form-item label="活动累计充值"><el-input v-model="remotePlanForm.activityRecharge" placeholder="可选" /></el-form-item>
          <el-form-item label="活动充值次数"><el-input-number v-model="remotePlanForm.activityRechargeCount" :min="0" :max="100000" /></el-form-item>
          <el-form-item label="远端活动 ID"><el-input-number v-model="remotePlanForm.activityId" :min="1" /></el-form-item>
          <el-form-item label="单用户领取次数"><el-input-number v-model="remotePlanForm.singleUserLimit" :min="1" :max="100" /></el-form-item>
          <el-form-item label="单码领取上限"><el-input-number v-model="remotePlanForm.singleKeyLimit" :min="1" :max="100000" /></el-form-item>
        </div>
        <div class="remote-switch-grid">
          <el-checkbox v-model="remotePlanForm.requireBindBankCard">要求绑定银行卡</el-checkbox>
          <el-checkbox v-model="remotePlanForm.requireBindPhone">要求绑定手机号</el-checkbox>
          <span><el-checkbox v-model="remotePlanForm.checkUuid">检查设备 UUID</el-checkbox><el-input-number v-model="remotePlanForm.uuidRewardLimit" :min="1" :max="100" /></span>
          <span><el-checkbox v-model="remotePlanForm.checkLoginIp">检查登录 IP</el-checkbox><el-input-number v-model="remotePlanForm.loginIpRewardLimit" :min="1" :max="100" /></span>
          <span><el-checkbox v-model="remotePlanForm.checkRegisterIp">检查注册 IP</el-checkbox><el-input-number v-model="remotePlanForm.registerIpRewardLimit" :min="1" :max="100" /></span>
        </div>
        <el-alert title="按统一账号预设配置" description="近 7 天充值读取各账号已保存的标签与档位预设；日充值按全部用户生成。本操作不连接远端。" type="warning" :closable="false" />
      </el-form>
      <template #footer><el-button @click="taskPlanDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveTaskPlans">为全部子任务配置</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.redemption-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; padding: 16px; }.redemption-filter .el-select { width: min(420px, 100%); }.redemption-filter span, .muted { color: var(--ink-muted); font-size: 13px; }
.redemption-detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }.redemption-detail-heading h2, .tier-heading h3 { margin: 0; }.redemption-detail-heading p { margin: 4px 0 0; color: var(--ink-muted); font-size: 13px; }.campaign-grid { display: grid; grid-template-columns: 1fr 1.4fr 0.8fr; gap: 0 14px; }.tier-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }.tier-grid { display: grid; grid-template-columns: 1.1fr repeat(3, 1fr) auto; gap: 8px; margin-bottom: 10px; }
.remote-plan-card { padding: 20px; }.remote-plan-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }.remote-plan-summary div { display: flex; flex-direction: column; gap: 5px; padding: 12px; border-radius: 10px; background: #f7f9fb; }.remote-plan-summary span { color: var(--ink-muted); font-size: 12px; }.remote-plan-summary strong { color: var(--ink-strong); font-size: 14px; }.execution-table { margin-top: 16px; }.remote-options-grid, .tier-label-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 14px; }.remote-switch-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }.remote-switch-grid span { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.task-actions { display: flex; flex-wrap: nowrap; white-space: nowrap; }
@media (max-width: 760px) { .redemption-detail-heading { align-items: flex-start; flex-direction: column; }.campaign-grid, .tier-grid, .remote-options-grid, .tier-label-grid, .remote-switch-grid, .remote-plan-summary { grid-template-columns: 1fr; } }
</style>
