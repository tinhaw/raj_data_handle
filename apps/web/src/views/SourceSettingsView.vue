<script setup lang="ts">
import { ArrowDown, ArrowUp, Connection, Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  clearSourceCredentials,
  createSource,
  deleteSource,
  fetchAllSources,
  reorderSources,
  testSourceConnection,
  testSourceScoringApi,
  updateSource,
} from '../api/sources'
import type { SourceConfig } from '../types'
import { formatDateTime } from '../ui'

type ConnectionTab = 'sources' | 'accounts'

const activeTab = ref<ConnectionTab>('sources')
const loading = ref(false)
const sourceSaving = ref(false)
const accountSaving = ref(false)
const accountTesting = ref(false)
const scoringApiTesting = ref(false)
const rows = ref<SourceConfig[]>([])
const reordering = ref(false)
const sourceDialogVisible = ref(false)
const accountDialogVisible = ref(false)
const editingSourceId = ref<string | null>(null)
const accountSourceId = ref('')
const originalAccountUsername = ref('')
const scoringApiKeyConfigured = ref(false)
const presetSourceIds = new Set(['rajwin', 'rajluck'])

const sourceForm = reactive({
  sourceId: '',
  displayName: '',
  baseUrl: '',
  businessTimezone: 'Asia/Kolkata',
  currency: 'INR',
  enabled: false,
  scoringApiBaseUrl: '',
  scoringApiKey: '',
})

const accountForm = reactive({
  username: '',
  password: '',
  totpSecret: '',
  enableAfterPassed: false,
})

const selectedAccountSource = computed(
  () => rows.value.find((source) => source.sourceId === accountSourceId.value) || null,
)

async function load(): Promise<void> {
  loading.value = true
  try {
    rows.value = await fetchAllSources()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端连接配置加载失败。'))
  } finally {
    loading.value = false
  }
}

function resetSourceForm(): void {
  editingSourceId.value = null
  scoringApiKeyConfigured.value = false
  sourceForm.sourceId = ''
  sourceForm.displayName = ''
  sourceForm.baseUrl = ''
  sourceForm.businessTimezone = 'Asia/Kolkata'
  sourceForm.currency = 'INR'
  sourceForm.enabled = false
  sourceForm.scoringApiBaseUrl = ''
  sourceForm.scoringApiKey = ''
}

function openCreateSource(): void {
  resetSourceForm()
  sourceDialogVisible.value = true
}

function openEditSource(row: SourceConfig): void {
  editingSourceId.value = row.sourceId
  scoringApiKeyConfigured.value = row.scoringApiKeyConfigured
  sourceForm.sourceId = row.sourceId
  sourceForm.displayName = row.displayName
  sourceForm.baseUrl = row.baseUrl || ''
  sourceForm.businessTimezone = row.businessTimezone
  sourceForm.currency = row.currency
  sourceForm.enabled = row.enabled
  sourceForm.scoringApiBaseUrl = row.scoringApiBaseUrl || ''
  sourceForm.scoringApiKey = ''
  sourceDialogVisible.value = true
}

function sourcePayload(enabled: boolean): Record<string, unknown> {
  return {
    displayName: sourceForm.displayName,
    baseUrl: sourceForm.baseUrl || null,
    businessTimezone: sourceForm.businessTimezone,
    currency: sourceForm.currency,
    enabled,
    scoringApi: {
      baseUrl: sourceForm.scoringApiBaseUrl || null,
      apiKey: sourceForm.scoringApiKey || null,
    },
  }
}

function validateSource(): boolean {
  if (!sourceForm.displayName.trim()) {
    ElMessage.warning('请填写盘口显示名。')
    return false
  }
  if (!sourceForm.baseUrl.trim()) {
    ElMessage.warning('请填写远端后台 Base URL。')
    return false
  }
  if (
    editingSourceId.value === null &&
    !/^[a-z][a-z0-9_-]{1,63}$/.test(sourceForm.sourceId.trim())
  ) {
    ElMessage.warning(
      '来源 ID 须为 2-64 位，以小写字母开头，且只能包含小写字母、数字、下划线和连字符。',
    )
    return false
  }
  return true
}

async function persistSource(enabled: boolean): Promise<string> {
  if (editingSourceId.value === null) {
    const sourceId = sourceForm.sourceId.trim()
    await createSource({ sourceId, ...sourcePayload(false) })
    editingSourceId.value = sourceId
    return sourceId
  }
  await updateSource(editingSourceId.value, sourcePayload(enabled))
  return editingSourceId.value
}

