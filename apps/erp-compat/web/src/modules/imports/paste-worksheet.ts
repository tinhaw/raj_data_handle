import { toDecimal } from '@/utils/money'

export type WorksheetColumnKey =
  | 'businessDate'
  | 'openingBalance'
  | 'transferAmount'
  | 'spendAmount'
  | 'exchangeLossAmount'
  | 'serviceFeeAmount'
  | 'refluxAmount'
  | 'refundAmount'
  | 'otherDeductionAmount'
  | 'fraudLossAmount'

export type WorksheetColumnKind = 'date' | 'amount'

export interface WorksheetColumn {
  key: WorksheetColumnKey
  label: string
  kind: WorksheetColumnKind
  width: number
  /** Header written to the existing TSV paste importer. Omitted columns are local-only. */
  importHeader?: string
}

export type WorksheetRow = Record<WorksheetColumnKey, string>

export interface WorksheetIssue {
  rowIndex: number
  columnKey: WorksheetColumnKey
  message: string
}

export interface WorksheetValidation {
  errors: WorksheetIssue[]
  warnings: WorksheetIssue[]
  normalizedDates: Record<number, string>
}

export const DEFAULT_WORKSHEET_COLUMNS: WorksheetColumn[] = [
  { key: 'businessDate', label: '日期', kind: 'date', width: 118, importHeader: '业务日期' },
  { key: 'openingBalance', label: '昨日结余', kind: 'amount', width: 122, importHeader: '期初余额' },
  { key: 'transferAmount', label: '转 U', kind: 'amount', width: 112, importHeader: '转U' },
  { key: 'spendAmount', label: '消耗', kind: 'amount', width: 112, importHeader: '消耗' },
  { key: 'exchangeLossAmount', label: '汇损', kind: 'amount', width: 112, importHeader: '汇损金额' },
  { key: 'serviceFeeAmount', label: '服务费', kind: 'amount', width: 112, importHeader: '服务费金额' },
  { key: 'refluxAmount', label: '回流', kind: 'amount', width: 104, importHeader: '回流' },
  { key: 'refundAmount', label: '退款', kind: 'amount', width: 104, importHeader: '退款' },
  { key: 'otherDeductionAmount', label: '其他', kind: 'amount', width: 104, importHeader: '其他扣减' },
  { key: 'fraudLossAmount', label: '欺诈损失', kind: 'amount', width: 120, importHeader: '欺诈损失' },
]

export function createWorksheetRow(): WorksheetRow {
  return {
    businessDate: '', openingBalance: '', transferAmount: '', spendAmount: '',
    exchangeLossAmount: '', serviceFeeAmount: '', refluxAmount: '', refundAmount: '', otherDeductionAmount: '',
    fraudLossAmount: '0',
  }
}

export function createWorksheetRows(count = 31) {
  return Array.from({ length: count }, () => createWorksheetRow())
}

function canonicalText(value: string) {
  return value.replace(/[\s_－—-]/g, '').toUpperCase()
}

function isCalendarDate(year: number, month: number, day: number) {
  const value = new Date(Date.UTC(year, month - 1, day))
  return value.getUTCFullYear() === year && value.getUTCMonth() === month - 1 && value.getUTCDate() === day
}

function dateText(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

interface WorksheetBusinessPeriod {
  value: string
  year: number
  /** Kept only so callers using the former YYYY-MM context remain compatible. */
  month?: number
}

function parseWorksheetBusinessYear(raw: string | number): { value?: WorksheetBusinessPeriod; error?: string } {
  const source = String(raw).trim()
  const match = source.match(/^(\d{4})(?:-(\d{1,2}))?$/)
  if (!match) return { error: '请选择有效的导入业务年份' }
  const year = Number(match[1])
  const legacyMonth = match[2] === undefined ? undefined : Number(match[2])
  if (!Number.isInteger(year) || (legacyMonth !== undefined && (!Number.isInteger(legacyMonth) || legacyMonth < 1 || legacyMonth > 12))) {
    return { error: '请选择有效的导入业务年份' }
  }
  return { value: { year, month: legacyMonth, value: String(year) } }
}

/** Normalize the common Excel/WPS date forms used in the Chinese daily-ledger sheet. */
export function normalizeWorksheetDate(raw: string, businessYear: string | number): { value?: string; error?: string } {
  const source = raw.trim()
  if (!source) return { error: '日期不能为空' }
  const period = parseWorksheetBusinessYear(businessYear)
  if (!period.value) return { error: period.error }
  let year: number | undefined
  let month: number | undefined
  let day: number | undefined
  let match = source.match(/^(\d{4})\s*(?:年|[./-])\s*(\d{1,2})\s*(?:月|[./-])\s*(\d{1,2})(?:日)?(?:[T\s].*)?$/)
  if (match) {
    year = Number(match[1]); month = Number(match[2]); day = Number(match[3])
  } else {
    match = source.match(/^(\d{4})(\d{2})(\d{2})$/)
    if (match) {
      year = Number(match[1]); month = Number(match[2]); day = Number(match[3])
    } else {
      // Excel/WPS sometimes copies an unformatted serial date (for example
      // 45474). Support the common five-digit form using Excel's 1900 date
      // system, including its historical fake 1900-02-29 offset.
      match = source.match(/^(\d{5})(?:\.\d+)?$/)
      if (match) {
        const serial = Number(match[1])
        if (serial === 60) return { error: 'Excel 序列日期 60 对应不存在的 1900-02-29' }
        const daysFromEpoch = serial > 60 ? serial - 1 : serial
        const excelDate = new Date(Date.UTC(1899, 11, 31) + daysFromEpoch * 24 * 60 * 60 * 1000)
        year = excelDate.getUTCFullYear(); month = excelDate.getUTCMonth() + 1; day = excelDate.getUTCDate()
      } else {
        match = source.match(/^(\d{1,2})\s*月\s*(\d{1,2})(?:日)?$/)
        if (match) {
          year = period.value.year; month = Number(match[1]); day = Number(match[2])
        } else {
          match = source.match(/^(\d{1,2})(?:日)?$/)
          if (match) {
            if (period.value.month === undefined) return { error: `日期缺少月份：${raw}；请填写如 7月1日` }
            year = period.value.year; month = period.value.month; day = Number(match[1])
          }
        }
      }
    }
  }
  if (!year || !month || !day || !Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day) || !isCalendarDate(year, month, day)) {
    return { error: `日期格式不正确：${raw}` }
  }
  const value = dateText(year, month, day)
  if (year !== period.value.year) return { error: `日期 ${value} 不属于所选导入业务年份 ${period.value.value}` }
  if (period.value.month !== undefined && month !== period.value.month) return { error: `日期 ${value} 不属于所选导入业务月份 ${businessYear}` }
  return { value }
}

