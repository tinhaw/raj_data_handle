<script setup lang="ts">
import { CopyDocument, Delete, Edit, Key, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  createTotpAccount,
  deleteTotpAccount,
  generateTotpCodes,
  updateTotpAccount,
} from '../api/totpCodes'
import type { TotpCodeItem, TotpCodeList } from '../types'

const loading = ref(false)
const saving = ref(false)
const snapshot = ref<TotpCodeList | null>(null)
const showCodes = ref(true)
const search = ref('')
const clientNow = ref(Date.now())
const serverOffsetMs = ref(0)
const dialogVisible = ref(false)
const editingAccountId = ref<string | null>(null)
const form = reactive({
  displayName: '',
  accountName: '',
  totpSecret: '',
  enabled: true,
})
let clockTimer: number | undefined
let lastAutoRefreshExpiry = ''

const serverNow = computed(() => clientNow.value + serverOffsetMs.value)
const remainingSeconds = computed(() => {
  if (!snapshot.value) return 0
  return Math.max(0, Math.ceil((Date.parse(snapshot.value.expiresAt) - serverNow.value) / 1_000))
})
const progressPercentage = computed(() => {
  if (!snapshot.value) return 0
  return Math.max(
    0,
    Math.min(100, (remainingSeconds.value / snapshot.value.periodSeconds) * 100),
  )
})
const availableCount = computed(
  () => snapshot.value?.items.filter((item) => item.status === 'available').length || 0,
)
const unavailableCount = computed(
  () => snapshot.value?.items.filter((item) => item.status !== 'available').length || 0,
)
const filteredItems = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  if (!keyword) return snapshot.value?.items || []
  return (snapshot.value?.items || []).filter(
    (item) =>
      item.displayName.toLocaleLowerCase().includes(keyword) ||
      item.accountName.toLocaleLowerCase().includes(keyword),
  )
})

async function loadCodes(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    const result = await generateTotpCodes()
    snapshot.value = result
    serverOffsetMs.value = Date.parse(result.generatedAt) - Date.now()
    clientNow.value = Date.now()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'TOTP 验证码加载失败。'))
  } finally {
    loading.value = false
  }
}

function addAccount(): void {
  editingAccountId.value = null
  form.displayName = ''
  form.accountName = ''
  form.totpSecret = ''
  form.enabled = true
  dialogVisible.value = true
}

function editAccount(item: TotpCodeItem): void {
  editingAccountId.value = item.accountId
  form.displayName = item.displayName
  form.accountName = item.accountName
  form.totpSecret = ''
  form.enabled = item.enabled
  dialogVisible.value = true
}

async function saveAccount(): Promise<void> {
  if (!form.displayName.trim() || !form.accountName.trim()) {
    ElMessage.warning('请填写显示名称和账号标识。')
    return
  }
  if (!editingAccountId.value && !form.totpSecret.trim()) {
    ElMessage.warning('新增账号必须填写 TOTP Secret。')
    return
  }

  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      displayName: form.displayName.trim(),
      accountName: form.accountName.trim(),
      enabled: form.enabled,
    }
    if (form.totpSecret.trim()) payload.totpSecret = form.totpSecret.trim()
    if (editingAccountId.value) {
      await updateTotpAccount(editingAccountId.value, payload)
      ElMessage.success('TOTP 账号已更新。')
    } else {
      await createTotpAccount(payload)
      ElMessage.success('TOTP 账号已创建。')
    }
    dialogVisible.value = false
    form.totpSecret = ''
    await loadCodes()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, 'TOTP 账号保存失败。'))
  } finally {
    saving.value = false
  }
}

