<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue'
import type { ClaimColumn, ClaimRow } from '@/api/claimStatistics'
import { trendAxis, trendColumnLabel, trendPath, trendPointLabel, trendPoints, updateTrendExclusions } from './claimTrend'

const props = defineProps<{ marketName: string; columns: ClaimColumn[]; rows: ClaimRow[]; loading: boolean }>()
const titleId = useId()
const chartType = ref<'curve' | 'bar'>('curve')
const excludedKeys = ref<string[]>([])
const selectedKeys = computed({
  get: () => props.columns.filter(column => !excludedKeys.value.includes(column.key)).map(column => column.key),
  set: (keys: string[]) => { excludedKeys.value = updateTrendExclusions(props.columns.map(column => column.key), excludedKeys.value, keys) },
})
function toggleSeries(key: string) {
  selectedKeys.value = selectedKeys.value.includes(key)
    ? selectedKeys.value.filter(value => value !== key)
    : [...selectedKeys.value, key]
}
const colorIndices = new Map<string, number>()
watch(() => props.columns, columns => {
  for (const column of columns) if (!colorIndices.has(column.key)) colorIndices.set(column.key, colorIndices.size)
}, { immediate: true })
function color(key: string) { return `var(--claim-line-${(colorIndices.get(key) || 0) % 20 + 1})` }
const allSeries = computed(() => props.columns.map(column => ({
  key: column.key, label: trendColumnLabel(column), points: trendPoints(props.rows, column.key),
})))
const series = computed(() => allSeries.value.filter(item => selectedKeys.value.includes(item.key)))
const axis = computed(() => trendAxis(series.value.flatMap(item => item.points.map(point => point.value))))
const hasValues = computed(() => series.value.some(item => item.points.some(point => point.value !== null)))
const plotElement = ref<HTMLDivElement>()
const width = ref(960)
const height = 300
const padding = { left: 56, right: 20, top: 24, bottom: 44 }
const plotWidth = computed(() => Math.max(1, width.value - padding.left - padding.right))
const plotHeight = height - padding.top - padding.bottom
let observer: ResizeObserver | undefined
const inspectedDate = ref('')
const inspectedIndex = computed(() => props.rows.findIndex(row => row.date === inspectedDate.value))
watch(() => props.rows, rows => { if (!rows.some(row => row.date === inspectedDate.value)) inspectedDate.value = '' })
function x(index: number) { return padding.left + (chartType.value === 'bar' ? (index + 0.5) / Math.max(1, props.rows.length) * plotWidth.value : props.rows.length <= 1 ? plotWidth.value / 2 : index / (props.rows.length - 1) * plotWidth.value) }
const barWidth = computed(() => Math.min(28, plotWidth.value / Math.max(1, props.rows.length) * 0.8 / Math.max(1, series.value.length)))
function barX(index: number, seriesIndex: number) { return x(index) + (seriesIndex - (series.value.length - 1) / 2) * barWidth.value - barWidth.value / 2 }
function y(value: number) { return padding.top + plotHeight * (1 - value / axis.value.maximum) }
function showDate(index: number) {
  const every = Math.max(1, Math.ceil((props.rows.length - 1) / Math.max(1, Math.floor(plotWidth.value / 110))))
  return index === 0 || index === props.rows.length - 1 || (index % every === 0 && index < props.rows.length - Math.max(1, every / 2))
}
function dateLabel(date: string) {
  return width.value < 480 || props.rows[0]?.date.slice(0, 4) === props.rows.at(-1)?.date.slice(0, 4) ? date.slice(5) : date
}
function inspectPointer(event: PointerEvent) {
  if (!props.rows.length) return
  const bounds = (event.currentTarget as SVGSVGElement).getBoundingClientRect()
  const localX = (event.clientX - bounds.left) / bounds.width * width.value
  const fraction = Math.max(0, Math.min(1, (localX - padding.left) / plotWidth.value))
  const index = chartType.value === 'bar' ? Math.min(props.rows.length - 1, Math.floor(fraction * props.rows.length)) : Math.round(fraction * (props.rows.length - 1))
  inspectedDate.value = props.rows[index]!.date
}
function inspectOffset(offset: number) {
  const index = Math.max(0, Math.min(props.rows.length - 1, Math.max(0, inspectedIndex.value) + offset))
  inspectedDate.value = props.rows[index]?.date || ''
}
function focusInspection() { if (inspectedIndex.value < 0) inspectFirst() }
function inspectFirst() { inspectedDate.value = props.rows[0]?.date || '' }
function inspectLast() { inspectedDate.value = props.rows.at(-1)?.date || '' }
watch(plotElement, element => {
  observer?.disconnect()
  if (!element) return
  width.value = Math.max(180, element.clientWidth)
  observer = new ResizeObserver(entries => { if (entries[0]) width.value = Math.max(180, entries[0].contentRect.width) })
  observer.observe(element)
}, { flush: 'post' })
onUnmounted(() => observer?.disconnect())
</script>

