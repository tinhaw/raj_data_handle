<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  confirmErpDailyBalance,
  createErpDailyBalance,
  fetchErpDailyBalances,
  updateErpDailyBalance,
  type ErpDailyBalanceWrite,
} from '../api/erpBalances'
import { fetchErpOperatorLines, fetchErpOperators } from '../api/erpOperators'
import { isAdmin } from '../stores/auth'
import type { ErpDailyBalance, ErpDeliveryLine } from '../types'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function currentMonth(): string {
  return today().slice(0, 7)
}

function clean(value: string): string | undefined {
  const trimmed = value.trim()
  return trimmed || undefined
}

function amount(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString()
}

const loading = ref(false)
const saving = ref(false)
const lines = ref<ErpDeliveryLine[]>([])
const records = ref<ErpDailyBalance[]>([])
const selectedLineId = ref('')
const month = ref(currentMonth())
const dialogVisible = ref(false)
const editing = ref<ErpDailyBalance | null>(null)

const form = reactive({
  operatorLineId: '',
  businessDate: today(),
  openingMode: 'MANUAL' as 'AUTO' | 'MANUAL',
  openingBalance: '',
  transferAmount: '',
  fraudLossAmount: '',
  fraudDeductionSource: '' as '' | 'TRANSFER' | 'BALANCE',
  spendAmount: '',
  exchangeLossRate: '',
  exchangeLossBasis: 'TRANSFER',
  exchangeLossMode: 'AUTO' as 'AUTO' | 'MANUAL',
  exchangeLossAmount: '',
  serviceFeeRate: '',
  serviceFeeBasis: 'TRANSFER',
  serviceFeeMode: 'AUTO' as 'AUTO' | 'MANUAL',
  serviceFeeAmount: '',
  refluxAmount: '',
  refundAmount: '',
  otherDeductionAmount: '',
  otherReason: '',
  remark: '',
})

const selectedLine = computed(() => lines.value.find((line) => line.id === selectedLineId.value))
const formLine = computed(() => lines.value.find((line) => line.id === form.operatorLineId))
const selectedLineLabel = computed(() => selectedLine.value
  ? `${selectedLine.value.operatorName} · ${selectedLine.value.name} · ${selectedLine.value.asset}`
  : '请选择投放线')

async function loadLines(): Promise<void> {
  const operators = await fetchErpOperators(false)
  lines.value = (
    await Promise.all(operators.map((operator) => fetchErpOperatorLines(operator.id)))
  ).flat()
  if (!selectedLineId.value && lines.value[0]) {
    selectedLineId.value = lines.value[0].id
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    if (!lines.value.length) await loadLines()
    if (!selectedLineId.value) {
      records.value = []
      return
    }
    const result = await fetchErpDailyBalances(selectedLineId.value, month.value)
    records.value = result.records
  } catch (error) {
    records.value = []
    ElMessage.error(apiErrorMessage(error, '台账数据加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
  }
}

function resetForm(record?: ErpDailyBalance): void {
  editing.value = record || null
  form.operatorLineId = record?.operatorLineId || selectedLineId.value
  form.businessDate = record?.businessDate || today()
  form.openingMode = record?.openingMode || 'MANUAL'
  form.openingBalance = record?.openingBalance || ''
  form.transferAmount = record?.transferAmount || ''
  form.fraudLossAmount = record?.fraudLossAmount || ''
  form.fraudDeductionSource = record?.fraudDeductionSource || ''
  form.spendAmount = record?.spendAmount || ''
  form.exchangeLossRate = record?.exchangeLossRate || formLine.value?.defaultExchangeLossRate || ''
  form.exchangeLossBasis = record?.exchangeLossBasis || formLine.value?.defaultExchangeLossBasis || 'TRANSFER'
  form.exchangeLossMode = record?.exchangeLossMode || 'AUTO'
  form.exchangeLossAmount = record?.exchangeLossMode === 'MANUAL' ? record.exchangeLossAmount : ''
  form.serviceFeeRate = record?.serviceFeeRate || formLine.value?.defaultServiceFeeRate || ''
  form.serviceFeeBasis = record?.serviceFeeBasis || formLine.value?.defaultServiceFeeBasis || 'TRANSFER'
  form.serviceFeeMode = record?.serviceFeeMode || 'AUTO'
  form.serviceFeeAmount = record?.serviceFeeMode === 'MANUAL' ? record.serviceFeeAmount : ''
  form.refluxAmount = record?.refluxAmount || ''
  form.refundAmount = record?.refundAmount || ''
  form.otherDeductionAmount = record?.otherDeductionAmount || ''
  form.otherReason = record?.otherReason || ''
  form.remark = record?.remark || ''
}

function openCreate(): void {
  resetForm()
  dialogVisible.value = true
}

function openEdit(record: ErpDailyBalance): void {
  resetForm(record)
  dialogVisible.value = true
}

function toPayload(): ErpDailyBalanceWrite {
  return {
    operatorLineId: form.operatorLineId,
    businessDate: form.businessDate,
    openingMode: form.openingMode,
    openingBalance: form.openingMode === 'MANUAL' ? clean(form.openingBalance) : undefined,
    transferAmount: clean(form.transferAmount),
    fraudLossAmount: clean(form.fraudLossAmount),
    fraudDeductionSource: form.fraudDeductionSource || undefined,
    spendAmount: clean(form.spendAmount),
    exchangeLossRate: clean(form.exchangeLossRate),
    exchangeLossBasis: form.exchangeLossBasis,
    exchangeLossMode: form.exchangeLossMode,
    exchangeLossAmount: form.exchangeLossMode === 'MANUAL' ? clean(form.exchangeLossAmount) : undefined,
    serviceFeeRate: clean(form.serviceFeeRate),
    serviceFeeBasis: form.serviceFeeBasis,
    serviceFeeMode: form.serviceFeeMode,
    serviceFeeAmount: form.serviceFeeMode === 'MANUAL' ? clean(form.serviceFeeAmount) : undefined,
    refluxAmount: clean(form.refluxAmount),
    refundAmount: clean(form.refundAmount),
    otherDeductionAmount: clean(form.otherDeductionAmount),
    otherReason: clean(form.otherReason),
    remark: clean(form.remark),
    rowVersion: editing.value?.rowVersion,
  }
}

async function save(): Promise<void> {
  if (!form.operatorLineId || !form.businessDate) {
    ElMessage.warning('请选择投放线并填写业务日期。')
    return
  }
  if (form.openingMode === 'MANUAL' && !clean(form.openingBalance)) {
    ElMessage.warning('人工期初结余不能为空。')
    return
  }
  if (clean(form.fraudLossAmount) && Number(form.fraudLossAmount) > 0 && !form.fraudDeductionSource) {
    ElMessage.warning('欺诈损失不为 0 时请选择承担方式。')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateErpDailyBalance(editing.value.id, toPayload())
      ElMessage.success('日结草稿已更新。')
    } else {
      await createErpDailyBalance(toPayload())
      ElMessage.success('日结草稿已创建。')
    }
    dialogVisible.value = false
    selectedLineId.value = form.operatorLineId
    month.value = form.businessDate.slice(0, 7)
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '日结保存失败。'))
  } finally {
    saving.value = false
  }
}

