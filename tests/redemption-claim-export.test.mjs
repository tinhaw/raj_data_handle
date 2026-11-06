import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import test from 'node:test'

const require = createRequire(new URL('../apps/erp-compat/web/package.json', import.meta.url))
const ts = require('typescript')
const source = readFileSync(new URL('../apps/erp-compat/web/src/modules/redemption/RedemptionClaimStatisticsPage.vue', import.meta.url), 'utf8')
const script = source.slice(source.indexOf('<script setup lang="ts">') + 24, source.indexOf('</script>'))
const ast = ts.createSourceFile('page.ts', script, ts.ScriptTarget.Latest, true)
const declaration = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'exportData')

test('export uses displayed query snapshot, not unsent filter edits, and triggers local download', async () => {
  const calls = [], downloads = []
  const bindings = {
    data: { value: { dateFrom: '2026-11-01', dateTo: '2026-11-06', queryVersion: 'visible-version' } },
    dates: { value: ['2026-10-01', '2026-10-31'] }, sourceId: { value: 'rajluck' },
    displayedSourceId: { value: 'rajwin' }, taskId: { value: '63' },
    loading: { value: false }, exporting: { value: false },
    claimStatisticsApi: { async export(id, params) { calls.push({ id, params }); return 'xlsx-blob' } },
    saveDownloadedFile(file) { downloads.push(file) }, ElMessage: { error() { assert.fail('unexpected error') } },
  }
  const handler = vm.runInNewContext(ts.transpile(declaration.getText(ast), { target: ts.ScriptTarget.ESNext }) + '; exportData', bindings)
  await handler()
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ id: '63', params: {
    dateFrom: '2026-11-01', dateTo: '2026-11-06', sourceId: 'rajwin', queryVersion: 'visible-version', layout: 'template',
  } }])
  assert.deepEqual(downloads, ['xlsx-blob'])
  assert.equal(bindings.exporting.value, false)
  bindings.loading.value = true
  await handler()
  assert.equal(calls.length, 1)
  bindings.loading.value = false
  bindings.exporting.value = true
  await handler()
  assert.equal(calls.length, 1)
})