<template>
  <section v-loading="loading" class="claim-trend" :aria-labelledby="titleId">
    <header class="trend-heading">
      <div><h3 :id="titleId">{{ marketName }} · 每日领取趋势</h3><p>勾选图例中的档位可显示或隐藏对应数据 · 单位：次</p></div>
      <div class="trend-selection">
        <el-radio-group v-model="chartType" size="small" aria-label="图表类型"><el-radio-button value="curve">曲线图</el-radio-button><el-radio-button value="bar">柱状图</el-radio-button></el-radio-group>
        <el-button text :disabled="selectedKeys.length === columns.length" @click="selectedKeys = columns.map(column => column.key)">全部展示</el-button>
        <el-button text :disabled="!selectedKeys.length" @click="selectedKeys = []">全部隐藏</el-button>
      </div>
    </header>
    <p class="trend-summary" aria-live="polite">已选 {{ selectedKeys.length }} / {{ columns.length }} 个档位<span v-if="rows.length"> · {{ rows[0]?.date }} 至 {{ rows.at(-1)?.date }}</span></p>
    <ul class="trend-legend" :aria-label="`${marketName} 展示档位`">
      <li v-for="item in allSeries" :key="item.key" :class="{ 'legend-hidden': !selectedKeys.includes(item.key) }">
        <label>
          <input type="checkbox" :checked="selectedKeys.includes(item.key)" :style="{ accentColor: color(item.key) }" :aria-label="item.label" @change="toggleSeries(item.key)" />
          <i :style="{ backgroundColor: color(item.key) }" />
          <span class="legend-label" :title="item.label">{{ item.label }}</span>
          <span v-if="!selectedKeys.includes(item.key)" class="legend-state">已隐藏</span>
          <strong v-else-if="inspectedIndex >= 0" :class="{ 'legend-partial': item.points[inspectedIndex]?.value !== null && !item.points[inspectedIndex]?.cell?.complete }">{{ trendPointLabel(item.points[inspectedIndex]!) }}</strong>
        </label>
      </li>
    </ul>
    <div v-if="!selectedKeys.length" class="trend-empty">请选择至少一个档位查看领取趋势。</div>
    <div v-else-if="!rows.length" class="trend-empty">当前查询范围暂无日期数据。</div>
    <template v-else>
      <div ref="plotElement" class="trend-plot">
        <svg :viewBox="`0 0 ${width} ${height}`" role="img" tabindex="0" :aria-label="`${marketName} 每日领取${chartType === 'curve' ? '曲线图' : '柱状图'}，横轴日期，纵轴当日领取次数，已选 ${selectedKeys.length} 个档位。使用左右方向键查看日期数量。`" @pointermove="inspectPointer" @pointerdown="inspectPointer" @focus="focusInspection" @keydown.left.prevent="inspectOffset(-1)" @keydown.right.prevent="inspectOffset(1)" @keydown.home.prevent="inspectFirst" @keydown.end.prevent="inspectLast">
          <title>{{ marketName }} 各档位每日兑换码领取次数</title>
          <g aria-hidden="true">
            <text class="trend-axis-label" :x="padding.left" y="14">领取次数（次）</text>
            <rect :x="padding.left" :y="padding.top" :width="plotWidth" :height="plotHeight" fill="transparent" />
            <g v-for="tick in axis.ticks" :key="tick" class="trend-grid">
              <line :x1="padding.left" :x2="width - padding.right" :y1="y(tick)" :y2="y(tick)" />
              <text :x="padding.left - 10" :y="y(tick) + 4" text-anchor="end">{{ tick.toLocaleString() }}</text>
            </g>
            <template v-for="(item, seriesIndex) in series" :key="item.key">
              <path v-if="chartType === 'curve'" class="trend-line" :d="trendPath(item.points, x, y)" :stroke="color(item.key)" />
              <template v-for="(point, index) in item.points" :key="point.date">
                <circle v-if="chartType === 'curve' && point.value !== null" :cx="x(index)" :cy="y(point.value)" r="3.5" :stroke="color(item.key)" :fill="point.cell?.complete ? color(item.key) : 'var(--theme-surface, #fff)'" stroke-width="2" />
                <rect v-else-if="chartType === 'bar' && point.value !== null" :x="barX(index, seriesIndex)" :y="y(point.value)" :width="Math.max(0.5, barWidth - 1)" :height="Math.max(0, y(0) - y(point.value))" :fill="color(item.key)" :fill-opacity="point.cell?.complete ? 1 : 0.45" />
              </template>
            </template>
            <line v-if="inspectedIndex >= 0" class="trend-cursor" :x1="x(inspectedIndex)" :x2="x(inspectedIndex)" :y1="padding.top" :y2="height - padding.bottom" />
            <template v-for="(row, index) in rows" :key="row.date">
              <text v-if="showDate(index)" class="trend-axis-label" :x="x(index)" :y="height - 24" :text-anchor="index === 0 ? 'start' : index === rows.length - 1 ? 'end' : 'middle'">{{ dateLabel(row.date) }}</text>
            </template>
            <text class="trend-axis-label" :x="width - padding.right" :y="height - 4" text-anchor="end">实际领取日</text>
          </g>
        </svg>
        <p v-if="!hasValues" class="trend-no-values">所选档位尚无已同步的领取数量</p>
      </div>
      <p class="trend-inspection" aria-live="polite">{{ inspectedIndex >= 0 ? `${inspectedDate} · 当日领取数量见图例` : '指向图表日期查看各系列数量；也可聚焦图表后使用左右方向键。' }}</p>

    </template>
    <p class="trend-footnote">按各盘口业务时区归日；{{ chartType === 'curve' ? '空心点' : '半透明柱' }}为部分数据，缺失数据保留空缺，不按 0 计算。</p>
  </section>