async function confirm(record: ErpDailyBalance): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认 ${record.businessDate} 的日结后将不能直接修改，是否继续？`,
      '确认日结',
      { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
    )
    await confirmErpDailyBalance(record.id, record.rowVersion)
    ElMessage.success('日结已确认。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '确认日结失败。'))
  }
}

watch([selectedLineId, month], () => void load())
onMounted(() => void load())
</script>

<template>
  <div class="page-stack erp-balance-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">ERP daily ledger</span>
        <h1>输入台账</h1>
        <p>按投放线记录本地日结，并由系统统一计算有效转 U、费用与期末结余。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="isAdmin" type="primary" :icon="Plus" :disabled="!lines.length" @click="openCreate">
          新建日结
        </el-button>
      </div>
    </header>

    <el-alert
      title="仅本地 ERP 台账"
      description="保存、确认和报表只操作当前项目的本地数据库；不会调用或修改任何远端盘口、账号或订单。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card ledger-filter">
      <el-select v-model="selectedLineId" filterable placeholder="选择投放线">
        <el-option v-for="line in lines" :key="line.id" :value="line.id" :label="`${line.operatorName} · ${line.name} · ${line.asset}`" />
      </el-select>
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" placeholder="选择月份" />
      <span>{{ selectedLineLabel }}</span>
    </section>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="records" row-key="id" empty-text="当前月份暂无本地日结记录">
        <el-table-column prop="businessDate" label="业务日期" width="118" fixed="left" />
        <el-table-column label="期初结余" min-width="118" align="right"><template #default="{ row }">{{ amount(row.openingBalance) }}</template></el-table-column>
        <el-table-column label="转 U / 有效转 U" min-width="154" align="right"><template #default="{ row }">{{ amount(row.transferAmount) }} / {{ amount(row.effectiveTransferAmount) }}</template></el-table-column>
        <el-table-column label="消耗" min-width="100" align="right"><template #default="{ row }">{{ amount(row.spendAmount) }}</template></el-table-column>
        <el-table-column label="汇损 / 服务费" min-width="154" align="right"><template #default="{ row }">{{ amount(row.exchangeLossAmount) }} / {{ amount(row.serviceFeeAmount) }}</template></el-table-column>
        <el-table-column label="回流 / 退款 / 其他" min-width="180" align="right"><template #default="{ row }">{{ amount(row.refluxAmount) }} / {{ amount(row.refundAmount) }} / {{ amount(row.otherDeductionAmount) }}</template></el-table-column>
        <el-table-column label="期末结余" min-width="118" align="right"><template #default="{ row }"><strong>{{ amount(row.closingBalance) }}</strong></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><el-tag :type="row.status === 'CONFIRMED' ? 'success' : 'warning'">{{ row.status === 'CONFIRMED' ? '已确认' : '草稿' }}</el-tag></template></el-table-column>
        <el-table-column v-if="isAdmin" label="操作" width="145" fixed="right"><template #default="{ row }"><el-button v-if="row.status === 'DRAFT'" text type="primary" @click="openEdit(row)">编辑</el-button><el-button v-if="row.status === 'DRAFT'" text type="success" @click="confirm(row)">确认</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑日结草稿' : '新建日结草稿'" width="880px" destroy-on-close>
      <el-form label-position="top" class="ledger-form">
        <div class="ledger-form__grid ledger-form__grid--three">
          <el-form-item label="投放线"><el-select v-model="form.operatorLineId" filterable><el-option v-for="line in lines" :key="line.id" :value="line.id" :label="`${line.operatorName} · ${line.name} · ${line.asset}`" /></el-select></el-form-item>
          <el-form-item label="业务日期"><el-date-picker v-model="form.businessDate" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="期初方式"><el-radio-group v-model="form.openingMode"><el-radio-button label="MANUAL">人工</el-radio-button><el-radio-button label="AUTO" :disabled="!editing">自动承接</el-radio-button></el-radio-group></el-form-item>
        </div>
        <div class="ledger-form__grid ledger-form__grid--four">
          <el-form-item label="期初结余"><el-input v-model="form.openingBalance" :disabled="form.openingMode === 'AUTO'" placeholder="0" /></el-form-item>
          <el-form-item label="转 U"><el-input v-model="form.transferAmount" placeholder="0" /></el-form-item>
          <el-form-item label="消耗"><el-input v-model="form.spendAmount" placeholder="0" /></el-form-item>
          <el-form-item label="回流"><el-input v-model="form.refluxAmount" placeholder="0" /></el-form-item>
          <el-form-item label="退款"><el-input v-model="form.refundAmount" placeholder="0" /></el-form-item>
          <el-form-item label="其他扣减"><el-input v-model="form.otherDeductionAmount" placeholder="0" /></el-form-item>
          <el-form-item label="欺诈损失"><el-input v-model="form.fraudLossAmount" placeholder="0" /></el-form-item>
          <el-form-item label="欺诈承担"><el-select v-model="form.fraudDeductionSource" clearable placeholder="损失为 0 可不选"><el-option label="从转 U 扣除" value="TRANSFER" /><el-option label="从结余扣除" value="BALANCE" /></el-select></el-form-item>
        </div>
        <el-form-item label="其他扣减原因"><el-input v-model="form.otherReason" maxlength="500" show-word-limit /></el-form-item>
        <div class="ledger-form__grid ledger-form__grid--four">
          <el-form-item label="汇损费率"><el-input v-model="form.exchangeLossRate" placeholder="例如 0.02" /></el-form-item>
          <el-form-item label="汇损基数"><el-select v-model="form.exchangeLossBasis"><el-option label="转 U" value="TRANSFER" /><el-option label="有效转 U" value="EFFECTIVE_TRANSFER" /><el-option label="消耗" value="SPEND" /><el-option label="手工" value="MANUAL" /></el-select></el-form-item>
          <el-form-item label="汇损模式"><el-select v-model="form.exchangeLossMode"><el-option label="自动计算" value="AUTO" /><el-option label="手工录入" value="MANUAL" /></el-select></el-form-item>
          <el-form-item label="汇损金额"><el-input v-model="form.exchangeLossAmount" :disabled="form.exchangeLossMode === 'AUTO'" placeholder="手工模式必填" /></el-form-item>
          <el-form-item label="服务费率"><el-input v-model="form.serviceFeeRate" placeholder="例如 0.02" /></el-form-item>
          <el-form-item label="服务费基数"><el-select v-model="form.serviceFeeBasis"><el-option label="转 U" value="TRANSFER" /><el-option label="有效转 U" value="EFFECTIVE_TRANSFER" /><el-option label="消耗" value="SPEND" /><el-option label="手工" value="MANUAL" /></el-select></el-form-item>
          <el-form-item label="服务费模式"><el-select v-model="form.serviceFeeMode"><el-option label="自动计算" value="AUTO" /><el-option label="手工录入" value="MANUAL" /></el-select></el-form-item>
          <el-form-item label="服务费金额"><el-input v-model="form.serviceFeeAmount" :disabled="form.serviceFeeMode === 'AUTO'" placeholder="手工模式必填" /></el-form-item>
        </div>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" maxlength="5000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存草稿</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ledger-filter { display: flex; align-items: center; gap: 14px; padding: 16px; }
.ledger-filter > .el-select { width: min(460px, 52vw); }
.ledger-filter > span { color: var(--ink-muted); font-size: 13px; }
.ledger-form__grid { display: grid; gap: 0 16px; }
.ledger-form__grid--three { grid-template-columns: 2fr 1fr 1fr; }
.ledger-form__grid--four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 760px) { .ledger-filter { align-items: stretch; flex-direction: column; } .ledger-filter > .el-select { width: 100%; } .ledger-form__grid--three, .ledger-form__grid--four { grid-template-columns: 1fr; } }
</style>
