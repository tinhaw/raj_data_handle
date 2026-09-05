<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { UploadFile } from 'element-plus'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Download, UploadFilled } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import type { ImportJob, ImportJobDetail, ImportJobRow, ImportPreview, Operator, OperatorAccount } from '@/api/types'
import StatusTag from '@/components/StatusTag.vue'
import { demoAccounts, demoOperators } from '@/utils/demo-data'
import { useSessionStore } from '@/stores/session'
import { saveDownloadedFile } from '@/utils/download'
import { demoEnabled } from '@/utils/runtime'
import { percent, previewCalculation, toDecimal } from '@/utils/money'
import {
  buildWorksheetTsv,
  createWorksheetRow,
  createWorksheetRows,
  DEFAULT_WORKSHEET_COLUMNS,
  fillWorksheetMissingAmounts,
  hasWorksheetHeader,
  isIgnoredWorksheetHeader,
  isSafeIgnoredWorksheetHeader,
  parseClipboardMatrix,
  rowHasWorksheetData,
  validateWorksheet,
  worksheetHeaderKey,
  worksheetIdentityHeaderKey,
  type WorksheetColumn,
  type WorksheetColumnKey,
  type WorksheetRow,
} from './paste-worksheet'

type SourceTab = 'paste' | 'excel'
type WorksheetFeeKind = 'exchange' | 'service'

interface WorksheetContextMenu {
  x: number
  y: number
  rowIndex: number
  columnIndex: number
}

function defaultBusinessYear() {
  const parts = new Intl.DateTimeFormat('en-US', { year: 'numeric', timeZone: 'Asia/Shanghai' }).formatToParts(new Date())
  const year = parts.find((part) => part.type === 'year')?.value
  return year || new Date().toISOString().slice(0, 4)
}

const source = ref<SourceTab>('paste')
const selectedFile = ref<File | null>(null)
const operators = ref<Operator[]>([])
const accounts = ref<OperatorAccount[]>([])
const pasteCompanyId = ref<string | number>('')
const pasteAccountId = ref<string | number>('')
const excelCompanyId = ref<string | number>('')
const excelAccountId = ref<string | number>('')
const businessYear = ref(defaultBusinessYear())
const excelBusinessYear = ref(defaultBusinessYear())
const worksheetColumns = ref<WorksheetColumn[]>(DEFAULT_WORKSHEET_COLUMNS.map((column) => ({ ...column })))
const worksheetRows = ref<WorksheetRow[]>(createWorksheetRows())
const draggedColumnIndex = ref<number | null>(null)
const worksheetContextMenu = ref<WorksheetContextMenu | null>(null)
const preview = ref<ImportPreview | null>(null)
const parsing = ref(false)
const committing = ref(false)
const downloadingTemplate = ref(false)
const conflictStrategy = ref('SKIP_EXISTING')
const loadError = ref('')
const usingDemo = ref(false)
const historyDialog = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const importJobs = ref<ImportJob[]>([])
const historyDetailDrawer = ref(false)
const historyDetailLoading = ref(false)
const historyDetailError = ref('')
const historyDetail = ref<ImportJobDetail | null>(null)
const sourceDownloading = ref(false)
const errorReportDownloading = ref(false)
const previewPanelRef = ref<HTMLElement | null>(null)
const session = useSessionStore()
let importInputRevision = 0
let parseRequestId = 0

const previewRows = computed(() => preview.value?.rows || [])
const canCommit = computed(() => Boolean(preview.value && preview.value.errorRows === 0 && preview.value.validRows > 0))
const historyRows = computed(() => historyDetail.value?.rows || [])
const activeCompanies = computed(() => operators.value.filter((operator) => operator.status === 'ACTIVE'))
const activeAccounts = computed(() => accounts.value.filter((account) => account.status === 'ACTIVE'))
const availablePasteAccounts = computed(() => pasteCompanyId.value === ''
  ? []
  : activeAccounts.value.filter((account) => String(account.operatorId) === String(pasteCompanyId.value)))
const availableExcelAccounts = computed(() => excelCompanyId.value === ''
  ? []
  : activeAccounts.value.filter((account) => String(account.operatorId) === String(excelCompanyId.value)))
const selectedWorksheetAccount = computed(() => availablePasteAccounts.value.find((account) => String(account.id) === String(pasteAccountId.value)) || null)
const selectedWorksheetLineLabel = computed(() => selectedWorksheetAccount.value ? deliveryLineLabel(selectedWorksheetAccount.value) : '')
const worksheetValidation = computed(() => validateWorksheet(worksheetRows.value, businessYear.value))
const worksheetDataRowCount = computed(() => worksheetRows.value.filter(rowHasWorksheetData).length)
const worksheetErrorCount = computed(() => worksheetValidation.value.errors.length)
const worksheetWarningCount = computed(() => worksheetValidation.value.warnings.length)
const worksheetErrorsSummary = computed(() => worksheetValidation.value.errors.slice(0, 4))
const worksheetWarningsSummary = computed(() => worksheetValidation.value.warnings.slice(0, 3))
const canImport = computed(() => {
  const user = session.user
  return Boolean(user?.permissions.includes('*') || user?.permissions.includes('IMPORT') || user?.roles.includes('SUPER_ADMIN'))
})

function markWorksheetChanged() {
  importInputRevision += 1
  preview.value = null
}

function onWorksheetScopeChanged() {
  const hadPreview = Boolean(preview.value)
  markWorksheetChanged()
  if (hadPreview) ElMessage.info('导入范围已变更，请重新解析')
}

function onWorksheetCompanyChanged() {
  if (!availablePasteAccounts.value.some((account) => String(account.id) === String(pasteAccountId.value))) {
    pasteAccountId.value = ''
  }
  onWorksheetScopeChanged()
}

function onExcelCompanyChanged() {
  if (!availableExcelAccounts.value.some((account) => String(account.id) === String(excelAccountId.value))) {
    excelAccountId.value = ''
  }
  onImportSourceChanged()
}

function onImportSourceChanged() {
  const hadPreview = Boolean(preview.value)
  importInputRevision += 1
  preview.value = null
  if (hadPreview) ElMessage.info('导入来源已变更，请重新解析')
}

function clearSelectedFile() {
  selectedFile.value = null
  onImportSourceChanged()
}

async function scrollToImportPreview() {
  await nextTick()
  const target = previewPanelRef.value
  if (!target) return
  const reducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' })
  target.focus({ preventScroll: true })
}

function ensureWorksheetRows(count: number) {
  while (worksheetRows.value.length < count) worksheetRows.value.push(createWorksheetRow())
}

function clearWorksheet() {
  worksheetRows.value = createWorksheetRows()
}

function addWorksheetRow(afterIndex = worksheetRows.value.length - 1) {
  const targetIndex = Math.max(0, afterIndex + 1)
  worksheetRows.value.splice(targetIndex, 0, createWorksheetRow())
  markWorksheetChanged()
}

function removeWorksheetRow(index: number) {
  if (worksheetRows.value.length <= 1) {
    ElMessage.warning('工作表至少保留一行')
    return
  }
  worksheetRows.value.splice(index, 1)
  markWorksheetChanged()
}

