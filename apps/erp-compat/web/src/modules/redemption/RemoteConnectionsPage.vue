<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Delete, EditPen, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, api } from '@/api/client'
import type { RedemptionRemoteConnection, RedemptionRemoteMarket } from '@/api/types'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const activeTab = ref('markets')
const marketsLoading = ref(false)
const accountsLoading = ref(false)
const marketSaving = ref(false)
const accountSaving = ref(false)
const checkingId = ref<string | number>()
const deletingId = ref<string | number>()
const marketDialogVisible = ref(false)
const accountDialogVisible = ref(false)
const editingMarket = ref<RedemptionRemoteMarket>()
const editingAccount = ref<RedemptionRemoteConnection>()
const markets = ref<RedemptionRemoteMarket[]>([])
const accounts = ref<RedemptionRemoteConnection[]>([])
const marketForm = ref<RedemptionRemoteMarket>(emptyMarket())
const accountForm = ref<RedemptionRemoteConnection>(emptyAccount())
const canManage = computed(() => Boolean(session.user?.permissions.includes('*') || session.user?.permissions.includes('REDEMPTION_REMOTE_MANAGE') || session.user?.roles.includes('SUPER_ADMIN')))
const enabledMarkets = computed(() => markets.value.filter((market) => market.enabled))
const selectedMarket = computed(() => markets.value.find((market) => String(market.id) === String(accountForm.value.marketId)))

function emptyMarket(): RedemptionRemoteMarket {
  return { code: '', name: '', baseUrl: '', enabled: true }
}
function emptyAccount(): RedemptionRemoteConnection {
  return {
    username: '', marketId: undefined, baseUrl: '', password: '', totpSecret: '', enabled: true,
  }
}
function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未检测' }

async function loadMarkets() {
  marketsLoading.value = true
  try { markets.value = await api.redemptionRemoteMarkets.list() }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '读取远端盘口失败') }
  finally { marketsLoading.value = false }
}
async function loadAccounts() {
  accountsLoading.value = true
  try { accounts.value = await api.redemptionRemoteConnections.list() }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '读取远端账号失败') }
  finally { accountsLoading.value = false }
}
async function load() { await Promise.all([loadMarkets(), loadAccounts()]) }

