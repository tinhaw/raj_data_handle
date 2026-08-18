<script setup lang="ts">
import { ArrowDown, ArrowUp, Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiErrorMessage } from '../api/client'
import {
  createSource,
  deleteSource,
  fetchAllSources,
  reorderSources,
  updateSource,
} from '../api/sources'
import type { SourceConfig } from '../types'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const reordering = ref(false)
const rows = ref<SourceConfig[]>([])
const sourceDialogVisible = ref(false)
const editingSourceId = ref<string | null>(null)
const scoringApiKeyConfigured = ref(false)
const initialReviewV1ApiKeyConfigured = ref(false)
const presetSourceIds = new Set(['rajwin', 'rajluck'])

const form = reactive({
  sourceId: '',
  displayName: '',
  baseUrl: '',
  businessTimezone: 'Asia/Kolkata',
  currency: 'INR',
  scoringApiBaseUrl: '',
  scoringApiKey: '',
  initialReviewV1ApiBaseUrl: '',
  initialReviewV1ApiKey: '',
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

function resetForm(): void {
  editingSourceId.value = null
  scoringApiKeyConfigured.value = false
  initialReviewV1ApiKeyConfigured.value = false
  form.sourceId = ''
  form.displayName = ''
  form.baseUrl = ''
  form.businessTimezone = 'Asia/Kolkata'
  form.currency = 'INR'
  form.scoringApiBaseUrl = ''
  form.scoringApiKey = ''
  form.initialReviewV1ApiBaseUrl = ''
  form.initialReviewV1ApiKey = ''
}

function openCreate(): void {
  resetForm()
  sourceDialogVisible.value = true
}

function openEdit(row: SourceConfig): void {
  editingSourceId.value = row.sourceId
  scoringApiKeyConfigured.value = row.scoringApiKeyConfigured
  initialReviewV1ApiKeyConfigured.value = row.initialReviewV1ApiKeyConfigured
  form.sourceId = row.sourceId
  form.displayName = row.displayName
  form.baseUrl = row.baseUrl || ''
  form.businessTimezone = row.businessTimezone
  form.currency = row.currency
  form.scoringApiBaseUrl = row.scoringApiBaseUrl || ''
  form.scoringApiKey = ''
  form.initialReviewV1ApiBaseUrl = row.initialReviewV1ApiBaseUrl || ''
  form.initialReviewV1ApiKey = ''
  sourceDialogVisible.value = true
}

function payload(): Record<string, unknown> {
  return {
    displayName: form.displayName.trim(),
    baseUrl: form.baseUrl.trim() || null,
    businessTimezone: form.businessTimezone.trim(),
    currency: form.currency.trim(),
    scoringApi: {
      baseUrl: form.scoringApiBaseUrl.trim() || null,
      apiKey: form.scoringApiKey || null,
    },
    initialReviewV1Api: {
      baseUrl: form.initialReviewV1ApiBaseUrl.trim() || null,
      apiKey: form.initialReviewV1ApiKey || null,
    },
  }
}

function apiConfigured(baseUrl: string | null, keyConfigured: boolean): boolean {
  return Boolean(baseUrl && keyConfigured)
}

function validate(): boolean {
  if (!form.displayName.trim() || !form.baseUrl.trim()) {
    ElMessage.warning('请填写盘口显示名和远端后台 Base URL。')
    return false
  }
  if (
    editingSourceId.value === null &&
    !/^[a-z][a-z0-9_-]{1,63}$/.test(form.sourceId.trim())
  ) {
    ElMessage.warning('来源 ID 须为 2-64 位，以小写字母开头，且只能包含小写字母、数字、下划线和连字符。')
    return false
  }
  return true
}

async function save(): Promise<void> {
  if (!validate()) return
  saving.value = true
  try {
    if (editingSourceId.value === null) {
      await createSource({ sourceId: form.sourceId.trim(), enabled: false, ...payload() })
      ElMessage.success('盘口草稿已创建，请在“ERP 业务授权”配置远端账号。')
    } else {
      await updateSource(editingSourceId.value, payload())
      ElMessage.success('盘口配置已保存。')
    }
    sourceDialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '盘口配置保存失败。'))
  } finally {
    saving.value = false
  }
}

