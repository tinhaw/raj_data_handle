<script setup lang="ts">
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'
import { init, use, type EChartsType } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    title: string
    option: EChartsOption
    empty?: boolean
    height?: number
  }>(),
  {
    empty: false,
    height: 280,
  },
)

const emit = defineEmits<{
  chartClick: [params: unknown]
}>()

const chartElement = ref<HTMLDivElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

function render(): void {
  if (!chartElement.value || props.empty) {
    chart?.clear()
    return
  }
  if (!chart) {
    chart = init(chartElement.value)
    chart.on('click', (params) => emit('chartClick', params))
  }
  chart.setOption(props.option, true)
}

watch(() => props.option, () => nextTick(render), { deep: true })
watch(() => props.empty, () => nextTick(render))

onMounted(() => {
  render()
  if (chartElement.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartElement.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="chart-panel surface-card">
    <header>{{ title }}</header>
    <div v-if="empty" class="chart-empty">暂无可展示数据</div>
    <div v-else ref="chartElement" class="chart-canvas" :style="{ height: `${height}px` }" />
  </section>
</template>

<style scoped>
.chart-panel {
  min-width: 0;
  padding: 18px 18px 10px;
}

.chart-panel header {
  color: var(--ink-strong);
  font-size: 15px;
  font-weight: 700;
}

.chart-canvas {
  width: 100%;
}

.chart-empty {
  height: 280px;
  display: grid;
  place-items: center;
  color: var(--ink-muted);
  font-size: 14px;
}
</style>
