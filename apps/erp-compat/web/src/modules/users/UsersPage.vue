<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { CircleCheck, EditPen, Key, Lock, Plus, Refresh, UserFilled, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import type { CreateUserInput, ManagedUser, Operator, Role } from '@/api/types'
import StatusTag from '@/components/StatusTag.vue'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const users = ref<ManagedUser[]>([])
const roles = ref<Role[]>([])
const operators = ref<Operator[]>([])
const keyword = ref('')
const status = ref<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')
const userDialog = ref(false)
const rolesDialog = ref(false)
const scopesDialog = ref(false)
const editingUser = ref<ManagedUser | null>(null)
const selectedRolesUser = ref<ManagedUser | null>(null)
const selectedScopesUser = ref<ManagedUser | null>(null)
const selectedRoleCodes = ref<string[]>([])

const userForm = reactive({
  username: '',
  password: '',
  displayName: '',
  enabled: true,
  roleCodes: [] as string[],
  allOperators: false,
  operatorIds: [] as Array<string | number>,
})

const scopeForm = reactive({
  allOperators: false,
  operatorIds: [] as Array<string | number>,
})

const canManageUsers = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('USER_MANAGE') || user?.roles.includes('SUPER_ADMIN'))
})
const activeOperators = computed(() => operators.value.filter((operator) => operator.status === 'ACTIVE'))
const currentUserId = computed(() => String(session.user?.id ?? ''))
const scopeLockedBySuperAdmin = computed(() => selectedScopesUser.value?.roles.includes('SUPER_ADMIN') ?? false)
const operatorNameById = computed(() => new Map(operators.value.map((operator) => [String(operator.id), operator.name])))

const filteredUsers = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return users.value.filter((user) => {
    const statusMatches = status.value === 'ALL' || (status.value === 'ACTIVE' ? user.enabled : !user.enabled)
    const queryMatches = !query || [user.username, user.displayName, ...user.roles]
      .some((value) => value.toLowerCase().includes(query))
    return statusMatches && queryMatches
  })
})

function roleName(code: string) {
  return roles.value.find((role) => role.code === code)?.name || code
}

function scopeLabel(user: ManagedUser) {
  if (user.allOperators || user.roles.includes('SUPER_ADMIN')) return '全部投放公司'
  const names = (user.operatorIds || []).map((id) => operatorNameById.value.get(String(id)) || `投放公司 #${id}`)
  return names.length ? names.join('、') : '未授予投放公司'
}

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function defaultRoleCodes() {
  return roles.value.some((role) => role.code === 'DATA_ENTRY') ? ['DATA_ENTRY'] : []
}

function resetUserForm() {
  Object.assign(userForm, {
    username: '', password: '', displayName: '', enabled: true,
    roleCodes: defaultRoleCodes(), allOperators: false, operatorIds: [],
  })
}

function replaceUser(updated: ManagedUser) {
  users.value = users.value.map((user) => user.id === updated.id ? updated : user)
  if (editingUser.value?.id === updated.id) editingUser.value = updated
  if (selectedRolesUser.value?.id === updated.id) selectedRolesUser.value = updated
  if (selectedScopesUser.value?.id === updated.id) selectedScopesUser.value = updated
}