async function resetWorksheet() {
  try {
    await ElMessageBox.confirm('将清空当前粘贴工作表的所有内容，但不会影响已提交的导入批次。是否继续？', '清空工作表', {
      type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  clearWorksheet()
  markWorksheetChanged()
}

function moveWorksheetColumn(from: number, to: number) {
  if (from === to || to < 0 || to >= worksheetColumns.value.length) return
  const next = [...worksheetColumns.value]
  const [column] = next.splice(from, 1)
  next.splice(to, 0, column)
  worksheetColumns.value = next
  markWorksheetChanged()
}

function beginWorksheetColumnDrag(index: number, event: DragEvent) {
  draggedColumnIndex.value = index
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function dropWorksheetColumn(index: number) {
  const from = draggedColumnIndex.value
  draggedColumnIndex.value = null
  if (from === null) return
  moveWorksheetColumn(from, index)
}

function worksheetIssue(rowIndex: number, columnKey: WorksheetColumnKey, type: 'errors' | 'warnings' = 'errors') {
  return worksheetValidation.value[type].find((issue) => issue.rowIndex === rowIndex && issue.columnKey === columnKey)
}

function worksheetCellClass(rowIndex: number, columnKey: WorksheetColumnKey) {
  return {
    'worksheet-input--error': Boolean(worksheetIssue(rowIndex, columnKey)),
    'worksheet-input--warning': !worksheetIssue(rowIndex, columnKey) && Boolean(worksheetIssue(rowIndex, columnKey, 'warnings')),
  }
}

function worksheetCellTitle(rowIndex: number, columnKey: WorksheetColumnKey) {
  const error = worksheetIssue(rowIndex, columnKey)
  if (error) return error.message
  const warning = worksheetIssue(rowIndex, columnKey, 'warnings')
  if (warning) return warning.message
  return ''
}

function basisLabel(value: string) {
  if (value === 'TRANSFER') return '转 U'
  if (value === 'EFFECTIVE_TRANSFER') return '有效转 U'
  if (value === 'SPEND') return '消耗'
  if (value === 'MANUAL') return '手工'
  return value
}

function companyNameForLine(line?: OperatorAccount | null) {
  if (!line) return ''
  return line.companyName || operators.value.find((company) => String(company.id) === String(line.operatorId))?.name || ''
}

function deliveryLineLabel(line: OperatorAccount, includeAsset = true) {
  const companyName = companyNameForLine(line)
  const name = line.displayName || [companyName, line.name].filter(Boolean).join(' · ') || line.name
  return includeAsset && line.asset ? `${name} · ${line.asset}` : name
}

function previewLineLabel(row: { operatorName?: string, accountName?: string }) {
  const rawName = row.accountName?.replace(/^账户\s*#/, '投放线 #') || ''
  if (!rawName) return '—'
  return row.operatorName && !rawName.startsWith(`${row.operatorName} ·`) ? `${row.operatorName} · ${rawName}` : rawName
}

function calculateWorksheetFee(kind: WorksheetFeeKind) {
  const account = selectedWorksheetAccount.value
  const isExchange = kind === 'exchange'
  const label = isExchange ? '汇损' : '服务费'
  if (!account) {
    ElMessage.warning(`请先选择启用的投放线，才能按默认${label}规则计算`)
    return
  }

  const rate = isExchange ? account.defaultExchangeLossRate : account.defaultServiceFeeRate
  const basis = isExchange ? account.defaultExchangeLossBasis : account.defaultServiceFeeBasis
  if (basis === 'MANUAL') {
    ElMessage.warning(`当前投放线的${label}基数为“手工”，不能进行本地自动计算；未覆盖任何金额。`)
    return
  }

  const targetKey: WorksheetColumnKey = isExchange ? 'exchangeLossAmount' : 'serviceFeeAmount'
  let updatedRows = 0
  worksheetRows.value.forEach((row) => {
    if (!rowHasWorksheetData(row)) return
    const fraudDeductionSource = toDecimal(row.fraudLossAmount).gt(0) ? 'TRANSFER' as const : null
    const calculated = previewCalculation({
      transferAmount: row.transferAmount,
      fraudLossAmount: row.fraudLossAmount,
      fraudDeductionSource,
      spendAmount: row.spendAmount,
      exchangeLossRate: account.defaultExchangeLossRate,
      exchangeLossBasis: account.defaultExchangeLossBasis,
      exchangeLossMode: 'AUTO',
      serviceFeeRate: account.defaultServiceFeeRate,
      serviceFeeBasis: account.defaultServiceFeeBasis,
      serviceFeeMode: 'AUTO',
      calculationScale: account.calculationScale,
    })
    row[targetKey] = isExchange ? calculated.exchangeLossAutoAmount : calculated.serviceFeeAutoAmount
    updatedRows += 1
  })

  if (!updatedRows) {
    ElMessage.info('工作表中没有可本地计算的业务数据行')
    return
  }
  markWorksheetChanged()
  ElMessage.success(`已按投放线默认${label}规则覆盖 ${updatedRows} 行：费率 ${percent(rate)}% · 基数 ${basisLabel(basis)} · 精度 ${account.calculationScale} 位`)
}

function pasteWorksheetMatrix(text: string, rowIndex: number, columnIndex: number) {
  const matrix = parseClipboardMatrix(text)
  if (!matrix.length || matrix.every((row) => row.every((value) => !value))) {
    ElMessage.warning('剪贴板中没有可粘贴的表格数据')
    return
  }
  const identityHeaders = matrix[0].filter((header) => worksheetIdentityHeaderKey(header))
  if (identityHeaders.length) {
    ElMessage.warning(`检测到 ${identityHeaders.join('、')} 身份列。固定投放线工作表不接受这些列，以避免错误投放线被导入；请删除身份列后重新粘贴，或改用“上传 Excel 文件”（服务端会保留并校验身份列）。`)
    return
  }
  const safeIgnoredHeaders = matrix[0].filter((header) => isSafeIgnoredWorksheetHeader(header))
  const unsupportedRuleHeaders = matrix[0].filter((header) => isIgnoredWorksheetHeader(header) && !isSafeIgnoredWorksheetHeader(header))
  if (unsupportedRuleHeaders.length) {
    ElMessage.warning(`检测到 ${unsupportedRuleHeaders.join('、')} 规则列。粘贴工作表当前只接受汇损、服务费的金额列；请删除费率、基数、模式、原因列后重试，或改用“上传 Excel 文件”。`)
    return
  }
  const hasHeaders = hasWorksheetHeader(matrix[0])
  let ignoredColumns = 0
  let defaultedCellCount = 0

  if (hasHeaders) {
    const mappings = matrix[0].map((header, sourceIndex) => ({
      sourceIndex,
      key: worksheetHeaderKey(header),
    }))
    const usableMappings = mappings.filter((mapping) => Boolean(mapping.key)) as Array<{ sourceIndex: number; key: WorksheetColumnKey }>
    ignoredColumns = mappings.filter((mapping) => !mapping.key && !isSafeIgnoredWorksheetHeader(matrix[0][mapping.sourceIndex])).length
    if (!usableMappings.length) {
      ElMessage.warning('未识别到可导入的表头；请从目标单元格开始粘贴无表头数据。')
      return
    }
    const dataRows = matrix.slice(1)
    if (!dataRows.length) {
      ElMessage.warning('仅识别到表头，没有可写入的明细行')
      return
    }
    ensureWorksheetRows(rowIndex + dataRows.length)
    dataRows.forEach((sourceRow, sourceRowIndex) => {
      const target = worksheetRows.value[rowIndex + sourceRowIndex]
      usableMappings.forEach(({ sourceIndex, key }) => {
        target[key] = sourceRow[sourceIndex] ?? ''
      })
      if (usableMappings.some(({ sourceIndex }) => Boolean(sourceRow[sourceIndex]?.trim()))) {
        defaultedCellCount += fillWorksheetMissingAmounts(target)
      }
    })
  } else {
    const availableColumns = worksheetColumns.value.length - columnIndex
    const overflowValues = matrix.flatMap((sourceRow) => sourceRow.slice(Math.max(0, availableColumns))).filter((value) => value.trim())
    if (overflowValues.length) {
      ElMessage.error(`粘贴区域有 ${overflowValues.length} 个非空单元格超出工作表列范围，未写入任何数据。请调整起始列，或复制带表头的数据后重试。`)
      return
    }
    ensureWorksheetRows(rowIndex + matrix.length)
    matrix.forEach((sourceRow, sourceRowIndex) => {
      const target = worksheetRows.value[rowIndex + sourceRowIndex]
      const writableValues = sourceRow.slice(0, Math.max(0, availableColumns))
      writableValues.forEach((value, sourceColumnIndex) => {
        const column = worksheetColumns.value[columnIndex + sourceColumnIndex]
        if (column) target[column.key] = value
      })
      if (writableValues.some((value) => value.trim())) defaultedCellCount += fillWorksheetMissingAmounts(target)
    })
  }

  markWorksheetChanged()
  const defaultedHint = defaultedCellCount ? `，${defaultedCellCount} 个未覆盖金额格已补 0` : ''
  ElMessage.success(hasHeaders ? `已按表头写入 ${Math.max(0, matrix.length - 1)} 行数据${defaultedHint}` : `已从当前单元格写入 ${matrix.length} 行数据${defaultedHint}`)
  if (safeIgnoredHeaders.length) ElMessage.info(`已安全忽略不提交列：${safeIgnoredHeaders.join('、')}；有效转 U 由服务端计算，欺诈损失大于 0 时将自动按 TRANSFER 提交。`)
  if (ignoredColumns) ElMessage.info(`已忽略 ${ignoredColumns} 个未映射或超出工作表的列`)
}

function onWorksheetPaste(event: ClipboardEvent, rowIndex: number, columnIndex: number) {
  const text = event.clipboardData?.getData('text/plain')
  if (!text) {
    ElMessage.warning('未读取到剪贴板文本，请使用 Excel/WPS 复制后再尝试。')
    return
  }
  pasteWorksheetMatrix(text, rowIndex, columnIndex)
}

function closeWorksheetContextMenu() {
  worksheetContextMenu.value = null
}

function openWorksheetContextMenu(event: MouseEvent, rowIndex: number, columnIndex: number) {
  worksheetContextMenu.value = { x: event.clientX, y: event.clientY, rowIndex, columnIndex }
}

async function pasteFromClipboard() {
  const target = worksheetContextMenu.value
  closeWorksheetContextMenu()
  if (!target) return
  try {
    if (!navigator.clipboard?.readText) throw new Error('Clipboard API unavailable')
    const text = await navigator.clipboard.readText()
    if (!text) {
      ElMessage.warning('剪贴板中没有可粘贴的文本')
      return
    }
    pasteWorksheetMatrix(text, target.rowIndex, target.columnIndex)
  } catch {
    ElMessage.warning('浏览器未允许读取剪贴板；请先点击目标单元格，再使用 Ctrl/Cmd+V 粘贴。')
  }
}

function buildWorksheetPayload() {
  if (!selectedWorksheetAccount.value) {
    ElMessage.warning('请先选择投放公司，再选择一条启用的投放线')
    return null
  }
  if (!worksheetDataRowCount.value) {
    ElMessage.warning('请先在工作表中填写至少一行数据')
    return null
  }
  if (worksheetErrorCount.value) {
    ElMessage.warning(`工作表有 ${worksheetErrorCount.value} 个格式问题，请修正高亮单元格后再解析`)
    return null
  }
  return buildWorksheetTsv(worksheetRows.value, worksheetColumns.value, worksheetValidation.value)
}

async function loadReferences() {
  try {
    const loadedOperators = await api.operators.list()
    operators.value = loadedOperators
    accounts.value = (await Promise.all(loadedOperators.map((operator) => api.operators.accounts(operator.id)))).flat()
    usingDemo.value = false
  } catch {
    if (demoEnabled) {
      operators.value = demoOperators
      accounts.value = demoAccounts
      usingDemo.value = true
    } else {
      operators.value = []
      accounts.value = []
    }
  }
}

function sourceLabel(value: string) {
  if (value === 'PASTE') return '粘贴数据'
  if (value === 'XLSX_LEGACY') return '旧版 Excel'
  if (value === 'XLSX_STANDARD') return '标准 Excel'
  return value || '未知来源'
}

function formatTime(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(date)
}

function shortHash(value?: string) {
  if (!value) return '—'
  return value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-6)}` : value
}

function accountLabel(row: ImportJobRow) {
  if (row.operatorAccountId === undefined) return '—'
  const account = accounts.value.find((item) => String(item.id) === String(row.operatorAccountId))
  if (account) return deliveryLineLabel(account)
  const fallback = `投放线 #${row.operatorAccountId}`
  return row.operatorName ? `${row.operatorName} · ${fallback}` : fallback
}

async function downloadTemplate() {
  if (!canImport.value) {
    ElMessage.warning('当前账号没有导入权限')
    return
  }
  downloadingTemplate.value = true
  try {
    saveDownloadedFile(await api.imports.downloadTemplate())
    ElMessage.success('标准导入模板已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载导入模板失败')
  } finally {
    downloadingTemplate.value = false
  }
}

async function loadHistory() {
  if (!canImport.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    importJobs.value = await api.imports.list()
  } catch (error) {
    importJobs.value = []
    historyError.value = error instanceof Error ? error.message : '无法加载导入历史，请稍后重试。'
  } finally {
    historyLoading.value = false
  }
}

function openHistory() {
  if (!canImport.value) {
    ElMessage.warning('当前账号没有导入权限')
    return
  }
  historyDialog.value = true
  void loadHistory()
}

async function openHistoryDetail(job: ImportJob) {
  historyDetail.value = null
  historyDetailError.value = ''
  historyDetailDrawer.value = true
  historyDetailLoading.value = true
  try {
    const [detail, rows] = await Promise.all([api.imports.get(job.id), api.imports.rows(job.id)])
    historyDetail.value = { ...detail, rows: rows.length ? rows : detail.rows }
  } catch (error) {
    historyDetailError.value = error instanceof Error ? error.message : '无法加载该导入批次的明细。'
  } finally {
    historyDetailLoading.value = false
  }
}

async function downloadSource(job: ImportJob) {
  sourceDownloading.value = true
  try {
    saveDownloadedFile(await api.imports.downloadSource(job.id))
    ElMessage.success('原始导入文件已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载原始文件失败')
  } finally {
    sourceDownloading.value = false
  }
}

async function downloadErrorReport(job: ImportJob) {
  errorReportDownloading.value = true
  try {
    saveDownloadedFile(await api.imports.downloadErrorReport(job.id))
    ElMessage.success('导入错误报告已开始下载')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载错误报告失败')
  } finally {
    errorReportDownloading.value = false
  }
}

function mockPastePreview(text: string): ImportPreview {
  const lines = text.trim().split(/\r?\n/).filter(Boolean)
  const headers = lines[0]?.split('\t') || []
  const businessDateIndex = headers.indexOf('业务日期')
  const dataLines = lines.slice(1)
  const rows = dataLines.map((line, index) => {
    const values = line.split('\t')
    const businessDate = values[businessDateIndex] || ''
    const validDate = /^\d{4}-\d{2}-\d{2}$/.test(businessDate)
    return {
      sourceRow: index + 2,
      businessDate,
      operatorName: companyNameForLine(selectedWorksheetAccount.value),
      accountName: selectedWorksheetAccount.value ? deliveryLineLabel(selectedWorksheetAccount.value, false) : undefined,
      action: validDate && selectedWorksheetAccount.value ? 'CREATE' as const : 'ERROR' as const,
      level: validDate && selectedWorksheetAccount.value ? 'SUCCESS' as const : 'ERROR' as const,
      message: validDate && selectedWorksheetAccount.value ? '将创建草稿日结记录；结余及派生金额将由服务端重新计算。' : '缺少合法日期或启用的投放线。',
      raw: { 原始行: line },
    }
  })
  return { jobId: `demo-paste-${Date.now()}`, sourceType: 'PASTE', totalRows: rows.length, validRows: rows.filter((row) => row.level === 'SUCCESS').length, warningRows: 0, errorRows: rows.filter((row) => row.level === 'ERROR').length, rows }
}

function mockExcelPreview(file: File): ImportPreview {
  return {
    jobId: `demo-xlsx-${Date.now()}`, sourceType: 'XLSX_LEGACY', totalRows: 2, validRows: 2, warningRows: 1, errorRows: 0,
    rows: [
      { sourceRow: 2, businessDate: '2026-07-01', operatorName: 'AA', accountName: '待映射：投放线 AA-USDT', action: 'CREATE', level: 'SUCCESS', message: `已识别 ${file.name} 的投放公司分块格式。` },
      { sourceRow: 2, businessDate: '2026-07-01', operatorName: 'BB', accountName: '待映射：投放线 BB-USDT', action: 'CREATE', level: 'WARNING', message: '服务费表头识别为 2%，实际金额将以系统规则复算。' },
    ],
  }
}

async function parse() {
  if (!canImport.value) {
    ElMessage.warning('当前账号没有导入权限')
    return
  }
  if (source.value === 'excel' && !selectedFile.value) {
    ElMessage.warning('请选择 .xlsx 文件')
    return
  }
  const pasteText = source.value === 'paste' ? buildWorksheetPayload() : null
  if (source.value === 'paste' && !pasteText) return
  const requestId = ++parseRequestId
  const inputRevision = importInputRevision
  const parseSource = source.value
  const parseStrategy = conflictStrategy.value
  const selectedPasteAccountId = selectedWorksheetAccount.value?.id
  const selectedExcelFile = selectedFile.value
  const selectedExcelAccountId = excelAccountId.value || undefined
  const selectedExcelBusinessYear = excelBusinessYear.value
  const isCurrentRequest = () => requestId === parseRequestId && inputRevision === importInputRevision && parseSource === source.value && parseStrategy === conflictStrategy.value
  parsing.value = true
  preview.value = null
  loadError.value = ''
  try {
    const nextPreview = parseSource === 'paste'
      ? await api.imports.previewPaste(pasteText as string, selectedPasteAccountId, parseStrategy)
      : await api.imports.previewExcel(selectedExcelFile as File, selectedExcelAccountId, parseStrategy, selectedExcelBusinessYear)
    if (!isCurrentRequest()) {
      ElMessage.info('导入内容或范围已变更，已忽略旧解析结果；请重新解析')
      return
    }
    preview.value = nextPreview
    await scrollToImportPreview()
    ElMessage.success('解析完成，已定位到导入预览；请确认结果后再提交')
  } catch (error) {
    if (!isCurrentRequest()) return
    if (demoEnabled) {
      preview.value = parseSource === 'paste' ? mockPastePreview(pasteText as string) : mockExcelPreview(selectedExcelFile as File)
      usingDemo.value = true
      await scrollToImportPreview()
      ElMessage.warning('服务未连接，当前为仅供界面验证的演示预览。')
    } else {
      loadError.value = error instanceof Error ? error.message : '导入预览失败，请确认 API 已启动。'
    }
  } finally {
    if (requestId === parseRequestId) parsing.value = false
  }
}

function onFileChange(file: UploadFile) {
  if (!file.raw) return
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    ElMessage.error('第一阶段仅支持 .xlsx 文件')
    clearSelectedFile()
    return
  }
  if (file.size && file.size > 10 * 1024 * 1024) {
    ElMessage.error('文件不能超过 10 MB')
    clearSelectedFile()
    return
  }
  selectedFile.value = file.raw
  onImportSourceChanged()
}

async function commit() {
  if (!canImport.value) {
    ElMessage.warning('当前账号没有导入权限')
    return
  }
  if (!preview.value || !canCommit.value) return
  await ElMessageBox.confirm(`将按“${conflictStrategy.value === 'SKIP_EXISTING' ? '跳过已有记录' : conflictStrategy.value === 'UPDATE_DRAFT' ? '仅覆盖草稿' : '遇到重复即拒绝'}”策略提交 ${preview.value.validRows} 行。提交后会生成审计记录，是否继续？`, '确认导入', { type: 'warning', confirmButtonText: '提交导入', cancelButtonText: '返回修改' })
  committing.value = true
  try {
    const wasPastePreview = preview.value.sourceType === 'PASTE'
    await api.imports.commit(preview.value.jobId, conflictStrategy.value)
    ElMessage.success('导入已提交，日结金额将由服务端完成统一计算。')
    preview.value = null
    if (wasPastePreview) clearWorksheet()
  } catch (error) {
    if (usingDemo.value && demoEnabled) {
      ElMessage.warning('演示预览不会提交或写入正式账本。')
    } else {
      ElMessage.error(error instanceof Error ? error.message : '导入提交失败')
    }
  } finally {
    committing.value = false
  }
}

onMounted(() => {
  void loadReferences()
  document.addEventListener('click', closeWorksheetContextMenu)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeWorksheetContextMenu)
})
</script>

<template>
  <section>
    <div class="page-title-row">
      <div>
        <h2>导入中心</h2>
        <p class="page-subtitle">支持从 Excel/WPS 表格粘贴和上传 .xlsx。所有数据先由服务端解析、校验和预览，确认后才写入台账。</p>
      </div>
      <div class="page-actions">
        <el-tooltip :disabled="canImport" content="当前账号没有导入权限，请联系管理员。"><span><el-button :icon="Download" :loading="downloadingTemplate" :disabled="!canImport" @click="downloadTemplate">下载标准模板</el-button></span></el-tooltip>
        <el-tooltip :disabled="canImport" content="当前账号没有导入权限，请联系管理员。"><span><el-button :icon="Document" :disabled="!canImport" @click="openHistory">查看导入历史</el-button></span></el-tooltip>
      </div>
    </div>

    <el-alert v-if="loadError" class="load-error" type="error" :closable="false" show-icon>{{ loadError }}</el-alert>
    <el-alert v-if="!canImport" class="load-error" type="warning" :closable="false" show-icon>当前账号没有 <b>IMPORT</b> 权限，不能解析、提交或查看导入批次。请联系管理员分配相应角色。</el-alert>

    <article class="panel import-editor">
      <el-tabs v-model="source" class="import-tabs" @tab-change="onImportSourceChanged">
        <el-tab-pane label="粘贴工作表" name="paste">
          <div class="paste-worksheet">
            <div class="worksheet-toolbar">
              <div>
                <p class="section-label">粘贴工作表</p>
                <p class="field-note">点击任一单元格后按 Ctrl/Cmd+V，可从该格开始覆盖粘贴 Excel / WPS 的多行多列数据；中间空单元格与空行会保留原有位置。</p>
              </div>
              <div class="worksheet-form">
                <el-form-item label="投放公司" required>
                  <el-select v-model="pasteCompanyId" filterable placeholder="请选择启用的投放公司" style="width: 210px" @change="onWorksheetCompanyChanged">
                    <el-option v-for="company in activeCompanies" :key="company.id" :label="company.name" :value="company.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="固定投放线" required>
                  <el-select v-model="pasteAccountId" filterable :disabled="!pasteCompanyId" :placeholder="pasteCompanyId ? '请选择启用的投放线' : '请先选择投放公司'" style="width: 230px" @change="onWorksheetScopeChanged">
                    <el-option v-for="account in availablePasteAccounts" :key="account.id" :label="deliveryLineLabel(account, false)" :value="account.id" />
                  </el-select>
                </el-form-item>
                <el-form-item label="导入业务年份" required>
                  <el-date-picker v-model="businessYear" type="year" value-format="YYYY" :clearable="false" style="width: 118px" @change="onWorksheetScopeChanged" />
                </el-form-item>
              </div>
            </div>

            <el-alert class="worksheet-note" type="info" :closable="false" show-icon>
              工作表固定使用上方选定的启用投放线和导入业务年份，不显示、也不会提交投放公司 / 投放线 / 币种列。粘贴含表头的数据时会自动识别可用列；无表头时按当前焦点格定位。每个已粘贴数据行中未覆盖到的金额单元格会自动补为 0。<b>欺诈损失</b> 默认 0，填入大于 0 的金额时自动按 TRANSFER（从转 U 扣减）提交；其他金额无需填写原因。汇损、服务费表头可按当前投放线默认规则进行本地计算并覆盖已有金额。
            </el-alert>

            <div class="worksheet-actions">
              <div class="worksheet-action-group">
                <el-button size="small" @click="addWorksheetRow()">新增行</el-button>
                <el-button size="small" @click="resetWorksheet">清空工作表</el-button>
                <el-popover placement="bottom-start" :width="300" trigger="click">
                  <template #reference><el-button size="small">列设置</el-button></template>
                  <p class="column-settings-tip">也可直接拖动表头调整列顺序。</p>
                  <div v-for="(column, columnIndex) in worksheetColumns" :key="column.key" class="column-settings-row">
                    <span>{{ columnIndex + 1 }}. {{ column.label }}</span>
                    <span><el-button link size="small" :disabled="columnIndex === 0" @click="moveWorksheetColumn(columnIndex, columnIndex - 1)">上移</el-button><el-button link size="small" :disabled="columnIndex === worksheetColumns.length - 1" @click="moveWorksheetColumn(columnIndex, columnIndex + 1)">下移</el-button></span>
                  </div>
                </el-popover>
              </div>
              <div class="worksheet-status"><el-tag size="small" type="primary" effect="plain">{{ businessYear }} 年导入</el-tag><span>{{ worksheetRows.length }} 行工作区</span><el-tag size="small" effect="plain">{{ worksheetDataRowCount }} 行有数据</el-tag><el-tag v-if="worksheetErrorCount" size="small" type="danger">{{ worksheetErrorCount }} 个错误</el-tag><el-tag v-if="worksheetWarningCount" size="small" type="warning">{{ worksheetWarningCount }} 个核对提示</el-tag></div>
            </div>

            <el-alert v-if="worksheetErrorCount" class="worksheet-validation" type="error" :closable="false" show-icon>
              <strong>请先修正高亮单元格。</strong><span v-for="issue in worksheetErrorsSummary" :key="`${issue.rowIndex}-${issue.columnKey}-${issue.message}`" class="worksheet-validation-item">第 {{ issue.rowIndex + 1 }} 行：{{ issue.message }}</span><span v-if="worksheetErrorCount > worksheetErrorsSummary.length" class="worksheet-validation-item">另有 {{ worksheetErrorCount - worksheetErrorsSummary.length }} 项问题。</span>
            </el-alert>
            <el-alert v-if="worksheetWarningCount" class="worksheet-validation" type="warning" :closable="false" show-icon>
              <span v-for="issue in worksheetWarningsSummary" :key="`${issue.rowIndex}-${issue.columnKey}-${issue.message}`" class="worksheet-validation-item">第 {{ issue.rowIndex + 1 }} 行：{{ issue.message }}</span>
            </el-alert>

            <div class="worksheet-scroll">
              <table class="worksheet-table">
                <thead>
                  <tr>
                    <th class="worksheet-row-number">#</th>
                    <th v-for="(column, columnIndex) in worksheetColumns" :key="column.key" :style="{ minWidth: `${column.width}px` }" draggable="true" @dragstart="beginWorksheetColumnDrag(columnIndex, $event)" @dragover.prevent @drop="dropWorksheetColumn(columnIndex)">
                      <span>{{ column.label }}</span>
                      <el-tooltip v-if="column.key === 'exchangeLossAmount' || column.key === 'serviceFeeAmount'" :disabled="Boolean(selectedWorksheetAccount)" content="请先选择启用的投放线">
                        <span class="worksheet-header-action" draggable="false" @mousedown.stop @dragstart.stop.prevent @click.stop>
                          <el-button link type="primary" size="small" :disabled="!selectedWorksheetAccount" @click="calculateWorksheetFee(column.key === 'exchangeLossAmount' ? 'exchange' : 'service')">按费率进行计算</el-button>
                        </span>
                      </el-tooltip>
                    </th>
                    <th class="worksheet-row-actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in worksheetRows" :key="rowIndex">
                    <td class="worksheet-row-number">{{ rowIndex + 1 }}</td>
                    <td v-for="(column, columnIndex) in worksheetColumns" :key="column.key">
                      <input v-model="row[column.key]" class="worksheet-input" :class="worksheetCellClass(rowIndex, column.key)" :title="worksheetCellTitle(rowIndex, column.key)" :aria-label="`第 ${rowIndex + 1} 行${column.label}`" @input="markWorksheetChanged" @paste.prevent="onWorksheetPaste($event, rowIndex, columnIndex)" @contextmenu.prevent="openWorksheetContextMenu($event, rowIndex, columnIndex)" />
                    </td>
                    <td class="worksheet-row-actions"><el-button link type="danger" size="small" @click="removeWorksheetRow(rowIndex)">删除</el-button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="field-note worksheet-footnote">日期支持 2026-07-01、2026/7/1、2026年7月1日、7月1日；缺少年份时会按上方导入业务年份补全，完整日期的年份须与所选年份一致。仅填“1日”或“1”无法判断月份，请填写如“7月1日”。仅默认欺诈损失 0 的空行不会导入；欺诈损失大于 0 时自动按 TRANSFER（从转 U 扣减）处理，且不能大于同一行转 U。表头“本地计算”会以当前投放线的默认费率、基数和精度覆盖所有业务行；基数为手工时不会覆盖。</p>
          </div>
        </el-tab-pane>
        <el-tab-pane label="上传 Excel 文件" name="excel">
          <div class="upload-panel">
            <el-upload drag :auto-upload="false" :show-file-list="false" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" :on-change="onFileChange">
              <el-icon class="upload-icon"><UploadFilled /></el-icon>
              <div class="el-upload__text">将 .xlsx 文件拖到这里，或 <em>点击选择文件</em></div>
              <template #tip><div class="el-upload__tip">仅支持 .xlsx，最大 10 MB / 20,000 行；不接受 .xlsm、.xls 或包含可执行宏的文件。</div></template>
            </el-upload>
            <div v-if="selectedFile" class="selected-file"><el-icon><Document /></el-icon><div><strong>{{ selectedFile.name }}</strong><span>{{ (selectedFile.size / 1024).toFixed(1) }} KB · 待解析</span></div><el-button link type="danger" @click="clearSelectedFile">移除</el-button></div>
            <div class="excel-scope-selectors">
              <el-form-item label="投放公司（可选）">
                <el-select v-model="excelCompanyId" clearable filterable placeholder="选择公司以筛选投放线" style="width: 100%" @change="onExcelCompanyChanged">
                  <el-option v-for="company in activeCompanies" :key="company.id" :label="company.name" :value="company.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="指定投放线（可选）">
                <el-select v-model="excelAccountId" clearable filterable :disabled="!excelCompanyId" :placeholder="excelCompanyId ? '请选择启用的投放线' : '请先选择投放公司'" style="width: 100%" @change="onImportSourceChanged">
                  <el-option v-for="account in availableExcelAccounts" :key="account.id" :label="deliveryLineLabel(account, false)" :value="account.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="导入业务年份" required>
                <el-date-picker v-model="excelBusinessYear" type="year" value-format="YYYY" :clearable="false" style="width: 100%" @change="onImportSourceChanged" />
              </el-form-item>
            </div>
            <div class="legacy-tip"><strong>兼容当前样本格式</strong><p>系统会识别“昨日结余、转U、消耗、回流、退款、其他、结余”等表头、投放公司分块与费率文本，并兼容历史表头；不带年份的日期会按上方业务年份补全，完整日期须属于所选年份；合计行和 Excel 公式结果不会作为台账事实导入。</p></div>
          </div>
        </el-tab-pane>
      </el-tabs>
      <div class="import-submit">
        <span>解析过程不会写入日结数据。</span>
        <div class="import-submit-actions">
          <el-button v-if="preview" type="success" plain @click="scrollToImportPreview">查看导入预览</el-button>
          <span>预检冲突策略</span>
          <el-select v-model="conflictStrategy" :disabled="!canImport || Boolean(preview) || parsing" style="width: 150px">
            <el-option label="跳过已有记录" value="SKIP_EXISTING" />
            <el-option label="仅覆盖草稿" value="UPDATE_DRAFT" />
            <el-option label="遇重复即拒绝" value="REJECT_ON_CONFLICT" />
          </el-select>
          <el-button type="primary" :loading="parsing" :disabled="!canImport || parsing" @click="parse">{{ preview ? '重新解析并更新预览' : '开始解析并预览' }}</el-button>
        </div>
      </div>
    </article>

    <article v-if="preview" ref="previewPanelRef" class="panel table-card preview-panel" tabindex="-1" role="region" aria-labelledby="import-preview-title">
      <div class="preview-arrival" role="status" aria-live="polite"><strong>解析已完成，以下是导入预览</strong><span>请检查可提交、警告和错误记录，确认无误后再提交。</span></div>
      <div class="preview-header"><div><h3 id="import-preview-title">导入预览</h3><p v-if="preview.sourceType === 'PASTE'">目标：{{ selectedWorksheetLineLabel }} · {{ businessYear }} 年 · 批次 {{ preview.jobId }} · 粘贴数据</p><p v-else>导入业务年份：{{ excelBusinessYear }} · 批次 {{ preview.jobId }} · {{ preview.sourceType === 'XLSX_LEGACY' ? '旧版分块格式' : '标准 Excel 模板' }}</p></div><div class="preview-counts"><span><b>{{ preview.validRows }}</b> 可提交</span><span class="warn"><b>{{ preview.warningRows }}</b> 警告</span><span class="error"><b>{{ preview.errorRows }}</b> 错误</span></div></div>
      <el-table :data="previewRows" max-height="360" size="small" :row-class-name="({ row }) => row.level === 'ERROR' ? 'error-row' : row.level === 'WARNING' ? 'warning-row' : ''">
        <el-table-column prop="sourceRow" label="源行" width="70" align="center" />
        <el-table-column prop="businessDate" label="日期" width="120" />
        <el-table-column prop="operatorName" label="投放公司" min-width="150" />
        <el-table-column label="投放线" min-width="180"><template #default="{ row }">{{ previewLineLabel(row) }}</template></el-table-column>
        <el-table-column label="操作" width="100" align="center"><template #default="{ row }"><StatusTag :status="row.action" /></template></el-table-column>
        <el-table-column label="校验" width="92" align="center"><template #default="{ row }"><StatusTag :status="row.level" /></template></el-table-column>
        <el-table-column prop="message" label="说明" min-width="360" show-overflow-tooltip />
      </el-table>
      <div class="commit-bar"><div><strong v-if="preview.errorRows">当前存在阻断错误，修正源数据后请重新解析。</strong><strong v-else>预览通过。提交时服务端会再次校验权限、重复记录、锁账与计算规则。</strong><p>本次预检策略：{{ conflictStrategy === 'SKIP_EXISTING' ? '跳过已有记录' : conflictStrategy === 'UPDATE_DRAFT' ? '仅覆盖草稿' : '遇重复即拒绝' }}。已确认、已锁定记录不能通过导入覆盖。</p></div><div class="commit-actions"><el-button type="primary" :disabled="!canCommit || !canImport" :loading="committing" @click="commit">确认提交</el-button></div></div>
    </article>

    <el-dialog v-model="historyDialog" title="导入历史" width="1120px" destroy-on-close>
      <div class="history-toolbar"><span>仅展示当前账号有权访问的批次，按创建时间倒序排列。</span><el-button size="small" :loading="historyLoading" @click="loadHistory">刷新</el-button></div>
      <el-alert v-if="historyError" class="history-error" type="error" :closable="false" show-icon>{{ historyError }}</el-alert>
      <el-table v-loading="historyLoading" :data="importJobs" border max-height="520" size="small" empty-text="暂无可访问的导入批次">
        <el-table-column label="批次" width="105"><template #default="{ row }"><strong>#{{ row.id }}</strong><span class="job-source">{{ sourceLabel(row.sourceType) }}</span></template></el-table-column>
        <el-table-column label="文件 / 来源" min-width="240" show-overflow-tooltip><template #default="{ row }"><strong>{{ row.originalFilename || (row.sourceType === 'PASTE' ? '粘贴表格数据' : '未保留文件名') }}</strong><span class="muted">{{ row.conflictStrategy || 'SKIP_EXISTING' }}</span><span v-if="row.fileSha256" class="job-hash" :title="row.fileSha256">SHA-256 {{ shortHash(row.fileSha256) }}</span></template></el-table-column>
        <el-table-column label="状态" width="100" align="center"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="行统计" min-width="198"><template #default="{ row }"><div class="job-counts"><span>{{ row.totalRows }} 总行</span><span class="ok">{{ row.validRows }} 通过</span><span class="warn">{{ row.warningRows }} 警告</span><span class="error">{{ row.errorRows }} 错误</span></div></template></el-table-column>
        <el-table-column label="创建人" width="100"><template #default="{ row }"><span class="muted">{{ row.createdBy === undefined || row.createdBy === null ? '—' : `用户 #${row.createdBy}` }}</span></template></el-table-column>
        <el-table-column label="创建时间" width="164"><template #default="{ row }"><span class="muted">{{ formatTime(row.createdAt) }}</span></template></el-table-column>
        <el-table-column label="提交时间" width="164"><template #default="{ row }"><span class="muted">{{ formatTime(row.committedAt) }}</span></template></el-table-column>
        <el-table-column label="操作" width="86" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openHistoryDetail(row)">查看结果</el-button></template></el-table-column>
      </el-table>
      <template #footer><el-button @click="historyDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-drawer v-model="historyDetailDrawer" title="导入批次结果" size="860px" append-to-body>
      <div v-loading="historyDetailLoading">
        <el-alert v-if="historyDetailError" type="error" :closable="false" show-icon>{{ historyDetailError }}</el-alert>
        <template v-else-if="historyDetail">
          <div class="detail-header"><div><h3>批次 #{{ historyDetail.job.id }} · {{ sourceLabel(historyDetail.job.sourceType) }}</h3><p>{{ historyDetail.job.originalFilename || '粘贴表格数据' }} · 创建于 {{ formatTime(historyDetail.job.createdAt) }}</p></div><StatusTag :status="historyDetail.job.status" /></div>
          <div class="detail-stats"><span><b>{{ historyDetail.job.totalRows }}</b> 总行</span><span><b>{{ historyDetail.job.validRows }}</b> 通过</span><span class="warn"><b>{{ historyDetail.job.warningRows }}</b> 警告</span><span class="error"><b>{{ historyDetail.job.errorRows }}</b> 错误</span><span>策略：{{ historyDetail.job.conflictStrategy || 'SKIP_EXISTING' }}</span></div>
          <div class="detail-actions"><el-button v-if="historyDetail.job.sourceType !== 'PASTE'" :icon="Download" :loading="sourceDownloading" @click="downloadSource(historyDetail.job)">下载原始文件</el-button><el-button :icon="Download" type="primary" plain :loading="errorReportDownloading" @click="downloadErrorReport(historyDetail.job)">下载错误报告</el-button></div>
          <el-table :data="historyRows" border max-height="510" size="small" :row-class-name="({ row }) => row.severity === 'ERROR' ? 'error-row' : row.severity === 'WARNING' ? 'warning-row' : ''">
            <el-table-column label="源位置" width="110"><template #default="{ row }"><span>{{ row.sourceSheet || '—' }}</span><span class="muted">第 {{ row.sourceRow }} 行</span></template></el-table-column>
            <el-table-column prop="businessDate" label="日期" width="112" />
            <el-table-column prop="operatorName" label="投放公司" min-width="138" />
            <el-table-column label="投放线" min-width="150"><template #default="{ row }">{{ accountLabel(row) }}</template></el-table-column>
            <el-table-column label="校验" width="86" align="center"><template #default="{ row }"><StatusTag :status="row.severity" /></template></el-table-column>
            <el-table-column label="结果" width="100" align="center"><template #default="{ row }"><StatusTag v-if="row.action" :status="row.action" /><span v-else class="muted">—</span></template></el-table-column>
            <el-table-column label="说明" min-width="240" show-overflow-tooltip><template #default="{ row }"><span>{{ row.errorMessage || row.errorCode || '—' }}</span></template></el-table-column>
          </el-table>
        </template>
      </div>
    </el-drawer>

    <teleport to="body">
      <div v-if="worksheetContextMenu" class="worksheet-context-menu" :style="{ left: `${worksheetContextMenu.x}px`, top: `${worksheetContextMenu.y}px` }" @click.stop>
        <button type="button" @click="pasteFromClipboard">从剪贴板粘贴</button>
      </div>
    </teleport>
  </section>
</template>

<style scoped>
.load-error { margin-bottom: 16px; }
.import-editor { overflow: hidden; }
.import-tabs { padding: 0 20px; }
.section-label { margin: 0 0 8px; color: #344054; font-size: 13px; font-weight: 600; }

.paste-worksheet { padding: 4px 0 20px; }
.worksheet-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 14px; }
.worksheet-toolbar .field-note { max-width: 680px; }
.worksheet-form { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: flex-end; gap: 10px; }
.worksheet-form :deep(.el-form-item) { margin: 0; }
.worksheet-note { margin-bottom: 12px; }
.worksheet-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.worksheet-action-group, .worksheet-status { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.worksheet-status { justify-content: flex-end; color: #667085; font-size: 12px; }
.column-settings-tip { margin: 0 0 8px; color: #667085; font-size: 12px; }
.column-settings-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 30px; color: #475467; font-size: 12px; border-bottom: 1px solid #f2f4f7; }
.column-settings-row:last-child { border-bottom: 0; }
.worksheet-validation { margin-bottom: 10px; }
.worksheet-validation-item { display: block; margin-top: 4px; }
.worksheet-scroll { max-height: 540px; overflow: auto; border: 1px solid #eaecf0; border-radius: 8px; background: #fff; }
.worksheet-table { width: max-content; min-width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.worksheet-table th { position: sticky; top: 0; z-index: 2; min-height: 42px; padding: 8px; color: #475467; font-size: 12px; font-weight: 600; line-height: 1.3; text-align: left; white-space: nowrap; background: #f9fafb; border-right: 1px solid #eaecf0; border-bottom: 1px solid #d0d5dd; cursor: grab; user-select: none; }
.worksheet-table th span, .worksheet-table th small { display: block; }
.worksheet-table th small { margin-top: 2px; color: #b54708; font-size: 10px; font-weight: 500; }
.worksheet-header-action { display: inline-flex !important; margin-top: 3px; cursor: default; }
.worksheet-header-action :deep(.el-button) { height: 20px; padding: 0 2px; font-size: 11px; cursor: pointer; }
.worksheet-table td { min-width: 104px; padding: 0; background: #fff; border-right: 1px solid #eaecf0; border-bottom: 1px solid #eaecf0; }
.worksheet-table tr:last-child td { border-bottom: 0; }
.worksheet-table th:last-child, .worksheet-table td:last-child { border-right: 0; }
.worksheet-row-number { position: sticky !important; left: 0; z-index: 4 !important; width: 48px; min-width: 48px !important; padding: 0 !important; color: #98a2b3 !important; text-align: center !important; background: #f9fafb !important; cursor: default !important; }
tbody .worksheet-row-number { z-index: 1 !important; color: #667085 !important; background: #fcfcfd !important; }
.worksheet-row-actions { position: sticky !important; right: 0; z-index: 4 !important; width: 62px; min-width: 62px !important; padding: 0 !important; text-align: center !important; background: #f9fafb !important; cursor: default !important; }
tbody .worksheet-row-actions { z-index: 1 !important; background: #fff !important; }
.worksheet-input { display: block; width: 100%; min-width: 100%; height: 36px; padding: 0 8px; color: #344054; font: inherit; font-size: 12px; line-height: 36px; background: transparent; border: 0; outline: 0; box-sizing: border-box; }
.worksheet-input:focus { position: relative; z-index: 1; background: #eff4ff; box-shadow: inset 0 0 0 2px #155eef; }
.worksheet-input--error { color: #b42318; background: #fff1f0; box-shadow: inset 0 0 0 1px #f04438; }
.worksheet-input--warning { color: #7a2e0e; background: #fffaeb; box-shadow: inset 0 0 0 1px #fec84b; }
.worksheet-context-menu { position: fixed; z-index: 3000; min-width: 152px; padding: 4px; background: #fff; border: 1px solid #d0d5dd; border-radius: 8px; box-shadow: 0 10px 24px rgb(16 24 40 / 16%); }
.worksheet-context-menu button { display: block; width: 100%; padding: 8px 10px; color: #344054; font: inherit; font-size: 13px; text-align: left; background: transparent; border: 0; border-radius: 5px; cursor: pointer; }
.worksheet-context-menu button:hover { color: #155eef; background: #eff4ff; }
.worksheet-footnote { margin: 10px 0 0; }

.upload-panel { padding: 5px 0 20px; }
.upload-icon { margin-bottom: 12px; color: #155eef; font-size: 44px; }
.selected-file { display: flex; align-items: center; gap: 10px; max-width: 610px; margin: 16px auto 0; padding: 12px; color: #344054; background: #eff4ff; border: 1px solid #b2ccff; border-radius: 8px; }
.selected-file > div { display: grid; flex: 1; gap: 3px; }
.selected-file span { color: #667085; font-size: 12px; }
.excel-scope-selectors { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 270px; gap: 14px; max-width: 980px; margin: 18px auto 0; }
.excel-scope-selectors :deep(.el-form-item) { margin: 0; }
.legacy-tip { max-width: 610px; margin: 16px auto 0; padding: 14px; background: #fffaeb; border: 1px solid #fedf89; border-radius: 8px; }
.legacy-tip strong { color: #b54708; font-size: 13px; }
.legacy-tip p { margin: 5px 0 0; color: #7a2e0e; font-size: 12px; line-height: 1.65; }
.import-submit { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 20px; color: #667085; font-size: 12px; border-top: 1px solid #eaecf0; }
.import-submit-actions { display: flex; align-items: center; gap: 8px; color: #667085; white-space: nowrap; }
.preview-panel { overflow: hidden; scroll-margin-top: 88px; border: 1px solid #84adff; box-shadow: 0 8px 24px rgb(21 94 239 / 10%); }
.preview-arrival { display: flex; align-items: center; gap: 9px; padding: 11px 20px; color: #175cd3; font-size: 13px; background: #eff8ff; border-bottom: 1px solid #b2ddff; }
.preview-arrival strong { color: #004eeb; }
.preview-arrival span { color: #475467; font-size: 12px; }
.preview-header { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px 14px; }
.preview-header h3 { margin: 0; color: #101828; font-size: 15px; }
.preview-header p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }
.preview-counts { display: flex; gap: 16px; color: #027a48; font-size: 13px; }
.preview-counts .warn { color: #b54708; }
.preview-counts .error { color: #d92d20; }
.error-row td { background: #fff7f5 !important; }
.commit-bar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 20px; border-top: 1px solid #eaecf0; }
.commit-bar strong { color: #344054; font-size: 13px; }
.commit-bar p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }
.commit-actions { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.history-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; color: #667085; font-size: 12px; }
.history-error { margin-bottom: 14px; }
.job-source { display: block; margin-top: 3px; color: #98a2b3; font-size: 10px; }
.job-hash { display: block; margin-top: 2px; color: #98a2b3; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 10px; }
.job-counts { display: flex; flex-wrap: wrap; gap: 5px 9px; color: #667085; font-size: 11px; }
.job-counts .ok { color: #027a48; }
.job-counts .warn { color: #b54708; }
.job-counts .error { color: #d92d20; }
.detail-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.detail-header h3 { margin: 0; color: #101828; font-size: 15px; }
.detail-header p { margin: 5px 0 0; color: #98a2b3; font-size: 12px; }
.detail-stats { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 14px; padding: 12px; color: #667085; font-size: 12px; background: #f9fafb; border: 1px solid #eaecf0; border-radius: 8px; }
.detail-stats b { color: #344054; }
.detail-stats .warn { color: #b54708; }
.detail-stats .error { color: #d92d20; }
.detail-actions { display: flex; justify-content: flex-end; gap: 10px; margin-bottom: 14px; }

@media (max-width: 900px) {
  .worksheet-toolbar, .worksheet-actions { align-items: stretch; flex-direction: column; }
  .worksheet-form, .worksheet-status { justify-content: flex-start; }
  .worksheet-form :deep(.el-form-item) { flex: 1 1 190px; }
  .worksheet-form :deep(.el-select), .worksheet-form :deep(.el-date-editor) { width: 100% !important; }
  .excel-scope-selectors { grid-template-columns: 1fr; }
  .import-submit { align-items: stretch; flex-direction: column; }
  .import-submit-actions { flex-wrap: wrap; justify-content: flex-start; white-space: normal; }
}
</style>