async function saveSource(): Promise<void> {
  if (!validateSource()) return
  const creating = editingSourceId.value === null
  sourceSaving.value = true
  try {
    await persistSource(creating ? false : sourceForm.enabled)
    ElMessage.success(creating ? '盘口已创建，请到“远端账号”配置登录凭据。' : '盘口配置已保存。')
    sourceDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口配置保存失败。'))
  } finally {
    sourceSaving.value = false
  }
}

async function saveAndTestScoringApi(): Promise<void> {
  if (!validateSource()) return
  scoringApiTesting.value = true
  try {
    const sourceId = await persistSource(false)
    const result = await testSourceScoringApi(sourceId)
    if (result.status !== 'passed') {
      ElMessage.warning(result.message)
      return
    }
    ElMessage.success('评分审核 API 连接测试通过，盘口配置已保存。')
    sourceDialogVisible.value = false
  } catch (error) {
    ElMessage.warning(apiErrorMessage(error, '保存或评分审核 API 测试失败。'))
  } finally {
    await load()
    scoringApiTesting.value = false
  }
}

function resetAccountForm(): void {
  accountSourceId.value = ''
  originalAccountUsername.value = ''
  accountForm.username = ''
  accountForm.password = ''
  accountForm.totpSecret = ''
  accountForm.enableAfterPassed = false
}

function populateAccountForm(sourceId: string): void {
  accountSourceId.value = sourceId
  const source = rows.value.find((item) => item.sourceId === sourceId)
  originalAccountUsername.value = source?.loginUsername || ''
  accountForm.username = source?.loginUsername || ''
  accountForm.password = ''
  accountForm.totpSecret = ''
  accountForm.enableAfterPassed = Boolean(source && !source.enabled)
}

function openCreateAccount(): void {
  resetAccountForm()
  accountDialogVisible.value = true
}

function openConfigureAccount(row: SourceConfig): void {
  resetAccountForm()
  populateAccountForm(row.sourceId)
  accountDialogVisible.value = true
}

function accountSourceChanged(sourceId: string): void {
  populateAccountForm(sourceId)
}

function validateAccount(): boolean {
  const source = selectedAccountSource.value
  if (!source) {
    ElMessage.warning('请选择账号所属的盘口。')
    return false
  }
  if (!source.credentialConfigured) {
    if (!accountForm.username.trim() || !accountForm.password || !accountForm.totpSecret.trim()) {
      ElMessage.warning('首次配置账号时，必须同时填写登录账号、密码和 TOTP Secret。')
      return false
    }
  }
  return true
}

function accountPayload(): Record<string, unknown> | null {
  const usernameChanged = accountForm.username.trim() !== originalAccountUsername.value
  if (!usernameChanged && !accountForm.password && !accountForm.totpSecret) return null
  return {
    credentials: {
      username: usernameChanged ? accountForm.username || null : null,
      password: accountForm.password || null,
      totpSecret: accountForm.totpSecret || null,
    },
  }
}

async function persistAccount(): Promise<string> {
  const sourceId = accountSourceId.value
  const payload = accountPayload()
  if (payload) await updateSource(sourceId, payload)
  return sourceId
}

async function saveAccount(): Promise<void> {
  if (!validateAccount()) return
  accountSaving.value = true
  try {
    await persistAccount()
    ElMessage.success('远端账号已保存。')
    accountDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '远端账号保存失败。'))
  } finally {
    accountSaving.value = false
  }
}

async function saveAndTestAccount(): Promise<void> {
  if (!validateAccount()) return
  accountTesting.value = true
  try {
    const sourceId = await persistAccount()
    const result = await testSourceConnection(sourceId)
    if (result.status !== 'passed') {
      ElMessage.warning(result.message)
      return
    }
    if (accountForm.enableAfterPassed) await updateSource(sourceId, { enabled: true })
    ElMessage.success(
      accountForm.enableAfterPassed ? '账号测试通过，所属盘口已启用。' : '远端账号测试通过。',
    )
    accountDialogVisible.value = false
  } catch (error) {
    ElMessage.warning(apiErrorMessage(error, '保存或远端账号测试失败。'))
  } finally {
    await load()
    accountTesting.value = false
  }
}

