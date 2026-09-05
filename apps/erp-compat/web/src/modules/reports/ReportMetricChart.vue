<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatMoney, toDecimal } from '@/utils/money'

type ChartType = 'bar' | 'line' | 'pie'

interface ChartPoint {
  label: string
  value: string
}

interface PieSlice {
  label: string
  value: number
  color: string
  percentage: number
  full: boolean
  path: string
}

const props = defineProps<{
  type: ChartType
  points: ChartPoint[]
  metricLabel: string
  assetLabel: string
}>()

// 汇总页是桌面宽屏布局，采用更宽的 SVG 画布将趋势图区压缩为横向信息带。
const chartWidth = 1600
const chartHeight = 260
const plot = { left: 88, right: 30, top: 18, bottom: 38 }
const colors = ['#155eef', '#12b76a', '#9e77ed', '#f79009', '#06aed4', '#f04438', '#6172f3', '#039855', '#fdb022', '#475467']

const points = computed(() => props.points.map((point) => {
  const value = toDecimal(point.value || 0).toNumber()
  return { ...point, value: Number.isFinite(value) ? value : 0 }
}))
const hasNegativeValues = computed(() => points.value.some((point) => point.value < 0))
const chartBounds = computed(() => {
  const values = points.value.map((point) => point.value)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  if (min === 0 && max === 0) return { min: 0, max: 1, range: 1 }
  const range = max - min || 1
  return { min, max, range }
})
const plotWidth = chartWidth - plot.left - plot.right
const plotHeight = chartHeight - plot.top - plot.bottom
const zeroY = computed(() => yFor(0))
const linePath = computed(() => points.value.map((point, index) => `${index === 0 ? 'M' : 'L'} ${xFor(index)} ${yFor(point.value)}`).join(' '))
const yTicks = computed(() => Array.from({ length: 5 }, (_, index) => {
  const ratio = index / 4
  const value = chartBounds.value.max - chartBounds.value.range * ratio
  return { value, y: plot.top + plotHeight * ratio }
}))
const selectedPieSlice = ref<PieSlice | null>(null)
const pieSlices = computed<PieSlice[]>(() => {
  if (hasNegativeValues.value) return []
  const total = points.value.reduce((sum, point) => sum + point.value, 0)
  if (total <= 0) return []
  let startAngle = -Math.PI / 2
  return points.value.map((point, index) => {
    const endAngle = startAngle + (point.value / total) * Math.PI * 2
    const slice: PieSlice = {
      ...point,
      color: colors[index % colors.length],
      percentage: (point.value / total) * 100,
      full: endAngle - startAngle >= Math.PI * 2 - 0.0001,
      path: piePath(startAngle, endAngle),
    }
    startAngle = endAngle
    return slice
  })
})

watch(pieSlices, () => {
  selectedPieSlice.value = null
})

function xFor(index: number) {
  const count = points.value.length
  return plot.left + (count <= 1 ? plotWidth / 2 : (index / (count - 1)) * plotWidth)
}

function yFor(value: number) {
  return plot.top + ((chartBounds.value.max - value) / chartBounds.value.range) * plotHeight
}

function barWidth() {
  return Math.max(6, Math.min(46, (plotWidth / Math.max(points.value.length, 1)) * 0.62))
}

function barX(index: number) {
  return xFor(index) - barWidth() / 2
}

function barY(value: number) {
  return Math.min(yFor(value), zeroY.value)
}

function barHeight(value: number) {
  return Math.max(1, Math.abs(yFor(value) - zeroY.value))
}

function showXLabel(index: number) {
  const count = points.value.length
  const every = Math.max(1, Math.ceil(count / 8))
  return index === 0 || index === count - 1 || index % every === 0
}

function shortLabel(label: string) {
  return label.length === 10 ? label.slice(5) : label
}

function barColor(value: number) {
  return value < 0 ? '#f04438' : '#155eef'
}

function piePath(startAngle: number, endAngle: number) {
  const centerX = 140
  const centerY = 132
  const radius = 96
  const startX = centerX + radius * Math.cos(startAngle)
  const startY = centerY + radius * Math.sin(startAngle)
  const endX = centerX + radius * Math.cos(endAngle)
  const endY = centerY + radius * Math.sin(endAngle)
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0
  return `M ${centerX} ${centerY} L ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} 1 ${endX} ${endY} Z`
}

