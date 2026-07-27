<script setup lang="ts">
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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
const currentStep = ref(0)
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

const fileSizeLabel = computed(() => {
  if (!file.value) return ''
  const megabytes = file.value.size / (1024 * 1024)
  return megabytes >= 1
    ? `${megabytes.toFixed(1)} MB`
    : `${Math.max(1, Math.round(file.value.size / 1024))} KB`
})

const paymentTimeOptions = computed<string[]>(() => {
  const headers = detection.value?.detectedHeaders || []
  return [...new Set(headers.map((header) => header.trim()).filter(Boolean))]
})

const uploadReady = computed(() => Boolean(form.sourceId && file.value))
const parsingReady = computed(() =>
  Boolean(detection.value && form.paymentTimeField),
)
const comparisonReady = computed(() =>
  Boolean(
    parsingReady.value &&
      form.selectedChannelCodes.length &&
      timeRange.value &&
      form.remoteTimeField &&
      form.paymentTimezone,
  ),
)

const selectedChannelSummary = computed(() => {
  const selected = channelBindings.value.filter((item) =>
    form.selectedChannelCodes.includes(item.remoteChannelCode),
  )
  if (!selected.length) return '尚未选择'
  return selected
    .map((item) => `${item.remoteChannelCode} · ${item.remoteChannelLabel}`)
    .join('、')
})

function resetAfterParsingChange(): void {
  detection.value = null
  form.paymentTimeField = ''
  timeRange.value = null
  form.selectedChannelCodes = []
}

function goToStep(step: number): void {
  currentStep.value = step
  void nextTick(() => {
    document.querySelector('.wizard-card')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  })
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

async function selectFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0] || null
  if (!selected) return

  if (file.value && (detection.value || currentStep.value > 0)) {
    try {
      await ElMessageBox.confirm(
        '更换文件会清除当前解析结果和已填写的比对参数，是否继续？',
        '确认更换文件',
        {
          type: 'warning',
          confirmButtonText: '更换文件',
          cancelButtonText: '保留原文件',
        },
      )
    } catch {
      input.value = ''
      return
    }
  }

  file.value = selected
  resetAfterParsingChange()
  goToStep(0)
  input.value = ''
}

function continueToParsing(): void {
  if (!form.sourceId || !file.value) {
    ElMessage.warning('请选择已启用盘口并上传支付平台文件。')
    return
  }
  goToStep(1)
}

function handleHeaderRowChange(): void {
  if (!detection.value) return
  resetAfterParsingChange()
  ElMessage.info('表头行已修改，请重新解析表格。')
}

