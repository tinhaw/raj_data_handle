<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import type { RedemptionTaskDeletionView } from '@/api/types'

const props = defineProps<{ taskId: string | number; taskNumber: string; issueIds?: Array<string | number>; startNew?: boolean; embedded?: boolean; readOnlyOpen?: boolean }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const plan = ref<RedemptionTaskDeletionView>()
const working = ref(false)
const error = ref('')
const enteredTaskNumber = ref('')
const acknowledged = ref(false)
let closed = false
onUnmounted(() => { closed = true })
const readyCount = computed(() => plan.value?.items.filter(item => item.status === 'CHECKED').length || 0)
const presentCount = computed(() => plan.value?.items.filter(item => item.status !== 'DELETED' && item.plan?.observation?.state === 'PRESENT').length || 0)
const unexecutedCount = computed(() => plan.value?.items.filter(item => ['WAITING', 'CHECKED', 'BLOCKED', 'SKIPPED'].includes(item.status)).length || 0)
const excludedCount = computed(() => totalCount.value - readyCount.value)
const keptCount = computed(() => plan.value?.items.filter(item => item.status === 'KEPT').length || 0)
const deletedCount = computed(() => plan.value?.items.filter(item => item.status === 'DELETED').length || 0)
const blockedCount = computed(() => plan.value?.items.filter(item => item.status === 'BLOCKED').length || 0)
const unknownCount = computed(() => plan.value?.items.filter(item => item.status === 'UNKNOWN').length || 0)
const checkedCount = computed(() => plan.value?.items.filter(item => item.status !== 'WAITING').length || 0)
const totalCount = computed(() => plan.value?.items.length || 0)
const skippedCount = computed(() => plan.value?.items.filter(item => item.status === 'SKIPPED').length || 0)
const executionStage = computed(() => Boolean(plan.value && (['RUNNING', 'PAUSED', 'FINISHED'].includes(plan.value.status) || unknownCount.value)))
const stageTitle = computed(() => {
  if (!plan.value) return props.readOnlyOpen && !props.startNew ? '暂无删除进度' : '正在准备删除前预检'
  if (plan.value.status === 'CHECKING') return `删除前预检中（${checkedCount.value}/${totalCount.value}），尚未开始删除`
  if (plan.value.status === 'CHECKED') {
    if (readyCount.value) return '预检结束，等待你确认删除'
    return deletedCount.value ? '预检结束，本轮没有可继续删除的配置' : '预检未通过，尚未开始删除'
  }
  if (plan.value.status === 'RUNNING') return working.value || plan.value.busy ? '正在执行已确认的删除' : '删除已确认，等待继续处理'
  if (plan.value.status === 'PAUSED') return '删除已暂停，请先核对结果'
  if (plan.value.status === 'FINISHED') return deletedCount.value === totalCount.value ? '全部配置已确认删除或不存在' : '本轮可执行项已处理，其他项未删除'
  return '本轮预检已结束，请重新预检'
})
const progressPercent = computed(() => Math.round((plan.value?.status === 'CHECKING' ? checkedCount.value : deletedCount.value) / (totalCount.value || 1) * 100))
const permissionBlocked = computed(() => plan.value?.items.some(item => item.status === 'BLOCKED' && item.message?.includes('兑换码永久删除')) || false)
const otherTasks = computed(() => [...new Set(plan.value?.items.flatMap(item => item.sharedTasks) || [])].filter(id => id !== props.taskNumber))
const canConfirm = computed(() => plan.value?.status === 'CHECKED' && readyCount.value > 0 && acknowledged.value && enteredTaskNumber.value.trim() === props.taskNumber && !working.value)
function statusLabel(status: string) {
  return ({ WAITING: '等待核验', CHECKED: '未执行 · 预检通过', SKIPPED: '未创建配置', BLOCKED: '检查未通过，未删除', UNKNOWN: '请求已提交或可能已提交 · 暂不重发', KEPT: '已核验并明确保留', DELETED: '已删除 / 已不存在' } as Record<string, string>)[status] || status
}
function existenceLabel(item: RedemptionTaskDeletionView['items'][number]) {
  if (item.status === 'DELETED') return '已确认不存在'
  return ({ PRESENT: '仍存在（上次核对）', ABSENT: '已确认不存在', IDENTITY_CHANGED: '身份或参数变化', UNAVAILABLE: '本次无法确认' } as Record<string, string>)[item.plan?.observation?.state || ''] || '尚未核对'
}
function checkedTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}
async function prepareRemaining() {
  if (!plan.value || working.value) return
  await run(async () => {
    enteredTaskNumber.value = ''; acknowledged.value = false
    // Reconcile is read-only, including a lost response. No DELETE is sent by this action.
    plan.value = await api.redemption.reconcileTaskDeletion(plan.value!)
    if (closed) return
    plan.value = await api.redemption.previewTaskDeletion(props.taskId, undefined, plan.value!.id)
    if (plan.value.status === 'CHECKING') await advance()
  })
}
async function advance() {
  while (!closed && plan.value && ['CHECKING', 'RUNNING'].includes(plan.value.status)) {
    plan.value = await api.redemption.nextTaskDeletion(plan.value)
    if (plan.value.busy) break
  }
}
async function run(action: () => Promise<void>) {
  if (working.value) return
  working.value = true
  error.value = ''
  try { await action() }
  catch (failure) { error.value = failure instanceof Error ? failure.message : '请求未完成，请刷新进度或核对结果；不要重复提交删除' }
  finally { working.value = false; emit('changed') }
}
async function confirm() {
  if (!canConfirm.value || !plan.value) return
  await run(async () => {
    plan.value = await api.redemption.confirmTaskDeletion(plan.value!, enteredTaskNumber.value.trim())
    await advance()
  })
}
async function refresh() {
  if (!plan.value) return
  await run(async () => { plan.value = await api.redemption.taskDeletion(props.taskId, plan.value!.id) })
}
async function reconcile() {
  if (!plan.value) return
  await run(async () => { plan.value = await api.redemption.reconcileTaskDeletion(plan.value!) })
}
async function keepConfiguration(issueId: string | number, sharedTasks: string[]) {
  await run(async () => {
    const checked = await api.redemption.previewDeletionKeep(issueId)
    if (checked.status !== 'KEPT') {
      try {
        await ElMessageBox.prompt(`已核验原配置 ${checked.configurationId} 仍存在，且与旧删除确认指纹一致。请确认旧删除请求已结束，并决定保留配置及库存，恢复相关业务。共享任务：${sharedTasks.join('、')}。原未知删除记录保留，旧删除不会重放。请输入配置 ID 确认。`, '确认保留原配置', {
          inputValidator: value => value.trim() === checked.configurationId || '请输入本次配置 ID', confirmButtonText: '确认保留并恢复业务', cancelButtonText: '取消', type: 'warning',
        })
      } catch { return }
      await api.redemption.confirmDeletionKeep(issueId, checked)
    }
    if (plan.value) plan.value = await api.redemption.reconcileTaskDeletion(plan.value)
  })
}
async function resume() { await run(advance) }
onMounted(async () => {
  await run(async () => {
    if (props.startNew) {
      plan.value = await api.redemption.previewTaskDeletion(props.taskId, props.issueIds)
      if (plan.value.status === 'CHECKING') await advance()
      return
    }
    const latest = await api.redemption.latestTaskDeletion(props.taskId)
    if (latest) { plan.value = latest; if (latest.status === 'CHECKING' && !latest.busy) await advance() }
    else if (!props.readOnlyOpen) { plan.value = await api.redemption.previewTaskDeletion(props.taskId); await advance() }

  })
})
</script>