function showPieDetails(slice: PieSlice) {
  selectedPieSlice.value = slice
}
</script>

<template>
  <div v-if="!points.length" class="metric-chart__empty">当前查询没有可用于绘图的时间序列数据。</div>
  <div v-else-if="type === 'pie' && hasNegativeValues" class="metric-chart__empty">该指标包含负值，饼图无法准确表达正负方向；请选择柱状图或折线图。</div>
  <div v-else-if="type === 'pie' && !pieSlices.length" class="metric-chart__empty">该指标在当前范围内均为 0，暂无可展示的饼图占比。</div>
  <div v-else-if="type === 'pie'" class="metric-chart metric-chart--pie">
    <svg viewBox="0 0 520 264" role="img" :aria-label="`${assetLabel} ${metricLabel} 在各时间点的占比`">
      <template v-for="slice in pieSlices" :key="slice.label">
        <circle
          v-if="slice.full"
          class="metric-chart__pie-slice"
          :class="{ 'metric-chart__pie-slice--active': selectedPieSlice?.label === slice.label }"
          cx="140"
          cy="132"
          r="96"
          :fill="slice.color"
          role="button"
          tabindex="0"
          :aria-label="`${slice.label}：${formatMoney(slice.value)}，占 ${slice.percentage.toFixed(1)}%`"
          @mouseenter="showPieDetails(slice)"
          @focus="showPieDetails(slice)"
          @click="showPieDetails(slice)"
        ><title>{{ slice.label }}：{{ formatMoney(slice.value) }}（{{ slice.percentage.toFixed(1) }}%）</title></circle>
        <path
          v-else
          class="metric-chart__pie-slice"
          :class="{ 'metric-chart__pie-slice--active': selectedPieSlice?.label === slice.label }"
          :d="slice.path"
          :fill="slice.color"
          role="button"
          tabindex="0"
          :aria-label="`${slice.label}：${formatMoney(slice.value)}，占 ${slice.percentage.toFixed(1)}%`"
          @mouseenter="showPieDetails(slice)"
          @focus="showPieDetails(slice)"
          @click="showPieDetails(slice)"
        ><title>{{ slice.label }}：{{ formatMoney(slice.value) }}（{{ slice.percentage.toFixed(1) }}%）</title></path>
      </template>
      <circle cx="140" cy="132" r="49" fill="#fff" />
      <text x="140" y="126" text-anchor="middle" class="pie-center__label">{{ metricLabel }}</text>
      <text x="140" y="148" text-anchor="middle" class="pie-center__asset">{{ assetLabel }}</text>
    </svg>
    <div class="metric-chart__pie-side">
      <div class="metric-chart__pie-detail" aria-live="polite">
        <template v-if="selectedPieSlice">
          <span><i :style="{ background: selectedPieSlice.color }"></i>{{ selectedPieSlice.label }}</span>
          <strong>{{ formatMoney(selectedPieSlice.value) }} {{ assetLabel }}</strong>
          <b>占 {{ selectedPieSlice.percentage.toFixed(1) }}%</b>
        </template>
        <span v-else>悬停或点击圆弧查看详情</span>
      </div>
      <div class="metric-chart__legend">
        <div v-for="slice in pieSlices" :key="slice.label" class="metric-chart__legend-item">
          <i :style="{ background: slice.color }"></i><span>{{ shortLabel(slice.label) }}</span><b>{{ slice.percentage.toFixed(1) }}%</b>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="metric-chart">
    <svg :viewBox="`0 0 ${chartWidth} ${chartHeight}`" role="img" :aria-label="`${assetLabel} ${metricLabel} 时间趋势`">
      <g class="metric-chart__grid">
        <template v-for="tick in yTicks" :key="tick.y">
          <line :x1="plot.left" :x2="chartWidth - plot.right" :y1="tick.y" :y2="tick.y" />
          <text :x="plot.left - 10" :y="tick.y + 4" text-anchor="end">{{ formatMoney(tick.value) }}</text>
        </template>
      </g>
      <line class="metric-chart__zero" :x1="plot.left" :x2="chartWidth - plot.right" :y1="zeroY" :y2="zeroY" />
      <template v-if="type === 'bar'">
        <g v-for="(point, index) in points" :key="point.label">
          <rect :x="barX(index)" :y="barY(point.value)" :width="barWidth()" :height="barHeight(point.value)" rx="4" :fill="barColor(point.value)"><title>{{ point.label }}：{{ formatMoney(point.value) }}</title></rect>
        </g>
      </template>
      <template v-else>
        <path class="metric-chart__line" :d="linePath" />
        <g v-for="(point, index) in points" :key="point.label">
          <circle :cx="xFor(index)" :cy="yFor(point.value)" r="4" :class="{ 'metric-chart__point--negative': point.value < 0 }"><title>{{ point.label }}：{{ formatMoney(point.value) }}</title></circle>
        </g>
      </template>
      <g class="metric-chart__x-axis">
        <template v-for="(point, index) in points" :key="point.label">
          <text v-if="showXLabel(index)" :x="xFor(index)" :y="chartHeight - 17" text-anchor="middle">{{ shortLabel(point.label) }}</text>
        </template>
      </g>
    </svg>
    <div class="metric-chart__caption"><span>{{ assetLabel }} · {{ metricLabel }}</span><span>{{ type === 'bar' ? '柱状图' : '折线图' }}按业务{{ points[0]?.label.length === 10 ? '日' : '月' }}展示</span></div>
  </div>
