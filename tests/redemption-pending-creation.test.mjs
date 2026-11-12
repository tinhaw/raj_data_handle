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
  return source.slice(from, source.indexOf(end, from))
}
const issue = (id, workflowStatus = 'PENDING_CREATION', extra = {}) => ({ id, workflowStatus, ...extra })
function setup(issues) {
  let detail = { batch: { id: 63, taskId: 88, status: 'CREATING', remoteOptions: { creationIntervalSeconds: 5 } }, issues }
  const writes = []
  const messages = []
  const processing = new Set()
  const context = vm.createContext({
    Error,
    taskDuplicateReviews: new Map(), duplicateReviewResolve: undefined,
    duplicateReviewAcknowledged: { value: false }, duplicateDialogVisible: { value: false }, duplicateConflicts: { value: [] },
    canGenerate: { value: true }, continuingCreationBatchId: { value: undefined },
    isProcessing: row => processing.has(row.detail.batch.id),
    markProcessing: (id, active) => active ? processing.add(id) : processing.delete(id),
    remoteMarketLabel: () => 'RajSpin', confirmCreationRewards: async detail => detail, replaceCodeGroup: () => {}, loadCodeGroups: async () => {}, wait: async () => {},
    isRepairing: row => row.detail.batch.status === 'CREATING' && Boolean(row.detail.batch.publishedAt),
    ElMessage: Object.fromEntries(['warning', 'error', 'success'].map(kind => [kind, text => messages.push([kind, text])])),
    ElMessageBox: { confirm: async () => {} },
    api: { redemption: {
      batch: async () => structuredClone(detail),
      checkPendingTaskDuplicates: async () => ({ conflicts: [] }),
      confirmTaskDuplicateReview: async () => {},
      createRemoteConfiguration: async (...args) => {
        writes.push(args)
        const target = detail.issues.find(item => item.id === args[0])
        target.workflowStatus = 'CREATED'
        target.remoteConfigurationId = `remote-${target.id}`
        if (detail.issues.every(item => item.workflowStatus === 'CREATED')) detail.batch.status = 'READY_TO_PUBLISH'
        return structuredClone(detail)
      },
    } },
  })
  const code = section('function creationReviewKey(', 'async function openDuplicateTask(')
    + section('function needsCreationReconciliation(', 'function isSuccess(')
    + section('function pendingRemoteCreationIssues(', 'function failedIssues(')
    + section('function canRetryRemoteCreation(', 'async function loadRemoteConnections(')
    + section('function hasPendingPublishReservation(', 'function remoteMarketLabel(')
    + section('async function continuePendingCreation(', 'async function retrySelectedFailedRemoteCreations(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, writes, messages, processing, row: () => ({ campaign: {}, detail: structuredClone(detail) }), detail }
}

test('the missing RajSpin item is selectable while 149 existing configurations are preserved', async () => {
  assert.match(source, /v-if="canContinuePendingCreation\(selectedGroup\)"[\s\S]+?@click="continuePendingCreation\(selectedGroup\)">继续创建剩余配置/)
  assert.ok(source.indexOf('v-if="canContinuePendingCreation(selectedGroup)"') < source.indexOf('<details class="task-parameters">'))
  const fixture = setup([...Array.from({ length: 149 }, (_, i) => issue(i + 1, 'CREATED', { remoteConfigurationId: `remote-${i + 1}` })), issue(150)])
  assert.equal(fixture.context.canContinuePendingCreation(fixture.row()), true)
  await fixture.context.continuePendingCreation(fixture.row())
  assert.deepEqual(fixture.writes.map(args => [args[0]]), [[150]])
  assert.equal(fixture.detail.batch.status, 'READY_TO_PUBLISH')
  assert.equal(fixture.context.continuingCreationBatchId.value, undefined)
  assert.equal(fixture.processing.size, 0)
  assert.match(fixture.messages.at(-1)[1], /请选择发布方式/)
})

test('permissions, publication, active requests and remote receipts prevent continuing', () => {
  const fixture = setup([issue(1)])
  fixture.context.canGenerate.value = false
  assert.equal(fixture.context.canContinuePendingCreation(fixture.row()), false)
  fixture.context.canGenerate.value = true
  for (const status of ['READY_TO_PUBLISH', 'PUBLISHED', 'COMPLETED']) {
    const row = fixture.row()
    row.detail.batch.status = status
    assert.equal(fixture.context.canContinuePendingCreation(row), false)
  }
  const published = fixture.row()
  published.detail.batch.publishedAt = '2026-09-29T00:00:00Z'
  assert.equal(fixture.context.canContinuePendingCreation(published), false)
  for (const issues of [[issue(1), issue(2, 'CREATING_REMOTE')], [issue(1, 'PENDING_CREATION', { remoteReferenceId: 'receipt' })], [issue(1, 'FAILED')]]) {
    const row = fixture.row()
    row.detail.issues = issues
    assert.equal(fixture.context.canContinuePendingCreation(row), false)
  }
})

test('previous retry and post-publication repair entries remain available for their states', () => {
  const fixture = setup([issue(1)])
  for (const status of ['FAILED', 'CREATING_REMOTE']) {
    assert.equal(fixture.context.canRetryRemoteCreation(issue(1, status)), true)
    assert.equal(fixture.context.canRetryRemoteCreation(issue(1, status, { remoteConfigurationId: 'existing' })), false)
    assert.equal(fixture.context.canRetryRemoteCreation(issue(1, status, { creationNeedsReconciliation: true })), false)
  }
  assert.equal(fixture.context.canRetryRemoteCreation(issue(1)), false)
  const repair = fixture.row()
  repair.detail.batch.publishedAt = '2026-09-29T00:00:00Z'
  repair.detail.issues[0].remoteReferenceId = 'previous-configuration'
  assert.equal(fixture.context.canContinuePendingCreation(repair), false)
  assert.equal(fixture.context.canContinueRepair(repair), true)
  assert.equal(fixture.context.repairActionLabel(repair), '继续补齐配置')
  repair.detail.issues[0].workflowStatus = 'CREATED'
  assert.equal(fixture.context.canContinueRepair(repair), true)
  assert.equal(fixture.context.repairActionLabel(repair), '选择发布方式')
  repair.detail.batch.remotePublishTaskId = 'PENDING:reservation'
  assert.equal(fixture.context.canContinueRepair(repair), false)
  assert.match(source, /v-if="canContinueRepair\(selectedGroup\)"[^\n]+@click="handleRepairAction\(selectedGroup\)"/)
})

test('fresh state after confirmation skips a configuration created in another page', async () => {
  const fixture = setup([issue(1), issue(2)])
  fixture.context.ElMessageBox.confirm = async () => {
    fixture.detail.issues[0] = issue(1, 'CREATED', { remoteConfigurationId: 'remote-1' })
  }
  await fixture.context.continuePendingCreation(fixture.row())
  assert.deepEqual(fixture.writes.map(args => [args[0]]), [[2]])
})

test('publication or an active request after confirmation stops all writes', async () => {
  for (const change of [detail => { detail.batch.status = 'PUBLISHED' }, detail => { detail.issues.push(issue(2, 'CREATING_REMOTE')) }]) {
    const fixture = setup([issue(1)])
    fixture.context.ElMessageBox.confirm = async () => change(fixture.detail)
    await fixture.context.continuePendingCreation(fixture.row())
    assert.deepEqual(fixture.writes, [])
    assert.match(fixture.messages.at(-1)[1], /已停止/)
  }
})

test('an uncertain failure stops the sequence and is never retried automatically', async () => {
  const fixture = setup([issue(1), issue(2), issue(3)])
  const create = fixture.context.api.redemption.createRemoteConfiguration
  fixture.context.api.redemption.createRemoteConfiguration = async (...args) => {
    if (args[0] === 2) { fixture.writes.push(args); throw Error('request interrupted') }
    return create(...args)
  }
  await fixture.context.continuePendingCreation(fixture.row())
  assert.deepEqual(fixture.writes.map(args => [args[0]]), [[1], [2]])
  assert.equal(fixture.detail.issues[2].workflowStatus, 'PENDING_CREATION')
  assert.equal(fixture.processing.size, 0)
  assert.match(fixture.messages.at(-1)[1], /request interrupted/)
})

test('double clicks cannot launch two sequences, and cancellation creates nothing', async () => {
  const fixture = setup([issue(1)])
  let release
  let confirmStarted
  const started = new Promise(resolve => { confirmStarted = resolve })
  fixture.context.ElMessageBox.confirm = () => { confirmStarted(); return new Promise(resolve => { release = resolve }) }
  const first = fixture.context.continuePendingCreation(fixture.row())
  await started
  await fixture.context.continuePendingCreation(fixture.row())
  release()
  await first
  assert.deepEqual(fixture.writes.map(args => [args[0]]), [[1]])
  const cancelled = setup([issue(1)])
  cancelled.context.ElMessageBox.confirm = async () => { throw Error('cancelled') }
  await cancelled.context.continuePendingCreation(cancelled.row())
  assert.deepEqual(cancelled.writes, [])
  assert.equal(cancelled.processing.size, 0)
})

const conflict = (issueId, reviewFingerprint = 'snapshot-v1') => ({
  source: 'LOCAL', issueId, reviewFingerprint, marketId: issueId % 2 + 1, code: `test-${issueId}`,
})
async function reviewReady(f) {
  for (let i = 0; i < 30 && !f.context.duplicateDialogVisible.value; i++) await Promise.resolve()
  assert.equal(f.context.duplicateDialogVisible.value, true)
}
function approve(f) {
  f.context.duplicateReviewAcknowledged.value = true
  f.context.finishDuplicateReview(true)
}

test('one task-wide duplicate confirmation is sent to every pending creation', async () => {
  const f = setup([issue(1), issue(2), issue(3)])
  let checks = 0
  f.context.api.redemption.checkPendingTaskDuplicates = async id => {
    checks++; assert.equal(id, 63)
    return { conflicts: [conflict(101), conflict(102), conflict(103)] }
  }
  const running = f.context.continuePendingCreation(f.row())
  await reviewReady(f)
  assert.equal(f.context.duplicateConflicts.value.length, 3)
  assert.equal(f.writes.length, 0)
  approve(f); await running
  assert.equal(checks, 1)
  assert.equal(f.writes.length, 3)
  assert.ok(f.writes.every(args => args[1] === false && args[2].confirmed
    && Object.keys(args[2].fingerprints).length === 3))
  assert.equal(f.detail.batch.status, 'READY_TO_PUBLISH')
})

test('cancelled duplicate review creates nothing and releases the continuation lock', async () => {
  const f = setup([issue(1), issue(2)])
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101)] })
  const running = f.context.continuePendingCreation(f.row())
  await reviewReady(f); f.context.finishDuplicateReview(false); await running
  assert.equal(f.writes.length, 0)
  assert.equal(f.context.taskDuplicateReviews.size, 0)
  assert.equal(f.processing.size, 0)
})

