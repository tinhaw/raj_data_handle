import test from 'node:test'
import assert from 'node:assert/strict'
import { publicationLabel, acquisitionLabel } from '../apps/erp-compat/web/src/modules/redemption/publicationStatus.ts'
const result = (state, configs = []) => ({ publicationState: state, configurations: configs })
test('local scheduled time cannot establish remote completion', () => {
  assert.equal(publicationLabel(), '发布待核验')
  assert.equal(publicationLabel(result('WAITING')), '等待远端执行')
  assert.equal(publicationLabel(result('RUNNING')), '远端执行中')
  assert.equal(publicationLabel(result('FAILED')), '远端发布异常')
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
    assert.equal(acquisitionLabel(false, true, result('COMPLETED', [{ state }])), '配置待核对')
  }
})
