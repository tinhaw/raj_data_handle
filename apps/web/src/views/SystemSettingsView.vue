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
  SpinOrderQueryRange,
  SpinOrderRefreshIntervalHours,
  SpinOrderRefreshPageSize,
  WithdrawOrderExportDateMode,
} from '../types'
import { formatDateTime } from '../ui'

const loading = ref(false)
const saving = ref(false)
const current = ref<RetentionSettings | null>(null)
const form = reactive({
  uploadedFileRetentionDays: 3,
  resultRetentionDays: 30,
  remoteCacheRetentionDays: 30,
  syncLogRetentionDays: 30,
  withdrawOrderExportDateMode: 'previous_day' as WithdrawOrderExportDateMode,
  withdrawOrderExportSpecificDate: null as string | null,
  withdrawOrderExportTime: '00:05:01',
  automaticSyncRetryLimit: 3,
  automaticSyncRetryIntervalMinutes: 5,
  remoteOrderSyncTimeoutSeconds: 180,
  chargeOrderExportDateMode: 'previous_day' as ChargeOrderExportDateMode,
  chargeOrderExportSpecificDate: null as string | null,
  chargeOrderExportTime: '00:00:01',
  spinOrderRefreshIntervalHours: 2 as SpinOrderRefreshIntervalHours,
  spinOrderRefreshPageSize: 100 as SpinOrderRefreshPageSize,
  spinOrderQueryRange: 'previous_business_day_to_completed_slot' as SpinOrderQueryRange,
  sessionTtlDays: 30,
})