export function normalizeAmount(raw: string, allowNegative = false): { value?: string; error?: string } {
  const source = raw.trim()
  if (!source) return {}
  const normalized = source.replace(/[，,]/g, '').replace(/(?:USDT|USDC)/gi, '').replace(/\s+/g, '')
  if (!/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/.test(normalized)) return { error: `金额格式不正确：${raw}` }
  const value = toDecimal(normalized)
  if (!allowNegative && value.isNegative()) return { error: '金额不能为负数' }
  return { value: normalized }
}

export function parseClipboardMatrix(text: string) {
  const matrix = text.replace(/\r\n?/g, '\n').split('\n').map((line) => line.split('\t').map((value) => value.trim()))
  // Excel commonly appends one empty line. Preserve every interior blank row/cell for matrix alignment.
  while (matrix.length > 1 && matrix[matrix.length - 1].every((value) => !value)) matrix.pop()
  return matrix
}

export function worksheetHeaderKey(raw: string): WorksheetColumnKey | undefined {
  const value = canonicalText(raw)
  if (value === '日期' || value === '业务日期' || value === 'DATE') return 'businessDate'
  if (value.includes('昨日结余') || value.includes('期初')) return 'openingBalance'
  // Derived and removed compact-grid columns are deliberately ignored, so
  // they can never shift the default no-header business-column coordinates.
  if (isSafeIgnoredWorksheetHeader(raw)) return undefined
  if (value === '转U' || value === '转USDT' || value === 'TRANSFER') return 'transferAmount'
  if (value.includes('消耗') || value === 'SPEND') return 'spendAmount'
  // The standard template also has rate / basis / mode columns. They are not
  // editable in this first worksheet, so do not accidentally put a rate such
  // as "2%" into the manual amount column when a whole template is pasted.
  if (value.includes('汇损')) {
    if (value.includes('费率') || value.includes('基数') || value.includes('模式') || value.includes('原因')) return undefined
    return 'exchangeLossAmount'
  }
  if (value.includes('服务费')) {
    if (value.includes('费率') || value.includes('基数') || value.includes('模式') || value.includes('原因')) return undefined
    return 'serviceFeeAmount'
  }
  if (value === '回流') return 'refluxAmount'
  if (value === '退款') return 'refundAmount'
  if (value === '其他' || value.includes('其他扣减')) return 'otherDeductionAmount'
  if (value.includes('欺诈')) return 'fraudLossAmount'
  return undefined
}

export function worksheetIdentityHeaderKey(raw: string): 'operator' | 'account' | 'asset' | undefined {
  const value = canonicalText(raw)
  // New templates use 投放公司 / 投放线. Keep the legacy labels so existing
  // exports can still be recognized and rejected safely in fixed-line mode.
  if (value.includes('投放公司') || value.includes('运营方') || value === '投放名字' || value === 'OPERATOR') return 'operator'
  if (value.includes('投放线') || value.includes('结算账户') || value === '账户' || value === 'ACCOUNT') return 'account'
  if (value === '币种' || value === 'ASSET') return 'asset'
  return undefined
}

export function isDerivedWorksheetHeader(raw: string) {
  const value = canonicalText(raw)
  return value.includes('有效转U') || value.includes('有效转USDT') || value === 'EFFECTIVETRANSFER'
}

