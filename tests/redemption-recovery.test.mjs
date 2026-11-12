import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
const code = source.slice(source.indexOf('const checkingRecovery = ref(false)'), source.indexOf('const reusingConfigurations = ref(false)'))
function fixture(overrides = {}) {
  const calls = [], messages = []
  const group = { campaign: {}, detail: { batch: { id: 9, remoteMarketCode: 'fixture' }, issues: [
    { id: 1, rowVersion: 5, workflowStatus: 'CODE_IMPORTED', reusedFromIssueId: 10 },
    { id: 2, rowVersion: 6, workflowStatus: 'FAILED' },
  ] } }
  const parameters = { issueId: 1, ownerId: 10, batchId: 9, accountId: 8, marketId: 7, marketName: 'fixture',
    issueVersion: 5, ownerVersion: 1, batchVersion: 1, claimDate: '2027-01-02', validFrom: '2027-01-03', validTo: '2027-01-05',
    labels: [41], bonusMin: 2, bonusMax: 11, options: { keyNumber: 3, singleKeyLimit: 19, singleUserLimit: 2 } }
  const missing = { id: 70, status: 'MISSING', rowVersion: 4, requestedIssueId: 1, ownerIssueId: 10,
    oldConfigurationId: 'old', reason: 'confirmed missing', relatedBatchCount: 4, parameters }
  const context = vm.createContext({ Error, Set, JSON, ref: value => ({ value }), canGenerate: { value: true },
    selectedGroup: { value: group }, selectedTaskMembers: { value: [group] },
    replaceCodeGroup: () => {}, loadCodeGroups: async () => {},
    generateCodes: async () => { calls.push('continue'); return true },
    ElMessage: { success: text => messages.push(text), warning: text => messages.push(text) },
    ElMessageBox: { confirm: async text => { calls.push(['confirm', text]) } },
    api: { redemption: {
      batch: async () => structuredClone(group.detail),
      inspectRecovery: async id => { calls.push(['inspect', id]); return { ...structuredClone(missing), requestedIssueId: id } },
      rebuildMissing: async (...args) => { calls.push(['rebuild', ...args]); return group.detail },
      ...overrides,
    } },
  })
  vm.runInContext(ts.transpileModule(code + '; globalThis.recoveryViews = recoveryViews; globalThis.recoveryProgress = recoveryProgress;', { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, calls, messages, missing }
}
test('read-only inspection includes already imported shared rows and never creates', async () => {
  const { context, calls } = fixture()
  await context.inspectMissingConfigurations()
  assert.deepEqual(calls, [['inspect', 1], ['inspect', 2]])
  assert.match(context.recoveryProgress.value, /2 条旧配置确认缺失.*重试并重建/)
})
test('confirmation shows actual task parameters and cancellation sends no rebuild', async () => {
  const { context, calls, missing } = fixture()
  context.recoveryViews.value = [missing]
  context.ElMessageBox.confirm = async text => { calls.push(text); throw Error('cancel') }
  await context.rebuildMissingConfigurations()
  assert.match(calls[0], /2–11.*每码 19 次.*每用户 2 次.*每组 3 码.*2027-01-03 至 2027-01-05.*标签 41.*4 个共享批次/)
  assert.equal(calls.length, 1)
})
test('changed policy stops before any rebuild even after confirmation', async () => {
  const { context, calls, missing } = fixture()
  context.recoveryViews.value = [missing]
  context.api.redemption.inspectRecovery = async () => ({ ...missing, parameters: { ...missing.parameters, bonusMax: 22 } })
  await context.rebuildMissingConfigurations()
  assert.equal(calls.filter(call => Array.isArray(call) && call[0] === 'rebuild').length, 0)
  assert.match(context.recoveryProgress.value, /参数已变化/)
})
test('unknown rebuild stops the serial queue and retains a retry explanation', async () => {
  const { context, calls, missing } = fixture({ rebuildMissing: async () => { calls.push('uncertain'); throw Error('创建结果待核对') } })
  context.recoveryViews.value = [missing, { ...missing, id: 71, requestedIssueId: 2 }]
  await context.rebuildMissingConfigurations()
  assert.equal(calls.filter(call => call === 'uncertain').length, 1)
  assert.match(context.recoveryProgress.value, /已保存 0 条进度.*创建结果待核对/)
  assert.equal(context.recoveryViews.value.length, 2)
})