function applySettings(settings: RetentionSettings): void {
  current.value = settings
  form.uploadedFileRetentionDays = settings.uploadedFileRetentionDays
  form.resultRetentionDays = settings.resultRetentionDays
  form.remoteCacheRetentionDays = settings.remoteCacheRetentionDays
  form.syncLogRetentionDays = settings.syncLogRetentionDays
  form.withdrawOrderExportDateMode = settings.withdrawOrderExportDateMode
  form.withdrawOrderExportSpecificDate = settings.withdrawOrderExportSpecificDate
  form.withdrawOrderExportTime = settings.withdrawOrderExportTime
  form.automaticSyncRetryLimit = settings.automaticSyncRetryLimit
  form.automaticSyncRetryIntervalMinutes = settings.automaticSyncRetryIntervalMinutes
  form.remoteOrderSyncTimeoutSeconds = settings.remoteOrderSyncTimeoutSeconds
  form.chargeOrderExportDateMode = settings.chargeOrderExportDateMode
  form.chargeOrderExportSpecificDate = settings.chargeOrderExportSpecificDate
  form.chargeOrderExportTime = settings.chargeOrderExportTime
  form.spinOrderRefreshIntervalHours = settings.spinOrderRefreshIntervalHours
  form.spinOrderRefreshPageSize = settings.spinOrderRefreshPageSize
  form.spinOrderQueryRange = settings.spinOrderQueryRange
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
    ElMessage.success('系统配置已更新；订单同步会在下一个周期使用新的规则。')
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
      description="修改文件、批次及订单级结果的默认值不会追溯改变已有数据；充值、提现和转盘订单本地缓存按当前缓存保留天数清理。"
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
          <p>登录、充值订单、提现订单、转盘订单、同步日志与数据保留策略集中维护。</p>
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
          <h2>远端订单同步超时</h2>
          <p>适用于充值、提现、转盘和评分审核订单的远端读取与 Excel 下载；不影响盘口连接测试。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="请求超时（秒）">
              <el-input-number
                v-model="form.remoteOrderSyncTimeoutSeconds"
                :min="30"
                :max="600"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 180 秒；连接建立仍最多等待 10 秒。新同步任务会使用保存后的值。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>自动同步失败重试</h2>
          <p>适用于充值、提现和转盘订单的自动任务；不影响管理员手动刷新。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="失败后最大重试次数">
              <el-input-number
                v-model="form.automaticSyncRetryLimit"
                :min="0"
                :max="10"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">不包含首次自动同步；设为 0 表示当天窗口失败后不再自动重试。</span>
            </el-form-item>
            <el-form-item label="重试间隔（分钟）">
              <el-input-number
                v-model="form.automaticSyncRetryIntervalMinutes"
                :min="1"
                :max="1440"
                :precision="0"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认每 5 分钟重试一次；达到次数上限后，等待下一个自动同步窗口。</span>
            </el-form-item>
          </div>
        </el-form>
      </section>

      <section class="settings-section">
        <div class="settings-section-heading">
          <h2>转盘订单远端同步</h2>
          <p>自动同步只读取远端数据，转盘订单页展示本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动刷新间隔（小时）">
              <el-select v-model="form.spinOrderRefreshIntervalHours" :disabled="!isAdmin">
                <el-option
                  v-for="hours in [1, 2, 3, 4, 6, 8, 12, 24]"
                  :key="hours"
                  :label="`每 ${hours} 小时`"
                  :value="hours"
                />
              </el-select>
              <span class="field-help">默认每 2 小时；每个时段开始 5 分钟后读取已完成时段的数据。</span>
            </el-form-item>
            <el-form-item label="自动查询时间范围">
              <el-select v-model="form.spinOrderQueryRange" :disabled="!isAdmin">
                <el-option label="仅上一完整时段" value="last_completed_slot" />
                <el-option label="最近 2 小时" value="last_2_hours" />
                <el-option label="最近 3 小时" value="last_3_hours" />
                <el-option label="最近 6 小时" value="last_6_hours" />
                <el-option label="最近 12 小时" value="last_12_hours" />
                <el-option label="前一天" value="previous_day" />
                <el-option
                  label="本业务日 00:00 至上一完整时段"
                  value="business_day_to_completed_slot"
                />
                <el-option
                  label="前一业务日 00:00 至上一完整时段（默认）"
                  value="previous_business_day_to_completed_slot"
                />
              </el-select>
              <span class="field-help">按各盘口业务时区计算；最近 N 小时截至上一完整时段，回查范围越长越能覆盖延迟审核状态。</span>
            </el-form-item>
            <el-form-item label="远端分页大小">
              <el-select v-model="form.spinOrderRefreshPageSize" :disabled="!isAdmin">
                <el-option
                  v-for="size in [10, 20, 30, 50, 100]"
                  :key="size"
                  :label="`${size} 条 / 页`"
                  :value="size"
                />
              </el-select>
              <span class="field-help">默认 100 条 / 页；数值越小，远端请求次数越多。</span>
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
              <el-time-picker
                v-model="form.chargeOrderExportTime"
                value-format="HH:mm:ss"
                format="HH:mm:ss"
                :clearable="false"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">每天按各盘口业务时区的该时刻开始导出；工作进程每 30 秒轮询，会自动补跑。</span>
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
          <h2>提现订单 Excel 导出同步</h2>
          <p>按盘口业务时区每天导出一个自然日；提现订单页只查询本地缓存。</p>
        </div>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="自动导出时间（盘口业务时区）">
              <el-time-picker
                v-model="form.withdrawOrderExportTime"
                value-format="HH:mm:ss"
                format="HH:mm:ss"
                :clearable="false"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">每天按各盘口业务时区的该时刻开始导出；若对应盘口的评分审核 API 已配置并测试通过，完成后会继续同步评分审核 Excel。</span>
            </el-form-item>
            <el-form-item label="自动导出日期">
              <el-select v-model="form.withdrawOrderExportDateMode" :disabled="!isAdmin">
                <el-option label="前一天" value="previous_day" />
                <el-option label="指定日期（仅执行一次）" value="specific_date" />
              </el-select>
              <span class="field-help">
                默认导出前一天 00:00:00 至 23:59:59；指定日期成功导出后不会在下一天重复执行。
              </span>
            </el-form-item>
            <el-form-item
              v-if="form.withdrawOrderExportDateMode === 'specific_date'"
              label="指定导出日期（盘口业务时区）"
            >
              <el-date-picker
                v-model="form.withdrawOrderExportSpecificDate"
                type="date"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                :disabled="!isAdmin"
                style="width: 100%"
              />
              <span class="field-help">仅导出该自然日的提现订单，需填写后才可保存。</span>
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
            <el-form-item label="同步运行日志">
              <el-input-number
                v-model="form.syncLogRetentionDays"
                :min="1"
                :max="3650"
                :disabled="!isAdmin"
              />
              <span class="field-help">默认 30 天；保留同步、导入、失败和部分完成的执行记录，不保留远端请求内容或原始 Excel。</span>
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