function openCreateMarket() { editingMarket.value = undefined; marketForm.value = emptyMarket(); marketDialogVisible.value = true }
function openEditMarket(market: RedemptionRemoteMarket) { editingMarket.value = market; marketForm.value = { ...market }; marketDialogVisible.value = true }
function openCreateAccount() {
  if (!enabledMarkets.value.length) { activeTab.value = 'markets'; ElMessage.warning('请先在“盘口管理”中创建并启用盘口'); return }
  editingAccount.value = undefined
  accountForm.value = { ...emptyAccount(), marketId: enabledMarkets.value[0]?.id }
  accountDialogVisible.value = true
}
function openEditAccount(account: RedemptionRemoteConnection) {
  editingAccount.value = account
  accountForm.value = { ...account, password: '', totpSecret: '' }
  accountDialogVisible.value = true
}
function validateMarket() {
  if (!marketForm.value.code.trim() || !marketForm.value.name.trim() || !marketForm.value.baseUrl.trim()) return '请填写盘口编码、盘口名称和远端 Base URL'
  if (!/^https?:\/\//i.test(marketForm.value.baseUrl.trim())) return '远端 Base URL 必须以 http:// 或 https:// 开头'
  return ''
}
function validateAccount() {
  if (!accountForm.value.username.trim() || !accountForm.value.marketId) return '请填写远端账号名并选择所属盘口'
  const passwordRequired = !editingAccount.value || !editingAccount.value.hasPassword
  const totpRequired = !editingAccount.value || !editingAccount.value.hasTotpSecret
  if ((passwordRequired && !accountForm.value.password?.trim()) || (totpRequired && !accountForm.value.totpSecret?.trim())) return '请填写登录密码和 TOTP 秘钥'
  return ''
}
async function saveMarket() {
  const message = validateMarket()
  if (message) { ElMessage.warning(message); return }
  marketSaving.value = true
  try {
    if (editingMarket.value?.id) {
      await api.redemptionRemoteMarkets.update(editingMarket.value.id, { ...marketForm.value, rowVersion: editingMarket.value.rowVersion })
      ElMessage.success('远端盘口已更新；关联账号会使用新的 Base URL')
    } else {
      await api.redemptionRemoteMarkets.create(marketForm.value)
      ElMessage.success('远端盘口已创建')
    }
    marketDialogVisible.value = false
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '保存远端盘口失败') }
  finally { marketSaving.value = false }
}
async function saveAccount() {
  const message = validateAccount()
  if (message) { ElMessage.warning(message); return }
  accountSaving.value = true
  try {
    if (editingAccount.value?.id) {
      await api.redemptionRemoteConnections.update(editingAccount.value.id, { ...accountForm.value, rowVersion: editingAccount.value.rowVersion })
      ElMessage.success('远端账号已更新')
    } else {
      await api.redemptionRemoteConnections.create(accountForm.value)
      ElMessage.success('远端账号凭据已加密保存；首次检测时将自动登录')
    }
    accountDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    if (error instanceof ApiError && error.code === 'REMOTE_CONNECTION_VERSION_CONFLICT' && editingAccount.value?.id) {
      await loadAccounts()
      const latest = accounts.value.find((account) => String(account.id) === String(editingAccount.value?.id))
      if (latest) {
        editingAccount.value = latest
        accountForm.value = { ...accountForm.value, rowVersion: latest.rowVersion }
        ElMessage.warning('账号检测结果刚更新，已同步最新版本；请确认内容后再次保存')
        return
      }
    }
    ElMessage.error(error instanceof Error ? error.message : '保存远端账号失败')
  }
  finally { accountSaving.value = false }
}
async function check(account: RedemptionRemoteConnection) {
  if (!account.id) return
  checkingId.value = account.id
  try {
    const result = await api.redemptionRemoteConnections.check(account.id)
    ElMessage.success(String(result.message || '连接正常'))
    await loadAccounts()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '连接检查失败') }
  finally { checkingId.value = undefined }
}
async function toggleMarket(market: RedemptionRemoteMarket, enabled: boolean) {
  if (!market.id) return
  try { await api.redemptionRemoteMarkets.update(market.id, { enabled, rowVersion: market.rowVersion }); await load() }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '更新盘口状态失败'); await loadMarkets() }
}
async function toggleAccount(account: RedemptionRemoteConnection, enabled: boolean) {
  if (!account.id) return
  try { await api.redemptionRemoteConnections.update(account.id, { enabled, rowVersion: account.rowVersion }); await loadAccounts() }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '更新账号状态失败'); await loadAccounts() }
}
async function removeAccount(account: RedemptionRemoteConnection) {
  if (!account.id) return
  try {
    await ElMessageBox.confirm(`确定删除远端账号“${account.username}”吗？删除后无法恢复。若该账号已用于兑换码批次，系统会阻止删除以保留历史记录。`, '删除远端账号', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  deletingId.value = account.id
  try {
    await api.redemptionRemoteConnections.remove(account.id, account.rowVersion)
    ElMessage.success('远端账号已删除')
    await loadAccounts()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '删除远端账号失败') }
  finally { deletingId.value = undefined }
}

onMounted(load)
</script>

<template>
  <section class="remote-connections-page">
    <div class="page-title-row">
      <div><h2>远端连接</h2><p class="page-subtitle">先维护各盘口的远端 Base URL，再将远端账号绑定到对应盘口。系统以账号名、密码和 TOTP 秘钥自动登录；密码、秘钥与会话令牌均只在服务端 AES-256-GCM 加密保存。</p></div>
      <el-button :icon="Refresh" :loading="marketsLoading || accountsLoading" @click="load">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab" class="remote-tabs">
      <el-tab-pane label="盘口管理（Base URL）" name="markets">
        <div class="tab-actions"><el-alert type="warning" :closable="false" show-icon>一个盘口对应一个远端后台 Base URL，例如 <code>https://remote-admin.example.com</code>。请不要附带 <code>/api</code> 或具体兑换码接口路径。</el-alert><el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreateMarket">新建盘口</el-button></div>
        <article v-loading="marketsLoading" class="panel panel--padded connection-table-wrap">
          <el-table :data="markets" empty-text="暂无远端盘口，请先创建盘口">
            <el-table-column label="盘口" min-width="190"><template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.code }}</small></template></el-table-column>
            <el-table-column label="远端 Base URL" min-width="420" prop="baseUrl" show-overflow-tooltip />
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-switch :model-value="row.enabled" :disabled="!canManage" @update:model-value="toggleMarket(row, Boolean($event))" /></template></el-table-column>
            <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button v-if="canManage" link type="primary" :icon="EditPen" @click="openEditMarket(row)">编辑</el-button></template></el-table-column>
          </el-table>
        </article>
      </el-tab-pane>

      <el-tab-pane label="远端账号" name="accounts">
        <div class="tab-actions"><el-alert type="info" :closable="false" show-icon>账号必须选择一个已启用盘口。保存密码和 TOTP 秘钥后，系统会在检测、读取标签和兑换码作业时自动登录远端后台并续用会话。</el-alert><el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreateAccount">新建远端账号</el-button></div>
        <article v-loading="accountsLoading" class="panel panel--padded connection-table-wrap">
          <el-table :data="accounts" empty-text="暂无远端账号">
            <el-table-column label="远端账号" min-width="180"><template #default="{ row }"><strong>{{ row.username }}</strong></template></el-table-column>
            <el-table-column label="所属盘口" min-width="180"><template #default="{ row }"><strong>{{ row.marketName }}</strong><small>{{ row.marketCode }}</small><el-tag v-if="!row.marketEnabled" type="danger" size="small">盘口已停用</el-tag></template></el-table-column>
            <el-table-column label="登录凭据" width="145"><template #default="{ row }"><el-tag :type="row.hasPassword ? 'success' : 'danger'" size="small">密码{{ row.hasPassword ? '已保存' : '缺失' }}</el-tag><el-tag :type="row.hasTotpSecret ? 'success' : 'danger'" size="small" style="margin-left: 4px">TOTP{{ row.hasTotpSecret ? '已保存' : '缺失' }}</el-tag></template></el-table-column>
            <el-table-column label="远端会话 / 最近检测" min-width="200"><template #default="{ row }"><el-tag :type="row.hasActiveSession ? 'success' : 'info'" size="small">{{ row.hasActiveSession ? '已登录' : '未登录' }}</el-tag><small>{{ row.lastLoggedInAt ? `登录：${formatTime(row.lastLoggedInAt)}` : `检测：${formatTime(row.lastCheckedAt)}` }}</small><small v-if="row.lastError" class="connection-error">{{ row.lastError }}</small></template></el-table-column>
            <el-table-column label="启用" width="80"><template #default="{ row }"><el-switch :model-value="row.enabled" :disabled="!canManage" @update:model-value="toggleAccount(row, Boolean($event))" /></template></el-table-column>
            <el-table-column label="操作" width="290" fixed="right"><template #default="{ row }"><el-button v-if="canManage" link type="primary" :icon="VideoPlay" :loading="checkingId === row.id" :disabled="!row.marketEnabled || !row.enabled" @click="check(row)">登录并检测</el-button><el-button v-if="canManage" link type="primary" :icon="EditPen" @click="openEditAccount(row)">编辑</el-button><el-button v-if="canManage" link type="danger" :icon="Delete" :loading="deletingId === row.id" @click="removeAccount(row)">删除</el-button></template></el-table-column>
          </el-table>
        </article>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="marketDialogVisible" :title="editingMarket ? `编辑盘口：${editingMarket.name}` : '新建盘口'" width="650px" destroy-on-close>
      <el-form label-position="top" class="connection-form">
        <div class="connection-form__grid"><el-form-item label="盘口编码" required><el-input v-model="marketForm.code" :disabled="Boolean(editingMarket)" placeholder="如 RAJWIN_0101" /></el-form-item><el-form-item label="盘口名称" required><el-input v-model="marketForm.name" placeholder="如 RajWin 0101" /></el-form-item></div>
        <el-form-item label="远端 Base URL" required><el-input v-model="marketForm.baseUrl" placeholder="https://remote-admin.example.com" autocomplete="off" /><p class="field-note">变更 Base URL 后，所有关联账号会自动同步使用新地址；浏览器不会直接请求远端后台。</p></el-form-item>
        <el-form-item label="盘口状态"><el-switch v-model="marketForm.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="marketDialogVisible = false">取消</el-button><el-button type="primary" :loading="marketSaving" @click="saveMarket">保存盘口</el-button></template>
    </el-dialog>

    <el-dialog v-model="accountDialogVisible" :title="editingAccount ? `编辑远端账号：${editingAccount.username}` : '新建远端账号'" width="760px" destroy-on-close>
      <el-form label-position="top" class="connection-form">
        <el-form-item label="远端账号名" required><el-input v-model="accountForm.username" autocomplete="username" placeholder="远端管理后台的登录账号名；账号名在本系统中唯一" /></el-form-item>
        <el-form-item label="所属盘口" required><el-select v-model="accountForm.marketId" filterable placeholder="请选择已启用盘口" style="width: 100%"><el-option v-for="market in markets" :key="market.id" :label="`${market.name} · ${market.code}`" :value="market.id" :disabled="!market.enabled && String(market.id) !== String(accountForm.marketId)" /></el-select><p v-if="selectedMarket" class="field-note">当前 Base URL：<code>{{ selectedMarket.baseUrl }}</code></p></el-form-item>
        <div class="connection-form__grid"><el-form-item :label="editingAccount ? '替换登录密码（留空表示不变）' : '登录密码'" required><el-input v-model="accountForm.password" type="password" show-password autocomplete="new-password" placeholder="远端管理后台登录密码" /></el-form-item><el-form-item :label="editingAccount ? '替换 TOTP 秘钥（留空表示不变）' : 'TOTP 秘钥'" required><el-input v-model="accountForm.totpSecret" type="password" show-password autocomplete="off" placeholder="Base32 秘钥或 otpauth:// 链接" /></el-form-item></div>
        <p class="field-note">保存后不会直接使用或展示 JWT。系统会使用当前密码和实时 TOTP 验证码调用远端登录接口，自动保存短期会话。兑换码的发布环境、流水和领取规则请在“兑换码管理”建立批次时配置。</p>
        <el-form-item label="账号状态" style="margin-top: 16px"><el-switch v-model="accountForm.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="accountDialogVisible = false">取消</el-button><el-button type="primary" :loading="accountSaving" @click="saveAccount">加密保存</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.remote-tabs { margin-top: 12px; }.tab-actions { display: flex; gap: 12px; align-items: flex-start; }.tab-actions :deep(.el-alert) { flex: 1; }.connection-table-wrap { margin-top: 16px; }.connection-table-wrap strong, .connection-table-wrap small { display: block; }.connection-table-wrap small { margin-top: 3px; color: #667085; font-size: 11px; }.connection-error { max-width: 220px; overflow: hidden; color: #b42318; text-overflow: ellipsis; white-space: nowrap; }.connection-form__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.field-note { margin: 5px 0 0; color: #667085; font-size: 12px; }.remote-connections-page code { color: #475467; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (max-width: 760px) { .tab-actions { align-items: stretch; flex-direction: column; }.connection-form__grid { grid-template-columns: 1fr; } }
</style>
