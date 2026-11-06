import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(new URL('../apps/web/package.json', import.meta.url))
const ts = require('typescript')
const { createRouter, createMemoryHistory } = require('vue-router')
const source = readFileSync(new URL('../apps/web/src/router/index.ts', import.meta.url), 'utf8')
const ast = ts.createSourceFile('router.ts', source, ts.ScriptTarget.Latest, true)
let routeDefinitions
function visit(node) {
  if (ts.isPropertyAssignment(node) && node.name.getText(ast) === 'routes') routeDefinitions = node.initializer.getText(ast)
  ts.forEachChild(node, visit)
}
visit(ast)
const routes = vm.runInNewContext(`(${routeDefinitions})`)
const router = createRouter({ history: createMemoryHistory(), routes })

function handler(file, name, bindings) {
  const text = readFileSync(new URL(file, import.meta.url), 'utf8')
  const script = text.slice(text.indexOf('<script setup lang="ts">') + 24, text.indexOf('</script>'))
  const ast = ts.createSourceFile('page.ts', script, ts.ScriptTarget.Latest, true)
  const declaration = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === name)
  assert.ok(declaration, `${name} handler exists`)
  const js = ts.transpile(declaration.getText(ast), { target: ts.ScriptTarget.ESNext })
  return vm.runInNewContext(`${js}; ${name}`, bindings)
}

test('merged task-list entry and return use real registered routes and preserve list position', () => {
  let target
  const navigation = { push(to) { target = router.resolve(to) } }
  handler('../apps/erp-compat/web/src/modules/redemption/RedemptionCampaignPage.vue', 'openClaimStatistics', {
    router: navigation,
    codeGroupTaskCurrentPage: { value: 3 }, codeGroupTaskPageSize: { value: 50 }, taskTableScroll: { value: 282 },
  })({ taskId: 47 })
  assert.equal(target.path, '/erp/redemption/47/claim-statistics')
  assert.equal(target.meta.erpPermission, 'ERP_REDEMPTION_VIEW')
  assert.ok(target.meta.erpCompatComponent.endsWith('/RedemptionClaimStatisticsPage.vue'))
  const statisticsRoute = target
  handler('../apps/erp-compat/web/src/modules/redemption/RedemptionClaimStatisticsPage.vue', 'back', {
    router: navigation, route: statisticsRoute,
  })()
  assert.equal(target.path, '/erp/redemption')
  assert.equal(target.query.page, '3')
  assert.equal(target.query.pageSize, '50')
  assert.equal(target.query.tableScroll, '282')
})
