import test from 'node:test'
import assert from 'node:assert/strict'
import { publicationLabel, acquisitionLabel, acceptsManualPublication, configurationVerificationSummary } from '../apps/erp-compat/web/src/modules/redemption/publicationStatus.ts'
const result = (state, configs = []) => ({ publicationState: state, configurations: configs })
test('only a confirmed failure or cancellation of the same system publication permits rebinding', () => {
  const batch = { status: 'PUBLISHED', remotePublishMode: 'SCHEDULED', remotePublishTaskId: '123' }
  for (const state of ['FAILED', 'CANCELLED', 'UNKNOWN', 'RUNNING', 'WAITING', 'COMPLETED']) {
    assert.equal(acceptsManualPublication(batch, { ...result(state), remotePublishTaskId: '123' }), ['FAILED', 'CANCELLED'].includes(state))
  }
  assert.equal(acceptsManualPublication(batch, { ...result('FAILED'), remotePublishTaskId: '456' }), false)
  assert.equal(acceptsManualPublication({ ...batch, remotePublishMode: 'EXTERNAL' }, { ...result('FAILED'), remotePublishTaskId: '123' }), false)
})
test('manual publication accepts only ready markets without a real receipt', () => {
  for (const remotePublishTaskId of [undefined, 'PENDING:own-reservation']) {
    assert.equal(acceptsManualPublication({status: 'READY_TO_PUBLISH', remotePublishTaskId}), true)
  }
  for (const status of ['CREATING', 'PUBLISHED', 'COMPLETED']) {
    assert.equal(acceptsManualPublication({status}), false)
  }
  assert.equal(acceptsManualPublication({status: 'READY_TO_PUBLISH', remotePublishTaskId: '123'}), false)
})
test('local scheduled time cannot establish remote completion', () => {
  assert.equal(publicationLabel(), '发布待核验')
  assert.equal(publicationLabel(result('WAITING')), '等待远端发布')
  assert.equal(publicationLabel(result('RUNNING')), '远端发布中')
  assert.equal(publicationLabel(result('FAILED')), '发布不成功')
  assert.equal(publicationLabel(result('CANCELLED')), '发布不成功')
  assert.match(configurationVerificationSummary(result('FAILED')), /原因：远端执行失败/)
  assert.equal(acquisitionLabel(false, false, result('WAITING')), '发布完成后核验兑换码')
})
test('remote completion and code download failure are independent', () => {
  const complete = result('COMPLETED', [{ state: 'MATCHED' }])
  assert.equal(publicationLabel(complete), '发布完成')
  assert.equal(acquisitionLabel(false, true, complete), '下载异常')
  assert.equal(acquisitionLabel(false, false, complete), '待下载兑换码')
  assert.equal(acquisitionLabel(true, false, complete), '兑换码已入库')
})
test('missing and mismatched configurations do not become generation success', () => {
  for (const state of ['MISSING', 'MISMATCH', 'UNKNOWN']) {
    assert.equal(acquisitionLabel(false, true, result('COMPLETED', [{ state }])), state === 'MISSING' ? '远端未找到配置' : '配置待核对')
  }
})

test('blocked download explains missing configuration IDs and does not suggest re-publishing', () => {
  const message = configurationVerificationSummary(result('COMPLETED', [
    { configurationId: '207', state: 'MISSING' },
    { configurationId: '208', state: 'MISSING' },
    { configurationId: '209', state: 'MISSING' },
  ]))
  assert.match(message, /3 个配置/)
  for (const id of ['207', '208', '209']) assert.match(message, new RegExp(`原 ID：${id}`))
  assert.match(message, /暂不能下载/)
  assert.match(message, /不会恢复配置或重新发布/)
  assert.doesNotMatch(message, /可以下载兑换码/)
})
test('failed refresh is shown instead of a cached successful check', () => {
  const message = configurationVerificationSummary(result('COMPLETED'), '连接超时')
  assert.match(message, /本次查询失败：连接超时/)
  assert.doesNotMatch(message, /可以下载兑换码/)
})
test('cancelled publication directs operators to rebind a verified new ID', () => {
  const message = configurationVerificationSummary(result('CANCELLED'))
  assert.match(message, /已撤销/)
  assert.match(message, /换绑新 ID/)
})
