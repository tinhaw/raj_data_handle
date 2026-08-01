<script setup lang="ts">
import { ArrowDown, ArrowUp, Connection, Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  clearSourceCredentials,
  createSource,
  deleteSource,
  fetchAllSources,
  reorderSources,
  testSourceConnection,
  updateSource,
} from '../api/sources'
import type { SourceConfig } from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const rows = ref<SourceConfig[]>([])
const reordering = ref(false)
const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const credentialsConfigured = ref(false)
const presetSourceIds = new Set(['rajwin', 'rajluck'])
const form = reactive({
  sourceId: '',
  displayName: '',
  baseUrl: '',
  businessTimezone: 'Asia/Kolkata',
  currency: 'INR',
  enabled: false,
  username: '',
  password: '',
  totpSecret: '',
})

async function load(): Promise<void> {
  loading.value = true
  try {
    rows.value = await fetchAllSources()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口配置加载失败。'))
  } finally {
    loading.value = false
  }
}

function add(): void {
  editingId.value = null
  credentialsConfigured.value = false
  form.sourceId = ''
  form.displayName = ''
  form.baseUrl = ''
  form.businessTimezone = 'Asia/Kolkata'
  form.currency = 'INR'
  form.enabled = false
  form.username = ''
  form.password = ''
  form.totpSecret = ''
  dialogVisible.value = true
}

function edit(row: SourceConfig): void {
  editingId.value = row.sourceId
  credentialsConfigured.value = row.credentialConfigured
  form.sourceId = row.sourceId
  form.displayName = row.displayName
  form.baseUrl = row.baseUrl || ''
  form.businessTimezone = row.businessTimezone
  form.currency = row.currency
  form.enabled = row.enabled
  form.username = ''
  form.password = ''
  form.totpSecret = ''
  dialogVisible.value = true
}

function validateForm(): boolean {
  if (
    editingId.value === null &&
    !/^[a-z][a-z0-9_-]{1,63}$/.test(form.sourceId.trim())
  ) {
    ElMessage.warning(
      '来源 ID 须为 2-64 位，以小写字母开头，且只能包含小写字母、数字、下划线和连字符。',
    )
    return false
  }
  return true
}

function sourcePayload(enabled: boolean): Record<string, unknown> {
  const credentials =
    form.username || form.password || form.totpSecret
      ? {
          username: form.username || null,
          password: form.password || null,
          totpSecret: form.totpSecret || null,
        }
      : undefined
  return {
    displayName: form.displayName,
    baseUrl: form.baseUrl || null,
    businessTimezone: form.businessTimezone,
    currency: form.currency,
    enabled,
    credentials,
  }
}

function credentialsWereProvided(): boolean {
  return Boolean(form.username || form.password || form.totpSecret)
}

async function persistSource(enabled: boolean): Promise<string> {
  if (editingId.value === null) {
    const sourceId = form.sourceId.trim()
    await createSource({
      sourceId,
      ...sourcePayload(false),
    })
    editingId.value = sourceId
    credentialsConfigured.value ||= credentialsWereProvided()
    return sourceId
  }
  await updateSource(editingId.value, sourcePayload(enabled))
  credentialsConfigured.value ||= credentialsWereProvided()
  return editingId.value
}

async function save(): Promise<void> {
  if (!validateForm()) return
  const wasCreating = editingId.value === null
  saving.value = true
  try {
    await persistSource(wasCreating ? false : form.enabled)
    ElMessage.success(wasCreating ? '盘口草稿已创建。' : '盘口配置已保存。')
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口配置保存失败。'))
  } finally {
    saving.value = false
  }
}

async function saveAndTest(): Promise<void> {
  if (!validateForm()) return
  const enableAfterPassed = form.enabled
  testing.value = true
  try {
    const sourceId = await persistSource(false)
    const result = await testSourceConnection(sourceId)
    if (result.status !== 'passed') {
      form.enabled = false
      ElMessage.warning(result.message)
      return
    }
    if (enableAfterPassed) {
      await updateSource(sourceId, { enabled: true })
    }
    ElMessage.success(
      enableAfterPassed ? '连接测试通过，盘口已启用。' : '连接测试通过，盘口草稿已保存。',
    )
    dialogVisible.value = false
  } catch (error) {
    ElMessage.warning(apiErrorMessage(error, '保存或连接测试失败。'))
  } finally {
    await load()
    testing.value = false
  }
}

