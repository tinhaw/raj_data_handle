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
  let detail = { batch: { id: 63, status: 'CREATING', remoteOptions: { creationIntervalSeconds: 5 } }, issues }
  const writes = []
  const messages = []
  const processing = new Set()
  const context = vm.createContext({
    Error,
    canGenerate: { value: true }, continuingCreationBatchId: { value: undefined },
    isProcessing: row => processing.has(row.detail.batch.id),
    markProcessing: (id, active) => active ? processing.add(id) : processing.delete(id),
    remoteMarketLabel: () => 'RajSpin', replaceCodeGroup: () => {}, loadCodeGroups: async () => {}, wait: async () => {},
    isRepairing: row => row.detail.batch.status === 'CREATING' && Boolean(row.detail.batch.publishedAt),
    ElMessage: Object.fromEntries(['warning', 'error', 'success'].map(kind => [kind, text => messages.push([kind, text])])),
    ElMessageBox: { confirm: async () => {} },
    api: { redemption: {
      batch: async () => structuredClone(detail),
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
  const code = section('function pendingRemoteCreationIssues(', 'function failedIssues(')
    + section('function canRetryRemoteCreation(', 'async function loadRemoteConnections(')
    + section('function hasPendingPublishReservation(', 'function remoteMarketLabel(')
    + section('async function continuePendingCreation(', 'async function retrySelectedFailedRemoteCreations(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, writes, messages, processing, row: () => ({ campaign: {}, detail: structuredClone(detail) }), detail }
}

test('the missing RajSpin item is selectable while 149 existing configurations are preserved', async () => {
  assert.match(source, /v-if="canContinuePendingCreation\(selectedGroup\)"[\s\S]+?@click="continuePendingCreation\(selectedGroup\)">继续创建剩余配置/)
  assert.ok(source.indexOf('v-if="canContinuePendingCreation(selectedGroup)"') < source.indexOf('<el-descriptions :column="2"'))
  const fixture = setup([...Array.from({ length: 149 }, (_, i) => issue(i + 1, 'CREATED', { remoteConfigurationId: `remote-${i + 1}` })), issue(150)])
  assert.equal(fixture.context.canContinuePendingCreation(fixture.row()), true)
  await fixture.context.continuePendingCreation(fixture.row())
  assert.deepEqual(fixture.writes, [[150]])
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
  assert.deepEqual(fixture.writes, [[2]])
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
  assert.deepEqual(fixture.writes, [[1], [2]])
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
  assert.deepEqual(fixture.writes, [[1]])
  const cancelled = setup([issue(1)])
  cancelled.context.ElMessageBox.confirm = async () => { throw Error('cancelled') }
  await cancelled.context.continuePendingCreation(cancelled.row())
  assert.deepEqual(cancelled.writes, [])
  assert.equal(cancelled.processing.size, 0)
})
