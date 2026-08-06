# Batch result page design QA

## Evidence

- Source visual truth: `/Users/dinghao/.codex/generated_images/019fa554-ce10-72f0-9049-21eba50522af/call_4rYlnnhRw8lgr1c6iRBBMqWn.png`
- Rendered implementation: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-implementation-final.png`
- Full-view comparison: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-comparison-final.png`
- Focused table comparison: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-focus-table-final.png`
- Chart-tab evidence: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-charts-fixed.png`
- Responsive evidence: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-responsive-1100-fixed.png`

## Normalization

- Source pixels: `1487 × 1058`
- Implementation pixels: `1487 × 1058`
- CSS viewport: `1487 × 1058`
- Device pixel ratio: `1`
- Density normalization: none required; source and implementation were compared at equal pixel dimensions.
- State: completed, final RajWin pay-in batch; 1,000 uploaded orders, 996 matched orders, 4 confirmed missing orders, and 996 remote rows.

## Findings

No actionable P0, P1, or P2 differences remain.

- Fonts and typography: the implementation uses the product stack `Inter, SF Pro Display, PingFang SC, Microsoft YaHei, system-ui, sans-serif`. Heading, metric, tab, helper-copy, and table weights follow the source hierarchy without visible wrapping or truncation regressions.
- Spacing and layout rhythm: title, metadata strip, four-column summary, tabs, action row, warning, table, and pagination align with the source composition. The existing product sidebar is intentionally retained, so its width and menu inventory differ from the exploratory mock.
- Colors and visual tokens: navy, teal, coral, pale-blue borders, white surfaces, and muted supporting text match the selected direction. Semantic success and difference colors remain distinguishable.
- Image and asset fidelity: the screen does not require raster imagery. Existing Element Plus icons and the product's real Raj brand mark are used; no placeholder or handcrafted asset substitutes were introduced.
- Copy and content: source-specific operational language was preserved and made more precise for the real system. The implementation uses INR and the actual source file/worksheet metadata instead of the mock's illustrative CNY values.
- Accessibility and interaction: the default selected tab is `差异明细`; `订单明细` and `图表分析` were activated successfully; the batch-ID copy control has an accessible label; all four chart canvases resize to their visible container width.
- Responsive behavior: at `1100 × 900`, the summary becomes a 2 × 2 grid and the page has no document-level horizontal overflow.

## Focused region comparison

The focused comparison covers the dense operational area: tabs, difference title, action buttons, warning message, table columns and rows, state tags, payment-status dots, source metadata, and pagination. These details are readable at the saved crop and do not need another focused region.

## Comparison history

### Iteration 1

- [P2] The first implementation retained a back link and explanatory subtitle, pushing the summary and table too far below the fold.
- [P2] The initial local fixture contained two invalid timestamps, preventing all four reference rows from rendering.
- Fixes: removed the extra header copy, tightened the vertical rhythm, corrected the fixture, added explicit payment-status normalization, and replaced the English pagination total with `共 N 条`.
- Post-fix evidence: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-comparison-final.png`.

### Iteration 2

