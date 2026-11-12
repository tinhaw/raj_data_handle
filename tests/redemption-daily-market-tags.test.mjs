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
const plain = value => JSON.parse(JSON.stringify(value))
const catalog = (base = 700, middle = base + 4) => [
  { id: base + 1, name: '日充值100-199' },
  { id: base + 2, name: '日充值200-999' },
  { id: base + 3, name: '日充值1000-2999' },
  { id: middle, name: `(${middle})日充值3,000–9,999` },
  { id: base + 5, name: '日充值recharge today-10000+' },
]
function setup(markets = ['RAJRACE']) {
  const ref = value => ({ value })
  const messages = []
  const c = vm.createContext({
    computed: fn => ({ get value() { return fn() } }),
    form: ref({ remoteMarketId: 1, remoteMarketIds: markets.map((_, i) => i + 1), tiers: [],
      redemptionType: 'PREVIOUS_DAY_DEPOSIT', dateRange: ['2026-10-03', '2026-10-03'], remoteOptions: { keyNumber: 1 } }),
    validityOffsets: ref([0, 0]), marketTierDrafts: ref({}),
    remoteConnections: ref(markets.map((name, i) => ({ id: i + 1, marketId: i + 1, marketCode: name, marketName: name }))),
    remoteTags: ref(catalog()), remoteTagsLoaded: ref(true),
    rewardTierPreset: ref({ exists: false, tiers: [], tagSnapshot: [] }),
    remoteTagsLoading: ref(false), rewardTierPresetLoading: ref(false), marketConfigurationError: ref(''),
    activeMarketTab: ref('1'), fallbackTags: [],
    ElMessage: { warning: message => messages.push(message) },
    api: { redemptionRemoteConnections: {
      tags: async id => catalog(id * 1000), rewardTierPreset: async () => ({ exists: false, tiers: [], tagSnapshot: [] }),
    } },
  })
  const code = 'let marketConfigurationRequest = 0;\n'
    + section('const previousDayTierProfiles:', 'const form =')
    + section('const tagOptions =', 'function hasPermission(')
    + section('function previousDayTiers(', 'function isAllUsersTier(')
    + section('function cloneTiers(', 'function generatedGroupName(')
    + section('async function loadMarketTierConfiguration()', 'async function loadCodeGroups()')
    + section('function resetPreviousDayTiers()', 'function sevenDayTierProfileForTag(')
    + section('function tiersFromRewardPreset(', 'function standardSevenDayTiers(')
    + section('function defaultAgentTiers()', 'function applyFutureRange(')
    + section('function minimumDepositFromTag(', 'function addTier(')
    + section('function validateForm()', 'async function createCodeGroup()')
    + '\nglobalThis.dailyOptions = previousDayTagOptions;'
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, c)
  return { c, messages }
}

test('RajRace and arbitrary new markets create daily groups using their own tag IDs', () => {
  for (const name of ['RAJRACE', 'RajWin', 'RajLuck', 'RajSpin', 'NEW_MARKET', '新盘口']) {
    const { c } = setup([name])
    c.applyMarketTierDefaults()
    c.saveActiveMarketDraft()
    assert.equal(c.validateForm(), '')
    assert.deepEqual(plain(c.form.value.tiers.map(t => t.labelIds)), [[], [701], [702], [703], [704], [705]])
    assert.deepEqual(plain(c.form.value.tiers.map(t => [t.bonusAmount, t.bonusMaxAmount])), [[1, 3], [3, 5], [7, 9], [13, 17], [27, 37], [57, 77]])
    assert.equal(c.form.value.tiers[0].userType, 'ALL_USERS')
  }
})

test('existing 3000-tier IDs come from each catalog, independent of the market name', () => {
  for (const id of [901996, 901994, 12345]) {
    const { c } = setup(['Renamed market'])
    c.remoteTags.value = catalog(800, id)
    c.resetPreviousDayTiers()
    assert.deepEqual(plain(c.form.value.tiers[4].labelIds), [id])
  }
})

test('saved custom daily tiers and amounts take priority over defaults', () => {
  const { c } = setup()
  c.rewardTierPreset.value = { exists: true, stale: false, tagSnapshot: catalog(), tiers: [
    { userType: 'ALL_USERS', labelIds: [], displayName: '全部用户', minDepositAmount: '0', bonusAmount: '2', bonusMaxAmount: '4' },
    { userType: 'LABEL_USERS', labelIds: [702], displayName: '自定义', minDepositAmount: '200', bonusAmount: '11', bonusMaxAmount: '22' },
  ] }
  c.applyMarketTierDefaults()
  c.saveActiveMarketDraft()
  assert.equal(c.validateForm(), '')
  assert.equal(c.form.value.tiers.length, 2)
  assert.equal(c.form.value.tiers[1].bonusAmount, 11)
  assert.equal(c.form.value.tiers[1].bonusMaxAmount, 22)
})

