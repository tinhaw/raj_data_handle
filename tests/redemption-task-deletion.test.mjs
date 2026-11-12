import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionTaskDeletionDialog.vue', import.meta.url), 'utf8')
const script = source.split('<script setup lang="ts">')[1].split('</script>')[0].replace(/^import .*$/gm, '')
const job = (status, overrides = {}) => ({ id: 1, rowVersion: 1, taskId: 5, taskNumber: '202611120002', status, busy: false, items: [{ issueId: 10, configurationId: '3436', status: 'CHECKED', sharedTasks: ['202611120001', '202611120002'] }], ...overrides })
function fixture({ latest = null, next, props = {} } = {}) {
  const calls = []; let mounted, unmounted
  const context = vm.createContext({ Error, defineProps: () => ({taskId:5, taskNumber:'202611120002', ...props}), defineEmits: () => event => calls.push(event),
    ref: value => ({value}), computed: fn => ({get value(){ return fn() }}),
    onMounted: fn => {mounted=fn}, onUnmounted: fn => {unmounted=fn},
    api: {redemption: {
      latestTaskDeletion: async () => latest,
      previewTaskDeletion: async (...args) => {calls.push('preview');calls.push({previewArgs:args});return job('CHECKING')},
      nextTaskDeletion: async plan => {calls.push('next');return next ? next(plan) : job(plan.status === 'CHECKING' ? 'CHECKED' : 'FINISHED')},
      confirmTaskDeletion: async () => {calls.push('confirm');return job('RUNNING')},
      taskDeletion: async () => {calls.push('get');return latest},
      reconcileTaskDeletion: async () => {calls.push('read');return job('PAUSED')},
    }},
  })
  vm.runInContext(ts.transpileModule(script,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
  return {context,calls,mount:()=>mounted(),close:()=>unmounted(),value:expr=>vm.runInContext(expr,context)}
}
test('opening previews all configuration scopes without submitting deletion',async()=>{
  const f=fixture();await f.mount();assert.equal(f.value('plan.value.status'),'CHECKED')
  assert.ok(!f.calls.includes('confirm'));assert.equal(f.value('otherTasks.value.join(",")'),'202611120001')
  f.close();assert.ok(!f.calls.includes('confirm'))
})
test('task number and explicit acknowledgement are required before confirmation',async()=>{
  const f=fixture();await f.mount();await f.context.confirm();assert.ok(!f.calls.includes('confirm'))
  f.value("acknowledged.value=true;enteredTaskNumber.value='wrong'");await f.context.confirm();assert.ok(!f.calls.includes('confirm'))
  f.value("enteredTaskNumber.value='202611120002'");await f.context.confirm();assert.equal(f.calls.filter(x=>x==='confirm').length,1)
  assert.equal(f.value('plan.value.status'),'FINISHED')
})
test('opening an already confirmed job does not automatically continue destructive requests',async()=>{
  const f=fixture({latest:job('RUNNING')});await f.mount();assert.ok(!f.calls.includes('next'))
  await f.context.reconcile();assert.ok(f.calls.includes('read'));assert.ok(!f.calls.includes('confirm'));assert.ok(!f.calls.includes('next'))
})
test('closing during an in-flight item prevents any further item submissions',async()=>{
  let release
  const f=fixture({latest:job('RUNNING'),next:()=>new Promise(resolve=>{release=resolve})});await f.mount()
  const running=f.context.resume();await Promise.resolve();f.close();release(job('RUNNING'));await running
  assert.equal(f.calls.filter(x=>x==='next').length,1)
})
test('request loss stops execution and offers read-only reconciliation without reconfirming',async()=>{
  const f=fixture({latest:job('RUNNING'),next:async()=>{throw Error('synthetic timeout')}});await f.mount();await f.context.resume()
  assert.equal(f.calls.filter(x=>x==='next').length,1);assert.match(f.value('error.value'),/timeout/)
  await f.context.reconcile();assert.ok(!f.calls.includes('confirm'));assert.equal(f.calls.filter(x=>x==='next').length,1)
})

test('all blocked preflight reports zero deletion and cannot be confirmed',async()=>{
  const f=fixture({latest:job('CHECKED',{items:[{issueId:10,status:'BLOCKED',message:'本系统尚未开启“兑换码永久删除”能力',sharedTasks:[]}]})})
  await f.mount();assert.equal(f.value('stageTitle.value'),'预检未通过，尚未开始删除')
  assert.equal(f.value('deletedCount.value'),0);assert.equal(f.value('blockedCount.value'),1);assert.equal(f.value('unknownCount.value'),0)
  assert.equal(f.value('permissionBlocked.value'),true)
  f.value("acknowledged.value=true;enteredTaskNumber.value='202611120002'");await f.context.confirm()
  assert.equal(f.value('canConfirm.value'),false);assert.ok(!f.calls.includes('confirm'));assert.ok(!f.calls.includes('next'))
})
test('preflight progress counts blocked reads without claiming deletion progress',async()=>{
  const items=Array.from({length:30},(_,i)=>({issueId:i,status:i<14?'BLOCKED':'WAITING',sharedTasks:[]}))
  const f=fixture({latest:job('CHECKING',{busy:true,items})});await f.mount()
  assert.equal(f.value('stageTitle.value'),'删除前预检中（14/30），尚未开始删除')
  assert.equal(f.value('deletedCount.value'),0);assert.equal(f.value('executionStage.value'),false)
})
test('partial blocked preflight and unknown execution have separate counters',async()=>{
  const f=fixture({latest:job('PAUSED',{items:[
    {issueId:1,status:'BLOCKED',sharedTasks:[]},{issueId:2,status:'UNKNOWN',sharedTasks:[]},{issueId:3,status:'DELETED',sharedTasks:[]},{issueId:4,status:'CHECKED',sharedTasks:[]},
  ]})});await f.mount()
  assert.equal(f.value('stageTitle.value'),'删除已暂停，请先核对结果')
  assert.equal(f.value('blockedCount.value'),1);assert.equal(f.value('unknownCount.value'),1);assert.equal(f.value('deletedCount.value'),1)
  assert.equal(f.value('executionStage.value'),true);assert.ok(!f.calls.includes('next'))
})

test('recovery prepares a fresh remaining list without sending deletion and clears old consent',async()=>{
  const f=fixture({latest:job('PAUSED')});await f.mount()
  f.value("acknowledged.value=true;enteredTaskNumber.value='202611120002'")
  await f.context.prepareRemaining()
  assert.deepEqual(f.calls.filter(c=>['read','preview','next','confirm'].includes(c)),['read','preview','next'])
  assert.equal(f.value('plan.value.status'),'CHECKED')
  assert.equal(f.value('acknowledged.value'),false)
  assert.equal(f.value('enteredTaskNumber.value'),'')
  assert.equal(f.value('canConfirm.value'),false)
  await f.context.confirm();assert.ok(!f.calls.includes('confirm'))
})
test('unknown present and unsubmitted configurations use separate facts and truthful progress',async()=>{
  const f=fixture({latest:job('PAUSED',{items:[
    {issueId:1,status:'DELETED',sharedTasks:[]},
    {issueId:2,status:'UNKNOWN',sharedTasks:[],plan:{observation:{state:'PRESENT',checkedAt:'2026-11-13T00:00:00Z'}}},
    {issueId:3,status:'CHECKED',sharedTasks:[],plan:{observation:{state:'PRESENT',checkedAt:'2026-11-13T00:00:00Z'}}},
    {issueId:4,status:'BLOCKED',sharedTasks:[],plan:{observation:{state:'UNAVAILABLE',checkedAt:'2026-11-13T00:00:00Z'}}},
  ]})});await f.mount()
  assert.equal(f.value('progressPercent.value'),25)
  assert.equal(f.value('presentCount.value'),2)
  assert.equal(f.value('unexecutedCount.value'),2)
  assert.equal(f.value('excludedCount.value'),3)
  assert.equal(f.value('existenceLabel(plan.value.items[1])'),'仍存在（上次核对）')
  assert.equal(f.value('existenceLabel(plan.value.items[3])'),'本次无法确认')
  assert.equal(f.value('existenceLabel({status:"WAITING"})'),'尚未核对')
})
test('completed processing with exclusions is never presented as all deleted',async()=>{
  const f=fixture({latest:job('FINISHED',{items:[{issueId:1,status:'DELETED',sharedTasks:[]},{issueId:2,status:'KEPT',sharedTasks:[]}]})})
  await f.mount();assert.equal(f.value('stageTitle.value'),'本轮可执行项已处理，其他项未删除')
  assert.equal(f.value('progressPercent.value'),50)
})
test('closing during read-only recovery does not prepare or execute further requests',async()=>{
  const f=fixture({latest:job('PAUSED')});await f.mount()
  let release
  f.context.api.redemption.reconcileTaskDeletion=()=>new Promise(resolve=>{release=resolve})
  const recovery=f.context.prepareRemaining();await Promise.resolve();f.close();release(job('PAUSED'));await recovery
  assert.ok(!f.calls.includes('preview'));assert.ok(!f.calls.includes('next'));assert.ok(!f.calls.includes('confirm'))
})

test('selected preview freezes only the requested IDs and never confirms on opening', async () => {
  const f=fixture({props:{startNew:true,issueIds:[10,12],embedded:true,readOnlyOpen:true}})
  await f.mount()
  assert.deepEqual(f.calls.find(c=>c?.previewArgs).previewArgs,[5,[10,12]])
  assert.ok(!f.calls.includes('confirm'))
})
test('opening the progress page without a job does not create a deletion preview', async () => {
  const f=fixture({props:{readOnlyOpen:true,embedded:true}})
  await f.mount()
  assert.ok(!f.calls.includes('preview'));assert.ok(!f.calls.includes('next'))
  assert.equal(f.value('stageTitle.value'),'暂无删除进度')
})
test('remaining preview references the previous frozen job instead of expanding to the task', async () => {
  const f=fixture({latest:job('PAUSED',{selectedOnly:true}),props:{issueIds:[10]}})
  await f.mount();await f.context.prepareRemaining()
  assert.deepEqual(f.calls.find(c=>c?.previewArgs).previewArgs,[5,undefined,1])
  assert.ok(!f.calls.includes('confirm'))
})
