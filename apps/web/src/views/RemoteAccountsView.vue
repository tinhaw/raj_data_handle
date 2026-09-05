<script setup lang="ts">
import { Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  createRemoteAccount,
  deleteLegacyRemoteAccount,
  fetchRemoteTagSnapshot,
  fetchRewardTierPreset,
  fetchRemoteAccounts,
  updateRemoteAccount,
  saveRemoteTagSnapshot,
  saveRewardTierPreset,
  operateAccountConnection,
  saveAccountSessionPolicy,
} from '../api/remoteAccounts'
import { fetchAllSources } from '../api/sources'
import { apiErrorMessage } from '../api/client'
import type {
  RemoteAccount,
  RemoteTag,
  RewardTierPresetTier,
  SourceConfig,
} from '../types'
import { hasErpPermission } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const accounts = ref<RemoteAccount[]>([])
const sources = ref<SourceConfig[]>([])
const accountDialogVisible = ref(false)
const presetDialogVisible = ref(false)
const editingAccount = ref<RemoteAccount | null>(null)
const connectionBusy = reactive<Record<string, string>>({})
const policyAccount = ref<RemoteAccount | null>(null)
const policyVisible = ref(false)
const policySaving = ref(false)
const policyForm = reactive({ autoRelogin: true, periodic: false, intervalHours: 1 })
const clockNow = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | undefined
const presetAccount = ref<RemoteAccount | null>(null)
const presetTags = ref<RemoteTag[]>([])
const presetTiers = ref<RewardTierPresetTier[]>([])
const accountForm = reactive({
  sourceId: '',
  loginUsername: '',
  displayName: '',
  password: '',
  totpSecret: '',
  enabled: true,
  isDefault: false,
})

const selectedSource = computed(
  () => sources.value.find((source) => source.sourceId === accountForm.sourceId) || null,
)
const isLegacyAccount = computed(
  () => editingAccount.value?.credentialMode === 'LEGACY_SOURCE',
)

async function load(): Promise<void> {
  loading.value = true
  try {
    const canManage = hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')
    const [nextSources, nextAccounts] = await Promise.all([
      canManage ? fetchAllSources() : Promise.resolve([]),
      fetchRemoteAccounts(),
    ])
    sources.value = nextSources
    accounts.value = nextAccounts
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端账号加载失败。'))
  } finally {
    loading.value = false
  }
}

function resetAccountForm(): void {
  editingAccount.value = null
  accountForm.sourceId = ''
  accountForm.loginUsername = ''
  accountForm.displayName = ''
  accountForm.password = ''
  accountForm.totpSecret = ''
  accountForm.enabled = true
  accountForm.isDefault = false
}

function displayTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function coolingDown(account: RemoteAccount): boolean {
  return Boolean(account.loginRetryAfter && new Date(account.loginRetryAfter).getTime() > clockNow.value)
}

function sessionLabel(account: RemoteAccount): string {
  if (!account.enabled || !account.sourceEnabled) return '已停用'
  if (coolingDown(account)) return '登录冷却中'
  if (account.hasActiveSession && account.sessionExpiresAt
      && new Date(account.sessionExpiresAt).getTime() > clockNow.value) return '会话可用'
  if (account.sessionLastError) return '连接异常'
  return account.lastLoggedInAt ? '会话已过期' : '尚未连接'
}

function reloginIntervalLabel(intervalHours: number | null): string {
  if (intervalHours === null) return '关闭'
  return `每 ${Number(intervalHours.toFixed(2))} 小时`
}

async function runConnection(account: RemoteAccount, operation: 'CHECK' | 'RELOGIN'): Promise<void> {
  if (connectionBusy[account.id] || coolingDown(account)) return
  try {
    await ElMessageBox.confirm(
      operation === 'CHECK'
        ? '将访问远端检查兑换码配置读取权限；会话不可用时按自动重登设置登录，不会创建或发布兑换码。'
        : '将重新登录远端并更新统一会话，可能使旧会话失效。不会重试失败的兑换码任务。',
      operation === 'CHECK' ? '检测连接' : '重新登录',
      { confirmButtonText: '确认执行', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  connectionBusy[account.id] = operation
  try {
    await operateAccountConnection(account.id, operation)
    ElMessage.success(operation === 'CHECK' ? '连接正常，已验证配置读取权限。' : '重新登录成功，会话已更新。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端连接操作失败。'))
  } finally {
    delete connectionBusy[account.id]
    await load()
  }
}

function openSessionPolicy(account: RemoteAccount): void {
  policyAccount.value = account
  policyForm.autoRelogin = account.autoRelogin
  policyForm.periodic = account.reloginIntervalHours !== null
  policyForm.intervalHours = Math.max(1, Math.ceil(account.reloginIntervalHours || 1))
  policyVisible.value = true
}

async function saveSessionPolicy(): Promise<void> {
  if (!policyAccount.value) return
  if (policyForm.periodic && (!Number.isInteger(policyForm.intervalHours)
      || policyForm.intervalHours < 1 || policyForm.intervalHours > 168)) {
    ElMessage.warning('重登间隔必须为 1～168 小时的整数。')
    return
  }
  policySaving.value = true
  try {
    await saveAccountSessionPolicy(policyAccount.value.id, {
      autoRelogin: policyForm.autoRelogin,
      reloginIntervalHours: policyForm.periodic ? policyForm.intervalHours : null,
      executionConfirmed: policyForm.periodic,
    })
    policyVisible.value = false
    ElMessage.success('登录设置已保存；本次保存不会立即连接远端。')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '登录设置保存失败。'))
  } finally { policySaving.value = false }
}