test('same task reuses an unchanged review across markets; changed facts require one new review', async () => {
  const f = setup([issue(1)])
  let conflicts = [conflict(101), conflict(102)]
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts })
  const first = f.context.checkPendingCreationDuplicates(f.detail)
  await reviewReady(f); approve(f)
  const approved = await first
  const otherMarket = { batch: { id: 64, taskId: 88 } }
  assert.equal(await f.context.checkPendingCreationDuplicates(otherMarket), approved)
  assert.equal(f.context.duplicateDialogVisible.value, false)
  conflicts = [conflict(102, 'changed')]
  const changed = f.context.checkPendingCreationDuplicates(otherMarket)
  await reviewReady(f); approve(f)
  assert.equal((await changed).fingerprints['102'], 'changed')
})

test('an unrecorded page approval never leaks to another task or pretends to be durable', async () => {
  const f = setup([issue(1)])
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101)] })
  f.context.taskDuplicateReviews.set('task:88', { confirmed: true, fingerprints: { 101: 'snapshot-v1' } })
  const other = f.context.checkPendingCreationDuplicates({ batch: { id: 77, taskId: 99 } })
  await reviewReady(f); f.context.finishDuplicateReview(false)
  assert.equal(await other, false)
  f.context.taskDuplicateReviews.clear()
  const reloaded = f.context.checkPendingCreationDuplicates(f.detail)
  await reviewReady(f); f.context.finishDuplicateReview(false)
  assert.equal(await reloaded, false)
})

