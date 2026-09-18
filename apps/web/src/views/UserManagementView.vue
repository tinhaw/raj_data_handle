<script setup lang="ts">
import { Key, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { createUser, fetchUsers, updateUser } from '../api/auth'
import { apiErrorMessage } from '../api/client'
import { fetchErpRoles, fetchErpUserAccess, updateErpUserAccess } from '../api/erpAccess'
import { fetchErpOperators } from '../api/erpOperators'
import type { ErpOperator, ErpRoleDefinition, UserRecord } from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const rows = ref<UserRecord[]>([])
const dialogVisible = ref(false)
const erpAccessDialogVisible = ref(false)
const editingId = ref<number | null>(null)
const accessUser = ref<UserRecord | null>(null)
const accessLoading = ref(false)
const accessSaving = ref(false)
const roleDefinitions = ref<ErpRoleDefinition[]>([])
const operatorRows = ref<ErpOperator[]>([])
const form = reactive({
  username: '',
  displayName: '',
  password: '',
  role: 'user' as 'admin' | 'user',
  isActive: true,
})
const erpAccessForm = reactive({
  roleGrants: [] as string[],
  allOperators: false,
  operatorIds: [] as string[],
})

async function load(): Promise<void> {
  loading.value = true
  try {
    rows.value = await fetchUsers()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '用户列表加载失败。'))
  } finally {
    loading.value = false
  }
}

function add(): void {
  editingId.value = null
  form.username = ''
  form.displayName = ''
  form.password = ''
  form.role = 'user'
  form.isActive = true
  dialogVisible.value = true
}

function edit(row: UserRecord): void {
  editingId.value = row.id
  form.username = row.username
  form.displayName = row.displayName
  form.password = ''
  form.role = row.role
  form.isActive = row.isActive
  dialogVisible.value = true
}

async function save(): Promise<void> {
  saving.value = true
  try {
    if (editingId.value === null) {
      await createUser({
        username: form.username,
        displayName: form.displayName,
        password: form.password,
        role: form.role,
      })
    } else {
      await updateUser(editingId.value, {
        displayName: form.displayName,
        role: form.role,
        isActive: form.isActive,
        password: form.password || undefined,
      })
    }
    ElMessage.success('用户已保存。')
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '用户保存失败。'))
  } finally {
    saving.value = false
  }
}

async function openErpAccess(row: UserRecord): Promise<void> {
  accessUser.value = row
  accessLoading.value = true
  try {
    const [access, roles, operators] = await Promise.all([
      fetchErpUserAccess(row.id),
      fetchErpRoles(),
      fetchErpOperators(true),
    ])
    roleDefinitions.value = roles
    operatorRows.value = operators
    erpAccessForm.roleGrants = access.roleGrants
    erpAccessForm.allOperators = access.allOperators
    erpAccessForm.operatorIds = access.operatorIds
    erpAccessDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'ERP 授权配置加载失败。'))
  } finally {
    accessLoading.value = false
  }
}

async function saveErpAccess(): Promise<void> {
  if (!accessUser.value) return
  accessSaving.value = true
  try {
    await updateErpUserAccess(accessUser.value.id, {
      roleGrants: erpAccessForm.roleGrants,
      allOperators: erpAccessForm.allOperators,
      operatorIds: erpAccessForm.allOperators ? [] : erpAccessForm.operatorIds,
    })
    ElMessage.success('ERP 角色与投放公司范围已保存。')
    erpAccessDialogVisible.value = false
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'ERP 授权配置保存失败。'))
  } finally {
    accessSaving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Account management</span>
        <h1>用户管理</h1>
        <p>平台角色控制登录与系统管理；ERP 角色和投放公司范围在用户级单独授予。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="add">创建用户</el-button>
      </div>
    </header>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="用户名" min-width="150" prop="username" />
        <el-table-column label="显示名" min-width="160" prop="displayName" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'warning' : 'info'">
              {{ row.role === 'admin' ? '管理员' : '业务用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.isActive ? 'success' : 'danger'">
              {{ row.isActive ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="ERP 范围" min-width="150">
          <template #default="{ row }">
            <span v-if="row.role === 'admin'">全部权限与全部公司</span>
            <span v-else class="muted">按 ERP 授权配置</span>
          </template>
        </el-table-column>
        <el-table-column label="最后登录" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.role !== 'admin'" text type="primary" :icon="Key" @click="openErpAccess(row)">
              ERP 授权
            </el-button>
            <el-button text type="primary" @click="edit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑用户' : '创建用户'" width="520px">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="editingId !== null" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.displayName" />
        </el-form-item>
        <el-form-item :label="editingId ? '重置密码（留空不修改）' : '初始密码'">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="角色">
            <el-select v-model="form.role" style="width: 100%">
              <el-option label="业务用户" value="user" />
              <el-option label="管理员" value="admin" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用状态">
            <el-switch v-model="form.isActive" :disabled="editingId === null" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="erpAccessDialogVisible"
      :title="`ERP 授权：${accessUser?.displayName || ''}`"
      width="680px"
    >
      <el-alert
        title="仅影响本地 ERP 权限"
        description="角色和投放公司范围不会改变平台登录角色，也不会为账号自动授予远端连接、标签同步或兑换码发布能力。"
        type="info"
        show-icon
        :closable="false"
      />
      <el-form v-loading="accessLoading" label-position="top" class="erp-access-form">
        <el-form-item label="ERP 角色">
          <el-checkbox-group v-model="erpAccessForm.roleGrants" class="role-options">
            <el-checkbox v-for="role in roleDefinitions" :key="role.code" :label="role.code">
              {{ role.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="投放公司范围">
          <el-switch v-model="erpAccessForm.allOperators" active-text="全部投放公司" inactive-text="指定投放公司" />
          <el-select
            v-if="!erpAccessForm.allOperators"
            v-model="erpAccessForm.operatorIds"
            multiple
            filterable
            placeholder="请选择可访问的投放公司"
            style="width: 100%; margin-top: 12px"
          >
            <el-option
              v-for="operator in operatorRows"
              :key="operator.id"
              :label="`${operator.name} · ${operator.code}`"
              :value="operator.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="erpAccessDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="accessSaving" @click="saveErpAccess">保存授权</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.erp-access-form {
  margin-top: 18px;
}

.role-options {
  display: grid;
  gap: 12px;
}
</style>
