<script setup lang="ts">
import { Edit, Plus, Refresh, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createRemoteAccount,
  fetchRemoteTagSnapshot,
  fetchRewardTierPreset,
  fetchRemoteAccountCapabilities,
  fetchRemoteAccounts,
  updateRemoteAccount,
  updateRemoteAccountCapabilities,
  saveRemoteTagSnapshot,
  saveRewardTierPreset,
} from '../api/remoteAccounts'
import { fetchAllSources } from '../api/sources'
import { apiErrorMessage } from '../api/client'
import type {
  RemoteAccount,
  RemoteAccountCapabilityDefinition,
  RemoteTag,
  RewardTierPresetTier,
  SourceConfig,
} from '../types'
import { formatDateTime } from '../ui'
import { hasErpPermission } from '../stores/auth'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const accounts = ref<RemoteAccount[]>([])
const sources = ref<SourceConfig[]>([])
const capabilityDefinitions = ref<RemoteAccountCapabilityDefinition[]>([])
const accountDialogVisible = ref(false)
const capabilityDialogVisible = ref(false)
const presetDialogVisible = ref(false)
const editingAccount = ref<RemoteAccount | null>(null)
const capabilityAccount = ref<RemoteAccount | null>(null)
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
})
const capabilityValues = reactive<Record<string, boolean>>({})

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
    const [nextSources, nextAccounts, nextCapabilities] = await Promise.all([
      canManage ? fetchAllSources() : Promise.resolve([]),
      fetchRemoteAccounts(),
      canManage ? fetchRemoteAccountCapabilities() : Promise.resolve([]),
    ])
    sources.value = nextSources
    accounts.value = nextAccounts
    capabilityDefinitions.value = nextCapabilities
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端账号与业务授权加载失败。'))
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
}

function openCreateAccount(): void {
  resetAccountForm()
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
  accountDialogVisible.value = true
}

function validateAccount(): boolean {
  if (!accountForm.displayName.trim()) {
    ElMessage.warning('请填写远端账号显示名称。')
    return false
  }
  if (editingAccount.value) return true
  if (!accountForm.sourceId || !accountForm.loginUsername.trim()) {
    ElMessage.warning('请选择所属盘口，并填写远端登录账号。')
    return false
  }
  if (!accountForm.password || !accountForm.totpSecret.trim()) {
    ElMessage.warning('新建远端账号必须同时填写密码和 TOTP Secret。')
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
        loginUsername?: string
        credentials?: { password?: string; totpSecret?: string }
      } = {
        displayName: accountForm.displayName.trim(),
        enabled: accountForm.enabled,
      }
      if (!isLegacyAccount.value && accountForm.loginUsername.trim()) {
        payload.loginUsername = accountForm.loginUsername.trim()
      }
      if (!isLegacyAccount.value && (accountForm.password || accountForm.totpSecret.trim())) {
        payload.credentials = {
          password: accountForm.password || undefined,
          totpSecret: accountForm.totpSecret.trim() || undefined,
        }
      }
      await updateRemoteAccount(editingAccount.value.id, payload)
      ElMessage.success('远端账号已更新。')
    } else {
      await createRemoteAccount({
        sourceId: accountForm.sourceId,
        loginUsername: accountForm.loginUsername.trim(),
        displayName: accountForm.displayName.trim(),
        enabled: accountForm.enabled,
        credentials: {
          password: accountForm.password,
          totpSecret: accountForm.totpSecret.trim(),
        },
      })
      ElMessage.success('远端账号已创建。')
    }
    accountDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端账号保存失败。'))
  } finally {
    saving.value = false
  }
}

function openCapabilities(account: RemoteAccount): void {
  capabilityAccount.value = account
  for (const key of Object.keys(capabilityValues)) delete capabilityValues[key]
  for (const definition of capabilityDefinitions.value) {
    capabilityValues[definition.code] = Boolean(account.capabilities[definition.code])
  }
  capabilityDialogVisible.value = true
}

async function saveCapabilities(): Promise<void> {
  if (!capabilityAccount.value) return
  saving.value = true
  try {
    await updateRemoteAccountCapabilities(capabilityAccount.value.id, { ...capabilityValues })
    ElMessage.success('账号能力授权已保存；这不会触发任何远端操作。')
    capabilityDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '账号能力授权保存失败。'))
  } finally {
    saving.value = false
  }
}

