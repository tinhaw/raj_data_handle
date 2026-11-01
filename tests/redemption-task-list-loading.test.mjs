import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
const start = source.indexOf('async function loadCodeGroups()')
const code = source.slice(start, source.indexOf('async function openCodeGroupDialog()', start))
const plain = value => JSON.parse(JSON.stringify(value))
function setup() {
  const ref = value => ({ value })
  const messages = []
  const c = vm.createContext({
    Error,
    loading: ref(false), codeGroupLoadError: ref(''), campaigns: ref([]), codeGroups: ref([]),
    api: { redemption: { list: async () => [{ id: 1 }], batchOverviews: async () => [
      { batch: { id: 2, campaignId: 1, createdAt: '2026-11-01' }, issues: [] },
    ] } },
    verifyPendingPublications: () => {}, ElMessage: { error: message => messages.push(message) },
  })
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, c)
  return { c, messages }
}

test('first-load timeout remains an explicit load failure instead of an empty task list', async () => {
  const { c, messages } = setup()
  c.api.redemption.batchOverviews = async () => { throw Error('timeout of 15000ms exceeded') }
  await c.loadCodeGroups()
  assert.match(c.codeGroupLoadError.value, /超时/)
  assert.match(messages[0], /超时/)
  assert.equal(c.loading.value, false)
  assert.match(source, /<el-empty v-else-if="!codeGroupLoadError"/)
  assert.match(source, /<el-alert v-if="codeGroupLoadError"/)
})

test('failed refresh preserves the last successful rows and reports the failure', async () => {
  const { c } = setup()
  await c.loadCodeGroups()
  const previous = plain(c.codeGroups.value)
  c.api.redemption.list = async () => { throw Error('Service unavailable') }
  await c.loadCodeGroups()
  assert.deepEqual(plain(c.codeGroups.value), previous)
  assert.match(c.codeGroupLoadError.value, /Service unavailable/)
})

test('successful retry clears the persistent error and loads campaigns with their batches', async () => {
  const { c } = setup()
  c.codeGroupLoadError.value = 'Previous failure'
  await c.loadCodeGroups()
  assert.equal(c.codeGroupLoadError.value, '')
  assert.equal(c.codeGroups.value.length, 1)
  assert.equal(c.codeGroups.value[0].campaign.id, 1)
  assert.equal(c.codeGroups.value[0].detail.batch.id, 2)
  assert.equal(c.loading.value, false)
})
