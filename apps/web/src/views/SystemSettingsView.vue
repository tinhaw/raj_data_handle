<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  fetchRetentionSettings,
  updateRetentionSettings,
} from '../api/systemSettings'
import { isAdmin } from '../stores/auth'
import type { RetentionSettings } from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const current = ref<RetentionSettings | null>(null)
const form = reactive({
  uploadedFileRetentionDays: 3,
  resultRetentionDays: 30,
  remoteCacheRetentionDays: 30,
  withdrawOrderRefreshIntervalHours: 1,
  sessionTtlDays: 30,
})

function applySettings(settings: RetentionSettings): void {
  current.value = settings
  form.uploadedFileRetentionDays = settings.uploadedFileRetentionDays
  form.resultRetentionDays = settings.resultRetentionDays
  form.remoteCacheRetentionDays = settings.remoteCacheRetentionDays
  form.withdrawOrderRefreshIntervalHours = settings.withdrawOrderRefreshIntervalHours
  form.sessionTtlDays = settings.sessionTtlDays
}

async function load(): Promise<void> {
  loading.value = true
  try {
    applySettings(await fetchRetentionSettings())
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '系统配置加载失败。'))
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    applySettings(await updateRetentionSettings({ ...form }))
    ElMessage.success('系统配置已更新；提现订单下次进入页面时会使用新的刷新间隔。')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '保留策略保存失败。'))
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
        <span class="page-eyebrow">System settings</span>
        <h1>系统配置</h1>
        <p>当前配置对所有用户可见；只有超级管理员可以修改。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert
      title="保留时间按创建时配置固化"
      description="修改默认值不会追溯改变已有文件、批次或远端缓存的过期时间。"
      type="info"
      show-icon
      :closable="false"
    />

    <el-alert
      title="登录有效期从成功登录时开始计时"
      description="会话不会因访问页面自动续期；修改时长只影响之后的新登录，不会追溯改变现有会话。"
      type="warning"
      show-icon
      :closable="false"
    />

    <section v-loading="loading" class="surface-card settings-card">
      <div class="settings-heading">
        <div>
          <h2>全局配置</h2>
          <p>登录、提现订单与数据保留策略集中维护。</p>
        </div>
        <el-tag v-if="current" type="info">配置版本 V{{ current.configVersion }}</el-tag>
      </div>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>登录与会话</h2>
          <p>超级管理员可调整后续登录会话的最长有效期。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="登录有效时长（天）">
              <el-input-number
                v-model="form.sessionTtlDays"
                :min="1"
                :max="365"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；到期后需重新登录。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>提现订单刷新</h2>
          <p>配置提现订单页面的统一自动刷新频率。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动刷新间隔（小时）">
              <el-input-number
                v-model="form.withdrawOrderRefreshIntervalHours"
                :min="1"
                :max="24"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">允许范围为 1–24 小时；保存后由提现订单页面使用。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>数据保留策略</h2>
          <p>允许范围为 1–3650 天。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="上传与导出文件">
              <el-input-number
                v-model="form.uploadedFileRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 3 天；最后一个有效引用过期后才清理物理文件。</span>
            </el-form-item>
            <el-form-item label="批次与订单级结果">
              <el-input-number
                v-model="form.resultRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；到期后不再保留订单级业务明细。</span>
            </el-form-item>
            <el-form-item label="远端订单缓存">
              <el-input-number
                v-model="form.remoteCacheRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；活跃批次引用的数据不会被清理。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <footer class="settings-footer">
        <span v-if="current">最后更新：{{ formatDateTime(current.updatedAt) }}</span>
        <el-button v-if="isAdmin" type="primary" :loading="saving" @click="save">
          保存配置
        </el-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.settings-card {
  padding: 24px;
}

.settings-heading,
.settings-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.settings-heading {
  margin-bottom: 22px;
}

.settings-heading h2,
.settings-heading p,
.settings-section-heading h2,
.settings-section-heading p {
  margin: 0;
}

.settings-heading p,
.settings-section-heading p,
.settings-footer,
.field-help {
  color: var(--ink-muted);
}

.settings-heading p,
.settings-section-heading p,
.field-help {
  font-size: 13px;
}

.settings-section {
  padding: 20px 0;
  border-top: 1px solid var(--border);
}

.settings-section + .settings-section {
  margin-top: 4px;
}

.settings-section-heading {
  margin-bottom: 16px;
}

.field-help {
  display: block;
  margin-top: 8px;
  line-height: 1.5;
}

.settings-footer {
  margin-top: 8px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
</style>
