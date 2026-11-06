<script setup lang="ts">
import { Document, Download, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import {
  commitErpImport,
  downloadErpImportArtifact,
  fetchErpImportJob,
  fetchErpImportJobs,
  previewErpExcelImport,
  previewErpPasteImport,
} from '../api/erpImports'
import { fetchErpOperatorLines, fetchErpOperators } from '../api/erpOperators'
import { hasErpPermission } from '../stores/auth'
import type {
  ErpDeliveryLine,
  ErpImportConflictStrategy,
  ErpImportJob,
  ErpImportPreview,
} from '../types'

const lines = ref<ErpDeliveryLine[]>([])
const selectedLineId = ref('')
const source = ref<'paste' | 'excel'>('paste')
const pasteText = ref('业务日期\t期初余额\t转U\t消耗\n2026-08-01\t0\t0\t0')
const selectedFile = ref<File | null>(null)
const conflictStrategy = ref<ErpImportConflictStrategy>('SKIP_EXISTING')
const businessYear = ref(new Date().getFullYear())
const preview = ref<ErpImportPreview | null>(null)
const jobs = ref<ErpImportJob[]>([])
const loading = ref(false)
const parsing = ref(false)
const committing = ref(false)

const canCommit = computed(() => Boolean(
  hasErpPermission('ERP_IMPORT')
  && preview.value
  && preview.value.job.errorRows === 0
  && preview.value.job.totalRows > 0,
))

async function load(): Promise<void> {
  loading.value = true
  try {
    const operators = await fetchErpOperators(false)
    lines.value = (await Promise.all(operators.map((operator) => fetchErpOperatorLines(operator.id)))).flat()
    if (!selectedLineId.value && lines.value[0]) selectedLineId.value = lines.value[0].id
    jobs.value = await fetchErpImportJobs()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导入中心加载失败。请确认本地 ERP 数据库已完成初始化。'))
  } finally {
    loading.value = false
  }
}

function pickFile(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  if (file && !file.name.toLowerCase().endsWith('.xlsx')) {
    ElMessage.warning('当前仅支持 .xlsx 文件。')
    return
  }
  selectedFile.value = file
  preview.value = null
}

async function createPreview(): Promise<void> {
  if (!selectedLineId.value) {
    ElMessage.warning('请先选择导入目标投放线。')
    return
  }
  if (source.value === 'excel' && !selectedFile.value) {
    ElMessage.warning('请选择 Excel 文件。')
    return
  }
  parsing.value = true
  try {
    preview.value = source.value === 'paste'
      ? await previewErpPasteImport({
        text: pasteText.value,
        operatorLineId: selectedLineId.value,
        conflictStrategy: conflictStrategy.value,
        businessYear: businessYear.value,
      })
      : await previewErpExcelImport({
        file: selectedFile.value!,
        operatorLineId: selectedLineId.value,
        conflictStrategy: conflictStrategy.value,
        businessYear: businessYear.value,
      })
    await load()
    ElMessage.success('导入预览已生成，请检查后提交。')
  } catch (error) {
    preview.value = null
    ElMessage.error(apiErrorMessage(error, '导入预览失败。'))
  } finally {
    parsing.value = false
  }
}

async function commit(): Promise<void> {
  if (!preview.value) return
  committing.value = true
  try {
    await commitErpImport(preview.value.job.id, conflictStrategy.value)
    ElMessage.success('导入已写入本地 ERP 日结。')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导入提交失败。'))
  } finally {
    committing.value = false
  }
}

async function openJob(job: ErpImportJob): Promise<void> {
  try {
    preview.value = await fetchErpImportJob(job.id)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '导入批次详情加载失败。'))
  }
}