async function parseFile(): Promise<void> {
  if (!file.value) {
    ElMessage.warning('请先选择支付平台导出文件。')
    return
  }
  resetAfterParsingChange()
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

function continueToComparison(): void {
  if (!detection.value) {
    ElMessage.warning('请先解析表格。')
    return
  }
  if (!form.paymentTimeField) {
    ElMessage.warning('请从解析出的表头中选择支付平台时间列。')
    return
  }
  goToStep(2)
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
  if (!form.selectedChannelCodes.length) {
    ElMessage.warning('请至少选择一个远端充值渠道。')
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

watch(
  () => form.sourceId,
  async () => {
    await loadChannels()
    if (selectedSource.value) {
      form.currency = selectedSource.value.currency
    }
  },
)
</script>

<template>
  <div class="page-stack narrow-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">New reconciliation</span>
        <h1>新建比对草稿</h1>
        <p>按步骤上传文件、确认解析结果并配置比对口径；创建草稿不会立即请求远端。</p>
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

    <section class="surface-card wizard-card">
      <div class="wizard-progress">
        <el-steps :active="currentStep" finish-status="success" align-center>
          <el-step title="上传文件" description="选择盘口与支付平台文件" />
          <el-step title="初步解析" description="确认表头与时间列" />
          <el-step title="配置比对" description="确认渠道和时间口径" />
        </el-steps>
      </div>

      <el-form class="wizard-form" label-position="top">
        <section v-if="currentStep === 0" class="wizard-step">
          <div class="step-intro">
            <span class="step-kicker">步骤 1 / 3</span>
            <h2>上传支付平台文件</h2>
            <p>先选择本次比对使用的盘口，再上传支付平台导出的 Excel 或 CSV 文件。</p>
          </div>

          <div class="form-grid">
            <el-form-item label="盘口">
              <el-select
                v-model="form.sourceId"
                placeholder="选择已启用盘口"
                style="width: 100%"
              >
                <el-option
                  v-for="source in sources"
                  :key="source.sourceId"
                  :label="`${source.displayName} · ${source.businessTimezone} · ${source.currency}`"
                  :value="source.sourceId"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="业务类型">
              <div class="static-field">
                <el-tag size="large" type="success">充值 / 代收</el-tag>
                <span>当前首个业务模块</span>
              </div>
            </el-form-item>
          </div>

          <el-form-item label="支付平台导出文件">
            <label class="upload-zone" :class="{ 'is-selected': file }">
              <el-icon><UploadFilled /></el-icon>
              <strong>{{ file?.name || '选择 .xlsx 或 .csv 文件' }}</strong>
              <span v-if="file">
                {{ fileSizeLabel }} · 文件已选择，可进入下一步设置解析参数
              </span>
              <span v-else>订单号始终按文本读取；当前限制 50 MB</span>
              <input type="file" accept=".xlsx,.csv" @change="selectFile" />
            </label>
          </el-form-item>

          <div class="wizard-actions">
            <el-button @click="router.push('/batches')">返回批次中心</el-button>
            <el-button
              type="primary"
              :disabled="!uploadReady"
              @click="continueToParsing"
            >
              下一步：初步解析
            </el-button>
          </div>
        </section>

        <section v-else-if="currentStep === 1" class="wizard-step">
          <article class="completed-step-card">
            <div>
              <span>已选择文件</span>
              <strong>{{ file?.name }}</strong>
              <small>
                {{ selectedSource?.displayName }} · {{ fileSizeLabel }} ·
                {{ selectedSource?.currency }}
              </small>
            </div>
            <el-button text type="primary" @click="goToStep(0)">修改上传</el-button>
          </article>

          <div class="step-intro">
            <span class="step-kicker">步骤 2 / 3</span>
            <h2>初步解析表格</h2>
            <p>确认表头所在行后执行解析，再从真实表头中选择支付平台时间列。</p>
          </div>

          <div class="parse-controls">
            <el-form-item label="表头所在行">
              <el-input-number
                v-model="form.headerRow"
                :min="1"
                :max="100"
                :disabled="parsing"
                @change="handleHeaderRowChange"
              />
              <span class="field-help">
                默认第 1 行；如文件前有说明或空行，请填写实际表头行。
              </span>
            </el-form-item>
            <el-form-item label="解析操作">
              <el-button
                type="primary"
                plain
                :loading="parsing"
                :disabled="!file"
                @click="parseFile"
              >
                {{ parsing ? '正在解析…' : detection ? '重新解析表格' : '解析表格' }}
              </el-button>
              <span class="field-help">解析会读取所选行的字段，但不会启动远端比对。</span>
            </el-form-item>
          </div>

          <el-alert
            v-if="!detection"
            type="info"
            :closable="false"
            show-icon
            title="等待解析"
            description="点击“解析表格”后，系统会识别模板并展示表头字段。"
          />

          <template v-else>
            <el-alert
              :type="detection.status === 'matched' ? 'success' : 'warning'"
              :title="detection.message"
              :description="
                detection.template
                  ? `${detection.template.platformDisplayName} · 模板 V${detection.template.version} · 表头覆盖率 ${Math.round(detection.headerCoverage * 100)}%`
                  : `已读取 ${paymentTimeOptions.length} 个表头；需在后续映射能力中进一步确认模板。`
              "
              show-icon
              :closable="false"
            />

            <div class="parse-result">
              <div class="parse-result-meta">
                <div>
                  <span>工作表</span>
                  <strong>{{ detection.sourceSheet || 'CSV' }}</strong>
                </div>
                <div>
                  <span>表头行</span>
                  <strong>第 {{ detection.headerRow }} 行</strong>
                </div>
                <div>
                  <span>识别字段</span>
                  <strong>{{ paymentTimeOptions.length }} 个</strong>
                </div>
              </div>

              <div class="header-preview">
                <span>表头字段预览</span>
                <div>
                  <el-tag
                    v-for="field in paymentTimeOptions"
                    :key="field"
                    effect="plain"
                  >
                    {{ field }}
                  </el-tag>
                </div>
              </div>

              <el-form-item label="支付平台时间列" required>
                <el-select
                  v-model="form.paymentTimeField"
                  filterable
                  placeholder="从解析出的表头中选择"
                  style="width: 100%"
                >
                  <el-option
                    v-for="field in paymentTimeOptions"
                    :key="field"
                    :label="field"
                    :value="field"
                  />
                </el-select>
                <span class="field-help">
                  该字段用于确认支付平台数据范围，并生成远端查询窗口。
                </span>
              </el-form-item>
            </div>
          </template>

          <div class="wizard-actions">
            <el-button @click="goToStep(0)">上一步：上传文件</el-button>
            <el-button
              type="primary"
              :disabled="!parsingReady"
              @click="continueToComparison"
            >
              下一步：配置比对
            </el-button>
          </div>
        </section>

        <section v-else class="wizard-step">
          <div class="completed-summary-grid">
            <article class="completed-step-card">
              <div>
                <span>上传文件</span>
                <strong>{{ file?.name }}</strong>
                <small>{{ selectedSource?.displayName }} · {{ fileSizeLabel }}</small>
              </div>
              <el-button text type="primary" @click="goToStep(0)">修改</el-button>
            </article>
            <article class="completed-step-card">
              <div>
                <span>解析结果</span>
                <strong>
                  {{ detection?.template?.platformDisplayName || '未匹配模板' }}
                </strong>
                <small>
                  表头第 {{ detection?.headerRow }} 行 · 时间列 {{ form.paymentTimeField }}
                </small>
              </div>
              <el-button text type="primary" @click="goToStep(1)">修改</el-button>
            </article>
          </div>

          <div class="step-intro">
            <span class="step-kicker">步骤 3 / 3</span>
            <h2>配置比对口径</h2>
            <p>确认远端渠道、双方时间口径和查询缓冲；这些参数会随草稿保存。</p>
          </div>

          <div class="comparison-layout">
            <div class="comparison-form">
              <el-form-item label="远端充值渠道" required>
                <el-select
                  v-model="form.selectedChannelCodes"
                  multiple
                  filterable
                  collapse-tags
                  placeholder="至少选择一个渠道"
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
                  当前盘口尚无已登记渠道；请先完成远端渠道字典同步。
                </span>
              </el-form-item>

              <div class="form-grid">
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
                  <el-input
                    :model-value="selectedSource?.businessTimezone || '—'"
                    disabled
                  />
                </el-form-item>
                <el-form-item label="默认币种">
                  <el-input :model-value="form.currency" disabled />
                </el-form-item>
              </div>

              <el-form-item label="支付平台时间范围" required>
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
                <span class="field-help">
                  请选择“{{ form.paymentTimeField }}”字段所覆盖的业务时间范围。
                </span>
              </el-form-item>

              <div class="form-grid">
                <el-form-item label="查询窗口前置缓冲（小时）">
                  <el-input-number
                    v-model="form.bufferBeforeHours"
                    :min="0"
                    :max="168"
                  />
                </el-form-item>
                <el-form-item label="查询窗口后置缓冲（小时）">
                  <el-input-number
                    v-model="form.bufferAfterHours"
                    :min="0"
                    :max="168"
                  />
                </el-form-item>
              </div>
            </div>

            <aside class="review-panel">
              <span class="review-eyebrow">本次比对摘要</span>
              <dl>
                <div>
                  <dt>盘口</dt>
                  <dd>{{ selectedSource?.displayName || '—' }}</dd>
                </div>
                <div>
                  <dt>支付平台时间列</dt>
                  <dd>{{ form.paymentTimeField || '—' }}</dd>
                </div>
                <div>
                  <dt>远端时间字段</dt>
                  <dd>{{ form.remoteTimeField }}</dd>
                </div>
                <div>
                  <dt>远端渠道</dt>
                  <dd>{{ selectedChannelSummary }}</dd>
                </div>
                <div>
                  <dt>支付平台时间范围</dt>
                  <dd>
                    {{
                      timeRange
                        ? `${timeRange[0]} 至 ${timeRange[1]}`
                        : '待确认'
                    }}
                  </dd>
                </div>
                <div>
                  <dt>远端查询扩展</dt>
                  <dd>
                    前 {{ form.bufferBeforeHours }} 小时 / 后
                    {{ form.bufferAfterHours }} 小时
                  </dd>
                </div>
              </dl>
              <p>创建后会进入批次详情页，由用户最终确认并启动远端比对。</p>
            </aside>
          </div>

          <div class="wizard-actions">
            <el-button @click="goToStep(1)">上一步：初步解析</el-button>
            <el-button
              type="primary"
              :loading="loading"
              :disabled="!comparisonReady"
              @click="submit"
            >
              创建比对草稿
            </el-button>
          </div>
        </section>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.wizard-card {
  overflow: hidden;
}

.wizard-progress {
  padding: 28px 36px 24px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, #fbfdff 0%, #f7fafc 100%);
}

.wizard-form {
  padding: 30px 32px 26px;
}

.wizard-step {
  display: grid;
  gap: 24px;
}

.step-intro {
  display: grid;
  gap: 6px;
}

.step-intro h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 23px;
}

.step-intro p {
  margin: 0;
  color: var(--ink-muted);
  line-height: 1.6;
}

.step-kicker,
.review-eyebrow {
  color: var(--teal);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.1em;
}

.static-field {
  display: flex;
  align-items: center;
  min-height: 40px;
  gap: 10px;
}

.static-field span {
  color: var(--ink-muted);
  font-size: 13px;
}

.upload-zone {
  width: 100%;
  min-height: 210px;
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

.upload-zone.is-selected {
  border-color: #7bc9bf;
  background: #f1fbf8;
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
  gap: 22px;
  padding: 20px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: #f8fafc;
}

.parse-controls :deep(.el-form-item) {
  margin-bottom: 0;
}

.field-help {
  display: block;
  margin-top: 6px;
  color: #829ab1;
  font-size: 13px;
  line-height: 1.5;
}

.completed-step-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: 16px;
  padding: 15px 17px;
  border: 1px solid #dfe8ef;
  border-radius: 12px;
  background: #f8fbfd;
}

.completed-step-card > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.completed-step-card span,
.completed-step-card small {
  color: var(--ink-muted);
  font-size: 12px;
}

.completed-step-card strong {
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.completed-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.parse-result {
  display: grid;
  gap: 22px;
  padding: 22px;
  border: 1px solid #d9e7e4;
  border-radius: 14px;
  background: #fbfefd;
}

.parse-result :deep(.el-form-item) {
  margin-bottom: 0;
}

.parse-result-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.parse-result-meta > div {
  display: grid;
  gap: 5px;
  padding: 12px 14px;
  border-radius: 10px;
  background: #eef7f5;
}

.parse-result-meta span,
.header-preview > span {
  color: var(--ink-muted);
  font-size: 12px;
}

.parse-result-meta strong {
  color: var(--ink-strong);
  font-size: 15px;
}

.header-preview {
  display: grid;
  gap: 10px;
}

.header-preview > div {
  display: flex;
  flex-wrap: wrap;
  max-height: 150px;
  gap: 8px;
  overflow-y: auto;
}

.comparison-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(250px, 0.8fr);
  align-items: start;
  gap: 24px;
}

.comparison-form {
  min-width: 0;
}

.review-panel {
  position: sticky;
  top: 20px;
  display: grid;
  gap: 16px;
  padding: 20px;
  border: 1px solid #dce6ef;
  border-radius: 14px;
  background: #f7fafc;
}

.review-panel dl {
  display: grid;
  gap: 0;
  margin: 0;
}

.review-panel dl > div {
  display: grid;
  gap: 4px;
  padding: 11px 0;
  border-bottom: 1px solid #e5ebf0;
}

.review-panel dl > div:last-child {
  border-bottom: 0;
}

.review-panel dt {
  color: var(--ink-muted);
  font-size: 12px;
}

.review-panel dd {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--ink-strong);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.5;
}

.review-panel p {
  margin: 0;
  padding: 12px;
  border-radius: 9px;
  color: #486581;
  background: #eaf2f8;
  font-size: 12px;
  line-height: 1.6;
}

.wizard-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}

@media (max-width: 820px) {
  .comparison-layout {
    grid-template-columns: 1fr;
  }

  .review-panel {
    position: static;
  }
}

@media (max-width: 640px) {
  .wizard-progress {
    padding: 22px 12px 18px;
  }

  .wizard-progress :deep(.el-step__description) {
    display: none;
  }

  .wizard-progress :deep(.el-step__title) {
    font-size: 13px;
  }

  .wizard-form {
    padding: 24px 18px 20px;
  }

  .parse-controls,
  .completed-summary-grid,
  .parse-result-meta {
    grid-template-columns: 1fr;
  }

  .completed-step-card {
    align-items: flex-start;
  }

  .wizard-actions {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .wizard-actions .el-button {
    width: 100%;
    margin-left: 0;
  }
}
</style>