async function removeSource(row: SourceConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将永久删除盘口“${row.displayName}”（${row.sourceId}）、其远端账号和渠道映射。该操作无法撤销。`,
      '删除盘口',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await deleteSource(row.sourceId)
    ElMessage.success('盘口已删除。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '盘口删除失败。'))
  }
}

async function clearAccount(row: SourceConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `清除“${row.displayName}”的远端账号后，盘口会自动停用，且无法恢复已保存的密码和 TOTP Secret。`,
      '清除远端账号',
      { type: 'warning', confirmButtonText: '确认清除' },
    )
    await clearSourceCredentials(row.sourceId)
    ElMessage.success('远端账号已清除，盘口已停用。')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '远端账号清除失败。'))
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
        <span class="page-eyebrow">Remote accounts</span>
        <h1>远端账号与盘口</h1>
        <p>以当前分析数据源为基础维护统一的盘口和远端账号；ERP 能力将通过单独授权附加到同一账号。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="activeTab === 'sources'" type="primary" :icon="Plus" @click="openCreateSource">
          新建盘口
        </el-button>
        <el-button v-else type="primary" :icon="Plus" @click="openCreateAccount">
          配置远端账号
        </el-button>
      </div>
    </header>

    <el-alert
      title="配置顺序"
      description="先在“盘口”登记显示名与 Base URL；再在“远端账号”选择所属盘口，填写账号、密码与 TOTP Secret，并执行连接测试。密码、TOTP Secret 与 API Key 均只写不读。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-tabs v-model="activeTab" class="connection-tabs">
      <el-tab-pane label="盘口" name="sources">
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
            <el-table-column label="盘口" min-width="140" prop="displayName" />
            <el-table-column label="远端后台 Base URL" min-width="270" prop="baseUrl" show-overflow-tooltip />
            <el-table-column label="远端账号" min-width="150">
              <template #default="{ row }">
                <span>{{ row.loginUsername || '未配置' }}</span>
                <small class="table-subtext">
                  {{ row.credentialConfigured ? '已绑定账号' : '请到账号页配置' }}
                </small>
              </template>
            </el-table-column>
            <el-table-column label="评分审核 API" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span>{{ row.scoringApiBaseUrl || '未配置' }}</span>
                <small class="table-subtext">
                  {{ row.scoringApiKeyConfigured ? 'API Key 已配置' : 'API Key 未配置' }}
                </small>
              </template>
            </el-table-column>
            <el-table-column label="时区 / 币种" min-width="165">
              <template #default="{ row }">{{ row.businessTimezone }} · {{ row.currency }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'">
                  {{ row.enabled ? '已启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="270" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" :icon="Edit" @click="openEditSource(row)">编辑盘口</el-button>
                <el-button text type="primary" :icon="Connection" @click="openConfigureAccount(row)">
                  配置账号
                </el-button>
                <el-tooltip :content="row.enabled ? '请先停用盘口再删除' : '永久删除盘口'">
                  <span>
                    <el-button
                      text
                      type="danger"
                      :icon="Delete"
                      :disabled="row.enabled"
                      @click="removeSource(row)"
                    >
                      删除
                    </el-button>
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="远端账号" name="accounts">
        <section class="surface-card table-card">
          <el-table v-loading="loading" :data="rows">
            <el-table-column label="所属盘口" min-width="190">
              <template #default="{ row }">
                <strong>{{ row.displayName }}</strong>
                <small class="table-subtext">{{ row.sourceId }}</small>
              </template>
            </el-table-column>
            <el-table-column label="远端后台" min-width="280" prop="baseUrl" show-overflow-tooltip />
            <el-table-column label="登录账号" min-width="150">
              <template #default="{ row }">{{ row.loginUsername || '未配置' }}</template>
            </el-table-column>
            <el-table-column label="凭据" width="110">
              <template #default="{ row }">
                <el-tag :type="row.credentialConfigured ? 'success' : 'info'">
                  {{ row.credentialConfigured ? '已配置' : '未配置' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="连接测试" min-width="170">
              <template #default="{ row }">
                <span>{{ row.lastTestStatus || '未测试' }}</span>
                <small class="table-subtext">{{ formatDateTime(row.lastTestedAt) }}</small>
              </template>
            </el-table-column>
            <el-table-column label="盘口状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'">
                  {{ row.enabled ? '已启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" :icon="Edit" @click="openConfigureAccount(row)">
                  {{ row.credentialConfigured ? '编辑账号' : '配置账号' }}
                </el-button>
                <el-button
                  v-if="row.credentialConfigured"
                  text
                  type="danger"
                  :icon="Delete"
                  @click="clearAccount(row)"
                >
                  清除账号
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="sourceDialogVisible"
      :title="editingSourceId === null ? '新建盘口' : `编辑盘口 ${editingSourceId}`"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item v-if="editingSourceId === null" label="来源 ID">
          <el-input v-model="sourceForm.sourceId" placeholder="例如 rajstar" maxlength="64" />
          <span class="field-help">创建后不可修改；使用小写字母、数字、下划线或连字符。</span>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="盘口显示名">
            <el-input v-model="sourceForm.displayName" placeholder="例如 RajSpin" />
          </el-form-item>
          <el-form-item label="业务时区">
            <el-input v-model="sourceForm.businessTimezone" />
          </el-form-item>
          <el-form-item label="币种">
            <el-input v-model="sourceForm.currency" maxlength="3" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="sourceForm.enabled" />
            <span class="field-help">启用前必须有通过测试的远端账号。</span>
          </el-form-item>
        </div>
        <el-form-item label="远端后台 Base URL">
          <el-input v-model="sourceForm.baseUrl" placeholder="https://remote-admin.example.com" />
          <span class="field-help">填写远端后台首页地址；不要附带 /api、查询参数或接口路径。</span>
        </el-form-item>
        <el-divider content-position="left">评分审核 API（可选，按盘口配置）</el-divider>
        <el-form-item label="评分审核 API Base URL">
          <el-input
            v-model="sourceForm.scoringApiBaseUrl"
            placeholder="https://primary.example.com/api"
          />
          <span class="field-help">评分审核 API 必须以 /api 结束，与远端账号登录地址独立。</span>
        </el-form-item>
        <el-form-item label="评分审核 API Key">
          <el-input
            v-model="sourceForm.scoringApiKey"
            :placeholder="scoringApiKeyConfigured ? '已设置，留空则保持原值' : '请输入具有 reviewed-cases:read 权限的 Key'"
            type="password"
            show-password
            autocomplete="off"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialogVisible = false">取消</el-button>
        <el-button :loading="sourceSaving" :disabled="scoringApiTesting" @click="saveSource">
          保存盘口
        </el-button>
        <el-button
          :loading="scoringApiTesting"
          :disabled="sourceSaving"
          @click="saveAndTestScoringApi"
        >
          测试评分 API
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" title="配置远端账号" width="620px">
      <el-form label-position="top">
        <el-form-item label="所属盘口">
          <el-select
            v-model="accountSourceId"
            placeholder="请选择账号所属盘口"
            filterable
            style="width: 100%"
            @change="accountSourceChanged"
          >
            <el-option
              v-for="source in rows"
              :key="source.sourceId"
              :label="`${source.displayName} · ${source.sourceId}`"
              :value="source.sourceId"
            >
              <div class="source-option">
                <strong>{{ source.displayName }} · {{ source.sourceId }}</strong>
                <span>{{ source.baseUrl || '未配置 Base URL' }}</span>
              </div>
            </el-option>
          </el-select>
          <span class="field-help">
            账号将绑定到所选盘口；当前系统每个盘口使用一套远端登录账号。
          </span>
        </el-form-item>
        <el-alert
          v-if="selectedAccountSource && !selectedAccountSource.baseUrl"
          title="该盘口尚未配置 Base URL，请先到“盘口”页补充远端后台地址。"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="form-grid account-form-grid">
          <el-form-item label="登录账号">
            <el-input v-model="accountForm.username" placeholder="请输入登录账号" autocomplete="username" />
          </el-form-item>
          <el-form-item label="登录密码">
            <el-input
              v-model="accountForm.password"
              :placeholder="selectedAccountSource?.credentialConfigured ? '已设置，留空则保持原值' : '请输入登录密码'"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
        </div>
        <el-form-item label="TOTP Secret">
          <el-input
            v-model="accountForm.totpSecret"
            :placeholder="selectedAccountSource?.credentialConfigured ? '已设置，留空则保持原值' : '请输入 TOTP Secret'"
            type="password"
            show-password
            autocomplete="off"
          />
          <span class="field-help">仅在服务端即时生成六码验证，不会回显或写入日志。</span>
        </el-form-item>
        <el-form-item label="测试通过后启用盘口">
          <el-switch v-model="accountForm.enableAfterPassed" :disabled="!selectedAccountSource" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button :loading="accountSaving" :disabled="accountTesting" @click="saveAccount">
          保存账号
        </el-button>
        <el-button
          type="primary"
          :icon="Connection"
          :loading="accountTesting"
          :disabled="accountSaving"
          @click="saveAndTestAccount"
        >
          保存并测试
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.connection-tabs {
  margin-top: 4px;
}

.field-help {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.5;
}

.source-option {
  display: grid;
  gap: 2px;
  line-height: 1.35;
}

.source-option span {
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
}

.account-form-grid {
  align-items: start;
}
</style>
