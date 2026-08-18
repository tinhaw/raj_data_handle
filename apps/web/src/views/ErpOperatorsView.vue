<script setup lang="ts">
import { Delete, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createErpDeliveryLine,
  createErpOperator,
  deleteErpOperator,
  disableErpOperator,
  fetchErpOperatorDeleteImpact,
  fetchErpOperatorLines,
  fetchErpOperators,
  updateErpOperator,
} from '../api/erpOperators'
import { apiErrorMessage } from '../api/client'
import { hasErpPermission } from '../stores/auth'
import type { ErpDeliveryLine, ErpOperator } from '../types'

const loading = ref(false)
const saving = ref(false)
const operators = ref<ErpOperator[]>([])
const lines = ref<ErpDeliveryLine[]>([])
const keyword = ref('')
const operatorDialogVisible = ref(false)
const lineDialogVisible = ref(false)
const editingOperator = ref<ErpOperator | null>(null)
const lineOperator = ref<ErpOperator | null>(null)

const operatorForm = reactive({
  name: '',
  contactName: '',
  contactValue: '',
  remark: '',
})
const lineForm = reactive({
  name: '',
  asset: 'USDT' as 'USDT' | 'USDC',
})

const filteredOperators = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return operators.value
  return operators.value.filter((item) =>
    [item.name, item.code, item.contactName, item.contactValue]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(query)),
  )
})

const linesByOperator = computed(() => {
  const result = new Map<string, ErpDeliveryLine[]>()
  for (const line of lines.value) {
    const current = result.get(line.operatorId) || []
    current.push(line)
    result.set(line.operatorId, current)
  }
  return result
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const nextOperators = await fetchErpOperators(true)
    const groupedLines = await Promise.all(
      nextOperators.map((operator) => fetchErpOperatorLines(operator.id)),
    )
    operators.value = nextOperators
    lines.value = groupedLines.flat()
  } catch (error) {
    operators.value = []
    lines.value = []
    ElMessage.error(apiErrorMessage(error, '投放公司数据加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
  }
}

function openCreateOperator(): void {
  editingOperator.value = null
  operatorForm.name = ''
  operatorForm.contactName = ''
  operatorForm.contactValue = ''
  operatorForm.remark = ''
  operatorDialogVisible.value = true
}

function openEditOperator(operator: ErpOperator): void {
  editingOperator.value = operator
  operatorForm.name = operator.name
  operatorForm.contactName = operator.contactName || ''
  operatorForm.contactValue = operator.contactValue || ''
  operatorForm.remark = operator.remark || ''
  operatorDialogVisible.value = true
}

async function saveOperator(): Promise<void> {
  if (!operatorForm.name.trim()) {
    ElMessage.warning('请填写投放公司名称。')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: operatorForm.name,
      contactName: operatorForm.contactName || null,
      contactValue: operatorForm.contactValue || null,
      remark: operatorForm.remark || null,
    }
    if (editingOperator.value) {
      await updateErpOperator(editingOperator.value.id, {
        ...payload,
        rowVersion: editingOperator.value.rowVersion,
      })
      ElMessage.success('投放公司已更新。')
    } else {
      await createErpOperator(payload)
      ElMessage.success('投放公司已创建。')
    }
    operatorDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '投放公司保存失败。'))
  } finally {
    saving.value = false
  }
}

function openCreateLine(operator: ErpOperator): void {
  lineOperator.value = operator
  lineForm.name = ''
  lineForm.asset = 'USDT'
  lineDialogVisible.value = true
}

async function saveLine(): Promise<void> {
  if (!lineOperator.value || !lineForm.name.trim()) {
    ElMessage.warning('请填写投放线名称。')
    return
  }
  saving.value = true
  try {
    await createErpDeliveryLine(lineOperator.value.id, {
      name: lineForm.name,
      asset: lineForm.asset,
    })
    lineDialogVisible.value = false
    ElMessage.success('投放线已创建。')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '投放线创建失败。'))
  } finally {
    saving.value = false
  }
}

async function disableOperator(operator: ErpOperator): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `停用“${operator.name}”后将保留全部台账和投放线记录，是否继续？`,
      '停用投放公司',
      { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
    )
    await disableErpOperator(operator.id, operator.rowVersion)
    ElMessage.success('投放公司已停用。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '投放公司停用失败。'))
  }
}

