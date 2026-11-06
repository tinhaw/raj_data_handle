import test from 'node:test'
import assert from 'node:assert/strict'
import { publicationLabel, acquisitionLabel, configurationVerificationSummary } from '../apps/erp-compat/web/src/modules/redemption/publicationStatus.ts'
const result = (state, configs = []) => ({ publicationState: state, configurations: configs })
test('local scheduled time cannot establish remote completion', () => {
  assert.equal(publicationLabel(), '发布待核验')
  assert.equal(publicationLabel(result('WAITING')), '等待远端发布')
  assert.equal(publicationLabel(result('RUNNING')), '远端发布中')
  assert.equal(publicationLabel(result('FAILED')), '远端发布异常')
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
