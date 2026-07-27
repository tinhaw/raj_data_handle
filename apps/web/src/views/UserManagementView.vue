<script setup lang="ts">
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { createUser, fetchUsers, updateUser } from '../api/auth'
import { apiErrorMessage } from '../api/client'
import type { UserRecord } from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const rows = ref<UserRecord[]>([])
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({
  username: '',
  displayName: '',
  password: '',
  role: 'user' as 'admin' | 'user',
  isActive: true,
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

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Account management</span>
        <h1>用户管理</h1>
        <p>管理员与普通用户拥有相同业务权限；管理员额外维护系统设置。</p>
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
        <el-table-column label="最后登录" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
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
  </div>
</template>
