import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
const code = source.slice(source.indexOf('const checkingRewardPolicy = ref(false)'), source.indexOf('const checkingRecovery = ref(false)'))
function fixture(overrides = {}) {
  const calls = []
  const group = { campaign: {}, detail: { batch: { id: 9 }, issues: [{ id: 1, rowVersion: 2 }] } }
  const plan = { id: 50, requestedIssueId: 1, rowVersion: 3, status: 'CHECKED', previousMin: 1, previousMax: 3,
    parameters: { marketName: 'fixture', claimDate: '2027-02-03', bonusMin: 1, bonusMax: 7,
      linkedIssueIds: [1, 4], sharedBatches: [{ id: 9, version: 2 }], options: {} } }
  const context = vm.createContext({ Error, JSON, Date, String, Math, ref: value => ({ value }),
    canGenerate: { value: true }, selectedGroup: { value: group }, selectedTaskMembers: { value: [group] },
    replaceCodeGroup: () => {}, refreshRecoveryGroups: async () => {}, wait: async () => {},
    ElMessage: { success: () => {}, warning: () => {} },
    ElMessageBox: { confirm: async message => { calls.push(['confirm', message]) } },
    api: { redemption: { batch: async () => structuredClone(group.detail),
      checkRewardPolicy: async id => { calls.push(['check', id]); return structuredClone(plan) },
      applyRewardPolicy: async (...args) => { calls.push(['apply', ...args]); return group.detail }, ...overrides } },
  })
  vm.runInContext(ts.transpileModule(code + ';globalThis.plans=rewardPolicyPlans;globalThis.progress=rewardPolicyProgress;',
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, calls, plan }
}
test('reward inspection reads actual policy without applying changes', async () => {
  const { context, calls } = fixture()
  await context.inspectRewardPolicies()
  assert.deepEqual(calls, [['check', 1]])
  assert.match(context.progress.value, /1 条需处理/)
})
test('reward confirmation displays actual and requested amounts and cancellation writes nothing', async () => {
  const { context, calls, plan } = fixture()
  context.plans.value = [plan]
  context.ElMessageBox.confirm = async message => { calls.push(['confirm', message]); throw Error('cancel') }
  await context.applyRewardPolicies()
  assert.equal(calls.length, 1)
  assert.match(calls[0][1], /实际 1–3 → 本任务 1–7.*共享 1 个批次/)
})
test('changed shared reference scope stops before applying', async () => {
  const { context, calls, plan } = fixture()
  context.plans.value = [plan]
  context.api.redemption.checkRewardPolicy = async () => ({ ...plan, parameters: { ...plan.parameters, linkedIssueIds: [1, 4, 8] } })
  await context.applyRewardPolicies()
  assert.equal(calls.filter(call => call[0] === 'apply').length, 0)
  assert.match(context.progress.value, /任务参数或共享范围已变化/)
})
test('unknown result stops the queue and refreshes its durable state', async () => {
  const { context, calls, plan } = fixture({ applyRewardPolicy: async () => { calls.push(['apply']); throw Error('结果待核对') } })
  context.plans.value = [plan, { ...plan, id: 51, requestedIssueId: 2 }]
  await context.applyRewardPolicies()
  assert.equal(calls.filter(call => call[0] === 'apply').length, 1)
  assert.match(context.progress.value, /已保存 0 条进度.*结果待核对/)
  assert.equal(context.plans.value.length, 2)
})