async function removeOperator(operator: ErpOperator): Promise<void> {
  try {
    const impact = await fetchErpOperatorDeleteImpact(operator.id)
    await ElMessageBox.confirm(
      `将永久删除“${operator.name}”及其 ${impact.deliveryLineCount} 条投放线。停用可完整保留历史，仍要继续删除吗？`,
      '删除投放公司',
      { type: 'warning', confirmButtonText: '继续检查', cancelButtonText: '取消' },
    )
    let purgeHistory = false
    let confirmationName: string | undefined
    if (impact.hasHistory) {
      const history = [
        impact.ledgerCount ? `${impact.ledgerCount} 条台账` : '',
        impact.lockedPeriodCount ? `${impact.lockedPeriodCount} 个结账期间` : '',
      ].filter(Boolean).join('、')
      const result = await ElMessageBox.prompt(
        `该公司存在${history}。清空后不可恢复，请输入完整公司名称“${operator.name}”确认。`,
        '确认清空历史并删除',
        {
          type: 'error',
          inputPlaceholder: operator.name,
          confirmButtonText: '清空并删除',
          cancelButtonText: '取消',
          inputValidator: (value) => value === operator.name || '公司名称不一致',
        },
      )
      purgeHistory = true
      confirmationName = result.value
    }
    await deleteErpOperator(operator.id, {
      rowVersion: operator.rowVersion,
      purgeHistory,
      confirmationName,
      reason: purgeHistory ? '用户已通过公司名称二次确认清空历史' : '公司无历史记录',
    })
    ElMessage.success(purgeHistory ? '历史数据及投放公司已删除。' : '投放公司已删除。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '投放公司删除失败。'))
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">ERP operators</span>
        <h1>投放公司与投放线</h1>
        <p>维护 ERP 本地台账所使用的投放公司和投放线；删除含历史记录的公司需二次确认。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="hasErpPermission('ERP_OPERATOR_MANAGE')" type="primary" :icon="Plus" @click="openCreateOperator">
          新建投放公司
        </el-button>
      </div>
    </header>

    <el-alert
      title="本地 ERP 数据"
      description="本模块仅写入当前项目的本地数据库，不会修改 RajWin、RajLuck 或其他远端系统。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card operator-filter">
      <el-input v-model="keyword" clearable placeholder="搜索公司名称、编号或联系人" />
      <span>共 {{ filteredOperators.length }} 个投放公司、{{ lines.length }} 条投放线</span>
    </section>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="filteredOperators" row-key="id">
        <el-table-column label="投放公司" min-width="220">
          <template #default="{ row }">
            <div class="company-name">
              <strong>{{ row.name }}</strong>
              <span>{{ row.code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="联系人" min-width="190">
          <template #default="{ row }">
            <div>{{ row.contactName || '—' }}</div>
            <small>{{ row.contactValue || '未填写联系方式' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="投放线" min-width="300">
          <template #default="{ row }">
            <div v-if="linesByOperator.get(row.id)?.length" class="line-list">
              <el-tag v-for="line in linesByOperator.get(row.id)" :key="line.id" effect="plain">
                {{ line.name }} · {{ line.asset }}
              </el-tag>
            </div>
            <span v-else class="muted">尚未创建投放线</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">
              {{ row.status === 'ACTIVE' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '—' }}</template>
        </el-table-column>
        <el-table-column v-if="hasErpPermission('ERP_OPERATOR_MANAGE')" label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <div class="operator-actions">
              <el-button text type="primary" @click="openCreateLine(row)">新建投放线</el-button>
              <el-button text type="primary" @click="openEditOperator(row)">编辑</el-button>
              <el-button v-if="row.status === 'ACTIVE'" text type="danger" @click="disableOperator(row)">停用</el-button>
              <el-button text type="danger" :icon="Delete" @click="removeOperator(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="operatorDialogVisible"
      :title="editingOperator ? '编辑投放公司' : '新建投放公司'"
      width="560px"
    >
      <el-form label-position="top" @submit.prevent="saveOperator">
        <el-form-item label="投放公司名称" required>
          <el-input v-model="operatorForm.name" maxlength="200" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="联系人">
            <el-input v-model="operatorForm.contactName" />
          </el-form-item>
          <el-form-item label="联系方式">
            <el-input v-model="operatorForm.contactValue" />
          </el-form-item>
        </div>
        <el-form-item label="备注">
          <el-input v-model="operatorForm.remark" type="textarea" :rows="3" maxlength="2_000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="operatorDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveOperator">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="lineDialogVisible" :title="`为 ${lineOperator?.name || ''} 新建投放线`" width="500px">
      <el-form label-position="top" @submit.prevent="saveLine">
        <el-form-item label="投放线名称" required>
          <el-input v-model="lineForm.name" maxlength="120" />
        </el-form-item>
        <el-form-item label="币种" required>
          <el-select v-model="lineForm.asset" style="width: 100%">
            <el-option label="USDT（默认）" value="USDT" />
            <el-option label="USDC" value="USDC" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lineDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveLine">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.operator-filter {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
}

.operator-filter .el-input {
  max-width: 320px;
}

.operator-filter span,
.company-name span,
.table-card small,
.muted {
  color: var(--ink-muted);
  font-size: 12px;
}

.company-name {
  display: grid;
  gap: 3px;
}

.company-name strong {
  color: var(--ink-strong);
}

.line-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.operator-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  white-space: nowrap;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

@media (max-width: 700px) {
  .operator-filter,
  .form-grid {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }

  .operator-filter .el-input {
    max-width: none;
  }
}
</style>