async function removeSource(row: SourceConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将永久删除盘口“${row.displayName}”（${row.sourceId}）及其本地映射。该操作无法撤销。`,
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
        <span class="page-eyebrow">Unified market registry</span>
        <h1>盘口配置</h1>
        <p>维护分析与 ERP 共用的盘口主数据、Base URL、时区和只读 API 配置。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button @click="router.push('/erp/remote-connections')">ERP 业务授权</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建盘口</el-button>
      </div>
    </header>

    <el-alert
      title="账号和盘口分离维护"
      description="此页只维护盘口主数据；远端登录账号与 ERP 能力统一在“ERP 业务授权”维护。为保持远端操作禁用，此页不提供连接测试或标签同步。"
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
        <el-table-column label="盘口" min-width="160" prop="displayName" />
        <el-table-column
          label="远端后台 Base URL"
          min-width="280"
          prop="baseUrl"
          show-overflow-tooltip
        />
        <el-table-column label="评分审核 API" width="140">
          <template #default="{ row }">
            <el-tag :type="apiConfigured(row.scoringApiBaseUrl, row.scoringApiKeyConfigured) ? 'success' : 'info'">
              {{ apiConfigured(row.scoringApiBaseUrl, row.scoringApiKeyConfigured) ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="v1版初审 API" width="140">
          <template #default="{ row }">
            <el-tag :type="apiConfigured(row.initialReviewV1ApiBaseUrl, row.initialReviewV1ApiKeyConfigured) ? 'success' : 'info'">
              {{ apiConfigured(row.initialReviewV1ApiBaseUrl, row.initialReviewV1ApiKeyConfigured) ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时区 / 币种" min-width="165">
          <template #default="{ row }">{{ row.businessTimezone }} · {{ row.currency }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <div class="source-actions">
              <el-button text type="primary" :icon="Edit" @click="openEdit(row)">编辑盘口</el-button>
              <el-button text type="primary" @click="router.push('/erp/remote-connections')">管理账号</el-button>
              <el-tooltip :content="row.enabled ? '请先按批准流程停用盘口再删除' : '永久删除盘口'">
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
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="sourceDialogVisible"
      :title="editingSourceId === null ? '新建盘口' : `编辑盘口 ${editingSourceId}`"
      width="620px"
    >
      <el-form label-position="top">
        <el-form-item v-if="editingSourceId === null" label="来源 ID">
          <el-input v-model="form.sourceId" placeholder="例如 rajstar" maxlength="64" />
          <span class="field-help">创建后不可修改；使用小写字母、数字、下划线或连字符。</span>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="盘口显示名"><el-input v-model="form.displayName" /></el-form-item>
          <el-form-item label="业务时区"><el-input v-model="form.businessTimezone" /></el-form-item>
          <el-form-item label="币种"><el-input v-model="form.currency" maxlength="3" /></el-form-item>
        </div>
        <el-form-item label="远端后台 Base URL">
          <el-input v-model="form.baseUrl" placeholder="https://remote-admin.example.com" />
          <span class="field-help">填写后台根地址；不要附带 /api、查询参数或接口路径。</span>
        </el-form-item>
        <el-divider content-position="left">评分审核 API（可选，按盘口配置）</el-divider>
        <el-form-item label="评分审核 API Base URL">
          <el-input v-model="form.scoringApiBaseUrl" placeholder="https://primary.example.com/api" />
        </el-form-item>
        <el-form-item label="评分审核 API Key">
          <el-input
            v-model="form.scoringApiKey"
            :placeholder="scoringApiKeyConfigured ? '已设置，留空则保持原值' : '请输入 API Key'"
            type="password"
            show-password
            autocomplete="off"
          />
        </el-form-item>
        <el-divider content-position="left">v1版初审 API（可选，按盘口配置）</el-divider>
        <el-form-item label="v1版初审 API Base URL">
          <el-input v-model="form.initialReviewV1ApiBaseUrl" placeholder="https://primary.example.com/api" />
        </el-form-item>
        <el-form-item label="v1版初审 API Key">
          <el-input
            v-model="form.initialReviewV1ApiKey"
            :placeholder="initialReviewV1ApiKeyConfigured ? '已设置，留空则保持原值' : '请输入 API Key'"
            type="password"
            show-password
            autocomplete="off"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存盘口</el-button>
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

.source-actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.source-actions > span {
  display: inline-flex;
}

.source-actions :deep(.el-button) {
  margin-left: 0;
  white-space: nowrap;
}
</style>
