import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const page = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
const registration = page.slice(page.indexOf('let resumeAfterRegistration:'), page.indexOf('function publishTime('))
const workflow = ts.transpile(registration + page.slice(page.indexOf('function chooseDownload('), page.indexOf('async function exportMultiMarketGroup(')), { target: ts.ScriptTarget.ES2022 })

for (const choice of ['publish', 'manual', 'direct', 'cancel']) {
  test('unpublished Excel download follows only the selected action: ' + choice, async () => {
    const calls = []
    const detail = { batch: { id: 1, status: 'READY_TO_PUBLISH', remoteConnectionId: 2, rowVersion: 0 }, issues: [{ id: 3, workflowStatus: 'CREATED' }] }
    const context = vm.createContext({
      canGenerate: { value: true }, downloadingTask: {}, downloadDecision: {}, verificationDialogVisible: {},
      resolveDownloadChoice: undefined,
      api: { redemption: {
        batch: async () => detail,
        publishRemoteBatch: async () => { calls.push('publish'); return detail },
        adoptExternalPublication: async (id, version, newId) => { assert.deepEqual([id, version, newId], [1, 0, '123']); calls.push('manual'); return detail },
        downloadRemoteCode: async (_, direct) => { assert.equal(direct, true); calls.push('direct'); return { ...detail, batch: { ...detail.batch, status: 'COMPLETED' } } },
      } },
      hasPendingPublishReservation: () => false, creationRewardIssues: () => [], deletionHeld: () => false,
      externalDialog: {}, externalChoices: {}, externalTarget: {}, externalTaskId: {}, externalError: {},
      linkingExternal: {}, publishDialogVisible: {}, watch() {}, publishRows: row => [row],
      canLinkExternal: () => true, remoteMarketLabel: () => 'RajSpin',
      isSuccess: row => row.detail.batch.status === 'COMPLETED', replaceCodeGroup() {}, markProcessing() {},
      verifyRemotePublication: async () => ({ publicationState: 'COMPLETED' }),
      downloadPublishedCodes: async () => { calls.push('verified download'); return true },
      exportGroup: async () => { calls.push('Excel') },
      ElMessage: { success() {}, error: assert.fail },
    })
    vm.runInContext(workflow, context)
    const run = context.requestDownload({ campaign: {}, detail }, true)
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(context.downloadDecision.value.market, 'RajSpin')
    assert.deepEqual(calls, [])
    context.chooseDownload(choice === 'cancel' ? undefined : choice)
    if (choice === 'manual') {
      await new Promise(resolve => setImmediate(resolve))
      assert.equal(context.externalDialog.value, true)
      context.externalTaskId.value = '123'
      await context.linkExternalPublication()
    }
    await run
    assert.deepEqual(calls, choice === 'cancel' ? [] : choice === 'direct' ? ['direct', 'Excel'] : [choice, 'verified download', 'Excel'])
  })
}

test('detail and download share the registration dialog for stock already imported', async () => {
  for (const fromDownload of [true, false]) {
    const detail = { batch: { id: 9, status: 'COMPLETED', rowVersion: 4, remoteConnectionId: 1 }, allImportedDirectly: true, issues: [{ workflowStatus: 'CODE_IMPORTED' }] }
    const row = { detail }
    const linked = { ...detail, batch: { ...detail.batch, remotePublishTaskId: '789' } }
    const calls = []
    const context = vm.createContext({
      resolveDownloadChoice: undefined, canGenerate: { value: true }, downloadingTask: {}, downloadDecision: {},
      verificationDialogVisible: {}, publishDialogVisible: {}, externalDialog: {}, externalChoices: {},
      externalTarget: {}, externalTaskId: {}, externalError: {}, linkingExternal: {}, watch() {},
      publishRows: target => [target], canLinkExternal: () => true, hasPendingPublishReservation: () => false,
      remoteMarketLabel: () => 'RajSpin', deletionHeld: () => false, isSuccess: () => true,
      replaceCodeGroup() {}, inspectPublication: () => calls.push('inspect'),
      api: { redemption: {
        batch: async () => detail,
        adoptExternalPublication: async (...args) => { assert.deepEqual(args, [9, 4, '789']); calls.push('register'); return linked },
      } },
      exportGroup: () => calls.push('Excel'), ElMessage: { success() {}, error: assert.fail },
    })
    vm.runInContext(workflow, context)
    let run
    if (fromDownload) {
      run = context.requestDownload(row, true)
      await new Promise(resolve => setImmediate(resolve))
      context.chooseDownload('manual')
      await new Promise(resolve => setImmediate(resolve))
    } else context.openExternalPublication(row)
    assert.equal(context.externalDialog.value, true)
    context.externalTaskId.value = '789'
    await context.linkExternalPublication()
    await run
    assert.deepEqual(calls, ['register', fromDownload ? 'Excel' : 'inspect'])
  }
})