test('persisted task approval survives page reload and continues without any duplicate dialog', async () => {
  const f = setup([issue(1), issue(2), issue(3)])
  assert.equal(f.context.taskDuplicateReviews.size, 0)
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101), conflict(102)], reviewConfirmed: true })
  f.context.api.redemption.confirmTaskDuplicateReview = async () => { throw Error('Already approved task must not need another confirmation') }
  await f.context.continuePendingCreation(f.row())
  assert.equal(f.context.duplicateDialogVisible.value, false)
  assert.equal(f.writes.length, 3)
  assert.ok(f.writes.every(args => args[2] === undefined), 'server loads its task approval, not a browser-provided bypass flag')
})

test('failed approval persistence stops all creation even after the user reviewed the list', async () => {
  const f = setup([issue(1)])
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101)] })
  f.context.api.redemption.confirmTaskDuplicateReview = async () => { throw Error('确认保存失败') }
  const running = f.context.continuePendingCreation(f.row())
  await reviewReady(f); approve(f); await running
  assert.equal(f.writes.length, 0)
  assert.equal(f.context.taskDuplicateReviews.size, 0)
  assert.match(f.messages.at(-1)[1], /确认保存失败/)
})

test('changed conflict during writes stops once and does not auto-confirm or replay', async () => {
  const f = setup([issue(1), issue(2), issue(3)])
  f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101)] })
  const create = f.context.api.redemption.createRemoteConfiguration
  f.context.api.redemption.createRemoteConfiguration = async (...args) => {
    if (args[0] === 2) { f.writes.push(args); throw Error('冲突记录已变化，请重新确认') }
    return create(...args)
  }
  const running = f.context.continuePendingCreation(f.row())
  await reviewReady(f); approve(f); await running
  assert.deepEqual(f.writes.map(args => args[0]), [1, 2])
  assert.equal(f.detail.issues[2].workflowStatus, 'PENDING_CREATION')
  assert.equal(f.messages.filter(message => message[0] === 'error').length, 1)
})