async function load() {
  if (!canManageUsers.value) return
  loading.value = true
  loadError.value = ''
  try {
    const [loadedUsers, loadedRoles, loadedOperators] = await Promise.all([
      api.users.list(),
      api.roles.list(),
      api.operators.list(),
    ])
    users.value = loadedUsers
    roles.value = loadedRoles
    operators.value = loadedOperators
  } catch (error) {
    users.value = []
    roles.value = []
    operators.value = []
    loadError.value = error instanceof Error ? error.message : '无法加载用户与权限数据，请稍后重试。'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingUser.value = null
  resetUserForm()
  userDialog.value = true
}

function openEdit(user: ManagedUser) {
  editingUser.value = user
  Object.assign(userForm, {
    username: user.username,
    password: '',
    displayName: user.displayName,
    enabled: user.enabled,
    roleCodes: [...user.roles],
    allOperators: user.allOperators || user.roles.includes('SUPER_ADMIN'),
    operatorIds: [...(user.operatorIds || [])],
  })
  userDialog.value = true
}

async function saveUser() {
  const isEdit = Boolean(editingUser.value)
  if (!userForm.displayName.trim()) {
    ElMessage.warning('请填写员工姓名或显示名称')
    return
  }
  if (!isEdit && !userForm.username.trim()) {
    ElMessage.warning('请填写登录用户名')
    return
  }
  if (!isEdit && userForm.password.length < 8) {
    ElMessage.warning('初始密码至少需要 8 位')
    return
  }
  if (!isEdit && !userForm.roleCodes.length) {
    ElMessage.warning('请至少选择一个角色')
    return
  }

  saving.value = true
  try {
    if (editingUser.value) {
      const updated = await api.users.update(editingUser.value.id, {
        displayName: userForm.displayName.trim(),
        enabled: userForm.enabled,
        rowVersion: editingUser.value.rowVersion,
      })
      replaceUser(updated)
      ElMessage.success('用户信息已更新')
    } else {
      const input: CreateUserInput = {
        username: userForm.username.trim(),
        password: userForm.password,
        displayName: userForm.displayName.trim(),
        enabled: userForm.enabled,
        roleCodes: [...userForm.roleCodes],
        allOperators: userForm.allOperators,
        operatorIds: userForm.allOperators ? [] : [...userForm.operatorIds],
      }
      const created = await api.users.create(input)
      users.value = [created, ...users.value]
      ElMessage.success('员工账号已创建；该员工首次登录后需要修改初始密码')
    }
    userDialog.value = false
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存用户失败')
  } finally {
    saving.value = false
  }
}

function openRoles(user: ManagedUser) {
  selectedRolesUser.value = user
  selectedRoleCodes.value = [...user.roles]
  rolesDialog.value = true
}

async function saveRoles() {
  const user = selectedRolesUser.value
  if (!user) return
  if (!selectedRoleCodes.value.length) {
    ElMessage.warning('请至少保留一个角色')
    return
  }
  if (String(user.id) === currentUserId.value && !selectedRoleCodes.value.includes('SUPER_ADMIN') && user.roles.includes('SUPER_ADMIN')) {
    try {
      await ElMessageBox.confirm('移除自己的超级管理员角色可能会失去本页访问权限。是否继续？', '确认修改自身权限', { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' })
    } catch {
      return
    }
  }
  saving.value = true
  try {
    const updated = await api.users.assignRoles(user.id, [...selectedRoleCodes.value])
    replaceUser(updated)
    rolesDialog.value = false
    ElMessage.success('角色已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新角色失败')
  } finally {
    saving.value = false
  }
}

function openScopes(user: ManagedUser) {
  selectedScopesUser.value = user
  Object.assign(scopeForm, {
    allOperators: user.allOperators || user.roles.includes('SUPER_ADMIN'),
    operatorIds: [...(user.operatorIds || [])],
  })
  scopesDialog.value = true
}

async function saveScopes() {
  const user = selectedScopesUser.value
  if (!user) return
  const allOperators = scopeLockedBySuperAdmin.value || scopeForm.allOperators
  saving.value = true
  try {
    const updated = await api.users.assignOperatorScopes(user.id, allOperators, allOperators ? [] : [...scopeForm.operatorIds])
    replaceUser(updated)
    scopesDialog.value = false
    ElMessage.success('投放公司数据范围已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新数据范围失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(user: ManagedUser) {
  if (String(user.id) === currentUserId.value) {
    ElMessage.warning('为避免当前管理员失去登录权限，不能在此停用自己的账号')
    return
  }
  const nextEnabled = !user.enabled
  try {
    await ElMessageBox.confirm(
      nextEnabled ? `确定重新启用“${user.displayName}”的账号吗？` : `停用“${user.displayName}”后，该员工将无法登录。是否继续？`,
      nextEnabled ? '启用用户' : '停用用户',
      { type: 'warning', confirmButtonText: nextEnabled ? '启用' : '停用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  saving.value = true
  try {
    const updated = await api.users.update(user.id, { enabled: nextEnabled, rowVersion: user.rowVersion })
    replaceUser(updated)
    ElMessage.success(nextEnabled ? '用户已启用' : '用户已停用')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新用户状态失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => { void load() })
</script>

<template>
  <section>
    <div class="page-title-row">
      <div>
        <h2>用户与权限</h2>
        <p class="page-subtitle">通过角色权限和投放公司数据范围控制员工能够查看、录入、确认和导出的数据。</p>
      </div>
      <div v-if="canManageUsers" class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      </div>
    </div>

    <template v-if="!canManageUsers">
      <div class="empty-panel access-denied">
        <div>
          <el-icon class="empty-icon"><Lock /></el-icon>
          <h3>无用户管理权限</h3>
          <p>此功能需要 <code>USER_MANAGE</code> 权限。请联系超级管理员为你的账号分配相应角色。</p>
        </div>
      </div>
    </template>

    <template v-else>
      <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>

      <article class="panel panel--padded permission-summary">
        <div class="permission-card"><el-icon><UserFilled /></el-icon><div><strong>角色决定功能权限</strong><p>角色包含可查看、录入、确认、导入、报表、审计及系统管理等功能权限；一个员工可拥有多个角色。</p></div></div>
        <div class="permission-card"><el-icon><Lock /></el-icon><div><strong>数据范围决定可见投放公司</strong><p>除功能权限外，每个员工还需被授予全部投放公司或指定投放公司的可访问数据范围。</p></div></div>
      </article>

      <article class="panel panel--padded">
        <div class="filter-bar">
          <el-form-item label="搜索用户"><el-input v-model="keyword" clearable placeholder="用户名、姓名或角色" style="width: 280px" /></el-form-item>
          <el-form-item label="状态"><el-select v-model="status" style="width: 130px"><el-option label="全部" value="ALL" /><el-option label="已启用" value="ACTIVE" /><el-option label="已停用" value="INACTIVE" /></el-select></el-form-item>
          <span class="hint">共 {{ users.length }} 位员工，当前显示 {{ filteredUsers.length }} 位</span>
        </div>
      </article>

      <article class="panel table-card">
        <el-table v-loading="loading" :data="filteredUsers" row-key="id" empty-text="暂无用户记录">
          <el-table-column label="员工" min-width="210">
            <template #default="{ row }"><div class="user-name"><strong>{{ row.displayName }}</strong><span>{{ row.username }}</span></div></template>
          </el-table-column>
          <el-table-column label="角色" min-width="205">
            <template #default="{ row }"><div class="role-tags"><el-tag v-for="code in row.roles" :key="code" size="small" effect="plain" :title="code">{{ roleName(code) }}</el-tag><span v-if="!row.roles.length" class="muted">未分配角色</span></div></template>
          </el-table-column>
          <el-table-column label="投放公司数据范围" min-width="220" show-overflow-tooltip><template #default="{ row }"><span :class="{ 'scope-all': row.allOperators || row.roles.includes('SUPER_ADMIN') }">{{ scopeLabel(row) }}</span></template></el-table-column>
          <el-table-column label="状态" width="96" align="center"><template #default="{ row }"><StatusTag :status="row.enabled ? 'ACTIVE' : 'INACTIVE'" /></template></el-table-column>
          <el-table-column label="密码" width="116" align="center"><template #default="{ row }"><el-tag v-if="row.mustChangePassword" size="small" type="warning" effect="light">首次需修改</el-tag><span v-else class="muted">已设置</span></template></el-table-column>
          <el-table-column label="创建时间" width="166"><template #default="{ row }"><span class="muted">{{ formatTime(row.createdAt) }}</span></template></el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :icon="EditPen" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" :icon="Key" @click="openRoles(row)">角色</el-button>
              <el-button link type="primary" @click="openScopes(row)">范围</el-button>
              <el-button link :type="row.enabled ? 'danger' : 'success'" :icon="row.enabled ? WarningFilled : CircleCheck" :disabled="String(row.id) === currentUserId" @click="toggleEnabled(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </article>
    </template>

    <el-dialog v-model="userDialog" :title="editingUser ? '编辑用户' : '新建用户'" width="650px" destroy-on-close>
      <el-form label-position="top" @submit.prevent="saveUser">
        <el-alert v-if="editingUser" type="info" :closable="false" show-icon>用户名不可修改。角色与投放公司数据范围请使用列表中的“角色”和“范围”操作独立维护。</el-alert>
        <div class="form-grid">
          <el-form-item label="员工姓名 / 显示名称" required><el-input v-model="userForm.displayName" maxlength="120" placeholder="如 张三" /></el-form-item>
          <el-form-item label="账号状态"><el-switch v-model="userForm.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
        </div>
        <template v-if="!editingUser">
          <div class="form-grid">
            <el-form-item label="登录用户名" required><el-input v-model="userForm.username" maxlength="80" autocomplete="off" placeholder="英文、数字或公司账号" /></el-form-item>
            <el-form-item label="初始密码" required><el-input v-model="userForm.password" type="password" show-password minlength="8" autocomplete="new-password" placeholder="至少 8 位" /></el-form-item>
          </div>
          <el-divider content-position="left">初始角色与数据范围</el-divider>
          <el-form-item label="角色" required><el-select v-model="userForm.roleCodes" multiple collapse-tags collapse-tags-tooltip placeholder="选择角色" style="width: 100%"><el-option v-for="role in roles" :key="role.code" :label="`${role.name}（${role.code}）`" :value="role.code"><div class="role-select-option"><strong>{{ role.name }}</strong><span>{{ role.description || role.code }}</span></div></el-option></el-select></el-form-item>
          <el-form-item label="投放公司数据范围"><el-radio-group v-model="userForm.allOperators"><el-radio :value="true">全部投放公司</el-radio><el-radio :value="false">指定投放公司</el-radio></el-radio-group><p class="field-note">选择“指定投放公司”但不选择任何对象时，该员工暂时没有任何投放公司数据权限。</p></el-form-item>
          <el-form-item v-if="!userForm.allOperators" label="可访问的投放公司"><el-select v-model="userForm.operatorIds" multiple filterable clearable placeholder="选择一个或多个投放公司" style="width: 100%"><el-option v-for="operator in activeOperators" :key="operator.id" :label="operator.name" :value="operator.id" /></el-select></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="userDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveUser">{{ editingUser ? '保存修改' : '创建用户' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="rolesDialog" :title="`分配角色 · ${selectedRolesUser?.displayName || ''}`" width="670px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon>至少保留一个角色。角色定义功能权限；投放公司数据范围需在“范围”操作中单独设置。</el-alert>
      <el-checkbox-group v-model="selectedRoleCodes" class="user-role-grid">
        <el-checkbox v-for="role in roles" :key="role.code" :value="role.code" border class="role-option">
          <strong>{{ role.name }}</strong><span>{{ role.description || role.code }}</span><small>{{ role.permissions.join(' · ') || '无权限' }}</small>
        </el-checkbox>
      </el-checkbox-group>
      <template #footer><el-button @click="rolesDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveRoles">保存角色</el-button></template>
    </el-dialog>

    <el-dialog v-model="scopesDialog" :title="`投放公司数据范围 · ${selectedScopesUser?.displayName || ''}`" width="610px" destroy-on-close>
      <el-alert v-if="scopeLockedBySuperAdmin" type="warning" :closable="false" show-icon>超级管理员始终拥有全部投放公司数据范围。如需收窄范围，请先移除超级管理员角色。</el-alert>
      <el-form class="scope-form" label-position="top">
        <el-form-item label="数据范围"><el-radio-group v-model="scopeForm.allOperators" :disabled="scopeLockedBySuperAdmin"><el-radio :value="true">全部投放公司</el-radio><el-radio :value="false">指定投放公司</el-radio></el-radio-group></el-form-item>
        <el-form-item v-if="!scopeForm.allOperators && !scopeLockedBySuperAdmin" label="允许访问的投放公司"><el-select v-model="scopeForm.operatorIds" multiple filterable clearable placeholder="选择一个或多个投放公司" style="width: 100%"><el-option v-for="operator in activeOperators" :key="operator.id" :label="operator.name" :value="operator.id" /></el-select><p class="field-note">不选择任何投放公司会使该员工没有投放公司数据访问权限，但不会改变其功能角色。</p></el-form-item>
      </el-form>
      <template #footer><el-button @click="scopesDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveScopes">保存范围</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.load-error { margin-bottom: 16px; }
.permission-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.permission-card { display: flex; gap: 12px; padding: 15px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 8px; }
.permission-card .el-icon { display: grid; place-items: center; flex: 0 0 auto; width: 32px; height: 32px; color: #155eef; font-size: 18px; background: #eff4ff; border-radius: 8px; }
.permission-card strong { color: #344054; font-size: 14px; }
.permission-card p { margin: 5px 0 0; color: #667085; font-size: 12px; line-height: 1.6; }
.user-name { display: grid; gap: 3px; }
.user-name strong { color: #182230; font-weight: 650; }
.user-name span { color: #98a2b3; font-size: 12px; }
.role-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.scope-all { color: #027a48; font-weight: 600; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.role-select-option { display: grid; gap: 2px; padding: 3px 0; }
.role-select-option strong { color: #344054; }
.role-select-option span { color: #98a2b3; font-size: 12px; }
.user-role-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 18px; }
.role-option { display: grid; align-content: start; height: auto; min-height: 96px; margin: 0; padding: 13px 14px; white-space: normal; }
.role-option :deep(.el-checkbox__label) { display: grid; gap: 4px; min-width: 0; padding-left: 9px; white-space: normal; }
.role-option strong { color: #344054; font-size: 13px; }
.role-option span { color: #667085; font-size: 12px; line-height: 1.45; }
.role-option small { color: #98a2b3; font-size: 10px; line-height: 1.4; }
.scope-form { margin-top: 18px; }
.empty-icon { margin-bottom: 9px; color: #98a2b3; font-size: 36px; }
.access-denied h3 { margin: 4px 0; color: #344054; }
.access-denied p { max-width: 510px; margin: 0; line-height: 1.7; }
.access-denied code { padding: 1px 4px; color: #6941c6; background: #f4f3ff; border-radius: 4px; }
@media (max-width: 1280px) { .user-role-grid { grid-template-columns: 1fr; } }
</style>
