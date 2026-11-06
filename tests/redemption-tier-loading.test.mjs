import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))) }
function setup() {
  const ref = (value) => ({ value })
  const context = vm.createContext({
    selectedRemoteConnection: ref({ id: 1 }), form: ref({ tiers: [], redemptionType: 'AGENT' }),
    remoteTags: ref([]), remoteTagsLoaded: ref(false), rewardTierPreset: ref(undefined),
    remoteTagsLoading: ref(false), rewardTierPresetLoading: ref(false), marketConfigurationError: ref(''),
    api: { redemptionRemoteConnections: {
      tags: async () => [{ id: 901027 }], rewardTierPreset: async () => ({ exists: false }),
    } },
    isPreviousDayDeposit: () => false, saveActiveMarketDraft: () => {},
    activeMarketTab: ref(''), marketKey: String, restoreMarketDraft: () => true,
    applyMarketTierDefaults: () => { context.form.value.tiers = [{ userType: 'ALL_USERS' }] },
  })
  const code = 'let marketConfigurationRequest = 0;\n'
    + section('async function loadMarketTierConfiguration()', 'async function loadCodeGroups()')
    + section('function addTier()', 'function isLabelUsedByOtherTier(')
    + section('async function activateMarket(', 'async function ensureSelectedMarketDrafts(')
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return context
}

test('empty catalog still allows a blank label tier; late load preserves entered amounts', async () => {
  const c = setup()
  c.addTier()
  assert.equal(c.form.value.tiers.length, 1)
  assert.equal(c.form.value.tiers[0].labelIds.length, 0)
  c.form.value.tiers[0].bonusAmount = 15
  await c.loadMarketTierConfiguration()
  assert.equal(c.form.value.tiers[0].bonusAmount, 15)
  assert.equal(c.form.value.tiers[0].labelIds.length, 0)
})

test('preset failure does not discard successful tags; retry clears error', async () => {
  const c = setup()
  c.api.redemptionRemoteConnections.rewardTierPreset = async () => { throw Error('offline') }
  await c.loadMarketTierConfiguration()
  assert.equal(c.remoteTagsLoaded.value, true)
  assert.equal(c.remoteTags.value[0].id, 901027)
  assert.equal(c.marketConfigurationError.value, '组合预设读取失败')
  c.api.redemptionRemoteConnections.rewardTierPreset = async () => ({ exists: false })
  await c.loadMarketTierConfiguration()
  assert.equal(c.marketConfigurationError.value, '')
})

test('tag failure preserves preset and entered tiers', async () => {
  const c = setup()
  c.addTier()
  c.api.redemptionRemoteConnections.tags = async () => { throw Error('offline') }
  await c.loadMarketTierConfiguration()
  assert.equal(c.remoteTagsLoaded.value, false)
  assert.equal(c.rewardTierPreset.value.exists, false)
  assert.equal(c.form.value.tiers.length, 1)
  assert.equal(c.marketConfigurationError.value, '标签读取失败')
})

test('superseded response cannot overwrite current market', async () => {
  const c = setup()
  let resolveOld
  c.api.redemptionRemoteConnections.tags = () => new Promise((resolve) => { resolveOld = resolve })
  const old = c.loadMarketTierConfiguration()
  c.api.redemptionRemoteConnections.tags = async () => [{ id: 901990 }]
  await c.loadMarketTierConfiguration()
  resolveOld([{ id: 123 }])
  await old
  assert.equal(c.remoteTags.value[0].id, 901990)
  assert.equal(c.remoteTagsLoading.value, false)
})

test('returning to an incomplete cached draft reloads and retains user input', async () => {
  const c = setup()
  c.form.value.remoteMarketId = 1
  c.addTier()
  c.form.value.tiers[0].bonusAmount = 30
  await c.activateMarket(2)
  assert.equal(c.remoteTagsLoaded.value, true)
  assert.equal(c.form.value.tiers[0].bonusAmount, 30)
  assert.equal(c.activeMarketTab.value, '2')
})