async function removeAccount(item: TotpCodeItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除“${item.displayName}（${item.accountName}）”吗？保存的加密密钥将无法恢复。`,
      '删除 TOTP 账号',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    await deleteTotpAccount(item.accountId)
    ElMessage.success('TOTP 账号已删除。')
    await loadCodes()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, 'TOTP 账号删除失败。'))
  }
}

function formattedCode(item: TotpCodeItem): string {
  if (!showCodes.value || remainingSeconds.value <= 0 || !item.code) return '••• •••'
  return `${item.code.slice(0, 3)} ${item.code.slice(3)}`
}

async function copyCode(item: TotpCodeItem): Promise<void> {
  if (!item.code || remainingSeconds.value <= 0) {
    ElMessage.warning('验证码已过期，请等待自动刷新。')
    return
  }
  try {
    await navigator.clipboard.writeText(item.code)
    ElMessage.success(`${item.displayName} 验证码已复制。`)
  } catch {
    ElMessage.error('浏览器未允许复制，请手动输入验证码。')
  }
}

onMounted(() => {
  void loadCodes()
  clockTimer = window.setInterval(() => {
    clientNow.value = Date.now()
    const expiry = snapshot.value?.expiresAt || ''
    if (
      expiry &&
      remainingSeconds.value <= 0 &&
      expiry !== lastAutoRefreshExpiry &&
      !loading.value
    ) {
      lastAutoRefreshExpiry = expiry
      void loadCodes()
    }
  }, 250)
})

onBeforeUnmount(() => {
  if (clockTimer) window.clearInterval(clockTimer)
  snapshot.value = null
  form.totpSecret = ''
})
</script>

<template>
  <div class="page-stack totp-page">
    <header class="page-header">
      <div>
        <div class="page-eyebrow">INDEPENDENT TOTP VAULT</div>
        <h1>TOTP 验证码</h1>
        <p>
          在这里独立维护需要查看验证码的账号。它们与盘口配置、远端同步账号完全分离，密钥只以密文保存。
        </p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadCodes">刷新验证码</el-button>
        <el-button type="primary" :icon="Plus" @click="addAccount">添加账号</el-button>
      </div>
    </header>

    <section class="surface-card totp-overview">
      <div class="countdown-block">
        <span>当前验证码剩余</span>
        <strong>{{ remainingSeconds }}<small>秒</small></strong>
        <el-progress
          :percentage="progressPercentage"
          :show-text="false"
          :stroke-width="8"
          :color="remainingSeconds <= 5 ? '#e76f51' : '#2a9d8f'"
        />
      </div>
      <div class="overview-stat">
        <span>可用账号</span>
        <strong>{{ availableCount }}</strong>
      </div>
      <div class="overview-stat">
        <span>停用或异常</span>
        <strong>{{ unavailableCount }}</strong>
      </div>
      <el-switch v-model="showCodes" active-text="显示验证码" inactive-text="隐藏验证码" />
    </section>

    <el-alert
      title="安全提示"
      type="warning"
      :closable="false"
      show-icon
      description="TOTP Secret 保存后不会再次回显；验证码仅管理员可查看，并会随 30 秒周期自动更新。"
    />

    <section v-if="snapshot?.items.length" class="surface-card filter-bar account-filter">
      <el-input
        v-model="search"
        :prefix-icon="Search"
        clearable
        placeholder="搜索显示名称或账号标识"
      />
      <span class="filter-total">显示 {{ filteredItems.length }} / {{ snapshot.items.length }}</span>
    </section>

    <div v-if="loading && !snapshot" class="surface-card loading-card">
      <el-skeleton :rows="5" animated />
    </div>

    <el-empty
      v-else-if="snapshot && snapshot.items.length === 0"
      class="surface-card empty-card"
      description="尚未添加独立 TOTP 账号"
    >
      <el-button type="primary" :icon="Plus" @click="addAccount">添加第一个账号</el-button>
    </el-empty>

    <el-empty
      v-else-if="snapshot && filteredItems.length === 0"
      class="surface-card empty-card"
      description="没有匹配的 TOTP 账号"
    />

    <section v-else-if="snapshot" class="code-grid">
      <article
        v-for="item in filteredItems"
        :key="item.accountId"
        class="surface-card code-card"
        :class="`code-card--${item.status}`"
      >
        <header class="code-card__header">
          <div class="account-identity">
            <span class="account-icon"><el-icon><Key /></el-icon></span>
            <div>
              <h2>{{ item.displayName }}</h2>
              <span>{{ item.accountName }}</span>
            </div>
          </div>
          <div class="card-actions">
            <el-tag :type="item.enabled ? 'success' : 'info'" effect="light">
              {{ item.enabled ? '已启用' : '已停用' }}
            </el-tag>
            <el-button text circle :icon="Edit" title="编辑账号" @click="editAccount(item)" />
            <el-button
              text
              circle
              type="danger"
              :icon="Delete"
              title="删除账号"
              @click="removeAccount(item)"
            />
          </div>
        </header>

        <template v-if="item.status === 'available'">
          <div class="code-row">
            <button
              class="code-value"
              type="button"
              :title="remainingSeconds > 0 ? '点击复制验证码' : '验证码刷新中'"
              @click="copyCode(item)"
            >
              {{ formattedCode(item) }}
            </button>
            <el-button
              circle
              :icon="CopyDocument"
              :disabled="remainingSeconds <= 0"
              title="复制验证码"
              @click="copyCode(item)"
            />
          </div>
          <div class="code-meta">
            <span>{{ remainingSeconds }} 秒后自动更新</span>
            <span>30 秒周期</span>
          </div>
        </template>

        <el-alert
          v-else
          :title="item.status === 'disabled' ? '账号已停用' : 'TOTP Secret 无效'"
          :description="item.message || undefined"
          :type="item.status === 'disabled' ? 'info' : 'error'"
          :closable="false"
          show-icon
        />
      </article>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editingAccountId ? '编辑 TOTP 账号' : '添加 TOTP 账号'"
      width="min(520px, 92vw)"
      destroy-on-close
      @closed="form.totpSecret = ''"
    >
      <el-form label-position="top">
        <el-form-item label="显示名称" required>
          <el-input v-model="form.displayName" maxlength="120" placeholder="例如：RajWin 运营后台" />
        </el-form-item>
        <el-form-item label="账号标识" required>
          <el-input v-model="form.accountName" maxlength="200" placeholder="账号、邮箱或便于识别的名称" />
        </el-form-item>
        <el-form-item
          :label="editingAccountId ? '更新 TOTP Secret' : 'TOTP Secret'"
          :required="!editingAccountId"
        >
          <el-input
            v-model="form.totpSecret"
            type="password"
            show-password
            maxlength="2000"
            autocomplete="new-password"
            :placeholder="editingAccountId ? '留空则保留原密钥' : 'Base32 Secret 或 otpauth:// URI'"
          />
          <span class="form-help">保存后密钥不会再次显示。</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.totp-page {
  max-width: 1240px;
  margin: 0 auto;
}

.totp-overview {
  display: grid;
  grid-template-columns: minmax(260px, 1.6fr) repeat(2, minmax(120px, 0.6fr)) auto;
  align-items: center;
  gap: 24px;
  padding: 20px 24px;
}

.countdown-block,
.overview-stat {
  display: grid;
  gap: 7px;
}

.countdown-block > span,
.overview-stat span,
.code-meta,
.form-help {
  color: var(--ink-muted);
  font-size: 13px;
}

.countdown-block strong {
  color: var(--ink-strong);
  font-size: 31px;
  font-variant-numeric: tabular-nums;
}

.countdown-block small {
  margin-left: 4px;
  font-size: 14px;
}

.overview-stat strong {
  color: var(--ink-strong);
  font-size: 27px;
}

.loading-card,
.empty-card {
  padding: 28px;
}

.account-filter :deep(.el-input) {
  width: min(420px, 100%);
}

.code-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.code-card {
  min-height: 210px;
  padding: 20px;
  overflow: hidden;
  border-top: 4px solid var(--teal);
}

.code-card--disabled {
  border-top-color: var(--ink-muted);
}

.code-card--invalid {
  border-top-color: var(--danger);
}

.code-card__header,
.account-identity,
.card-actions,
.code-row,
.code-meta {
  display: flex;
  align-items: center;
}

.code-card__header {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 28px;
}

.account-identity {
  min-width: 0;
  gap: 11px;
}

.account-icon {
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: var(--primary);
}

.account-identity h2 {
  margin: 0 0 2px;
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-identity span {
  display: block;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-actions {
  flex: 0 0 auto;
  gap: 2px;
}

.code-row {
  justify-content: space-between;
  gap: 12px;
}

.code-value {
  min-width: 0;
  padding: 0;
  border: 0;
  color: var(--ink-strong);
  background: transparent;
  cursor: pointer;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: clamp(30px, 3vw, 40px);
  font-variant-numeric: tabular-nums;
  font-weight: 800;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.code-meta {
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
}

.form-help {
  display: block;
  margin-top: 6px;
}

@media (max-width: 1100px) {
  .code-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .totp-overview {
    grid-template-columns: minmax(260px, 1fr) repeat(2, minmax(110px, 0.5fr));
  }

  .totp-overview :deep(.el-switch) {
    grid-column: 1 / -1;
    justify-self: start;
  }
}

@media (max-width: 720px) {
  .code-grid,
  .totp-overview {
    grid-template-columns: 1fr;
  }

  .code-card__header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