/** Columns intentionally omitted from the compact worksheet but harmless in a pasted headed table. */
export function isSafeIgnoredWorksheetHeader(raw: string) {
  const value = canonicalText(raw)
  const isRemovedInputColumn = value.includes('其他原因') || value === '备注' || value === 'REMARK'
    || (value.includes('欺诈') && (value.includes('承担') || value.includes('扣减') || value.includes('扣除') || value.includes('来源')))
  return isDerivedWorksheetHeader(raw) || isRemovedInputColumn
}

export function isIgnoredWorksheetHeader(raw: string) {
  const value = canonicalText(raw)
  const isCalculationRuleColumn = (value.includes('汇损') || value.includes('服务费'))
    && (value.includes('费率') || value.includes('基数') || value.includes('模式') || value.includes('原因'))
  return isSafeIgnoredWorksheetHeader(raw) || isCalculationRuleColumn
}

export function hasWorksheetHeader(row: string[]) {
  const recognized = row.filter((value) => worksheetHeaderKey(value) || worksheetIdentityHeaderKey(value) || isIgnoredWorksheetHeader(value))
  return recognized.length >= 2 || (row.length === 1 && recognized.length === 1) || Boolean(worksheetHeaderKey(row[0] || '') === 'businessDate')
}

export function rowHasWorksheetData(row: WorksheetRow) {
  return Object.entries(row).some(([key, value]) => {
    const trimmed = value.trim()
    if (!trimmed) return false
    if (key !== 'fraudLossAmount') return true
    const amount = normalizeAmount(trimmed)
    return Boolean(amount.error) || !amount.value || !toDecimal(amount.value).isZero()
  })
}

const amountKeys: WorksheetColumnKey[] = [
  'openingBalance', 'transferAmount', 'spendAmount', 'exchangeLossAmount', 'serviceFeeAmount',
  'refluxAmount', 'refundAmount', 'otherDeductionAmount', 'fraudLossAmount',
]

/** A pasted row may omit some amount columns; omitted amounts are explicitly zero. */
export function fillWorksheetMissingAmounts(row: WorksheetRow) {
  let filled = 0
  for (const key of amountKeys) {
    if (!row[key].trim()) {
      row[key] = '0'
      filled += 1
    }
  }
  return filled
}

export function validateWorksheet(rows: WorksheetRow[], businessYear: string | number): WorksheetValidation {
  const errors: WorksheetIssue[] = []
  const warnings: WorksheetIssue[] = []
  const normalizedDates: Record<number, string> = {}
  const firstDateRow = new Map<string, number>()

  rows.forEach((row, rowIndex) => {
    const hasData = rowHasWorksheetData(row)
    const date = row.businessDate.trim() ? normalizeWorksheetDate(row.businessDate, businessYear) : undefined
    if (hasData && !row.businessDate.trim()) errors.push({ rowIndex, columnKey: 'businessDate', message: '填写数据的行必须填写日期' })
    if (date?.error) errors.push({ rowIndex, columnKey: 'businessDate', message: date.error })
    if (date?.value) {
      normalizedDates[rowIndex] = date.value
      const first = firstDateRow.get(date.value)
      if (first === undefined) firstDateRow.set(date.value, rowIndex)
      else {
        errors.push({ rowIndex, columnKey: 'businessDate', message: `重复日期：${date.value}` })
        errors.push({ rowIndex: first, columnKey: 'businessDate', message: `重复日期：${date.value}` })
      }
    }

    const amounts = new Map<WorksheetColumnKey, string>()
    for (const key of amountKeys) {
      const result = normalizeAmount(row[key], key === 'openingBalance')
      if (result.error) errors.push({ rowIndex, columnKey: key, message: result.error })
      if (result.value !== undefined) amounts.set(key, result.value)
    }

    const fraud = amounts.get('fraudLossAmount')
    const transfer = amounts.get('transferAmount')
    if (fraud && toDecimal(fraud).gt(0)) {
      if (toDecimal(fraud).gt(toDecimal(transfer))) errors.push({ rowIndex, columnKey: 'fraudLossAmount', message: '欺诈损失默认从转U扣除，不能大于转U' })
    }
  })

  return { errors, warnings, normalizedDates }
}

export function buildWorksheetTsv(rows: WorksheetRow[], columns: WorksheetColumn[], validation: WorksheetValidation) {
  const submittedColumns = columns.filter((column) => Boolean(column.importHeader))
  const values = rows
    .map((row, rowIndex) => ({ row, rowIndex }))
    .filter(({ row }) => rowHasWorksheetData(row))
    .map(({ row, rowIndex }) => {
      const valuesForRow = submittedColumns.map((column) => {
        if (column.key === 'businessDate') return validation.normalizedDates[rowIndex] || row.businessDate.trim()
        return normalizeAmount(row[column.key], column.key === 'openingBalance').value || row[column.key].trim()
      })
      const normalizedFraud = normalizeAmount(row.fraudLossAmount).value
      const fraudSource = normalizedFraud && toDecimal(normalizedFraud).gt(0) ? 'TRANSFER' : ''
      return [...valuesForRow, fraudSource]
    })
  return [[...submittedColumns.map((column) => column.importHeader || ''), '欺诈承担方'].join('\t'), ...values.map((row) => row.join('\t'))].join('\n')
}