function openCreateAccount(): void {
  if (!sources.value.length) {
    ElMessage.warning('请先创建盘口，再为盘口配置远端账号。')
    void router.push('/settings/sources')
    return
  }
  resetAccountForm()
  const requestedSourceId = String(route.query.sourceId || '')
  accountForm.sourceId = sources.value.some((source) => source.sourceId === requestedSourceId)
    ? requestedSourceId
    : sources.value[0]?.sourceId || ''
  accountForm.isDefault = !accounts.value.some(
    (account) => account.sourceId === accountForm.sourceId && account.isDefault,
  )
  accountDialogVisible.value = true
}

function openEditAccount(account: RemoteAccount): void {
  editingAccount.value = account
  accountForm.sourceId = account.sourceId
  accountForm.loginUsername = account.loginUsername || ''
  accountForm.displayName = account.displayName
  accountForm.password = ''
  accountForm.totpSecret = ''
  accountForm.enabled = account.enabled
  accountForm.isDefault = account.isDefault
  accountDialogVisible.value = true
}

function selectSource(sourceId: string): void {
  if (editingAccount.value) return
  accountForm.isDefault = !accounts.value.some(
    (account) => account.sourceId === sourceId && account.isDefault,
  )
}

function validateAccount(): boolean {
  if (!accountForm.displayName.trim()) {
    ElMessage.warning('请填写远端账号显示名称。')
    return false
  }
  if (!accountForm.sourceId || !accountForm.loginUsername.trim()) {
    ElMessage.warning('请选择所属盘口，并填写远端登录账号。')
    return false
  }
  if (
    (!editingAccount.value || isLegacyAccount.value) &&
    (!accountForm.password || !accountForm.totpSecret.trim())
  ) {
    ElMessage.warning('请同时填写密码和 TOTP Secret。')
    return false
  }
  return true
}

async function saveAccount(): Promise<void> {
  if (!validateAccount()) return
  saving.value = true
  try {
    if (editingAccount.value) {
      const payload: {
        displayName?: string
        enabled?: boolean
        isDefault?: boolean
        loginUsername?: string
        credentials?: { password?: string; totpSecret?: string }
      } = {
        displayName: accountForm.displayName.trim(),
        enabled: accountForm.enabled,
      }
      if (accountForm.loginUsername.trim()) {
        payload.loginUsername = accountForm.loginUsername.trim()
      }
      if (accountForm.password || accountForm.totpSecret.trim()) {
        payload.credentials = {
          password: accountForm.password || undefined,
          totpSecret: accountForm.totpSecret.trim() || undefined,
        }
      }
      if (accountForm.isDefault && !editingAccount.value.isDefault) {
        payload.isDefault = true
      }
      await updateRemoteAccount(editingAccount.value.id, payload)
      ElMessage.success('远端账号已更新。')
    } else {
      await createRemoteAccount({
        sourceId: accountForm.sourceId,
        loginUsername: accountForm.loginUsername.trim(),
        displayName: accountForm.displayName.trim(),
        enabled: accountForm.enabled,
        isDefault: accountForm.isDefault,
        credentials: {
          password: accountForm.password,
          totpSecret: accountForm.totpSecret.trim(),
        },
      })
      ElMessage.success('远端账号已创建，并已获得该盘口的全部功能。需要时请在盘口配置中启用盘口。')
    }
    accountDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端账号保存失败。'))
  } finally {
    saving.value = false
  }
}

