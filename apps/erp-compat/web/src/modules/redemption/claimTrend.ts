import type { ClaimCell, ClaimColumn, ClaimRow } from '@/api/claimStatistics'

export interface ClaimTrendPoint {
  date: string
  value: number | null
  cell: ClaimCell | undefined
}

export function trendColumnLabel(column: ClaimColumn): string {
  const labels = column.labels.length ? ` · 标签 ${column.labels.join('、')}` : ''
  return `${column.sourceName} · ${column.tierName}（${column.currency} ${column.rewardMin}–${column.rewardMax}${labels}）`
}

export function trendPoints(rows: ClaimRow[], key: string): ClaimTrendPoint[] {
  return rows.map(row => {
    const cell = row.cells[key]
    const count = cell?.count
    return {
      date: row.date, cell,
      value: typeof count === 'number' && Number.isFinite(count) && count >= 0 ? count : null,
    }
  })
}

export function trendPointLabel(point: ClaimTrendPoint): string {
  if (point.value !== null) return `${point.value.toLocaleString()} 次${point.cell?.complete ? '' : '（部分）'}`
  if (point.cell?.state === 'future') return '未到日期'
  if (point.cell?.state === 'notApplicable') return '无适用配置'
  return '待同步'
}

// Keep hidden markets' choices when the query temporarily filters them out.
// Newly appearing columns remain selected by default.
export function updateTrendExclusions(available: string[], excluded: string[], selected: string[]): string[] {
  const visible = new Set(available), chosen = new Set(selected)
  return [...excluded.filter(key => !visible.has(key)), ...available.filter(key => !chosen.has(key))]
}

export function trendPath(points: ClaimTrendPoint[], x: (index: number) => number, y: (value: number) => number): string {
  let previous: { x: number; y: number } | undefined
  return points.map((point, index) => {
    if (point.value === null) { previous = undefined; return '' }
    const current = { x: x(index), y: y(point.value) }
    const mid = previous ? (previous.x + current.x) / 2 : 0
    const command = previous
      ? `C ${mid} ${previous.y} ${mid} ${current.y} ${current.x} ${current.y}`
      : `M ${current.x} ${current.y}`
    previous = current
    return command
  }).filter(Boolean).join(' ')
}

export function trendAxis(values: Array<number | null>): { maximum: number; ticks: number[] } {
  const maximum = values.reduce<number>((max, value) => value !== null && Number.isFinite(value) ? Math.max(max, value) : max, 0)
  const roughStep = Math.max(1, maximum / 4)
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const step = [1, 2, 5, 10].find(value => value * magnitude >= roughStep)! * magnitude
  const top = Math.max(step, Math.ceil(maximum / step) * step)
  return { maximum: top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) }
}