</template>

<style scoped>
.claim-trend {
  --claim-line-1: #2563b7;
  --claim-line-2: #228350;
  --claim-line-3: #a87912;
  --claim-line-4: #7952b3;
  --claim-line-5: #bd435a;
  --claim-line-6: #137e93;
  --claim-line-7: #b85e26;
  --claim-line-8: #5e7f2b;
  --claim-line-9: #765cae;
  --claim-line-10: #a84988;
  --claim-line-11: #226cb0;
  --claim-line-12: #12775c;
  --claim-line-13: #8f6b15;
  --claim-line-14: #80519e;
  --claim-line-15: #ad3e52;
  --claim-line-16: #187d83;
  --claim-line-17: #a75c2d;
  --claim-line-18: #727a1e;
  --claim-line-19: #516eb4;
  --claim-line-20: #8e527e;
  min-width: 0; margin: 16px 0 24px; padding: 20px; border: 1px solid var(--theme-border, #dce6ee); border-radius: 10px; background: var(--theme-surface, #fff); }
html.dark .claim-trend {
  --claim-line-1: #78b3f5;
  --claim-line-2: #76d5a1;
  --claim-line-3: #f1c46b;
  --claim-line-4: #c1acf5;
  --claim-line-5: #f18e96;
  --claim-line-6: #43bdd5;
  --claim-line-7: #ef9e69;
  --claim-line-8: #94b871;
  --claim-line-9: #a998e8;
  --claim-line-10: #d887bd;
  --claim-line-11: #3f8fda;
  --claim-line-12: #30a783;
  --claim-line-13: #c39835;
  --claim-line-14: #926acc;
  --claim-line-15: #d46777;
  --claim-line-16: #2b9da7;
  --claim-line-17: #c87942;
  --claim-line-18: #b2ba62;
  --claim-line-19: #7b8cce;
  --claim-line-20: #a475a8;
}
.trend-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.trend-heading h3 { margin: 0; color: var(--theme-text-strong, #17324d); font-size: 16px; }
.trend-heading p, .trend-summary, .trend-footnote, .trend-inspection { color: var(--theme-text-muted, #66798f); font-size: 12px; line-height: 1.7; margin: 4px 0 0; }
.trend-selection { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.trend-selection label { color: var(--theme-text, #344054); font-size: 12px; }
.trend-selection .el-button + .el-button { margin-left: 0; }
.trend-summary { margin: 12px 0 0; }
.trend-plot { position: relative; width: 100%; min-width: 0; margin-top: 12px; }
.trend-plot svg { display: block; width: 100%; height: 300px; touch-action: pan-y; border-radius: 4px; }
.trend-plot svg:focus-visible { outline: 2px solid var(--theme-info, #155eef); outline-offset: 2px; }
.trend-grid line { stroke: var(--theme-border, #dce6ee); stroke-width: 1; stroke-dasharray: 3 4; }
.trend-grid text, .trend-axis-label { fill: var(--theme-text-muted, #66798f); font-size: 11px; font-variant-numeric: tabular-nums; }
.trend-line { fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.trend-cursor { stroke: var(--theme-text-muted, #66798f); stroke-width: 1; stroke-dasharray: 4 3; pointer-events: none; }
.trend-inspection { min-height: 22px; }
.trend-legend { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 6px 20px; padding: 8px 0; margin: 0; list-style: none; }
.trend-legend li { min-width: 0; }
.trend-legend label { display: flex; cursor: pointer; min-height: 44px; padding: 4px 8px; border-radius: 4px; box-sizing: border-box; align-items: center; gap: 8px; min-width: 0; color: var(--theme-text, #344054); font-size: 12px; line-height: 1.7; }
.trend-legend label:hover { background: var(--theme-bg-soft, rgba(128, 128, 128, 0.08)); }
.trend-legend input { flex: 0 0 18px; width: 18px; height: 18px; margin: 0; cursor: pointer; }
.trend-legend input:focus-visible { outline: 2px solid var(--theme-info, #155eef); outline-offset: 3px; }
.legend-hidden .legend-label { color: var(--theme-text-muted, #66798f); }
.legend-hidden i { opacity: 0.35; }
.legend-state { margin-left: auto; white-space: nowrap; font-size: 11px; color: var(--theme-text-muted, #66798f); }
.trend-legend i { flex: 0 0 12px; width: 12px; height: 3px; border-radius: 2px; }
.legend-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trend-legend strong { margin-left: auto; font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
.trend-legend .legend-partial { color: var(--theme-warning, #b7791f); }
.trend-footnote { margin-top: 8px; }
.trend-empty { display: grid; place-items: center; min-height: 240px; color: var(--theme-text-muted, #66798f); font-size: 13px; }
.trend-no-values { position: absolute; inset: 70px 20px auto 56px; margin: 0; padding: 12px; text-align: center; font-size: 13px; color: var(--theme-text-muted, #66798f); background: var(--theme-surface, #fff); pointer-events: none; }
@media (max-width: 640px) {
  .claim-trend { padding: 16px 12px; }
  .trend-selection { width: 100%; }
  .trend-heading { gap: 12px; }
  .trend-legend { grid-template-columns: minmax(0, 1fr); }
}
</style>
