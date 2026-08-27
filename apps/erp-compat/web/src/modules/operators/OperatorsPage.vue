<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ApiError, api } from '@/api/client'
import type { Operator, OperatorAccount } from '@/api/types'
import StatusTag from '@/components/StatusTag.vue'
import { demoAccounts, demoOperators } from '@/utils/demo-data'
import { demoEnabled } from '@/utils/runtime'

const loading = ref(false)
const saving = ref(false)
const operators = ref<Operator[]>([])
const accounts = ref<OperatorAccount[]>([])
const keyword = ref('')
const operatorDialog = ref(false)
const accountDialog = ref(false)
const editingOperatorId = ref<string | number | null>(null)
const selectedOperator = ref<Operator | null>(null)
const usingDemo = ref(false)

const operatorForm = reactive({
  name: '', contactName: '', contactValue: '', remark: '',
})
const accountForm = reactive({
  name: '', asset: 'USDT' as OperatorAccount['asset'],
})

const filteredOperators = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return operators.value
  return operators.value.filter((item) => [item.name, item.contactName, item.contactValue].some((value) => value?.toLowerCase().includes(text)))
})

const accountsByOperator = computed(() => new Map(operators.value.map((operator) => [operator.id, accounts.value.filter((account) => account.operatorId === operator.id)])))

function normalizedName(value: string) {
  return value.trim().toLocaleLowerCase()
}

async function load() {
  loading.value = true
  try {
    const loadedOperators = await api.operators.list()
    const loadedAccounts = (await Promise.all(loadedOperators.map((operator) => api.operators.accounts(operator.id)))).flat()
    operators.value = loadedOperators
    accounts.value = loadedAccounts
    usingDemo.value = false
  } catch {
    if (demoEnabled) {
      operators.value = demoOperators.map((item) => ({ ...item }))
      accounts.value = demoAccounts.map((item) => ({ ...item }))
      usingDemo.value = true
    } else {
      operators.value = []
      accounts.value = []
      usingDemo.value = false
      ElMessage.error('无法连接投放公司数据服务，请确认 API 已启动后刷新。')
    }
  } finally {
    loading.value = false
  }
}

function resetOperatorForm() {
  Object.assign(operatorForm, { name: '', contactName: '', contactValue: '', remark: '' })
}

function openCreateOperator() {
  editingOperatorId.value = null
  resetOperatorForm()
  operatorDialog.value = true
}

function openEditOperator(operator: Operator) {
  editingOperatorId.value = operator.id
  Object.assign(operatorForm, {
    name: operator.name, contactName: operator.contactName || '', contactValue: operator.contactValue || '', remark: operator.remark || '',
  })
  operatorDialog.value = true
}

async function saveOperator() {
  const name = operatorForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写投放公司名称')
    return
  }
  if (operators.value.some((item) => item.id !== editingOperatorId.value && normalizedName(item.name) === normalizedName(name))) {
    ElMessage.warning('投放公司名称不能重复')
    return
  }

  saving.value = true
  const existing = editingOperatorId.value ? operators.value.find((item) => item.id === editingOperatorId.value) : undefined
  const payload: Partial<Operator> = {
    name,
    // 仅保留为兼容当前接口；页面不再让用户设置公司类型。
    type: existing?.type || 'COMPANY',
    contactName: operatorForm.contactName.trim() || undefined,
    contactValue: operatorForm.contactValue.trim() || undefined,
    remark: operatorForm.remark.trim() || undefined,
    rowVersion: existing?.rowVersion,
  }
  try {
    if (editingOperatorId.value) {
      const updated = await api.operators.update(editingOperatorId.value, payload)
      operators.value = operators.value.map((item) => item.id === updated.id ? updated : item)
      ElMessage.success('投放公司已更新')
    } else {
      const created = await api.operators.create(payload)
      operators.value = [created, ...operators.value]
      ElMessage.success('投放公司已创建')
    }
    operatorDialog.value = false
  } catch (error) {
    if (!usingDemo.value) {
      ElMessage.error(error instanceof Error ? error.message : '保存失败')
    } else {
      const id = `demo-company-${Date.now()}`
      const next: Operator = {
        id,
        code: `DEMO-${Date.now()}`,
        type: payload.type || 'COMPANY',
        status: 'ACTIVE',
        name,
        contactName: payload.contactName,
        contactValue: payload.contactValue,
        remark: payload.remark,
      }
      operators.value = editingOperatorId.value
        ? operators.value.map((item) => item.id === editingOperatorId.value ? { ...item, ...next, id: item.id } : item)
        : [next, ...operators.value]
      operatorDialog.value = false
      ElMessage.warning('服务未连接，已仅在演示页面保存')
    }
  } finally {
    saving.value = false
  }
}

