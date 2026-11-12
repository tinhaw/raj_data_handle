import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function section(start, end) {
  const from = source.indexOf(start)
  assert.ok(from >= 0 && source.indexOf(end, from) > from)
  return source.slice(from, source.indexOf(end, from)).replace(/\nasync\s*$/, '\n')
}
function fixture(fail = true) {
  const rows = [1, 2].map(id => ({ batch: { id, remoteOptions: { creationIntervalSeconds: 1 } },
    issues: [1, 2, 3].map(index => ({ id: id * 10 + index, workflowStatus: 'PENDING_CREATION' })) }))
  const writes = [], messages = [], processing = new Set(), displayed = []
  const context = vm.createContext({
    checkPendingCreationDuplicates: async () => ({ confirmed: true, fingerprints: {} }),
    duplicateCreationReview: { value: undefined },
    Error, Date, created: structuredClone(rows), form: { value: { remoteOptions: {} } },
    selectedGroup: { value: { campaign: {}, detail: rows[0] } },
    needsCreationReconciliation: issue => issue.creationNeedsReconciliation === true,
    markProcessing: (id, on) => on ? processing.add(id) : processing.delete(id),
    confirmCreationRewards: async detail => detail, replaceCodeGroup: row => displayed.push(row), loadCodeGroups: async () => {}, wait: async () => {},
    ElMessage: Object.fromEntries(['warning', 'error', 'success'].map(kind => [kind, text => messages.push(text)])),
    api: { redemption: {
      batch: async id => structuredClone(rows.find(row => row.batch.id === id)),
      createRemoteConfiguration: async id => {
        writes.push(id)
        const row = rows.find(row => row.issues.some(issue => issue.id === id))
        const issue = row.issues.find(issue => issue.id === id)
        if (fail && id === 12) {
          Object.assign(issue, { workflowStatus: 'FAILED', creationNeedsReconciliation: true, creationAwaitingRemoteReview: true })
          throw Error('远端创建结果未确认：待远端主管审核')
        }
        issue.workflowStatus = 'CREATED'
        return structuredClone(row)
      },
    } },
  })
  const outer = section('    for (const detail of created) {', '  } catch (error) {')
  const code = section('async function generateCodes(', 'function openPublishDialog(')
    + `\nasync function runAll() { ${outer} }`
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { rows, writes, messages, processing, displayed, context }
}

test('review response stops remaining configurations and subsequent markets, then refreshes the failed row', async () => {
  const f = fixture()
  await f.context.runAll()
  assert.deepEqual(f.writes, [11, 12])
  assert.equal(f.rows[0].issues[2].workflowStatus, 'PENDING_CREATION')
  assert.ok(f.rows[1].issues.every(issue => issue.workflowStatus === 'PENDING_CREATION'))
  assert.equal(f.displayed.at(-1).detail.issues[1].creationAwaitingRemoteReview, true)
  assert.equal(f.processing.size, 0)
  assert.match(f.messages.at(-1), /已停止后续自动创建.*待远端主管审核/)
})

test('normal positive responses continue across markets without automatic publishing', async () => {
  const f = fixture(false)
  await f.context.runAll()
  assert.deepEqual(f.writes, [11, 12, 13, 21, 22, 23])
  assert.equal(f.processing.size, 0)
})

test('fresh pending review prevents a stale initial detail from submitting any create', async () => {
  const f = fixture()
  f.rows[0].issues[0].creationNeedsReconciliation = true
  await f.context.runAll()
  assert.deepEqual(f.writes, [])
})

test('batch retry stops on its first review response and leaves other selected issues untouched', async () => {
  const f = fixture()
  const group = { campaign: {}, detail: f.rows[0] }
  Object.assign(f.context, {
    selectedGroup: { value: group }, isRepairing: () => false,
    selectedFailedRemoteCreations: () => f.rows[0].issues,
    ElMessageBox: { confirm: async () => {} }, retryingSelectedFailedTasks: { value: false },
    remoteMarketLabel: () => 'test-market', formatDate: () => 'test-date', clearFailedIssueSelection: () => {},
  })
  vm.runInContext(ts.transpileModule(section('async function retrySelectedFailedRemoteCreations(', 'async function exportMultiMarketGroup('),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, f.context)
  await f.context.retrySelectedFailedRemoteCreations()
  assert.deepEqual(f.writes, [11, 12])
  assert.equal(f.context.retryingSelectedFailedTasks.value, false)
  assert.equal(f.processing.size, 0)
  assert.match(f.messages.at(-1), /已停止后续重试.*待远端主管审核/)
})