test('single and selected failed retries carry the same task-wide reviewed fingerprints', async () => {
  for (const bulk of [false, true]) {
    const f = setup([issue(1, 'FAILED'), issue(2, 'FAILED')])
    Object.assign(f.context, {
      selectedGroup: { value: f.row() }, retryingIssueId: { value: undefined },
      retryingSelectedFailedTasks: { value: false }, selectedFailedRemoteCreations: () => f.detail.issues,
      formatDate: () => 'date', clearFailedIssueSelection: () => {},
    })
    f.context.api.redemption.checkPendingTaskDuplicates = async () => ({ conflicts: [conflict(101), conflict(102)] })
    const code = section('async function retryRemoteCreation(', 'async function continuePendingCreation(')
      + section('async function retrySelectedFailedRemoteCreations(', 'async function exportMultiMarketGroup(')
    vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, f.context)
    const running = bulk ? f.context.retrySelectedFailedRemoteCreations() : f.context.retryRemoteCreation(f.detail.issues[0])
    await reviewReady(f); approve(f); await running
    assert.equal(f.writes.length, bulk ? 2 : 1)
    assert.ok(f.writes.every(args => args[1] === true && args[2].confirmed
      && Object.keys(args[2].fingerprints).length === 2))
  }
})

test('a failed task-wide preview never submits a create or silently falls back', async () => {
  const f = setup([issue(1)])
  f.context.api.redemption.checkPendingTaskDuplicates = async () => { throw Error('查重读取失败') }
  await f.context.continuePendingCreation(f.row())
  assert.equal(f.writes.length, 0)
  assert.equal(f.processing.size, 0)
  assert.match(f.messages.at(-1)[1], /查重读取失败/)
})
