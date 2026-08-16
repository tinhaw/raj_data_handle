<script setup lang="ts">
import { Download, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  createErpRedemptionBatch,
  createErpRedemptionCampaign,
  downloadErpRedemptionBatch,
  fetchErpRedemptionBatch,
  fetchErpRedemptionBatches,
  fetchErpRedemptionCampaigns,
  importErpRedemptionCodes,
  publishErpRedemptionBatchLocal,
} from '../api/erpRedemption'
import { isAdmin } from '../stores/auth'
import type {
  ErpRedemptionBatch,
  ErpRedemptionBatchDetail,
  ErpRedemptionCampaign,
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
const selectedBatch = ref<ErpRedemptionBatchDetail | null>(null)
const campaignDialog = ref(false)
const batchDialog = ref(false)
const codeDrafts = reactive<Record<string, string>>({})

const campaignForm = reactive({
  code: '', name: '', lookbackDays: 7, description: '',
  tiers: [{ displayName: '基础档位', minDepositAmount: '0', bonusAmount: '0', bonusMaxAmount: '0' }],
})
const batchDateRange = ref<[string, string]>([today(), today()])

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
    return
  }
  batches.value = await fetchErpRedemptionBatches(selectedCampaignId.value)
  if (selectedBatch.value && !batches.value.some((batch) => batch.id === selectedBatch.value?.batch.id)) {
    selectedBatch.value = null
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    await loadCampaigns()
    await loadBatches()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码管理加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
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
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '兑换码任务加载失败。'))
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

watch(selectedCampaignId, () => void loadBatches())
onMounted(() => void load())
</script>

