import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function section(start, end) { const a = source.indexOf(start); const b = source.indexOf(end, a); assert.ok(a >= 0 && b > a); return source.slice(a, b).replace(/\nasync\s*$/, '\n') }
function fixture() {
  const detail = { batch: { id: 91, status: 'CREATING', remoteOptions: { creationIntervalSeconds: 5 } },
    issues: [1, 2].map(id => ({ id, workflowStatus: 'PENDING_CREATION' })) }
  const calls = [], messages = []
  const plans = [1, 2].map(id => ({ id: id + 10, requestedIssueId: id, rowVersion: 1, configurationId: String(id + 900),
    status: 'CHECKED', previousMin: 1, previousMax: 3,
    parameters: { marketName: 'Test market', claimDate: `2027-01-0${id}`, bonusMin: 1, bonusMax: 7,
      linkedIssueIds: [id, id + 20], sharedBatches: [{ id: 91 }, { id: 92 }], options: { creationIntervalSeconds: 5 } } }))
  const context = vm.createContext({
    checkPendingCreationDuplicates: async () => ({ confirmed: true, fingerprints: {} }), Error, JSON, Date, String, Math,
    form: { value: { remoteOptions: {} } }, selectedGroup: { value: undefined },
    needsCreationReconciliation: () => false, markProcessing: () => {}, loadCodeGroups: async () => {}, wait: async () => {},
    ElMessage: Object.fromEntries(['success', 'warning'].map(kind => [kind, text => messages.push([kind, text])])),
    ElMessageBox: { confirm: async message => calls.push(['confirm', message]) },
    api: { redemption: {
      batch: async () => structuredClone(detail),
      createRemoteConfiguration: async id => {
        calls.push(['create', id]); detail.issues.find(issue => issue.id === id).workflowStatus = 'REWARD_CONFIRM_REQUIRED'
        return structuredClone(detail)
      },
      checkRewardPolicy: async id => { calls.push(['check', id]); return structuredClone(plans.find(plan => plan.requestedIssueId === id)) },
      applyRewardPolicy: async id => {
        calls.push(['apply', id]); detail.issues.find(issue => issue.id === id).workflowStatus = 'CREATED'
        if (detail.issues.every(issue => issue.workflowStatus === 'CREATED')) detail.batch.status = 'READY_TO_PUBLISH'
        return structuredClone(detail)
      },
    } },
  })
  const code = section('function needsCreationRewardCheck(', 'function reconciliationIssues(')
    + section('function rewardPolicyIntent(', 'async function openTaskRewardPolicies(')
    + section('async function generateCodes(', 'function openPublishDialog(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { detail, plans, calls, messages, context }
}

test('new creation groups same-code reward differences into one explicit confirmation before updates', async () => {
  const f = fixture()
  assert.equal(await f.context.generateCodes(f.detail), true)
  assert.equal(f.calls.filter(call => call[0] === 'confirm').length, 1)
  assert.deepEqual(f.calls.filter(call => call[0] === 'apply'), [['apply', 1], ['apply', 2]])
  const confirmation = f.calls.findIndex(call => call[0] === 'confirm')
  assert.ok(f.calls.findIndex(call => call[0] === 'apply') > confirmation)
  assert.match(f.calls[confirmation][1], /实际 1–3 → 本任务 1–7.*共享 2 个批次/)
  assert.equal(f.detail.batch.status, 'READY_TO_PUBLISH')
})

test('cancel preserves pending tasks and never reports generated success or modifies rewards', async () => {
  const f = fixture()
  f.context.ElMessageBox.confirm = async () => { throw Error('cancel') }
  assert.equal(await f.context.generateCodes(f.detail), false)
  assert.equal(f.calls.filter(call => call[0] === 'apply').length, 0)
  assert.ok(f.detail.issues.every(issue => issue.workflowStatus === 'REWARD_CONFIRM_REQUIRED'))
  assert.equal(f.messages.filter(message => message[0] === 'success').length, 0)
})

test('permission rejection or unknown update result stops later reward writes and reports no success', async () => {
  for (const message of ['账号没有奖励修改权限', '奖励修改结果待核对']) {
    const f = fixture()
    f.context.api.redemption.applyRewardPolicy = async id => { f.calls.push(['apply', id]); throw Error(message) }
    assert.equal(await f.context.generateCodes(f.detail), false)
    assert.deepEqual(f.calls.filter(call => call[0] === 'apply'), [['apply', 1]])
    assert.equal(f.messages.filter(message => message[0] === 'success').length, 0)
  }
})

test('actual amount or shared scope changing after confirmation requires new consent', async () => {
  for (const change of [plan => { plan.previousMax = 4 }, plan => { plan.parameters.linkedIssueIds.push(99) }]) {
    const f = fixture(); f.context.ElMessageBox.confirm = async () => change(f.plans[0])
    assert.equal(await f.context.generateCodes(f.detail), false)
    assert.equal(f.calls.filter(call => call[0] === 'apply').length, 0)
    assert.match(f.messages.at(-1)[1], /已变化.*重新确认/)
  }
})

test('a successful HTTP response that still has an unverified reward cannot become generation success', async () => {
  const f = fixture()
  f.context.api.redemption.applyRewardPolicy = async id => { f.calls.push(['apply', id]); return structuredClone(f.detail) }
  assert.equal(await f.context.generateCodes(f.detail), false)
  assert.deepEqual(f.calls.filter(call => call[0] === 'apply'), [['apply', 1]])
  assert.equal(f.messages.filter(message => message[0] === 'success').length, 0)
})

test('confirmed duplicate review is forwarded to every pending create while reward readback remains required', async () => {
  const f = fixture()
  const review = { confirmed: true, fingerprints: { '10': 'review-v1' } }
  const payloads = []
  const create = f.context.api.redemption.createRemoteConfiguration
  f.context.api.redemption.createRemoteConfiguration = async (id, retry, approved) => {
    payloads.push({ retry, approved }); return create(id)
  }
  assert.equal(await f.context.generateCodes(f.detail, review), true)
  assert.equal(payloads.length, 2)
  assert.ok(payloads.every(p => p.retry === false && p.approved === review))
  assert.equal(f.calls.filter(c => c[0] === 'apply').length, 2)
})