</template>

<style scoped>
.metric-chart { padding: 8px 20px 14px; }
.metric-chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.metric-chart__grid line { stroke: #eaecf0; stroke-width: 1; }
.metric-chart__grid text, .metric-chart__x-axis text { fill: #98a2b3; font-size: 11px; }
.metric-chart__zero { stroke: #98a2b3; stroke-width: 1; }
.metric-chart__line { fill: none; stroke: #155eef; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.metric-chart:not(.metric-chart--pie) circle { fill: #fff; stroke: #155eef; stroke-width: 3; }
.metric-chart .metric-chart__point--negative { stroke: #f04438; }
.metric-chart__caption { display: flex; justify-content: space-between; gap: 18px; margin-top: 1px; color: #98a2b3; font-size: 12px; }
.metric-chart__caption span:first-child { color: #667085; font-weight: 650; }
.metric-chart__empty { padding: 42px 20px; color: #98a2b3; font-size: 13px; text-align: center; }
.metric-chart--pie { display: grid; grid-template-columns: minmax(260px, .8fr) minmax(260px, 1.2fr); align-items: center; gap: 18px; padding: 18px 20px; }
.metric-chart--pie svg { max-width: 520px; }
.metric-chart__pie-slice { cursor: pointer; outline: none; transition: opacity .15s ease, stroke-width .15s ease; }
.metric-chart__pie-slice:hover, .metric-chart__pie-slice:focus, .metric-chart__pie-slice--active { opacity: .88; stroke: #fff; stroke-width: 3; }
.pie-center__label { fill: #344054; font-size: 14px; font-weight: 700; }
.pie-center__asset { fill: #98a2b3; font-size: 12px; }
.metric-chart__pie-detail { display: flex; align-items: center; gap: 10px; min-height: 42px; margin: 0 0 10px; padding: 10px 12px; color: #667085; background: #f8fafc; border: 1px solid #e4e7ec; border-radius: 7px; font-size: 12px; }
.metric-chart__pie-detail span:first-child { display: inline-flex; align-items: center; gap: 7px; min-width: 0; color: #344054; }
.metric-chart__pie-detail i { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
.metric-chart__pie-detail strong { margin-left: auto; color: #101828; font-size: 14px; white-space: nowrap; }
.metric-chart__pie-detail b { color: #027a48; white-space: nowrap; font-weight: 700; }
.metric-chart__legend { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px 14px; max-height: 210px; padding: 8px 0; overflow: auto; }
.metric-chart__legend-item { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 6px; color: #667085; font-size: 12px; }
.metric-chart__legend-item i { width: 8px; height: 8px; border-radius: 50%; }
.metric-chart__legend-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metric-chart__legend-item b { color: #344054; font-weight: 650; }
</style>