test('missing, ambiguous or seven-day-only tags leave explicit empty tiers instead of guessed IDs', () => {
  for (const tags of [[], [{ id: 123, name: '近7天充值100-199' }], [
    { id: 123, name: '日充值100-199' }, { id: 124, name: '日充值100-199' },
  ]]) {
    const { c, messages } = setup()
    c.remoteTags.value = tags
    c.resetPreviousDayTiers()
    c.saveActiveMarketDraft()
    assert.equal(c.form.value.tiers.length, 6)
    assert.deepEqual(plain(c.form.value.tiers[1].labelIds), [])
    assert.match(c.validateForm(), /必须选择至少一个标签 ID/)
    assert.equal(messages.length, 1)
  }
})

test('manual nonstandard daily labels are accepted without requiring a default profile', () => {
  const { c } = setup()
  c.remoteTags.value = [{ id: 9000, name: 'VIP 自定义活动人群' }]
  c.form.value.tiers = [{ userType: 'LABEL_USERS', labelIds: [9000], minDepositAmount: 500, bonusAmount: 10, bonusMaxAmount: 15 }]
  c.saveActiveMarketDraft()
  assert.equal(c.validateForm(), '')
})

test('stale or foreign preset labels are replaced with defaults from the current catalog', () => {
  for (const stale of [true, false]) {
    const { c } = setup()
    c.rewardTierPreset.value = { exists: true, stale, tagSnapshot: catalog(1000), tiers: [
      { userType: 'LABEL_USERS', labelIds: [1001], minDepositAmount: '100', bonusAmount: '10', bonusMaxAmount: '20' },
    ] }
    c.applyMarketTierDefaults()
    c.saveActiveMarketDraft()
    assert.equal(c.form.value.tiers.length, 6)
    assert.deepEqual(plain(c.form.value.tiers[1].labelIds), [701])
    assert.equal(c.validateForm(), '')
  }
})

test('daily tag options never inject fixed IDs or retain deleted snapshot tags', () => {
  const { c } = setup()
  c.remoteTagsLoaded.value = false
  assert.deepEqual(plain(c.dailyOptions.value), [])
  c.rewardTierPreset.value = { tagSnapshot: [{ id: 123, name: '日充值100-199' }] }
  assert.deepEqual(plain(c.dailyOptions.value.map(t => t.id)), [123])
  c.remoteTagsLoaded.value = true
  c.remoteTags.value = []
  assert.deepEqual(plain(c.dailyOptions.value), [])
})

test('loaded tags, ownership, account, nonempty tiers and amount bounds remain required', () => {
  const { c } = setup()
  c.resetPreviousDayTiers()
  c.saveActiveMarketDraft()
  const draft = c.marketTierDrafts.value['1']
  draft.remoteTagsLoaded = false
  assert.match(c.validateForm(), /标签尚未加载成功/)
  draft.remoteTagsLoaded = true
  draft.tiers[1].labelIds = [999]
  assert.match(c.validateForm(), /当前盘口不存在的标签 ID/)
  draft.tiers[1].labelIds = ['701']
  assert.equal(c.validateForm(), '')
  draft.tiers[1].bonusMaxAmount = 0
  assert.match(c.validateForm(), /兑换金额上下限不正确/)
  draft.tiers = []
  assert.match(c.validateForm(), /至少一个充值档位/)
  c.remoteConnections.value = []
  assert.match(c.validateForm(), /暂无可用远端账号/)
})

test('all-users-only daily groups need no tag directory', () => {
  const { c } = setup()
  c.form.value.tiers = c.defaultAgentTiers()
  c.remoteTagsLoaded.value = false
  c.remoteTags.value = []
  c.saveActiveMarketDraft()
  assert.equal(c.validateForm(), '')
})

test('multi-market switching preserves edits and validates each separate tag catalog', async () => {
  const { c } = setup(['RAJRACE', 'NEW_MARKET'])
  c.resetPreviousDayTiers()
  c.form.value.tiers[2].bonusAmount = 8
  await c.ensureSelectedMarketDrafts()
  assert.equal(c.form.value.remoteMarketId, 1)
  assert.equal(c.form.value.tiers[2].bonusAmount, 8)
  assert.deepEqual(plain(c.marketTierDrafts.value['2'].tiers[2].labelIds), [2002])
  assert.equal(c.validateForm(), '')
  c.marketTierDrafts.value['2'].tiers[2].labelIds = [702]
  assert.match(c.validateForm(), /NEW_MARKET.*当前盘口不存在的标签 ID/)
})
