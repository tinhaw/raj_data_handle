<script setup lang="ts">
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { createBatch } from '../api/batches'
import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import {
  detectPaymentTemplate,
  fetchPaymentChannelBindings,
} from '../api/paymentTemplates'
import type {
  PaymentChannelBinding,
  SourceConfig,
  TemplateDetection,
} from '../types'

const router = useRouter()
const loading = ref(false)
const parsing = ref(false)
const sources = ref<SourceConfig[]>([])
const channelBindings = ref<PaymentChannelBinding[]>([])
const file = ref<File | null>(null)
const detection = ref<TemplateDetection | null>(null)
const timeRange = ref<[string, string] | null>(null)
const form = reactive({
  sourceId: '',
  businessType: 'payin' as const,
  headerRow: 1,
  selectedChannelCodes: [] as string[],
  paymentTimeField: '',
  paymentTimezone: 'Asia/Kolkata',
  remoteTimeField: 'create_time',
  bufferBeforeHours: 24,
  bufferAfterHours: 24,
  currency: 'INR',
})

const selectedSource = computed(() =>
  sources.value.find((source) => source.sourceId === form.sourceId),
)

const paymentTimeOptions = computed<string[]>(() => {
  const headers = detection.value?.detectedHeaders || []
  return [...new Set(headers.map((header) => header.trim()).filter(Boolean))]
})

function resetParsedFile(): void {
  detection.value = null
  form.paymentTimeField = ''
  timeRange.value = null
}

function preferredPaymentTimeField(): string {
  const configuredCandidates = detection.value?.template?.columnMapping
    .candidate_time_fields
  const templateCandidate = Array.isArray(configuredCandidates)
    ? configuredCandidates.find(
        (field): field is string =>
          typeof field === 'string' && paymentTimeOptions.value.includes(field),
      )
    : undefined
  if (templateCandidate) return templateCandidate
  return (
    paymentTimeOptions.value.find((field) => /时间|日期|time|date/i.test(field)) ||
    ''
  )
}

function selectFile(event: Event): void {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] || null
  resetParsedFile()
}

async function parseFile(): Promise<void> {
  if (!file.value) {
    ElMessage.warning('请先选择支付平台导出文件。')
    return
  }
  resetParsedFile()
  parsing.value = true
  try {
    detection.value = await detectPaymentTemplate(file.value, form.headerRow)
    form.paymentTimeField = preferredPaymentTimeField()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '文件模板探测失败。'))
  } finally {
    parsing.value = false
  }
}

async function loadChannels(): Promise<void> {
  form.selectedChannelCodes = []
  if (!form.sourceId) {
    channelBindings.value = []
    return
  }
  try {
    channelBindings.value = await fetchPaymentChannelBindings({
      sourceId: form.sourceId,
      businessType: 'payin',
    })
  } catch {
    channelBindings.value = []
  }
}

async function submit(): Promise<void> {
  if (!form.sourceId || !file.value || !detection.value) {
    ElMessage.warning('请选择已启用盘口，上传文件并完成表格解析。')
    return
  }
  if (!form.paymentTimeField || !timeRange.value) {
    ElMessage.warning('请从解析出的表头中选择支付平台时间列，并确认时间范围。')
    return
  }
  loading.value = true
  try {
    const result = await createBatch({
      sourceId: form.sourceId,
      businessType: form.businessType,
      headerRow: form.headerRow,
      file: file.value,
      parameters: {
        selectedChannels: channelBindings.value
          .filter((item) => form.selectedChannelCodes.includes(item.remoteChannelCode))
          .map((item) => ({
            code: item.remoteChannelCode,
            label: item.remoteChannelLabel,
            platformKey: item.platformKey,
          })),
        comparisonWindow: {
          start: timeRange.value[0],
          end: timeRange.value[1],
          paymentTimeField: form.paymentTimeField,
          paymentTimezone: form.paymentTimezone,
          remoteTimeField: form.remoteTimeField,
          remoteBusinessTimezone: selectedSource.value?.businessTimezone,
          bufferBeforeHours: form.bufferBeforeHours,
          bufferAfterHours: form.bufferAfterHours,
        },
        currency: form.currency,
      },
    })
    if (result.duplicateOfExisting) {
      ElMessage.info('检测到相同文件和参数，已打开已有批次。')
    } else {
      ElMessage.success('比对草稿已创建。')
    }
    await router.push(`/batches/${result.batch.id}`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '创建批次失败。'))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    sources.value = await fetchEnabledSources()
  } catch {
    sources.value = []
  }
})

watch(() => form.sourceId, loadChannels)
</script>