function enabledCapabilityLabels(account: RemoteAccount): string[] {
  return capabilityDefinitions.value
    .filter((definition) => account.capabilities[definition.code])
    .map((definition) => definition.label)
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

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">Unified remote accounts</span>
        <h1>远端账号与业务授权</h1>
        <p>一个远端账号归属一个盘口；分析读取与 ERP 能力通过同一账号单独授权。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" @click="router.push('/settings/sources')">管理盘口</el-button>
        <el-button v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" type="primary" :icon="Plus" @click="openCreateAccount">新建账号</el-button>
      </div>
    </header>

    <el-alert
      title="远端动作保持禁用"
      description="此页只保存本地账号与能力授权；不会测试连接、同步标签、创建或发布兑换码。即使勾选 ERP 能力，未来实际远端动作仍需逐项取得授权。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="accounts" row-key="id">
        <el-table-column label="盘口" min-width="190">
          <template #default="{ row }">
            <strong>{{ row.sourceDisplayName }}</strong>
            <small class="table-subtext">{{ row.sourceId }}</small>
          </template>
        </el-table-column>
        <el-table-column label="远端账号" min-width="190">
          <template #default="{ row }">
            <strong>{{ row.loginUsername || row.displayName }}</strong>
            <small class="table-subtext">{{ row.displayName }}</small>
            <el-tag v-if="row.credentialMode === 'LEGACY_SOURCE'" type="info" size="small">
              历史分析凭据
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭据" width="115" align="center">
          <template #default="{ row }">
            <el-tag :type="row.credentialConfigured ? 'success' : 'info'">
              {{ row.credentialConfigured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="能力授权" min-width="250">
          <template #default="{ row }">
            <div v-if="enabledCapabilityLabels(row).length" class="capability-tags">
              <el-tag v-for="label in enabledCapabilityLabels(row)" :key="label" effect="plain">
                {{ label }}
              </el-tag>
            </div>
            <span v-else class="muted">未授予能力</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="115" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled && row.sourceEnabled ? 'success' : 'info'">
              {{ row.enabled && row.sourceEnabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近远端测试" min-width="180">
          <template #default="{ row }">
            <div>{{ row.lastTestStatus || '未测试' }}</div>
            <small class="table-subtext">{{ formatDateTime(row.lastTestedAt) }}</small>
          </template>
        </el-table-column>
        <el-table-column v-if="hasErpPermission('ERP_REMOTE_ACCOUNT_MANAGE')" label="操作" width="285" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" :icon="Edit" @click="openEditAccount(row)">
              编辑账号
            </el-button>
            <el-button text type="primary" :icon="Setting" @click="openCapabilities(row)">
              授权
            </el-button>
            <el-button text type="primary" @click="openPreset(row)">标签/档位</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="accountDialogVisible"
      :title="editingAccount ? '编辑远端账号' : '新建远端账号'"
      width="620px"
    >
      <el-form label-position="top">
        <el-alert
          v-if="isLegacyAccount"
          title="历史默认账号只引用现有分析凭据"
          description="为避免复制或解密既有凭据，本阶段只能修改显示名称与启用状态。后续凭据接管会与分析读取链路一起迁移。"
          type="info"
          show-icon
          :closable="false"
        />
        <el-form-item label="所属盘口">
          <el-select v-model="accountForm.sourceId" :disabled="Boolean(editingAccount)" style="width: 100%">
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
            <el-input v-model="accountForm.loginUsername" :disabled="isLegacyAccount" autocomplete="username" />
          </el-form-item>
          <el-form-item label="账号显示名称">
            <el-input v-model="accountForm.displayName" placeholder="例如 RajWin 主账号" />
          </el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item :label="editingAccount ? '登录密码（留空不修改）' : '登录密码'">
            <el-input
              v-model="accountForm.password"
              :disabled="isLegacyAccount"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item :label="editingAccount ? 'TOTP Secret（留空不修改）' : 'TOTP Secret'">
            <el-input
              v-model="accountForm.totpSecret"
              :disabled="isLegacyAccount"
              type="password"
              show-password
              autocomplete="off"
            />
          </el-form-item>
        </div>
        <el-form-item label="启用账号">
          <el-switch v-model="accountForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="capabilityDialogVisible" title="授予账号能力" width="620px">
      <p class="dialog-lead">
        {{ capabilityAccount?.displayName }}：能力是本地服务端校验项，不会立即调用任何远端系统。
      </p>
      <div class="capability-options">
        <el-checkbox
          v-for="definition in capabilityDefinitions"
          :key="definition.code"
          v-model="capabilityValues[definition.code]"
        >
          {{ definition.label }}
        </el-checkbox>
      </div>
      <template #footer>
        <el-button @click="capabilityDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCapabilities">保存授权</el-button>
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

.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dialog-lead {
  margin: 0 0 16px;
  color: var(--ink-muted);
  line-height: 1.6;
}

.capability-options {
  display: grid;
  gap: 14px;
}

.preset-heading { display: flex; align-items: center; justify-content: space-between; margin: 18px 0 10px; }
.tag-editor { display: grid; gap: 8px; }
.tag-editor__row { display: grid; grid-template-columns: 160px 1fr 60px; gap: 10px; align-items: center; }
</style>
