import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'
const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', import.meta.url), 'utf8')
function fixture({cancel = false, unknown = false} = {}) {
  const calls = [], messages = []
  const context = vm.createContext({String, Boolean, Error, ref: value => ({value}),
    detailMode: {value: false}, canGenerate: {value: true}, refreshRecoveryGroups: async () => calls.push('refresh'),
    ElMessageBox: {confirm: async text => {calls.push(['confirm', text]);if(cancel) throw Error('cancel')}},
    ElMessage: Object.fromEntries(['info','warning','success'].map(type => [type, message => messages.push([type,message])])),
    api: {redemption: {
      previewDeletion: async () => {calls.push('preview');return {id:1, rowVersion:2, status:'CHECKED', configurationId:'3590', remote:{giftCode:'fixture'}, parameters:{marketName:'Fixture', sharedBatches:[{id:10},{id:20}]}}},
      confirmDeletion: async () => {calls.push('execute');if(unknown) throw Error('删除结果待核对');return {status:'DELETED', message:'已删除'}},
      reconcileDeletion: async () => {calls.push('read');return {status:'UNKNOWN', message:'仍待核对'}},
    }},
  })
  const code=source.slice(source.indexOf('function deletionHeld('),source.indexOf('function groupStatus('))
    + source.slice(source.indexOf('const deletingIssueId = ref<'),source.indexOf('const checkingRecovery = ref(false)'))
  vm.runInContext(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
  return {context,calls,messages}
}
test('deletion preview names exact ID and shared scope before one confirmed execution', async () => {
  const f=fixture();await f.context.deleteRemoteConfiguration({id:1,remoteConfigurationId:'3590'})
  assert.equal(f.calls[0],'preview');assert.equal(f.calls[1][0],'confirm');assert.match(f.calls[1][1],/3590.*共享批次：#10、#20.*不可恢复/)
  assert.equal(f.calls.filter(x=>x==='execute').length,1);assert.equal(f.calls.at(-1),'refresh')
})
test('cancel does not submit deletion and still refreshes current state',async()=>{
  const f=fixture({cancel:true});await f.context.deleteRemoteConfiguration({id:1,remoteConfigurationId:'3590'})
  assert.ok(!f.calls.includes('execute'));assert.ok(!f.messages.some(([type])=>type==='success'))
})
test('unknown deletion retries perform reads only',async()=>{
  const f=fixture({unknown:true});await f.context.deleteRemoteConfiguration({id:1,remoteConfigurationId:'3590'})
  await f.context.deleteRemoteConfiguration({id:1,remoteConfigurationId:'3590',workflowStatus:'REMOTE_DELETE_PENDING'})
  assert.equal(f.calls.filter(x=>x==='execute').length,1);assert.equal(f.calls.filter(x=>x==='read').length,1)
  assert.ok(!f.messages.some(([type])=>type==='success'))
})
test('deleted configurations have a distinct label and cannot reenter deletion submission',async()=>{
  const f=fixture();const issue={id:1,remoteConfigurationId:'3590',workflowStatus:'REMOTE_DELETED'}
  assert.equal(f.context.deletionLabel([issue]),'远端配置已删除');await f.context.deleteRemoteConfiguration(issue)
  assert.deepEqual(f.calls,['read','refresh'])
})