<template>
  <div class="page-stack narrow-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">New reconciliation</span>
        <h1>新建比对草稿</h1>
        <p>上传代收明细，确认盘口、渠道、时间口径和币种；创建草稿不会立即请求远端。</p>
      </div>
    </header>

    <el-alert
      v-if="!sources.length"
      type="warning"
      :closable="false"
      show-icon
      title="当前没有已启用盘口"
      description="管理员需先完成 Base URL、加密凭据和连接测试，启用盘口后才能创建批次。"
    />

    <section class="surface-card form-card">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="盘口">
            <el-select v-model="form.sourceId" placeholder="选择已启用盘口" style="width: 100%">
              <el-option
                v-for="source in sources"
                :key="source.sourceId"
                :label="`${source.displayName} · ${source.businessTimezone} · ${source.currency}`"
                :value="source.sourceId"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="业务类型">
            <el-tag size="large" type="success">充值 / 代收（首个业务模块）</el-tag>
          </el-form-item>
        </div>

        <el-divider content-position="left">1. 上传支付平台导出文件</el-divider>
        <el-form-item label="支付平台导出文件">
          <label class="upload-zone">
            <el-icon><UploadFilled /></el-icon>
            <strong>{{ file?.name || '选择 .xlsx 或 .csv 文件' }}</strong>
            <span>
              {{ file ? '文件已选择，请设置表头行后解析。' : '订单号始终按文本读取；当前限制 50 MB' }}
            </span>
            <input type="file" accept=".xlsx,.csv" @change="selectFile" />
          </label>
        </el-form-item>

        <el-divider content-position="left">2. 设置表头并解析</el-divider>
        <div class="parse-controls">
          <el-form-item label="表头所在行">
            <el-input-number
              v-model="form.headerRow"
              :min="1"
              :max="100"
              :disabled="parsing"
              @change="resetParsedFile"
            />
            <span class="field-help">默认第 1 行；如文件前有说明或空行，请先填写实际表头行再解析。</span>
          </el-form-item>
          <el-form-item label="解析操作">
            <el-button
              type="primary"
              plain
              :loading="parsing"
              :disabled="!file"
              @click="parseFile"
            >
              {{ parsing ? '正在解析…' : '解析表格' }}
            </el-button>
            <span class="field-help">解析后才会提供支付平台时间列和后续比较口径。</span>
          </el-form-item>
        </div>

        <el-alert
          v-if="detection"
          :type="detection.status === 'matched' ? 'success' : 'warning'"
          :title="detection.message"
          :description="
            detection.template
              ? `${detection.template.platformDisplayName} · 模板 V${detection.template.version} · 表头覆盖率 ${Math.round(detection.headerCoverage * 100)}%`
              : `已读取 ${detection.detectedHeaders.filter(Boolean).length} 个表头；需在映射向导中确认。`
          "
          show-icon
          :closable="false"
        />

        <el-alert
          v-else
          type="info"
          :closable="false"
          show-icon
          title="请先解析表格"
          description="选择文件后，确认表头所在行并点击“解析表格”。系统会读取该行字段，再提供时间列与比较口径。"
        />

        <template v-if="detection">
          <el-divider content-position="left">3. 比较口径（草稿快照）</el-divider>
          <el-form-item label="远端充值渠道">
            <el-select
              v-model="form.selectedChannelCodes"
              multiple
              filterable
              collapse-tags
              placeholder="可多选；启动比对前至少确认一个渠道"
              style="width: 100%"
            >
              <el-option
                v-for="channel in channelBindings"
                :key="channel.id"
                :label="`${channel.remoteChannelCode} · ${channel.remoteChannelLabel}`"
                :value="channel.remoteChannelCode"
              />
            </el-select>
            <span v-if="form.sourceId && !channelBindings.length" class="field-help">
              当前盘口尚无已登记渠道；后续连接器会从远端渠道字典同步。
            </span>
          </el-form-item>

          <div class="form-grid">
            <el-form-item label="支付平台时间列">
              <el-select
                v-model="form.paymentTimeField"
                placeholder="请选择解析出的表头字段"
                style="width: 100%"
              >
                <el-option
                  v-for="field in paymentTimeOptions"
                  :key="field"
                  :label="field"
                  :value="field"
                />
              </el-select>
              <span class="field-help">选项来自第 {{ detection.headerRow }} 行解析出的表头。</span>
            </el-form-item>
            <el-form-item label="远端对应时间字段">
              <el-select v-model="form.remoteTimeField" style="width: 100%">
                <el-option label="创建时间（create_time）" value="create_time" />
                <el-option label="支付时间（pay_time）" value="pay_time" />
              </el-select>
            </el-form-item>
            <el-form-item label="支付平台时区">
              <el-input v-model="form.paymentTimezone" />
            </el-form-item>
            <el-form-item label="盘口业务时区">
              <el-input :model-value="selectedSource?.businessTimezone || '选择盘口后显示'" disabled />
            </el-form-item>
          </div>

          <el-form-item label="用户确认的支付平台时间范围">
            <el-date-picker
              v-model="timeRange"
              type="datetimerange"
              value-format="YYYY-MM-DD HH:mm:ss"
              format="YYYY-MM-DD HH:mm:ss"
              range-separator="至"
              start-placeholder="开始时间"
              end-placeholder="结束时间"
              style="width: 100%"
            />
          </el-form-item>

          <div class="form-grid">
            <el-form-item label="查询窗口前置缓冲（小时）">
              <el-input-number v-model="form.bufferBeforeHours" :min="0" :max="168" />
            </el-form-item>
            <el-form-item label="查询窗口后置缓冲（小时）">
              <el-input-number v-model="form.bufferAfterHours" :min="0" :max="168" />
            </el-form-item>
            <el-form-item label="默认币种">
              <el-select v-model="form.currency" style="width: 100%">
                <el-option label="INR · 印度卢比" value="INR" />
              </el-select>
            </el-form-item>
          </div>
        </template>

        <div class="form-actions">
          <el-button @click="router.push('/batches')">返回</el-button>
          <el-button type="primary" :loading="loading" :disabled="!sources.length" @click="submit">
            创建草稿
          </el-button>
        </div>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.upload-zone {
  width: 100%;
  min-height: 190px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  border: 1.5px dashed #9fb3c8;
  border-radius: 14px;
  color: #486581;
  background: #f7fafc;
  cursor: pointer;
  transition: 0.2s ease;
}

.upload-zone:hover {
  border-color: #2a9d8f;
  background: #f0fbf9;
}

.upload-zone .el-icon {
  color: #2a9d8f;
  font-size: 34px;
}

.upload-zone span {
  color: #829ab1;
  font-size: 13px;
}

.upload-zone input {
  display: none;
}

.parse-controls {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.field-help {
  display: block;
  margin-top: 6px;
  color: #829ab1;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 720px) {
  .parse-controls {
    grid-template-columns: 1fr;
  }
}
</style>
