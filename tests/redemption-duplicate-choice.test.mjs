import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))) }
function fixture() {
  const calls = [], messages = []
  const context = vm.createContext({ Error, String, Map, Object, Promise, JSON,
    duplicateReviewResolve: undefined, duplicateReviewAcknowledged: { value: false }, duplicateCreationReview: { value: undefined },
    usesSpecialCode: { value: true }, checkRemoteDuplicates: { value: false },
    checkingDuplicates: { value: false }, duplicateCheckProgress: { value: '' },
    duplicateConflicts: { value: [] }, duplicateDialogVisible: { value: false }, working: { value: false },
    form: { value: { remoteMarketIds: [1, 2], redemptionType: 'PREVIOUS_DAY_DEPOSIT', dateRange: ['2026-11-13', '2026-11-30'] } },
    marketTierDrafts: { value: { 1: { tiers: [{ minDepositAmount: 0 }] }, 2: { tiers: [{ minDepositAmount: 200 }] } } },
    marketKey: String, marketLabel: id => `Market ${id}`, ensureSelectedMarketDrafts: async () => {}, validateForm: () => '',
    ElMessage: { error: message => messages.push(message), warning: message => messages.push(message) },
    ElMessageBox: { confirm: async () => { calls.push(['confirm']); throw 'cancel' } },
    expectedTaskCount: () => 36, codesPerGroup: { value: 1 }, validityRuleSummary: { value: 'Daily' },
    api: { redemption: {
      checkDuplicates: async (markets, remote) => { calls.push(['check', markets.map(m => m.marketId), remote]); return { conflicts: [], remoteChecked: remote } },
      createGroup: async () => { throw Error('Task must not be created in a cancelled or blocked flow') },
    } },
  })
  const code = section('async function checkCreationDuplicates()', 'async function openDuplicateTask(')
    + section('async function createCodeGroup()', 'function markProcessing(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, calls, messages }
}

test('default local-only performs one batched check and no remote request', async () => {
  const f = fixture()
  assert.equal(await f.context.checkCreationDuplicates(), true)
  assert.equal(JSON.stringify(f.calls), JSON.stringify([['check', [1, 2], false]]))
  assert.match(source, /const checkRemoteDuplicates = ref\(false\)/)
  assert.match(source, /配置较多时可能耗时较长/)
})

test('explicit remote choice scans each market once after local check', async () => {
  const f = fixture(); f.context.checkRemoteDuplicates.value = true
  assert.equal(await f.context.checkCreationDuplicates(), true)
  assert.equal(JSON.stringify(f.calls), JSON.stringify([['check', [1, 2], false], ['check', [1], true], ['check', [2], true]]))
})

test('local duplicates wait for review; cancel stops before creation', async () => {
  const f = fixture()
  f.context.api.redemption.checkDuplicates = async (markets, remote) => {
    f.calls.push(['check', remote]); return { conflicts: [{ code: '1113rajfree', source: 'LOCAL', taskNumber: '202611120001' }], remoteChecked: false }
  }
  const pending = f.context.createCodeGroup()
  for (let i = 0; i < 8; i++) await Promise.resolve()
  assert.equal(f.context.duplicateDialogVisible.value, true)
  f.context.finishDuplicateReview(false)
  await pending
  assert.deepEqual(f.calls, [['check', false]])
  assert.equal(f.context.checkingDuplicates.value, false)
})

test('remote timeout or incomplete result stops creation and never falls back to local-only', async () => {
  for (const incomplete of [false, true]) {
    const f = fixture(); f.context.checkRemoteDuplicates.value = true
    const original = f.context.api.redemption.checkDuplicates
    f.context.api.redemption.checkDuplicates = async (markets, remote) => {
      if (!remote) return original(markets, remote)
      f.calls.push(['remote-attempt'])
      if (!incomplete) throw Error('Remote check timeout')
      return { conflicts: [], remoteChecked: false }
    }
    await f.context.createCodeGroup()
    assert.equal(f.calls.filter(c => c[0] === 'remote-attempt').length, 1)
    assert.equal(f.calls.filter(c => c[0] === 'confirm').length, 0)
    assert.equal(f.messages.length, 1)
    assert.equal(f.context.checkingDuplicates.value, false)
  }
})

test('remote-only duplicate is shown and cancels all task creation', async () => {
  const f = fixture(); f.context.checkRemoteDuplicates.value = true
  f.context.api.redemption.checkDuplicates = async (markets, remote) => ({ remoteChecked: remote,
    conflicts: remote ? [{ code: '1113rajfree', source: 'REMOTE', configurationId: '901' }] : [] })
  const pending = f.context.createCodeGroup()
  for (let i = 0; i < 12; i++) await Promise.resolve()
  assert.equal(f.context.duplicateDialogVisible.value, true)
  f.context.finishDuplicateReview(false)
  await pending
  assert.equal(f.context.duplicateConflicts.value.length, 1)
  assert.equal(f.calls.filter(c => c[0] === 'confirm').length, 0)
})

test('cancel after a clear check never creates tasks, double click does not overlap checks', async () => {
  const f = fixture()
  await Promise.all([f.context.createCodeGroup(), f.context.createCodeGroup()])
  assert.equal(f.calls.filter(c => c[0] === 'check').length, 1)
  assert.equal(f.calls.filter(c => c[0] === 'confirm').length, 1)
  assert.equal(f.context.working.value, false)
})

test('random-code groups do not run special-code duplicate scans', async () => {
  const f = fixture(); f.context.usesSpecialCode.value = false; f.context.checkRemoteDuplicates.value = true
  assert.equal(await f.context.checkCreationDuplicates(), true)
  assert.equal(f.calls.length, 0)
})

test('reviewing historical duplicates does not ask for a second creation confirmation', async () => {
  const f = fixture()
  const created = []
  Object.assign(f.context, {
    validityOffsets: { value: [0, 0] }, makeExportGroupKey: () => 'group',
    makeGroupCode: id => `group-${id}`, generatedGroupName: () => 'group', generatedGroupDescription: () => 'description',
    isPreviousDayDeposit: () => true, loadCodeGroups: async () => {},
    codeGroupDialogVisible: { value: true }, taskDuplicateReviews: new Map(), generateCodes: async () => true,
  })
  f.context.ElMessage.success = () => {}
  f.context.api.redemption.createGroup = async input => { created.push(input); return { batch: { id: input.remoteMarketId, taskId: 99, expectedCodeCount: 1 } } }

  f.context.api.redemption.checkDuplicates = async () => ({ remoteChecked: false, conflicts: [
    { marketId: 1, code: '1113rajfree', source: 'LOCAL', issueId: 10, reviewFingerprint: 'snapshot-v1' },
  ] })
  const pending = f.context.createCodeGroup()
  for (let i = 0; i < 8; i++) await Promise.resolve()
  f.context.finishDuplicateReview(true)
  assert.equal(f.context.duplicateDialogVisible.value, true, 'cannot continue until reviewed checkbox is ticked')
  f.context.duplicateReviewAcknowledged.value = true
  f.context.finishDuplicateReview(true)
  await pending
  assert.equal(f.calls.filter(c => c[0] === 'confirm').length, 0)
  assert.equal(created.length, 2)
  assert.equal(JSON.stringify(f.context.duplicateCreationReview.value), JSON.stringify({ confirmed: true, fingerprints: { '10': 'snapshot-v1' } }))
})

test('remote choice still runs even when local historical records exist', async () => {
  const f = fixture(); f.context.checkRemoteDuplicates.value = true
  f.context.api.redemption.checkDuplicates = async (markets, remote) => {
    f.calls.push(['check', remote])
    return { remoteChecked: remote, conflicts: remote ? [] : [{ marketId: 1, code: '1113rajfree', source: 'LOCAL', issueId: 10, reviewFingerprint: 'v1' }] }
  }
  const pending = f.context.checkCreationDuplicates()
  for (let i = 0; i < 12; i++) await Promise.resolve()
  f.context.duplicateReviewAcknowledged.value = true
  f.context.finishDuplicateReview(true)
  assert.equal(await pending, true)
  assert.equal(f.calls.filter(c => c[1] === true).length, 2)
})

test('initial task creation carries the reviewed list into each local group transaction', async () => {
  const f = fixture(), inputs = []
  Object.assign(f.context, {
    validityOffsets: { value: [0, 0] }, makeExportGroupKey: () => 'group',
    makeGroupCode: id => `group-${id}`, generatedGroupName: () => 'group', generatedGroupDescription: () => 'description',
    isPreviousDayDeposit: () => true, loadCodeGroups: async () => {},
    codeGroupDialogVisible: { value: true }, taskDuplicateReviews: new Map(), generateCodes: async () => true,
  })
  f.context.ElMessage.success = () => {}
  f.context.ElMessageBox.confirm = async () => {}
  f.context.api.redemption.checkDuplicates = async () => ({ conflicts: [
    { source: 'LOCAL', marketId: 1, issueId: 101, reviewFingerprint: 'review-a' },
    { source: 'LOCAL', marketId: 2, issueId: 102, reviewFingerprint: 'review-b' },
  ] })
  f.context.api.redemption.createGroup = async input => { inputs.push(input); return { batch: { id: input.remoteMarketId, taskId: 99, expectedCodeCount: 1 } } }
  const running = f.context.createCodeGroup()
  for (let i = 0; i < 15 && !f.context.duplicateDialogVisible.value; i++) await Promise.resolve()
  assert.equal(f.context.duplicateDialogVisible.value, true)
  f.context.duplicateReviewAcknowledged.value = true
  f.context.finishDuplicateReview(true)
  await running
  assert.equal(inputs.length, 2)
  assert.ok(inputs.every(input => input.duplicateReview.confirmed
    && input.duplicateReview.fingerprints['101'] === 'review-a' && input.duplicateReview.fingerprints['102'] === 'review-b'))
})