<template>
  <div class="page-stack redemption-page">
    <header class="page-header">
      <div><span class="page-eyebrow">ERP local redemption</span><h1>兑换码管理</h1><p>维护本地活动、兑换码任务和已取得代码的登记记录；远端创建、发布、下载始终未启用。</p></div>
      <div class="header-actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button><el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openCampaignDialog">新建活动</el-button></div>
    </header>

    <el-alert title="远端兑换操作保持禁用" description="此页面不保存远端密码、会话或 TOTP，不调用 ERP/盘口远端接口。此处的“本地发布”只是本地工作流状态。" type="warning" show-icon :closable="false" />

    <section class="surface-card redemption-filter"><el-select v-model="selectedCampaignId" filterable placeholder="选择兑换活动"><el-option v-for="campaign in campaigns" :key="campaign.id" :value="campaign.id" :label="`${campaign.code} · ${campaign.name}`" /></el-select><span v-if="selectedCampaign">档位 {{ selectedCampaign.tiers.length }} 个 · 已登记 {{ selectedCampaign.importedCodeCount }} / {{ selectedCampaign.plannedCodeCount }} 个代码</span><el-button v-if="isAdmin && selectedCampaign" type="primary" plain @click="batchDialog = true">新建任务批次</el-button></section>

    <section class="surface-card table-card"><div class="section-heading"><div><h2>本地任务批次</h2><p>每个领取日期 × 充值档位生成一条本地代码登记任务。</p></div></div><el-table v-loading="loading" :data="batches" row-key="id" empty-text="当前活动暂无任务批次"><el-table-column label="领取日期" min-width="180"><template #default="{ row }">{{ row.claimDateFrom }} 至 {{ row.claimDateTo }}</template></el-table-column><el-table-column prop="expectedCodeCount" label="任务数" width="90" align="right" /><el-table-column label="已登记" width="100" align="right"><template #default="{ row }">{{ row.importedCodeCount }}</template></el-table-column><el-table-column label="状态" width="130"><template #default="{ row }"><el-tag :type="row.status === 'PUBLISHED_LOCAL' ? 'success' : row.status === 'READY_LOCAL' ? 'warning' : 'info'">{{ row.status }}</el-tag></template></el-table-column><el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button text type="primary" @click="selectBatch(row.id)">查看</el-button></template></el-table-column></el-table></section>

    <section v-if="selectedBatch" class="surface-card table-card"><div class="redemption-detail-heading"><div><h2>代码登记：{{ selectedBatch.batch.claimDateFrom }} 至 {{ selectedBatch.batch.claimDateTo }}</h2><p>将已经取得的兑换码逐行登记到本地任务；不会自动下载或生成代码。</p></div><div><el-button :icon="Download" @click="exportBatch">导出</el-button><el-button v-if="isAdmin && readyForLocalPublish" type="success" @click="publishLocal">标记本地发布</el-button><el-button v-if="isAdmin && selectedBatch.batch.status !== 'PUBLISHED_LOCAL'" type="primary" :loading="saving" @click="saveCodes">保存兑换码</el-button></div></div><el-table :data="selectedBatch.issues" row-key="id" max-height="520"><el-table-column prop="claimDate" label="领取日期" width="112" /><el-table-column label="充值窗口" min-width="180"><template #default="{ row }">{{ row.depositWindowStart }} 至 {{ row.depositWindowEnd }}</template></el-table-column><el-table-column label="档位" min-width="150"><template #default="{ row }">{{ row.tierName || '—' }} · ≥ {{ row.minDepositAmount }} / 奖励 {{ row.bonusAmount }}</template></el-table-column><el-table-column label="兑换码" min-width="220"><template #default="{ row }"><el-input v-model="codeDrafts[row.id]" :disabled="selectedBatch?.batch.status === 'PUBLISHED_LOCAL'" placeholder="手工登记取得的兑换码" /></template></el-table-column><el-table-column prop="workflowStatus" label="本地状态" width="155" /></el-table></section>

    <el-dialog v-model="campaignDialog" title="新建本地兑换活动" width="760px"><el-form label-position="top"><div class="campaign-grid"><el-form-item label="活动编码"><el-input v-model="campaignForm.code" placeholder="例如 AUG-2026" /></el-form-item><el-form-item label="活动名称"><el-input v-model="campaignForm.name" /></el-form-item><el-form-item label="回看天数"><el-input-number v-model="campaignForm.lookbackDays" :min="1" :max="60" /></el-form-item></div><el-form-item label="说明"><el-input v-model="campaignForm.description" type="textarea" :rows="2" /></el-form-item><div class="tier-heading"><h3>充值档位</h3><el-button text type="primary" @click="addTier">添加档位</el-button></div><div v-for="(tier, index) in campaignForm.tiers" :key="index" class="tier-grid"><el-input v-model="tier.displayName" placeholder="档位名称" /><el-input v-model="tier.minDepositAmount" placeholder="充值门槛" /><el-input v-model="tier.bonusAmount" placeholder="赠金" /><el-input v-model="tier.bonusMaxAmount" placeholder="最大奖金" /><el-button v-if="campaignForm.tiers.length > 1" text type="danger" @click="campaignForm.tiers.splice(index, 1)">移除</el-button></div></el-form><template #footer><el-button @click="campaignDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCampaign">创建活动</el-button></template></el-dialog>
    <el-dialog v-model="batchDialog" title="新建本地代码任务批次" width="500px"><el-form label-position="top"><el-form-item label="领取日期范围"><el-date-picker v-model="batchDateRange" type="daterange" value-format="YYYY-MM-DD" /></el-form-item><p class="muted">请选择范围后创建。每个领取日期会按活动的所有充值档位生成本地任务。</p></el-form><template #footer><el-button @click="batchDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveBatch">创建批次</el-button></template></el-dialog>
  </div>
</template>

<style scoped>
.redemption-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; padding: 16px; }.redemption-filter .el-select { width: min(420px, 100%); }.redemption-filter span, .muted { color: var(--ink-muted); font-size: 13px; }
.redemption-detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }.redemption-detail-heading h2, .tier-heading h3 { margin: 0; }.redemption-detail-heading p { margin: 4px 0 0; color: var(--ink-muted); font-size: 13px; }.campaign-grid { display: grid; grid-template-columns: 1fr 1.4fr 0.8fr; gap: 0 14px; }.tier-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }.tier-grid { display: grid; grid-template-columns: 1.1fr repeat(3, 1fr) auto; gap: 8px; margin-bottom: 10px; }
@media (max-width: 760px) { .redemption-detail-heading { align-items: flex-start; flex-direction: column; }.campaign-grid, .tier-grid { grid-template-columns: 1fr; } }
</style>