async function remove(row: SourceConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将永久删除盘口“${row.displayName}”（${row.sourceId}）、本地加密凭据和渠道映射。该操作无法撤销。`,
      '删除盘口',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
    await deleteSource(row.sourceId)
    ElMessage.success('盘口已删除。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '盘口删除失败。'))
  }
}

async function clearCredentials(row: SourceConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '清除后盘口会自动停用，且无法恢复已保存的账号、密码和 TOTP Secret。',
      '清除远端凭据',
      { type: 'warning', confirmButtonText: '确认清除' },
    )
    await clearSourceCredentials(row.sourceId)
    ElMessage.success('凭据已清除，盘口已停用。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '清除凭据失败。'))
  }
}

async function moveSource(index: number, offset: -1 | 1): Promise<void> {
  const targetIndex = index + offset
  if (targetIndex < 0 || targetIndex >= rows.value.length || reordering.value) return
  const sourceIds = rows.value.map((row) => row.sourceId)
  const [movedSource] = sourceIds.splice(index, 1)
  if (!movedSource) return
  sourceIds.splice(targetIndex, 0, movedSource)
  reordering.value = true
  try {
    rows.value = await reorderSources(sourceIds)
    ElMessage.success('盘口展示顺序已保存。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口展示顺序保存失败。'))
  } finally {
    reordering.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Admin settings</span>
        <h1>盘口配置</h1>
        <p>集中维护远端盘口的连接地址、访问凭据、业务时区、启用状态与展示顺序。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="add">新增盘口</el-button>
      </div>
    </header>

    <el-alert
      title="凭据字段只写不读"
      description="页面只显示是否已配置；账号、密码和 TOTP Secret 加密保存，接口永不回显。连接测试只执行登录，并读取 pay_method 的 key/title 与 pay_channel_name 的 value/label 两套只读字典。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="rows">
        <el-table-column label="展示顺序" width="140" align="center">
          <template #default="{ $index }">
            <el-button-group>
              <el-button
                text
                :icon="ArrowUp"
                :disabled="$index === 0 || reordering"
                aria-label="上移盘口"
                @click="moveSource($index, -1)"
              />
              <el-button
                text
                :icon="ArrowDown"
                :disabled="$index === rows.length - 1 || reordering"
                aria-label="下移盘口"
                @click="moveSource($index, 1)"
              />
            </el-button-group>
            <span class="order-number">{{ $index + 1 }}</span>
          </template>
        </el-table-column>
        <el-table-column label="来源 ID" min-width="150">
          <template #default="{ row }">
            <span>{{ row.sourceId }}</span>
            <el-tag
              v-if="presetSourceIds.has(row.sourceId)"
              type="info"
              size="small"
              style="margin-left: 8px"
            >
              预设
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="盘口名" min-width="130" prop="displayName" />
        <el-table-column label="Base URL" min-width="230" prop="baseUrl" show-overflow-tooltip />
        <el-table-column label="时区 / 币种" min-width="180">
          <template #default="{ row }">{{ row.businessTimezone }} · {{ row.currency }}</template>
        </el-table-column>
        <el-table-column label="凭据" width="110">
          <template #default="{ row }">
            <el-tag :type="row.credentialConfigured ? 'success' : 'info'">
              {{ row.credentialConfigured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接测试" min-width="160">
          <template #default="{ row }">
            <span>{{ row.lastTestStatus || '未测试' }}</span>
            <small class="table-subtext">{{ formatDateTime(row.lastTestedAt) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">
              {{ row.enabled ? '已启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" :icon="Edit" @click="edit(row)">编辑</el-button>
            <el-button
              v-if="row.credentialConfigured"
              text
              type="danger"
              :icon="Delete"
              @click="clearCredentials(row)"
            >
              清除凭据
            </el-button>
            <el-tooltip :content="row.enabled ? '请先停用盘口再删除' : '永久删除盘口'">
              <span>
                <el-button
                  text
                  type="danger"
                  :icon="Delete"
                  :disabled="row.enabled"
                  @click="remove(row)"
                >
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新增盘口' : `编辑 ${editingId}`"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item v-if="editingId === null" label="来源 ID">
          <el-input v-model="form.sourceId" placeholder="例如 rajstar" maxlength="64" />
          <span class="field-help">
            创建后不可修改；使用小写字母、数字、下划线或连字符。
          </span>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="盘口显示名">
            <el-input v-model="form.displayName" />
          </el-form-item>
          <el-form-item label="业务时区">
            <el-input v-model="form.businessTimezone" />
          </el-form-item>
          <el-form-item label="币种">
            <el-input v-model="form.currency" maxlength="3" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="form.enabled" />
            <span class="field-help">
              选择启用时，请使用“保存并测试”；连接通过后会自动启用。
            </span>
          </el-form-item>
        </div>
        <el-form-item label="Base URL">
          <el-input v-model="form.baseUrl" placeholder="https://admin.example.com" />
        </el-form-item>
        <el-divider content-position="left">
          {{
            credentialsConfigured
              ? '远端凭据（已设置；留空则保持原值）'
              : '远端凭据（首次配置需填写账号、密码和 TOTP Secret）'
          }}
        </el-divider>
        <div class="form-grid">
          <el-form-item label="登录账号">
            <el-input
              v-model="form.username"
              :placeholder="credentialsConfigured ? '已设置，留空则保持原值' : '请输入登录账号'"
              autocomplete="off"
            />
          </el-form-item>
          <el-form-item label="登录密码">
            <el-input
              v-model="form.password"
              :placeholder="credentialsConfigured ? '已设置，留空则保持原值' : '请输入登录密码'"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
        </div>
        <el-form-item label="TOTP Secret">
          <el-input
            v-model="form.totpSecret"
            :placeholder="credentialsConfigured ? '已设置，留空则保持原值' : '请输入 TOTP Secret'"
            type="password"
            show-password
            autocomplete="off"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button :loading="saving" :disabled="testing" @click="save">
          {{ editingId === null ? '创建草稿' : '保存配置' }}
        </el-button>
        <el-button
          type="primary"
          :icon="Connection"
          :loading="testing"
          :disabled="saving"
          @click="saveAndTest"
        >
          保存并测试
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.field-help {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.5;
}
</style>
