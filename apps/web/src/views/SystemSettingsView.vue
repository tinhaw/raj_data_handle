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
import type {
  ChargeOrderExportDateMode,
  RetentionSettings,
  WithdrawOrderQueryRange,
  WithdrawOrderRefreshPageSize,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const current = ref<RetentionSettings | null>(null)
const form = reactive({
  uploadedFileRetentionDays: 3,
  resultRetentionDays: 30,
  remoteCacheRetentionDays: 30,
  withdrawOrderRefreshIntervalHours: 1,
  withdrawOrderRefreshPageSize: 100 as WithdrawOrderRefreshPageSize,
  withdrawOrderQueryRange: 'today' as WithdrawOrderQueryRange,
  chargeOrderExportDateMode: 'previous_day' as ChargeOrderExportDateMode,
  chargeOrderExportSpecificDate: null as string | null,
  sessionTtlDays: 30,
})

const orderQueryRangeOptions: Array<{
  value: WithdrawOrderQueryRange
  label: string
  description: string
}> = [
  {
    value: 'today',
    label: '今日 00:00:00 至 23:59:59',
    description: '按盘口业务时区获取当天订单；未来时间会在同步时自动截断。',
  },
  {
    value: 'last_1_hour',
    label: '最近 1 小时',
    description: '从同步执行时刻向前滚动 1 小时。',
  },
  {
    value: 'last_2_hours',
    label: '最近 2 小时',
    description: '从同步执行时刻向前滚动 2 小时。',
  },
  {
    value: 'last_3_hours',
    label: '最近 3 小时',
    description: '从同步执行时刻向前滚动 3 小时。',
  },
  {
    value: 'last_6_hours',
    label: '最近 6 小时',
    description: '从同步执行时刻向前滚动 6 小时。',
  },
  {
    value: 'last_12_hours',
    label: '最近 12 小时',
    description: '从同步执行时刻向前滚动 12 小时。',
  },
  {
    value: 'last_24_hours',
    label: '最近 24 小时',
    description: '从同步执行时刻向前滚动 24 小时。',
  },
  {
    value: 'last_48_hours',
    label: '最近 48 小时',
    description: '从同步执行时刻向前滚动 48 小时。',
  },
]

const orderRefreshPageSizeOptions: Array<{
  value: WithdrawOrderRefreshPageSize
  label: string
}> = ([10, 20, 30, 50, 100] as WithdrawOrderRefreshPageSize[]).map((value) => ({
  value,
  label: `${value} 条/页`,
}))

function applySettings(settings: RetentionSettings): void {
  current.value = settings
  form.uploadedFileRetentionDays = settings.uploadedFileRetentionDays
  form.resultRetentionDays = settings.resultRetentionDays
  form.remoteCacheRetentionDays = settings.remoteCacheRetentionDays
  form.withdrawOrderRefreshIntervalHours = settings.withdrawOrderRefreshIntervalHours
  form.withdrawOrderRefreshPageSize = settings.withdrawOrderRefreshPageSize
  form.withdrawOrderQueryRange = settings.withdrawOrderQueryRange
  form.chargeOrderExportDateMode = settings.chargeOrderExportDateMode
  form.chargeOrderExportSpecificDate = settings.chargeOrderExportSpecificDate
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
    ElMessage.success('系统配置已更新；订单后台同步会在下一个周期使用新的规则。')
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
      title="保留策略的生效范围"
      description="修改文件、批次及订单级结果的默认值不会追溯改变已有数据；充值和提现订单本地缓存按当前缓存保留天数清理。"
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
          <p>登录、充值订单、提现订单与数据保留策略集中维护。</p>
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
          <h2>充值订单 Excel 导出同步</h2>
          <p>按盘口业务时区每天导出一个自然日；充值订单页只查询本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动导出时间（盘口业务时区）">
              <el-input model-value="每日 00:00:01" disabled />
              <span class="field-help">每天印度时间 00:00:01 开始导出；工作进程轮询触发时会自动补跑。</span>
            </el-form-item>
            <el-form-item label="自动导出日期">
              <el-select v-model="form.chargeOrderExportDateMode" :disabled="!isAdmin">
                <el-option
                  label="前一天"
                  value="previous_day"
                />
                <el-option label="指定日期（仅执行一次）" value="specific_date" />
              </el-select>
              <span class="field-help">
                默认导出前一天 00:00:00 至 23:59:59；指定日期成功导出后不会在下一天重复执行。
              </span>
            </el-form-item>
            <el-form-item
              v-if="form.chargeOrderExportDateMode === 'specific_date'"
              label="指定导出日期（盘口业务时区）"
            >
              <el-date-picker
                v-model="form.chargeOrderExportSpecificDate"
                type="date"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">仅导出该自然日的充值订单，需填写后才可保存。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>提现订单后台同步</h2>
          <p>后台按统一规则从远端同步；提现订单页仅查询本地数据。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="后台刷新间隔（小时）">
              <el-input-number
                v-model="form.withdrawOrderRefreshIntervalHours"
                :min="1"
                :max="24"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">允许范围为 1–24 小时；后台按此周期执行同步。</span>
            </el-form-item>
            <el-form-item label="后台单次请求条数">
              <el-select v-model="form.withdrawOrderRefreshPageSize" :disabled="!isAdmin">
                <el-option
                  v-for="option in orderRefreshPageSizeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <span class="field-help">
                每次请求远端提现订单的分页大小；默认 100 条/页。仅影响后台同步，不影响本地列表分页。
              </span>
            </el-form-item>
            <el-form-item label="后台查询时间范围">
              <el-select v-model="form.withdrawOrderQueryRange" :disabled="!isAdmin">
                <el-option
                  v-for="option in orderQueryRangeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <span class="field-help">
                {{
                  orderQueryRangeOptions.find(
                    (option) => option.value === form.withdrawOrderQueryRange,
                  )?.description
                }}
              </span>
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

.settings-card :deep(.el-select) {
  width: 100%;
}

.settings-footer {
  margin-top: 8px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}
</style>