async function removeLegacyAccount(account: RemoteAccount): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${account.sourceDisplayName} 的“${account.displayName}”吗？系统会先校验当前默认账号、全部功能及标签/档位配置。`,
      '删除历史账号',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    await deleteLegacyRemoteAccount(account.id)
    ElMessage.success('历史账号已删除，当前默认账号继续承担分析与 ERP 功能。')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '历史账号删除失败。'))
  } finally {
    saving.value = false
  }
}

async function openPreset(account: RemoteAccount): Promise<void> {
  saving.value = true
  try {
    const [snapshot, preset] = await Promise.all([
      fetchRemoteTagSnapshot(account.id),
      fetchRewardTierPreset(account.id),
    ])
    presetAccount.value = account
    presetTags.value = snapshot.tags.map((tag) => ({ ...tag }))
    presetTiers.value = preset.tiers.map((tier) => ({ ...tier, labelIds: [...tier.labelIds] }))
    presetDialogVisible.value = true
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '标签与兑换档位加载失败。'))
  } finally {
    saving.value = false
  }
}

function addTag(): void {
  presetTags.value.push({ id: 1, name: '' })
}

function addTier(): void {
  presetTiers.value.push({
    labelIds: [],
    displayName: '',
    minDepositAmount: '0',
    bonusAmount: '0',
    bonusMaxAmount: '0',
  })
}

async function savePreset(): Promise<void> {
  if (!presetAccount.value) return
  const tags = presetTags.value.filter((tag) => tag.id > 0 && tag.name.trim())
  if (!tags.length || !presetTiers.value.length) {
    ElMessage.warning('至少配置一个标签和一个兑换档位。')
    return
  }
  saving.value = true
  try {
    await saveRemoteTagSnapshot(presetAccount.value.id, tags)
    await saveRewardTierPreset(presetAccount.value.id, presetTiers.value, tags)
    ElMessage.success('标签快照与兑换档位已保存。')
    presetDialogVisible.value = false
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '标签与兑换档位保存失败。'))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  clockTimer = setInterval(() => { clockNow.value = Date.now() }, 1000)
  await load()
  if (route.query.create === '1' && hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')) {
    openCreateAccount()
  }
})
onUnmounted(() => { if (clockTimer) clearInterval(clockTimer) })
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Unified remote accounts</span>
        <h1>远端账号</h1>
        <p>账号创建时选择所属盘口；启用后可处理该盘口的数据分析、ERP 和其他远端功能。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" @click="router.push('/settings/sources')">管理盘口</el-button>
        <el-button v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" type="primary" :icon="Plus" @click="openCreateAccount">新建账号</el-button>
      </div>
    </header>

    <el-alert
      title="配置顺序：先配置盘口，再创建账号"
      description="每个盘口可配置多个账号；自动同步和后台任务使用唯一的默认账号，其他启用账号可作为备用或由业务任务明确选择。所有账号固定具备完整功能，无需逐项授权。"
      type="info"
      show-icon
      :closable="false"
    />

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="accounts" row-key="id">
        <el-table-column label="盘口" min-width="160">
          <template #default="{ row }">
            <strong>{{ row.sourceDisplayName }}</strong>
            <small class="table-subtext">{{ row.sourceId }}</small>
          </template>
        </el-table-column>
        <el-table-column label="远端账号" min-width="170">
          <template #default="{ row }">
            <strong>{{ row.loginUsername || row.displayName }}</strong>
            <small class="table-subtext">{{ row.displayName }}</small>
            <el-tag v-if="row.credentialMode === 'LEGACY_SOURCE'" type="info" size="small">
              待重新配置
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="用途" width="130" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.isDefault" type="primary">默认账号</el-tag>
            <span v-else class="muted">备用 / 指定</span>
          </template>
        </el-table-column>
        <el-table-column label="凭据" width="115" align="center">
          <template #default="{ row }">
            <el-tag :type="row.credentialConfigured ? 'success' : 'info'">
              {{ row.credentialConfigured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="功能" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.credentialConfigured ? 'success' : 'info'" effect="plain">
              {{ row.credentialConfigured ? '全部功能' : '配置后启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="115" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled && row.sourceEnabled ? 'success' : 'info'">
              {{ row.enabled && row.sourceEnabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接 / 登录会话" min-width="250">
          <template #default="{ row }">
            <el-tag :type="sessionLabel(row) === '会话可用' ? 'success' : 'info'">{{ sessionLabel(row) }}</el-tag>
            <small class="table-subtext">最近登录：{{ displayTime(row.lastLoggedInAt) }}</small>
            <small class="table-subtext">{{ row.sessionExpiryEstimated ? '缓存有效至（估计）' : '会话有效至' }}：{{ displayTime(row.sessionExpiresAt) }}</small>
            <small class="table-subtext">最近检测：{{ displayTime(row.lastTestedAt) }}{{ row.lastTestStatus ? (row.lastTestStatus === 'SUCCESS' ? ' · 正常' : ' · 失败') : '' }}</small>
            <small v-if="row.sessionLastError" class="connection-error">{{ row.sessionLastError }}</small>
            <small v-if="coolingDown(row)" class="table-subtext">可重试时间：{{ displayTime(row.loginRetryAfter) }}</small>
          </template>
        </el-table-column>
        <el-table-column label="自动登录策略" min-width="200">
          <template #default="{ row }">
            <div>过期重登：{{ row.autoRelogin ? '开启（按需）' : '关闭' }}</div>
            <small class="table-subtext">定时重登：{{ reloginIntervalLabel(row.reloginIntervalHours) }}</small>
            <small v-if="row.nextReloginAt" class="table-subtext">下次计划：{{ displayTime(row.nextReloginAt) }}</small>
          </template>
        </el-table-column>
        <el-table-column v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <div class="account-actions">
              <el-button text type="primary" :loading="connectionBusy[row.id] === 'CHECK'"
                :disabled="Boolean(connectionBusy[row.id]) || coolingDown(row) || !row.enabled || !row.sourceEnabled || !row.credentialConfigured"
                @click="runConnection(row, 'CHECK')">检测连接</el-button>
              <el-button text type="primary" :loading="connectionBusy[row.id] === 'RELOGIN'"
                :disabled="Boolean(connectionBusy[row.id]) || coolingDown(row) || !row.enabled || !row.sourceEnabled || !row.credentialConfigured"
                @click="runConnection(row, 'RELOGIN')">重新登录</el-button>
              <el-button text type="primary" @click="openSessionPolicy(row)">登录设置</el-button>
              <el-button text type="primary" :icon="Edit" @click="openEditAccount(row)">
                配置账号
              </el-button>
              <el-button text type="primary" @click="openPreset(row)">标签/档位</el-button>
              <el-button
                v-if="row.credentialMode === 'LEGACY_SOURCE'"
                text
                type="danger"
                :icon="Delete"
                :loading="saving"
                @click="removeLegacyAccount(row)"
              >
                删除历史账号
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="policyVisible" title="自动登录设置" width="580px">
      <p v-if="policyAccount">{{ policyAccount.sourceDisplayName }} · {{ policyAccount.loginUsername }}</p>
      <el-form label-position="top" class="session-policy-form">
        <el-form-item label="会话过期后自动重新登录">
          <el-switch v-model="policyForm.autoRelogin" />
          <span class="field-help">业务请求发现会话过期时重新登录；明确的登录失效响应最多重登并重试一次。关闭后需手动重新登录。</span>
        </el-form-item>
        <el-form-item label="按指定时间间隔重新登录">
          <el-switch v-model="policyForm.periodic" />
          <span class="field-help">由后台执行，关闭页面仍生效。默认关闭；开启会增加远端登录次数。</span>
        </el-form-item>
        <el-form-item v-if="policyForm.periodic" label="重登间隔（小时）">
          <el-input-number v-model="policyForm.intervalHours" :min="1" :max="168" :precision="0" />
          <span class="field-help">1～168 小时。首次在保存间隔后执行；此后从最近成功登录计算。登录失败会进入冷却。</span>
        </el-form-item>
        <el-alert :closable="false" type="warning" show-icon
          title="登录限流保护"
          :description="policyForm.periodic ? '保存即授权后台按此间隔登录该账号。重新登录可能使旧会话失效；冷却期内不会强行重登。不会自动补跑兑换码任务。' : '检测连接会优先复用已有会话；手动重登仍受冷却保护。保存设置不会立即登录远端。'" />
      </el-form>
      <template #footer>
        <el-button @click="policyVisible = false">取消</el-button>
        <el-button type="primary" :loading="policySaving" @click="saveSessionPolicy">{{ policyForm.periodic ? '保存并启用定时登录' : '保存设置' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="accountDialogVisible"
      :title="editingAccount ? '编辑远端账号' : '新建远端账号'"
      width="620px"
    >
      <el-form label-position="top">
        <el-alert
          v-if="isLegacyAccount"
          title="请重新配置这个历史账号"
          description="填写登录账号、密码和 TOTP Secret 后，分析与 ERP 会统一使用这条账号记录；旧盘口凭据不再参与账号选择。"
          type="warning"
          show-icon
          :closable="false"
        />
        <el-form-item label="所属盘口">
          <el-select
            v-model="accountForm.sourceId"
            :disabled="Boolean(editingAccount)"
            style="width: 100%"
            @change="selectSource"
          >
            <el-option
              v-for="source in sources"
              :key="source.sourceId"
              :label="`${source.displayName} · ${source.sourceId}`"
              :value="source.sourceId"
            />
          </el-select>
          <span v-if="selectedSource" class="field-help">
            {{ selectedSource.baseUrl || '该盘口尚未配置 Base URL' }}
          </span>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="远端登录账号">
            <el-input v-model="accountForm.loginUsername" autocomplete="username" />
          </el-form-item>
          <el-form-item label="账号显示名称">
            <el-input v-model="accountForm.displayName" placeholder="例如 RajWin 主账号" />
          </el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item :label="editingAccount && !isLegacyAccount ? '登录密码（留空不修改）' : '登录密码'">
            <el-input
              v-model="accountForm.password"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item :label="editingAccount && !isLegacyAccount ? 'TOTP Secret（留空不修改）' : 'TOTP Secret'">
            <el-input
              v-model="accountForm.totpSecret"
              type="password"
              show-password
              autocomplete="off"
            />
          </el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="启用账号">
            <el-switch
              v-model="accountForm.enabled"
              :disabled="Boolean(editingAccount?.isDefault)"
            />
            <span v-if="editingAccount?.isDefault" class="field-help">
              默认账号不能直接停用，请先将其他账号设为默认。
            </span>
          </el-form-item>
          <el-form-item label="默认账号">
            <el-switch
              v-model="accountForm.isDefault"
              :disabled="Boolean(editingAccount?.isDefault)"
            />
            <span class="field-help">自动同步和后台任务使用默认账号。</span>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="presetDialogVisible" title="标签快照与兑换档位" width="920px">
      <el-alert
        title="当前仅保存本地配置"
        description="这里用于迁移或人工维护标签目录与档位预设；不会连接盘口或同步标签。获得单独授权后，远端同步可替换本地快照。"
        type="warning"
        show-icon
        :closable="false"
      />
      <div class="preset-heading"><strong>标签快照</strong><el-button size="small" @click="addTag">添加标签</el-button></div>
      <div class="tag-editor">
        <div v-for="(tag, index) in presetTags" :key="index" class="tag-editor__row">
          <el-input-number v-model="tag.id" :min="1" controls-position="right" />
          <el-input v-model="tag.name" placeholder="标签名称" />
          <el-button type="danger" link @click="presetTags.splice(index, 1)">删除</el-button>
        </div>
      </div>
      <div class="preset-heading"><strong>兑换金额档位</strong><el-button size="small" @click="addTier">添加档位</el-button></div>
      <el-table :data="presetTiers" row-key="displayName" max-height="340">
        <el-table-column label="显示名称" min-width="150"><template #default="{ row }"><el-input v-model="row.displayName" /></template></el-table-column>
        <el-table-column label="标签" min-width="210"><template #default="{ row }"><el-select v-model="row.labelIds" multiple filterable><el-option v-for="tag in presetTags" :key="tag.id" :label="`${tag.name} (${tag.id})`" :value="tag.id" /></el-select></template></el-table-column>
        <el-table-column label="充值门槛" width="130"><template #default="{ row }"><el-input v-model="row.minDepositAmount" /></template></el-table-column>
        <el-table-column label="兑换金额" width="130"><template #default="{ row }"><el-input v-model="row.bonusAmount" /></template></el-table-column>
        <el-table-column label="最大奖金" width="130"><template #default="{ row }"><el-input v-model="row.bonusMaxAmount" /></template></el-table-column>
        <el-table-column label="操作" width="70"><template #default="{ $index }"><el-button type="danger" link @click="presetTiers.splice($index, 1)">删除</el-button></template></el-table-column>
      </el-table>
      <template #footer><el-button @click="presetDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="savePreset">保存配置</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.field-help,
.table-subtext {
  display: block;
  margin-top: 4px;
  color: var(--ink-muted);
  font-size: 12px;
}

.account-actions {
  display: grid;
  grid-template-columns: repeat(3, max-content);
  gap: 4px;
  align-items: center;
  white-space: nowrap;
}
.account-actions :deep(.el-button) { margin-left: 0; }
.session-policy-form .field-help { width: 100%; line-height: 1.6; }
.connection-error { display: block; color: var(--el-color-danger); margin-top: 4px; }

.preset-heading { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 10px; }
.tag-editor { display: grid; gap: 8px; }
.tag-editor__row { display: grid; grid-template-columns: 160px 1fr 60px; gap: 10px; align-items: center; }
</style>
