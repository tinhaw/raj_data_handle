import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function fixture() {
  const calls = [], watchers = []
  const ref = value => ({ value })
  const context = vm.createContext({
    String, Boolean, Map, Set, Error,
    computed: fn => ({ get value() { return fn() } }), watch: (refs, fn) => watchers.push(fn),
    route: { params: { taskId: '88' }, query: { batch: '102', returnPage: 3, returnPageSize: 20, returnTableScroll: 180 } },
    router: { push: value => calls.push(value) },
    codeGroupTaskCurrentPage: ref(3), codeGroupTaskPageSize: ref(20), taskTableScroll: ref(180),
    detailSearch: ref(''), detailDate: ref(''), detailStatus: ref(''), detailPane: ref('configurations'),
    selectedDeletionIds: ref([]), selectedTaskId: ref(88), selectedTaskDisplayId: ref('202611130002'),
    taskDeletionTarget: ref(), deletionPanelKey: ref(0), canGenerate: ref(true),
    loading: ref(false), codeGroupLoadError: ref(''), campaigns: ref([]), codeGroups: ref([]),
    selectedTaskMembers: ref([]), selectedGroup: ref(), activeTaskBatchId: ref('101'),
    updateSelectedFailedIssues: () => {}, clearFailedIssueSelection: () => { context.selectedDeletionIds.value = [] },
    issueRemark: issue => issue.error || '', issueStatus: issue => ({ text: issue.status }),
    deletionHeld: issue => issue.held, isFailedRemoteCreation: issue => issue.status === '失败',
    api: { redemption: { taskDetail: async id => {
      calls.push(['read-task', id]);return { campaigns: [{ id: 1 }], batches: [101, 102].map(id => ({ batch: { id, campaignId: 1 }, issues: [] })) }
    } } },
  })
  const code = source.slice(source.indexOf('function navigateTaskDetail('), source.indexOf('async function openTaskDetail('))
  vm.runInContext(ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText, context)
  return { context, calls, watchers, value: code => vm.runInContext(code, context) }
}
test('direct task URL loads only that task and restores its market', async () => {
  const f = fixture(); await f.context.loadTaskDetail()
  assert.deepEqual(f.calls, [['read-task', '88']])
  assert.equal(f.context.selectedGroup.value.detail.batch.id, 102)
  assert.equal(f.context.loading.value, false)
})
test('task navigation preserves list page, page size and table position', () => {
  const f = fixture(); f.context.navigateTaskDetail(88, 102); f.context.returnToTaskList()
  assert.deepEqual(JSON.parse(JSON.stringify(f.calls)), [
    { name: 'redemption-task-detail', params: { taskId: 88 }, query: { batch: 102, returnPage: 3, returnPageSize: 20, returnTableScroll: 180 } },
    { name: 'redemption', query: { page: 3, pageSize: 20, tableScroll: 180 } },
  ])
})
test('filters combine code, date and status; changing a filter clears hidden selections', () => {
  const f = fixture()
  f.context.selectedGroup.value = { detail: { issues: [
    { id: 1, redemptionCode: '1113raj10K', claimDate: '2026-11-13', status: '已下载' },
    { id: 2, redemptionCode: '1114raj10K', claimDate: '2026-11-14', status: '失败' },
    { id: 3, redemptionCode: '1114raj200', claimDate: '2026-11-14', status: '失败' },
  ] } }
  f.context.detailSearch.value = '10k'; f.context.detailDate.value = '2026-11-14'; f.context.detailStatus.value = '失败'
  assert.equal(f.value('filteredDetailIssues.value.map(i=>i.id).join(",")'), '2')
  f.context.selectedDeletionIds.value = [1]; f.watchers[0]()
  assert.equal(f.context.selectedDeletionIds.value.length, 0)
})
test('selected deletion excludes missing and held identities and snapshots the selected IDs', () => {
  const f = fixture()
  f.context.updateDetailSelection([{ id: 1, remoteConfigurationId: '4000' }, { id: 2 }, { id: 3, remoteConfigurationId: '4001', held: true }])
  assert.equal(f.context.selectedDeletionIds.value.join(','), '1')
  f.context.showTaskDeletion(f.context.selectedDeletionIds.value)
  f.context.selectedDeletionIds.value.push(4)
  assert.equal(f.context.taskDeletionTarget.value.issueIds.join(','), '1')
  assert.equal(f.context.detailPane.value, 'deletion')
  f.context.closeTaskDeletion();assert.equal(f.context.taskDeletionTarget.value, undefined)
})
