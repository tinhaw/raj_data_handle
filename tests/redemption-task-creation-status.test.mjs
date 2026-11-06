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
function member(id, status, count = 150, extra = {}) {
  return {
    campaign: {},
    detail: {
      batch: { id, status, expectedCodeCount: 150, createdCount: status === 'COMPLETED' ? 0 : count, importedCodeCount: status === 'COMPLETED' ? count : 0, plannedCodeCount: 150, ...extra },
      issues: Array.from({ length: 150 }, (_, index) => ({ id: `${id}-${index}`, workflowStatus: index >= count ? 'PENDING_CREATION' : status === 'COMPLETED' ? 'CODE_IMPORTED' : 'CREATED' })),
    },
  }
}
function fixture() {
  const task = { members: [member(61, 'COMPLETED'), member(62, 'COMPLETED'), member(63, 'CREATING', 149)] }
  const context = vm.createContext({
    canGenerate: { value: true }, working: { value: false }, continuingCreationBatchId: { value: undefined },
    processingGroupIds: { value: new Set() }, groupKey: String,
    publicationCheck: row => row.check,
    publicationLabel: check => check?.publicationState === 'COMPLETED' ? '发布完成' : '发布待核验',
    codeAcquisitionStatus: row => row.detail.batch.status === 'COMPLETED' ? '兑换码已入库' : '等待发布核验',
    isScheduledPublish: row => row.detail.batch.remotePublishMode === 'SCHEDULED',
    remoteMarketLabel: row => ({ 61: 'RajWin', 62: 'RajLuck', 63: 'RajSpin' }[row.detail.batch.id]),
    selectedFailedIssueIds: { value: [] }, failedIssueTable: { value: undefined }, selectedTaskMembers: { value: [] }, selectedGroup: { value: undefined }, activeTaskBatchId: { value: '' }, detailDrawerVisible: { value: false },
    api: { redemption: { batch: async id => structuredClone(task.members.find(row => row.detail.batch.id === id).detail) } },
  })
  const code = section('function isProcessing(', 'function canCancelScheduledPublish(')
    + section('function hasPendingPublishReservation(', 'function remoteMarketLabel(')
    + section('function taskAcquisitionStatus(', 'async function verifyPendingPublications(')
    + section('async function openTaskDetail(', 'function selectTaskMember(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { task, context, spin: task.members[2] }
}

test('149 created and one pending alongside two completed markets is actionable in the list', () => {
  const { task, context, spin } = fixture()
  assert.equal(context.taskStatus(task).text, '待继续创建')
  assert.equal(context.groupStatus(spin).text, '待继续创建')
  assert.equal(context.taskCreationSummary(task), 'RajSpin：1 条待创建')
  assert.equal(context.taskAcquisitionStatus(task), '2/3 个盘口兑换码已入库')
  assert.match(context.taskProgress(task), /449 \/ 450.*1 条待创建/)
  assert.equal(context.taskPendingCreationCount(task), 1)
  assert.equal(context.canOpenPendingCreationTask(task), true)
  assert.match(source, /class="creation-status-summary"[^\n]+taskCreationSummary\(row\)/)
  assert.match(source, /@click="openPendingCreationTask\(row\)">处理待创建/)
})

test('published siblings cannot hide an unfinished market', () => {
  const { task, context } = fixture()
  task.members[0].detail.batch.status = 'PUBLISHED'
  assert.equal(context.taskStatus(task).text, '待继续创建')
  assert.equal(context.taskCreationSummary(task), 'RajSpin：1 条待创建')
})

test('a local running sequence is distinguished from idle pending work', () => {
  const { task, context, spin } = fixture()
  context.processingGroupIds.value.add('63')
  assert.equal(context.groupStatus(spin).text, '配置创建中')
  assert.equal(context.taskStatus(task).text, '配置创建中')
  assert.match(context.taskCreationSummary(task), /RajSpin：正在创建，1 条待创建/)
  assert.equal(context.canOpenPendingCreationTask(task), false)
})

test('an outstanding remote request without a local sequence requires verification', () => {
  const { task, context, spin } = fixture()
  spin.detail.issues[149].workflowStatus = 'CREATING_REMOTE'
  assert.equal(context.taskStatus(task).text, '创建结果待确认')
  assert.equal(context.groupStatus(spin).text, '创建结果待确认')
  assert.equal(context.taskCreationSummary(task), 'RajSpin：1 条请求待确认')
  assert.equal(context.taskPendingCreationCount(task), 0)
})

test('failures and remaining pending work are surfaced together', () => {
  const { task, context, spin } = fixture()
  spin.detail.issues[148].workflowStatus = 'FAILED'
  assert.equal(context.taskStatus(task).text, '配置创建失败')
  assert.equal(context.taskCreationSummary(task), 'RajSpin：1 条创建失败，1 条待创建')
  assert.match(context.taskProgress(task), /448 \/ 450.*1 个失败/)
})

test('completed, ready and repair tasks retain their distinct states', () => {
  const { task, context, spin } = fixture()
  spin.detail.issues[149].workflowStatus = 'CREATED'
  spin.detail.batch.status = 'READY_TO_PUBLISH'
  assert.equal(context.taskStatus(task).text, '待发布')
  assert.equal(context.taskCreationSummary(task), '')
  assert.equal(context.taskPendingCreationCount(task), 0)
  spin.detail.batch.status = 'COMPLETED'
  assert.equal(context.taskStatus(task).text, '生成成功')
  spin.detail.batch.status = 'CREATING'
  spin.detail.batch.publishedAt = '2026-09-29T12:00:00Z'
  spin.detail.issues[149].workflowStatus = 'PENDING_CREATION'
  assert.equal(context.taskStatus(task).text, '待补齐缺失配置')
  assert.equal(context.taskPendingCreationCount(task), 0)
  spin.detail.issues[149].workflowStatus = 'CREATED'
  assert.equal(context.groupStatus(spin).text, '待发布')
  assert.equal(context.taskStatus(task).text, '待发布')
})

test('read-only users see the cause but cannot use the recovery action', () => {
  const { task, context } = fixture()
  context.canGenerate.value = false
  assert.equal(context.taskStatus(task).text, '待继续创建')
  assert.equal(context.taskCreationSummary(task), 'RajSpin：1 条待创建')
  assert.equal(context.taskPendingCreationCount(task), 0)
  assert.equal(context.canOpenPendingCreationTask(task), false)
})

test('creation loops, receipts and other outstanding requests block conflicting entry', () => {
  const { task, context, spin } = fixture()
  context.working.value = true
  assert.equal(context.canOpenPendingCreationTask(task), false)
  context.working.value = false
  context.continuingCreationBatchId.value = 61
  assert.equal(context.canOpenPendingCreationTask(task), false)
  context.continuingCreationBatchId.value = undefined
  task.members[0].detail.issues[0].workflowStatus = 'CREATING_REMOTE'
  assert.equal(context.canOpenPendingCreationTask(task), false)
  task.members[0].detail.issues[0].workflowStatus = 'CODE_IMPORTED'
  spin.detail.issues[149].remoteReferenceId = 'receipt'
  assert.equal(context.taskPendingCreationCount(task), 0)
})

test('the list recovery entry opens fresh details directly on RajSpin without any writes', async () => {
  const { task, context } = fixture()
  const reads = []
  const batch = context.api.redemption.batch
  context.api.redemption.batch = async id => { reads.push(id); return batch(id) }
  await context.openPendingCreationTask(task)
  assert.deepEqual(reads, [61, 62, 63])
  assert.equal(context.selectedGroup.value.detail.batch.id, 63)
  assert.equal(context.activeTaskBatchId.value, '63')
  assert.equal(context.detailDrawerVisible.value, true)
})