async function download(path: string, filename: string): Promise<void> {
  try {
    await downloadErpImportArtifact(path, filename)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '文件下载失败。'))
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="page-stack">
    <header class="page-header">
      <div><span class="page-eyebrow">ERP local import</span><h1>导入中心</h1><p>先预览、校验并选择冲突策略，再把日结写入当前项目的本地 ERP 台账。</p></div>
      <div class="header-actions"><el-button :icon="Download" @click="download('/erp/imports/template', 'erp-daily-balance-template.xlsx')">标准模板</el-button><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button></div>
    </header>

    <el-alert title="本地预览后提交" description="导入不读取或写入任何远端盘口与业务系统。请在预览中处理错误与重复记录，再提交到本地台账。" type="info" show-icon :closable="false" />

    <section class="surface-card import-form">
      <div class="import-form__grid">
        <el-form-item label="目标投放线"><el-select v-model="selectedLineId" filterable><el-option v-for="line in lines" :key="line.id" :value="line.id" :label="`${line.operatorName} · ${line.name} · ${line.asset}`" /></el-select></el-form-item>
        <el-form-item label="冲突策略"><el-select v-model="conflictStrategy"><el-option label="跳过已有记录" value="SKIP_EXISTING" /><el-option label="更新未确认草稿" value="UPDATE_DRAFT" /><el-option label="遇到重复即拒绝" value="REJECT_ON_CONFLICT" /></el-select></el-form-item>
        <el-form-item label="业务年份"><el-input-number v-model="businessYear" :min="2000" :max="2200" /></el-form-item>
      </div>
      <el-tabs v-model="source"><el-tab-pane label="粘贴表格" name="paste"><el-input v-model="pasteText" type="textarea" :rows="11" placeholder="首行可使用业务日期、期初余额、转U、消耗等列名；也支持标准列顺序。" /></el-tab-pane><el-tab-pane label="Excel (.xlsx)" name="excel"><label class="file-picker"><UploadFilled :size="20" /><input type="file" accept=".xlsx" @change="pickFile" /><span>{{ selectedFile?.name || '选择 .xlsx 文件' }}</span></label></el-tab-pane></el-tabs>
      <el-button v-if="hasErpPermission('ERP_IMPORT')" type="primary" :icon="Document" :loading="parsing" @click="createPreview">生成预览</el-button>
    </section>

    <section v-if="preview" class="surface-card table-card">
      <div class="import-preview-heading"><div><h2>预览结果</h2><p>有效 {{ preview.job.validRows }} 行，警告 {{ preview.job.warningRows }} 行，错误 {{ preview.job.errorRows }} 行。</p></div><el-button v-if="canCommit" type="success" :loading="committing" @click="commit">确认提交本地台账</el-button></div>
      <el-table :data="preview.rows" row-key="id" max-height="420"><el-table-column label="来源" min-width="115"><template #default="{ row }">{{ row.sourceSheet || '—' }} #{{ row.sourceRow || '—' }}</template></el-table-column><el-table-column prop="businessDate" label="业务日期" width="115" /><el-table-column label="状态" width="105"><template #default="{ row }"><el-tag :type="row.severity === 'ERROR' ? 'danger' : row.severity === 'WARNING' ? 'warning' : 'success'">{{ row.severity }}</el-tag></template></el-table-column><el-table-column prop="action" label="预期动作" width="110" /><el-table-column label="说明" min-width="310"><template #default="{ row }">{{ row.errorMessage || '校验通过' }}</template></el-table-column></el-table>
    </section>

    <section class="surface-card table-card"><div class="import-preview-heading"><div><h2>导入历史</h2><p>可回看逐行预检、下载原始文件和错误报告。</p></div></div><el-table :data="jobs" row-key="id" max-height="330"><el-table-column label="创建时间" min-width="170"><template #default="{ row }">{{ new Date(row.createdAt).toLocaleString() }}</template></el-table-column><el-table-column prop="sourceType" label="来源" width="100" /><el-table-column prop="originalFilename" label="文件" min-width="180" /><el-table-column label="有效 / 警告 / 错误" min-width="145"><template #default="{ row }">{{ row.validRows }} / {{ row.warningRows }} / {{ row.errorRows }}</template></el-table-column><el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.status === 'SUCCEEDED' ? 'success' : 'warning'">{{ row.status === 'SUCCEEDED' ? '已提交' : '待提交' }}</el-tag></template></el-table-column><el-table-column label="操作" min-width="235" fixed="right"><template #default="{ row }"><div class="history-actions"><el-button link type="primary" @click="openJob(row)">查看明细</el-button><el-button v-if="row.sourceAvailable" link type="primary" @click="download(`/erp/imports/${row.id}/source`, row.originalFilename || `erp-import-${row.id}.xlsx`)">源文件</el-button><el-button v-if="row.errorReportAvailable" link type="danger" @click="download(`/erp/imports/${row.id}/error-report`, `erp-import-errors-${row.id}.xlsx`)">错误报告</el-button></div></template></el-table-column></el-table></section>
  </div>
</template>

<style scoped>
.import-form { display: grid; gap: 18px; padding: 20px; }
.import-form__grid { display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 0 16px; }
.file-picker { display: flex; align-items: center; gap: 10px; min-height: 220px; padding: 20px; border: 1px dashed var(--el-border-color); border-radius: 8px; color: var(--ink-muted); cursor: pointer; }
.file-picker input { display: none; }
.import-preview-heading { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 14px; }
.import-preview-heading h2 { margin: 0; font-size: 17px; }.import-preview-heading p { margin: 4px 0 0; color: var(--ink-muted); font-size: 13px; }
.history-actions { display: flex; align-items: center; white-space: nowrap; }
@media (max-width: 700px) { .import-form__grid { grid-template-columns: 1fr; } .import-preview-heading { align-items: flex-start; flex-direction: column; } }
</style>
