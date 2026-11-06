import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/claimTrend.ts', import.meta.url), 'utf8')
const exports = {}
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, { exports })
const { trendPoints, trendPath, trendAxis, trendPointLabel, updateTrendExclusions, trendColumnLabel } = exports
const cell = (count, complete = true, state = 'complete') => ({ count, complete, state })
const rows = [
 { date: '2026-11-01', cells: { win: cell(0), luck: cell(4) } },
 { date: '2026-11-02', cells: { win: cell(3, false, 'partial'), luck: cell(0) } },
 { date: '2026-11-03', cells: { win: cell(null, false, 'pending'), luck: cell(2) } },
 { date: '2026-11-04', cells: { win: cell(8), luck: cell(null, true, 'future') } },
]
test('each market/tier uses its own table cells; known zero, partial and missing remain distinct', () => {
 assert.deepEqual(Array.from(trendPoints(rows, 'win'), p => p.value), [0, 3, null, 8])
 assert.deepEqual(Array.from(trendPoints(rows, 'luck'), p => p.value), [4, 0, 2, null])
 assert.equal(trendPointLabel(trendPoints(rows, 'win')[0]), '0 次')
 assert.equal(trendPointLabel(trendPoints(rows, 'win')[1]), '3 次（部分）')
 assert.equal(trendPointLabel(trendPoints(rows, 'win')[2]), '待同步')
 assert.equal(trendPointLabel(trendPoints(rows, 'luck')[3]), '未到日期')
})
test('missing dates break the curve instead of becoming zero or joining across the gap', () => {
 assert.equal(trendPath(trendPoints(rows, 'win'), i => i, n => n), 'M 0 0 C 0.5 0 0.5 3 1 3 M 3 8')
 assert.deepEqual(Array.from(trendPoints(rows, 'missing'), p => p.value), [null, null, null, null])
})
test('date and market filters retain hidden selections; new columns default to selected', () => {
 assert.deepEqual(Array.from(updateTrendExclusions(['win', 'luck'], [], ['win'])), ['luck'])
 assert.deepEqual(Array.from(updateTrendExclusions(['win'], ['luck'], [])), ['luck', 'win'])
 assert.deepEqual(Array.from(updateTrendExclusions(['win'], ['luck', 'win'], ['win'])), ['luck'])
})
test('axes start at zero and only use integer ticks, including zero-only and empty series', () => {
 for (const values of [[], [0, null, 0], [1], [73, 10], [123456]]) {
  const axis = trendAxis(values)
  assert.equal(axis.ticks[0], 0)
  assert.ok(axis.ticks.every(Number.isInteger))
  assert.ok(axis.maximum >= Math.max(0, ...values.filter(n => n !== null)))
 }
})
test('series labels distinguish equal tier names across markets and include the table header metadata', () => {
 const column = { sourceName: 'RajWin', tierName: '日充值100–199', currency: 'INR', rewardMin: '13', rewardMax: '13', labels: [901990] }
 assert.ok(trendColumnLabel(column).includes('RajWin · 日充值100–199'))
 assert.ok(trendColumnLabel(column).includes('INR 13–13'))
 assert.notEqual(trendColumnLabel(column), trendColumnLabel({ ...column, sourceName: 'RajLuck' }))
})