function resetAccountForm() {
  Object.assign(accountForm, { name: '', asset: 'USDT' })
}

function openCreateAccount(operator: Operator) {
  selectedOperator.value = operator
  resetAccountForm()
  accountDialog.value = true
}

async function saveAccount() {
  const name = accountForm.name.trim()
  if (!selectedOperator.value || !name) {
    ElMessage.warning('请填写投放线名称')
    return
  }
  const hasDuplicateLine = accounts.value.some((account) => account.operatorId === selectedOperator.value?.id && normalizedName(account.name) === normalizedName(name))
  if (hasDuplicateLine) {
    ElMessage.warning('同一投放公司下的投放线名称不能重复')
    return
  }

  saving.value = true
  const payload: Partial<OperatorAccount> = {
    name,
    asset: accountForm.asset,
  }
  try {
    const account = await api.operators.createAccount(selectedOperator.value.id, payload)
    accounts.value = [...accounts.value, account]
    accountDialog.value = false
    ElMessage.success('投放线已创建')
  } catch (error) {
    if (!usingDemo.value) {
      ElMessage.error(error instanceof Error ? error.message : '保存失败')
    } else {
      accounts.value = [...accounts.value, {
        id: `demo-line-${Date.now()}`,
        operatorId: selectedOperator.value.id,
        code: `DEMO-LINE-${Date.now()}`,
        name,
        asset: accountForm.asset,
        defaultExchangeLossRate: '0.02',
        defaultExchangeLossBasis: 'TRANSFER',
        defaultServiceFeeRate: '0.02',
        defaultServiceFeeBasis: 'TRANSFER',
        calculationScale: 2,
        status: 'ACTIVE',
      }]
      accountDialog.value = false
      ElMessage.warning('服务未连接，已仅在演示页面保存')
    }
  } finally {
    saving.value = false
  }
}

