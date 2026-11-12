import type { EChartsOption } from 'echarts'

// Some existing chart options specify light-theme labels explicitly. Remap only
// neutral UI colors, retaining series colors, tooltip formatting and callbacks.
const neutralText = new Set([
  '#31465d', '#8a9aab', '#53657a', '#718399', '#40536a', '#617b92',
  '#66798f', '#7a91a8', '#17324d', '#344054', '#183955',
])
const neutralLines = new Set(['#edf2f6', '#dbe6ef', '#eaecf0', '#dce6ee'])

export const darkChartTheme = {
  backgroundColor: 'transparent',
  textStyle: { color: '#B1C2D9' },
  title: { textStyle: { color: '#E6EDF7' }, subtextStyle: { color: '#9BAEC6' } },
  legend: { textStyle: { color: '#B1C2D9' }, pageTextStyle: { color: '#9BAEC6' } },
  tooltip: {
    backgroundColor: '#1A2A40',
    borderColor: '#2C405B',
    textStyle: { color: '#E6EDF7' },
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#2C405B' } },
    axisLabel: { color: '#9BAEC6' },
    splitLine: { lineStyle: { color: '#2C405B' } },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: '#2C405B' } },
    axisLabel: { color: '#9BAEC6' },
    splitLine: { lineStyle: { color: '#2C405B' } },
  },
}

export function darkChartOption(option: EChartsOption): EChartsOption {
  function remap(value: unknown, key = ''): unknown {
    if (typeof value === 'string' && /color$/i.test(key)) {
      if (neutralText.has(value.toLowerCase())) return '#B1C2D9'
      if (neutralLines.has(value.toLowerCase())) return '#2C405B'
    }
    if (Array.isArray(value)) return value.map((item) => remap(item, key))
    if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
      return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, remap(item, name)]))
    }
    return value
  }
  return remap(option) as EChartsOption
}