<template>
  <component :is="embedded ? 'section' : 'el-dialog'" :class="{ 'embedded-deletion': embedded }" :model-value="true" :title="`批量删除 · 任务 ${taskNumber}`" width="min(1120px, calc(100vw - 32px))" :close-on-click-modal="false" @close="emit('close')">
    <h3 v-if="embedded">删除进度与结果</h3>
    <el-empty v-if="!plan && !working && !error && readOnlyOpen" description="该任务还没有批量删除记录；可在配置列表勾选后删除，或选择删除整任务配置。" :image-size="64" />
    <p class="scope-note">范围：{{ plan?.selectedOnly || issueIds ? '仅本次选择的配置' : '该任务全部盘口、全部日期和档位的配置' }}，共享配置只处理一次。本地历史记录保留。</p>
    <el-alert type="warning" :closable="false" show-icon title="永久删除远端配置后，本系统将阻止相关任务继续发布、下载及自动重建。已发布兑换码是否立即失效尚未验证。" />
    <el-alert v-if="otherTasks.length" class="section-gap" type="error" :closable="false" show-icon :title="`同时影响其他共享任务：${otherTasks.join('、')}`" />
    <el-alert v-if="error" class="section-gap" type="error" :closable="false" :title="error" />
    <div class="summary section-gap" aria-live="polite">
      <strong>{{ stageTitle }}</strong>
      <span v-if="plan">共 {{ totalCount }} 项配置</span>
    </div>
    <el-progress v-if="plan?.status === 'CHECKING' || executionStage" class="section-gap" :percentage="progressPercent" :status="unknownCount || blockedCount ? 'warning' : undefined" :stroke-width="8" />
    <p v-if="plan?.status === 'CHECKING'" class="scope-note section-gap">这里的进度是配置检查进度。检查结束后，还需要勾选确认并输入任务编号，才会提交删除。</p>
    <div v-if="plan" class="result-counts section-gap" aria-live="polite">
      <span>已删除 / 已确认不存在 <strong>{{ deletedCount }}</strong></span>
      <span v-if="keptCount">已明确保留 <strong>{{ keptCount }}</strong></span>
      <span>仍存在（上次核对） <strong>{{ presentCount }}</strong></span>
      <span>未执行 <strong>{{ unexecutedCount }}</strong></span>
      <span>预检受阻 <strong>{{ blockedCount }}</strong></span>
      <span>结果待核对 <strong>{{ unknownCount }}</strong></span>
      <span>{{ executionStage ? '尚待执行' : '可确认删除' }} <strong>{{ readyCount }}</strong></span>
      <span v-if="skippedCount">未创建配置 {{ skippedCount }}</span>
    </div>
    <el-alert v-if="plan?.status === 'CHECKED' && !readyCount && blockedCount" class="section-gap" type="error" :closable="false" show-icon
      title="没有配置通过删除前检查，本轮未提交删除。请按下表具体原因处理后重新预检。" />
    <div v-if="permissionBlocked" class="scope-note section-gap">
      请由具备账号管理权限的管理员，在对应盘口和账号上开启“兑换码永久删除”能力。开启后返回此处重新预检，每次删除仍需确认。
      <el-link type="primary" href="/erp/remote-connections" target="_blank" rel="noopener">打开盘口与远端账号</el-link>
    </div>
    <p v-if="plan" class="scope-note section-gap">“存在性”来自原配置 ID 的只读核对，“未执行”表示尚未提交删除，两者可能重叠。核对时间按当前浏览器时区显示；超时或无权限不会算作已删除。</p>
    <el-alert v-if="unknownCount" class="section-gap" type="warning" :closable="false" show-icon
      :title="`${unknownCount} 项旧请求结果尚未确定，本轮继续时将排除。可先核对并预检其余项，确认后继续；不会重复提交这些旧请求。`" />
    <el-table :data="plan?.items || []" max-height="400" row-key="issueId" class="section-gap" empty-text="正在准备删除范围…">
      <el-table-column label="盘口 / 兑换日" min-width="160"><template #default="{ row }">{{ row.plan?.parameters.marketName || '—' }}<br>{{ row.plan?.parameters.claimDate || '—' }}</template></el-table-column>
      <el-table-column prop="configurationId" label="配置 ID" width="100" />
      <el-table-column label="兑换码 / 奖励" min-width="155"><template #default="{ row }">{{ row.plan?.remote.giftCode || row.plan?.parameters.code || row.plan?.remote.description || '—' }}<br><span v-if="row.plan">任务奖励 {{ row.plan.parameters.bonusMin }}–{{ row.plan.parameters.bonusMax }}</span></template></el-table-column>
      <el-table-column label="共享任务" min-width="150"><template #default="{ row }">{{ row.sharedTasks.join('、') || '—' }}</template></el-table-column>
      <el-table-column label="远端存在性 / 核对时间" min-width="185"><template #default="{ row }"><strong>{{ existenceLabel(row) }}</strong><div>{{ checkedTime(row.plan?.observation?.checkedAt) }}</div><div v-if="row.plan?.observation">{{ row.plan.observation.message }}</div></template></el-table-column>
      <el-table-column label="执行状态 / 说明" min-width="240"><template #default="{ row }"><strong>{{ statusLabel(row.status) }}</strong><div>{{ row.message }}</div><el-button v-if="row.status === 'UNKNOWN'" link type="primary" :disabled="working" @click="keepConfiguration(row.issueId, row.sharedTasks)">核验并明确保留</el-button></template></el-table-column>
    </el-table>
    <div v-if="plan?.status === 'CHECKED' && readyCount" class="confirmation section-gap">
      <p class="scope-note">本次仅处理通过预检的 {{ readyCount }} 项；排除 {{ excludedCount }} 项（已删除、明确保留、结果不明或预检受阻）。上表清单及共享影响均属于本次确认范围。</p>
      <el-checkbox v-model="acknowledged">已核对剩余 {{ readyCount }} 项及共享任务影响，同意排除其他 {{ excludedCount }} 项并继续删除</el-checkbox>
      <el-input v-model="enteredTaskNumber" :placeholder="`请输入任务编号 ${taskNumber}`" aria-label="输入任务编号确认批量删除" :disabled="working" />
    </div>
    <p v-if="executionStage" class="scope-note section-gap">关闭窗口会停止提交后续删除；当前已提交的请求仍会完成核验。再次打开可查看进度。结果不明时只读核对，不重复删除。</p>
    <p v-else class="scope-note section-gap">当前处于删除前预检阶段。关闭只结束预检；只有勾选确认、输入正确任务编号并点击“确认永久删除”后，才会提交删除。</p>
    <div class="deletion-actions">
      <el-button @click="emit('close')">{{ working ? (executionStage ? '关闭并停止后续删除' : '关闭并停止后续预检') : '关闭' }}</el-button>
      <el-button v-if="plan" :disabled="working" @click="refresh">刷新进度</el-button>
      <el-button v-if="plan && (plan.busy || ['PAUSED', 'RUNNING'].includes(plan.status))" :disabled="working" @click="reconcile">只读核对结果</el-button>

      <el-button v-if="plan && ['CHECKED', 'PAUSED', 'RUNNING', 'FINISHED', 'STOPPED'].includes(plan.status)" :disabled="working" @click="prepareRemaining">核对并预检剩余项</el-button>
      <el-button v-if="plan?.status === 'CHECKING' && !plan.busy" :disabled="working" @click="resume">继续预检</el-button>
      <el-button v-if="plan?.status === 'CHECKED' && readyCount" type="danger" :disabled="!canConfirm" :loading="working" @click="confirm">确认永久删除 {{ readyCount }} 个配置</el-button>
    </div>
  </component>
</template>

<style scoped>
.embedded-deletion { padding: 20px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color); }
.embedded-deletion h3 { margin: 0 0 16px; font-size: 16px; }
.deletion-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
.deletion-actions :deep(.el-button + .el-button) { margin-left: 0; }
.embedded-deletion .deletion-actions { position: sticky; bottom: 0; z-index: 2; padding: 12px 0; border-top: 1px solid var(--el-border-color); background: var(--el-bg-color); }
.scope-note { color: var(--el-text-color-secondary); line-height: 1.6; margin: 0 0 12px; }
.section-gap { margin-top: 16px; }
.summary { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.result-counts { display: flex; flex-wrap: wrap; gap: 8px 24px; color: var(--el-text-color-secondary); font-variant-numeric: tabular-nums; }
.result-counts strong { color: var(--el-text-color-primary); }
:deep(.el-table__body .cell) { color: var(--el-text-color-regular); }
.confirmation { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.confirmation .el-input { max-width: 320px; }
.confirmation .el-checkbox { height: auto; max-width: 100%; align-items: flex-start; white-space: normal; }
.confirmation :deep(.el-checkbox__label) { min-width: 0; white-space: normal; }
</style>