async function disableOperator(operator: Operator) {
  await ElMessageBox.confirm(`停用“${operator.name}”后不会删除历史台账，是否继续？`, '停用投放公司', { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' })
  try {
    await api.operators.disable(operator.id, operator.rowVersion, '投放公司不再使用')
    operators.value = operators.value.map((item) => item.id === operator.id ? { ...item, status: 'INACTIVE' } : item)
    ElMessage.success('投放公司已停用')
  } catch (error) {
    if (usingDemo.value) {
      operators.value = operators.value.map((item) => item.id === operator.id ? { ...item, status: 'INACTIVE' } : item)
      ElMessage.warning('服务未连接，已仅在演示页面停用')
    } else {
      ElMessage.error(error instanceof Error ? error.message : '停用失败')
    }
  }
}

async function deleteOperator(operator: Operator) {
  const lines = accountsByOperator.value.get(operator.id) || []
  try {
    await ElMessageBox.confirm(
      `将永久删除“${operator.name}”及其 ${lines.length} 条投放线。若含历史台账，系统会要求再次确认清空台账，是否继续？`,
      '删除投放公司',
      { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    if (usingDemo.value) {
      operators.value = operators.value.filter((item) => item.id !== operator.id)
      accounts.value = accounts.value.filter((item) => item.operatorId !== operator.id)
      ElMessage.warning('服务未连接，已仅在演示页面删除')
      return
    }
    await api.operators.remove(operator.id, operator.rowVersion)
    removeOperatorFromList(operator.id)
    ElMessage.success('投放公司已删除')
  } catch (error) {
    if (error instanceof ApiError && error.code === 'OPERATOR_HAS_HISTORY') {
      await confirmHistoryPurge(operator, error)
      return
    }
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

function removeOperatorFromList(operatorId: string | number) {
  operators.value = operators.value.filter((item) => item.id !== operatorId)
  accounts.value = accounts.value.filter((item) => item.operatorId !== operatorId)
}

async function confirmHistoryPurge(operator: Operator, error: ApiError) {
  const ledgerCount = Number(error.details?.ledgerCount || 0)
  const lockedPeriodCount = Number(error.details?.lockedPeriodCount || 0)
  const parts = [ledgerCount ? `${ledgerCount} 条台账` : '', lockedPeriodCount ? `${lockedPeriodCount} 个结账期间` : ''].filter(Boolean)
  try {
    await ElMessageBox.confirm(
      `“${operator.name}”名下存在${parts.join('、') || '历史台账'}。确认后将永久清空这些数据，并删除投放公司及投放线；此操作不可恢复。`,
      '确认清空台账并删除？',
      { type: 'error', confirmButtonText: '确认清空并删除', confirmButtonClass: 'el-button--danger', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    await api.operators.remove(operator.id, operator.rowVersion, true)
    removeOperatorFromList(operator.id)
    ElMessage.success('已清空关联台账并删除投放公司')
  } catch (purgeError) {
    ElMessage.error(purgeError instanceof Error ? purgeError.message : '清空台账并删除失败')
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title-row">
      <div>
        <h2>投放公司与投放线</h2>
        <p class="page-subtitle">维护投放公司及其投放线。每条投放线独立核算币种；删除含历史台账的公司时需再次确认清空关联数据。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreateOperator">新建投放公司</el-button>
      </div>
    </div>

    <article class="panel panel--padded">
      <div class="filter-bar">
        <el-form-item label="搜索投放公司">
          <el-input v-model="keyword" clearable placeholder="名称、联系人、联系方式" style="width: 280px" />
        </el-form-item>
        <span class="hint">共 {{ filteredOperators.length }} 个投放公司，{{ accounts.length }} 条投放线</span>
      </div>
    </article>

    <article class="panel table-card">
      <el-table v-loading="loading" :data="filteredOperators" row-key="id" :row-class-name="({ row }) => row.status === 'INACTIVE' ? 'inactive-row' : ''">
        <el-table-column label="投放公司" min-width="240">
          <template #default="{ row }">
            <div class="company-name"><strong>{{ row.name }}</strong><span>投放线按公司独立管理</span></div>
          </template>
        </el-table-column>
        <el-table-column label="联系人" min-width="190">
          <template #default="{ row }"><div>{{ row.contactName || '—' }}</div><span class="muted">{{ row.contactValue || '未填写联系方式' }}</span></template>
        </el-table-column>
        <el-table-column label="投放线" min-width="330">
          <template #default="{ row }">
            <div v-if="accountsByOperator.get(row.id)?.length" class="line-list">
              <span v-for="account in accountsByOperator.get(row.id)" :key="account.id" class="line-chip">
                <b>{{ row.name }} · {{ account.name }}</b><em>{{ account.asset }}</em>
              </span>
            </div>
            <span v-else class="muted">尚未创建投放线</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="备注" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ row.remark || '—' }}</template></el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <div class="operator-actions">
              <el-button link type="primary" :icon="Plus" @click="openCreateAccount(row)">新建投放线</el-button>
              <el-button link type="primary" :icon="Edit" @click="openEditOperator(row)">编辑投放公司</el-button>
              <el-button v-if="row.status === 'ACTIVE'" link type="danger" @click="disableOperator(row)">停用</el-button>
              <el-button link type="danger" :icon="Delete" @click="deleteOperator(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-footer"><span>投放线的币种默认是 USDT；如需使用 USDC，可在创建时选择。</span><span v-if="usingDemo">当前为演示数据</span></div>
    </article>

    <el-dialog v-model="operatorDialog" :title="editingOperatorId ? '编辑投放公司' : '新建投放公司'" width="560px" destroy-on-close>
      <el-form label-position="top" @submit.prevent="saveOperator">
        <el-form-item label="投放公司名称" required><el-input v-model="operatorForm.name" maxlength="200" placeholder="如 示例投放公司" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="联系人"><el-input v-model="operatorForm.contactName" placeholder="姓名或称呼" /></el-form-item>
          <el-form-item label="联系方式"><el-input v-model="operatorForm.contactValue" placeholder="Telegram / WhatsApp / 邮箱" /></el-form-item>
        </div>
        <el-form-item label="备注"><el-input v-model="operatorForm.remark" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="operatorDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveOperator">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="accountDialog" :title="`为 ${selectedOperator?.name || ''} 新建投放线`" width="520px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon>投放线名称只需在当前投放公司内保持唯一；报表中会以“投放公司 · 投放线”展示。</el-alert>
      <el-form class="dialog-form" label-position="top" @submit.prevent="saveAccount">
        <el-form-item label="投放线名称" required><el-input v-model="accountForm.name" maxlength="120" placeholder="如 主投放线" /></el-form-item>
        <el-form-item label="币种" required>
          <el-select v-model="accountForm.asset" style="width: 100%">
            <el-option label="USDT（默认）" value="USDT" />
            <el-option label="USDC" value="USDC" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="accountDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveAccount">创建投放线</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.company-name { display: grid; gap: 3px; }
.company-name strong { color: #182230; font-weight: 650; }
.company-name span { color: #98a2b3; font-size: 12px; }
.line-list { display: flex; flex-wrap: wrap; gap: 6px; }
.line-chip { display: inline-flex; align-items: center; gap: 5px; padding: 4px 7px; color: #344054; font-size: 12px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 5px; }
.line-chip b { font-weight: 550; }
.line-chip em { color: #667085; font-style: normal; }
.operator-actions { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
.operator-actions :deep(.el-button + .el-button) { margin-left: 0; }
.inactive-row td { color: #98a2b3; background: #fcfcfd; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.dialog-form { margin-top: 18px; }
</style>
