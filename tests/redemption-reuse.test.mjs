import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function section(start, end) {
  const a = source.indexOf(start), b = source.indexOf(end, a)
  assert.ok(a >= 0 && b > a)
  return source.slice(a, b)
}
function load(code, objects) {
  const context = vm.createContext(objects)
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return context
}
test('batch reconciliation calls only read-verify-link and leaves unverified identities unresolved', async () => {
  const calls = [], messages = []
  const detail = { batch: { id: 9 }, issues: [
    { id: 1, workflowStatus: 'FAILED', rowVersion: 2 },
    { id: 2, workflowStatus: 'CREATED', remoteConfigurationId: '-1', creationNeedsReconciliation: true, rowVersion: 3 },
    { id: 3, workflowStatus: 'CODE_IMPORTED', reusedFromIssueId: 8, remoteConfigurationId: '44', rowVersion: 1 },
  ] }
  const context = load(section('const reusingConfigurations = ref(false)', 'async function retryRemoteCreation('), {
    Error, ref: value => ({ value }), canGenerate: { value: true }, codeGroups: { value: [] },
    selectedGroup: { value: { campaign: {}, detail } }, isProcessing: () => false,
    needsCreationReconciliation: issue => issue.creationNeedsReconciliation === true,
    confirmCreationRewards: async detail => detail, replaceCodeGroup: () => {}, loadCodeGroups: async () => {},
    ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(kind => [kind, message => messages.push(message)])),
    api: { redemption: {
      batch: async () => structuredClone(detail),
      reuseExistingConfiguration: async (id, version) => {
        calls.push([id, version])
        if (id === 2) throw Error('远端配置码串不匹配')
        return structuredClone(detail)
      },
      createRemoteConfiguration: () => { throw Error('Reconciliation must never create') },
    } },
  })
  await context.reuseExistingConfigurations()
  assert.deepEqual(calls, [[1, 2], [2, 3]])
  assert.match(messages.at(-1), /已复用 1 条.*1 条未关联/)
})
test('shared published configurations remain downloadable without inventing a batch publication', async () => {
  const calls = []
  const detail = { batch: { id: 9, status: 'PUBLISHED', remotePublishTaskId: null },
    issues: [{ id: 1, workflowStatus: 'PUBLISHED' }, { id: 2, workflowStatus: 'CODE_IMPORTED' }] }
  const context = load(section('function canDownloadScheduledCodes(', 'const externalTarget')
      + section('async function downloadPublishedCodes(', 'async function cancelScheduledPublish('), {
    publicationCheck: () => undefined, markProcessing: () => {}, replaceCodeGroup: () => {}, loadCodeGroups: async () => {},
    ElMessage: { success: () => {}, warning: () => {}, error: () => {} },
    verifyRemotePublication: () => { throw Error('No synthetic batch task may be verified') },
    showPublicationResult: () => {}, api: { redemption: { downloadRemoteCode: async id => {
      calls.push(id)
      return { ...detail, batch: { ...detail.batch, status: 'COMPLETED' } }
    } } },
  })
  assert.equal(context.canDownloadScheduledCodes({ detail }), true)
  assert.equal(await context.downloadPublishedCodes({ campaign: {}, detail }), true)
  assert.deepEqual(calls, [1])
})

test('reused rows identify the existing remote policy instead of claiming the requested limit applies', () => {
  const context = load(section('function reusedIssueLimitLabel(', 'async function reuseExistingConfigurations('), {
    codeGroups: { value: [{ detail: { batch: { id: 8, taskNumber: '202611110001' } } }] },
    singleKeyLimitLabel: () => '3 次',
  })
  const alias = { reusedFromIssueId: 7, reusedFromBatchId: 8 }
  assert.equal(context.reusedIssueLimitLabel({}, alias), '沿用远端已有配置')
  assert.equal(context.reusedIssueLimitLabel({}, {}), '3 次')
  assert.match(context.reuseOrigin(alias), /202611110001.*沿用远端已有配置/)
})