- [P1] ECharts initialized while its tab was hidden, leaving canvases at 100 pixels wide when the chart tab became visible.
- Fix: added an explicit active-state contract to `ChartPanel`, deferred initialization until the element has non-zero dimensions, and resized on activation.
- Post-fix evidence: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-charts-fixed.png`; each canvas width equals its 548-pixel container width at the target viewport.

### Iteration 3

- [P2] At a 1,100-pixel viewport, the page's implicit grid track expanded to table min-content width and caused document-level horizontal overflow.
- Fix: constrained the result-page grid to `minmax(0, 1fr)` and kept wide table content inside its own scrolling surface.
- Post-fix evidence: `/Users/dinghao/.codex/visualizations/2026/07/27/019fa554-ce10-72f0-9049-21eba50522af/design-qa/design-qa-responsive-1100-fixed.png`; document `scrollWidth` equals `clientWidth` at 1,100 pixels.

## Primary interactions tested

- Default difference tab and all four confirmed-missing rows.
- Order-detail tab, status filter surface, full-result table, and 1,000-row pagination state.
- Chart-analysis tab and four correctly sized chart canvases.
- Final browser console check: no warnings or errors.

## Follow-up polish

- [P3] The existing sidebar has fewer, permission-aware product menus than the exploratory mock. This is intentional and avoids introducing non-functional navigation.
- [P3] The mock shows a page-size selector; the implementation fixes the page size at 10 to keep the current API and interaction model simple.

final result: passed

---

# 提现订单操作人员汇总设计 QA

**比较目标**

- 源视觉稿：`/Users/dinghao/.codex/generated_images/019fafa8-ef4e-7d91-a9e3-38f1c72bac74/exec-d76c5fa2-453f-4949-8559-dfcd3418cc41.png`
- 实现截图：`/tmp/withdraw_operator_summary_chart_qa_v2.png`
- 路由与状态：`/withdraw-orders` 的“操作人员汇总”Tab；默认全部状态；Rohan 行的“图表”弹窗已打开。
- 视口：实现使用 1600 × 1000 CSS px、1× 密度；截图为 1600 × 1000 px。源视觉稿为 1568 × 1003 px；两者均为近似 1×，按内容区对齐比较，无额外密度缩放。

**全视图与区域证据**

- 已在同一比较输入中打开源视觉稿和实现截图，比较双 Tab 层级、筛选区、宽表、行尾“图表”入口与弹窗饼图。
- 重点区域为弹窗：源稿和实现都采用居中白色 dialog、遮罩、环形饼图、中心总订单数与右侧状态图例。实现使用本地样例数据，因此状态数量和订单数与源稿不同。
- 还验证了首次查询页、本地操作人员聚合、空 `audit_admin` 合并为“未填写操作人员”、图表打开/关闭；浏览器控制台无 error/warning。

**Findings**

- 无待修复的 P0/P1/P2 视觉问题。实现沿用现有 Raj Data 的字体、色彩令牌、左侧导航、卡片边框与表格密度；源稿中未包含的“操作人员包含匹配”筛选作为产品能力保留。

**Required Fidelity Surfaces**

- 字体与层级：页面标题、Tab、表头、正文和辅助说明沿用现有应用字号/字重；状态列的中文标签与原始状态码分层可读。
- 间距与布局：1600px 视口下查询区、统计表和分页均无截断；动态状态列横向扩展，首列和操作列固定。
- 色彩与令牌：沿用深蓝侧栏、青绿色活动状态、白色 surface 与低对比边框；饼图使用与源稿接近的蓝/青/橙/绿/红/紫序列。
- 图片与资产：该页面没有新增位图或自定义插图；沿用现有图标库和 ECharts Canvas 图表，没有以占位图替代目标资产。
- 文案与内容：状态显示使用字典标签，未知状态保留原始代码；弹窗明确说明占比仅按当前选中状态计算。

**Comparison History**

- [P1，已修复] 汇总请求在切换盘口时可能展示过期结果。修复为请求序号保护，只接收当前筛选对应的响应；普通订单查询同样应用该保护。
- [P2，已修复] 前端未限制状态多选数量，可能超过后端 20 项上限。已添加 `multiple-limit="20"` 和可见提示。
- [P2，已修复] 首轮视觉比较中的 dialog 偏宽、图例位于底部且与确认稿的图表信息层级不一致。已收紧 dialog 宽度，改为左侧环形图/中心总订单数/右侧图例计数与百分比，并重新截取比较。

**Implementation Checklist**

- [x] 保留完整提现订单查询页并放入“提现订单查询”Tab。
- [x] 增加本地缓存的操作人员状态聚合、动态状态列、分页、时间范围与状态筛选。
- [x] 增加单人状态占比 dialog 饼图。
- [x] 完成浏览器交互、控制台、测试、静态检查与生产构建验证。

**Follow-up Polish**

- [P3] 当真实盘口存在较多状态时，可根据使用频率调整图例排序或增加颜色主题配置；不影响当前交付。

final result: passed
