<script setup lang="ts">
import { Refresh, Search, UploadFilled } from '@element-plus/icons-vue'
import { ElButton, ElMessage, ElTag, TableV2FixedDir } from 'element-plus'
import type { Column } from 'element-plus'
import type { EChartsOption } from 'echarts'
import { computed, h, onMounted, reactive, ref } from 'vue'

import { apiErrorMessage } from '../api/client'
import { fetchEnabledSources } from '../api/sources'
import {
  importScoringReviewedCases,
  queryWithdrawChannelSummary,
  queryWithdrawOperatorSummary,
  queryWithdrawOrders,
  queryWithdrawScoringSummary,
  startWithdrawOrderRefresh,
  syncScoringReviewedCases,
} from '../api/withdrawOrders'
import ChartPanel from '../components/ChartPanel.vue'
import { currentUser } from '../stores/auth'
import type {
  SourceConfig,
  ScoringReviewSummaryCounts,
  WithdrawChannelSummaryItem,
  WithdrawChannelSummaryResponse,
  WithdrawOperatorSummaryItem,
  WithdrawOperatorSummaryResponse,
  WithdrawOrder,
  WithdrawOrderQueryResponse,
  WithdrawOrderRefreshRange,
  WithdrawOrderSummary,
  WithdrawScoringSummaryItem,
  WithdrawScoringSummaryResponse,
  WithdrawStatusDictionaryEntry,
} from '../types'
import { businessFullDayRange, formatDateTime, yesterdayFullDayRange } from '../ui'

type WithdrawTab = 'orders' | 'channels' | 'operators' | 'withdraw-summary'
type WithdrawChannelChartMetric = 'successfulOrderShare' | 'successfulAmountShare' | 'stuckRate'
type ChartDisplayType = 'bar' | 'pie' | 'line'

interface WithdrawChannelChartMetricDefinition {
  value: WithdrawChannelChartMetric
  label: string
  color: string
  read: (row: WithdrawChannelSummaryItem) => string
}

const OPERATOR_SUMMARY_EXCLUDED_STATUS_CODES = new Set(['0', '4', '5'])
const OPERATOR_SUMMARY_EXCLUDED_STATUS_LABELS = new Set(['待审核', '待审查', '提交中'])
const OPERATOR_CHART_COLORS = ['#377eea', '#39b8b0', '#f5a623', '#8d6ee8', '#ec6b62', '#5d8fc5']
const WITHDRAW_CHANNEL_CHART_COLORS = [
  '#2fa69d', '#4f8bc9', '#6fc6bd', '#e9a23b', '#8a67d6', '#d76d80', '#6f849c',
  '#2f9f98', '#4d8fd0', '#70c1b6', '#eaa23b', '#8467d7', '#d5677d', '#7388a0',
]
const HTML_ESCAPE_MAP: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}
const WITHDRAW_CHANNEL_CHART_METRICS: WithdrawChannelChartMetricDefinition[] = [
  {
    value: 'successfulOrderShare',
    label: '渠道成功订单占比',
    color: '#397de5',
    read: (row) => row.successfulOrderShare,
  },
  {
    value: 'successfulAmountShare',
    label: '渠道成功金额占比',
    color: '#8a67d6',
    read: (row) => row.successfulAmountShare,
  },
  {
    value: 'stuckRate',
    label: '卡单率',
    color: '#e9a23b',
    read: (row) => row.stuckRate,
  },
]
const WITHDRAW_CHANNEL_CHART_DISPLAY_OPTIONS: Array<{ value: ChartDisplayType; label: string }> = [
  { value: 'bar', label: '柱状图' },
  { value: 'pie', label: '饼图' },
  { value: 'line', label: '折线图' },
]
const WITHDRAW_CHANNEL_CHART_PREFERENCE_KEY_PREFIX = 'raj-withdraw-channel-chart-preferences'
const PIE_DIRECT_LABEL_LIMIT = 8
const MANUAL_REFRESH_RANGE_OPTIONS: Array<{
  value: WithdrawOrderRefreshRange
  label: string
  description: string
}> = [
  {
    value: 'day_before_yesterday',
    label: '前天 00:00:00 至 23:59:59',
    description: '按所选盘口的业务时区导出前天的完整自然日订单。',
  },
  {
    value: 'yesterday',
    label: '昨天 00:00:00 至 23:59:59',
    description: '按所选盘口的业务时区导出昨天的完整自然日订单。',
  },
  {
    value: 'today',
    label: '今日 00:00:00 至 23:59:59',
    description: '按所选盘口的业务时区导出当天订单；未来时间会自动截断。',
  },
]

const emptySummary: WithdrawOrderSummary = {
  orderCount: 0,
  amount: '0.00',
  realAmount: '0.00',
  averageAmount: '0.00',
  statusDistribution: [],
  timeSeries: [],
}

const emptyScoringReviewSummaryCounts: ScoringReviewSummaryCounts = {
  totalCount: 0,
  notEnteredScoringCount: 0,
  scoreLte30Count: 0,
  score31To60Count: 0,
  scoreGte61Count: 0,
}

const activeTab = ref<WithdrawTab>('orders')
const loading = ref(false)
const refreshStarting = ref(false)
const manualRefreshDialogVisible = ref(false)
const manualRefreshQueryRange = ref<WithdrawOrderRefreshRange>('yesterday')
const sourcesLoading = ref(false)
const sources = ref<SourceConfig[]>([])
const response = ref<WithdrawOrderQueryResponse | null>(null)
const rows = ref<WithdrawOrder[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const scoringDetailsVisible = ref(false)
const selectedScoringDetailRow = ref<WithdrawOrder | null>(null)
const queuedAt = ref<string | null>(null)
const knownStatuses = ref<string[]>([])
const filters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  uid: '',
  status: '',
  auditAdmin: '',
  orderNum: '',
  outTradeNo: '',
  payChannel: '',
})

const channelSummaryLoading = ref(false)
const channelSummaryResponse = ref<WithdrawChannelSummaryResponse | null>(null)
const channelSummaryPage = ref(1)
const channelSummaryPageSize = ref(50)
const withdrawChannelChartMetric = ref<WithdrawChannelChartMetric>('successfulOrderShare')
const withdrawChannelChartDisplayType = ref<ChartDisplayType>('bar')
const withdrawChannelChartPreferences = ref<Partial<Record<WithdrawChannelChartMetric, ChartDisplayType>>>({})
const channelSummaryFilters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  payChannel: '',
})

const operatorSummaryLoading = ref(false)
const operatorSummaryResponse = ref<WithdrawOperatorSummaryResponse | null>(null)
const operatorSummaryPage = ref(1)
const operatorSummaryPageSize = ref(50)
const operatorSummaryChartVisible = ref(false)
const selectedOperatorSummaryItem = ref<WithdrawOperatorSummaryItem | null>(null)
const operatorSummaryFilters = reactive({
  sourceId: '',
  createTimeRange: null as [string, string] | null,
  statuses: [] as string[],
  auditAdmin: '',
})
const scoringReviewImporting = ref(false)
const scoringReviewSyncing = ref(false)
const scoringReviewUploadInput = ref<HTMLInputElement | null>(null)
const scoringReviewImportFile = ref<File | null>(null)
const withdrawSummaryLoading = ref(false)
const withdrawSummaryResponse = ref<WithdrawScoringSummaryResponse | null>(null)
const withdrawSummaryFilters = reactive({
  sourceId: '',
  createTimeRange: yesterdayFullDayRange('Asia/Kolkata') as [string, string] | null,
})
let orderQueryRequestId = 0
let channelSummaryRequestId = 0
let operatorSummaryRequestId = 0
let withdrawSummaryRequestId = 0

const selectedOrderSource = computed(() =>
  sources.value.find((source) => source.sourceId === filters.sourceId),
)
const selectedOperatorSummarySource = computed(() =>
  sources.value.find((source) => source.sourceId === operatorSummaryFilters.sourceId),
)
const selectedChannelSummarySource = computed(() =>
  sources.value.find((source) => source.sourceId === channelSummaryFilters.sourceId),
)
const selectedWithdrawSummarySource = computed(() =>
  sources.value.find((source) => source.sourceId === withdrawSummaryFilters.sourceId),
)
const scoringReviewApiReady = computed(() => {
  const source = selectedWithdrawSummarySource.value
  return Boolean(
    source?.scoringApiBaseUrl &&
      source.scoringApiKeyConfigured &&
      source.scoringApiLastTestStatus === 'passed',
  )
})
const summary = computed(() => response.value?.summary || emptySummary)
const statusDictionary = computed(() => response.value?.statusDictionary || [])
const statusEntryByCode = computed(
  () => new Map(statusDictionary.value.map((entry) => [entry.code, entry])),
)
const operatorSummaryDictionary = computed(() => {
  if (operatorSummaryResponse.value?.sourceId === operatorSummaryFilters.sourceId) {
    return operatorSummaryResponse.value.statusDictionary
  }
  if (response.value?.sourceId === operatorSummaryFilters.sourceId) {
    return response.value.statusDictionary
  }
  return []
})
function isOperatorSummaryExcludedStatus(entry: WithdrawStatusDictionaryEntry): boolean {
  return (
    OPERATOR_SUMMARY_EXCLUDED_STATUS_CODES.has(entry.code.trim()) ||
    OPERATOR_SUMMARY_EXCLUDED_STATUS_LABELS.has(entry.label.trim())
  )
}
const operatorSummaryExcludedStatusCodes = computed(
  () =>
    new Set(
      [
        ...OPERATOR_SUMMARY_EXCLUDED_STATUS_CODES,
        ...operatorSummaryDictionary.value
          .filter(isOperatorSummaryExcludedStatus)
          .map((entry) => entry.code.trim()),
      ],
    ),
)
const operatorSummaryStatusEntryByCode = computed(
  () => new Map(operatorSummaryDictionary.value.map((entry) => [entry.code, entry])),
)
const operatorSummaryStatusColumns = computed(
  () =>
    (operatorSummaryResponse.value?.statusColumns || []).filter(
      (status) => !operatorSummaryExcludedStatusCodes.value.has(status.trim()),
    ),
)
const currency = computed(
  () => response.value?.currency || selectedOrderSource.value?.currency || 'INR',
)
const channelSummaryCurrency = computed(
  () =>
    channelSummaryResponse.value?.currency ||
    selectedChannelSummarySource.value?.currency ||
    response.value?.currency ||
    'INR',
)
const channelSummaryRows = computed(() => channelSummaryResponse.value?.items || [])
const withdrawSummaryRows = computed(() => withdrawSummaryResponse.value?.rows || [])
const withdrawSummaryTotals = computed(
  () => withdrawSummaryResponse.value?.totals || emptyScoringReviewSummaryCounts,
)
const withdrawScoreDistribution = computed(
  () => withdrawSummaryResponse.value?.scoreDistribution || [],
)
const withdrawScoreDistributionEmpty = computed(() => withdrawScoreDistribution.value.length === 0)
const withdrawScoreDistributionChartOption = computed<EChartsOption>(() => {
  const items = withdrawScoreDistribution.value
  const scoreCount = items.length
  const labelInterval = scoreCount > 24 ? Math.ceil(scoreCount / 12) - 1 : 0
  return {
    animationDuration: 420,
    animationDurationUpdate: 320,
    animationEasing: 'cubicOut',
    grid: { left: 30, right: 24, top: 28, bottom: 58, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: unknown) => `${Number(value).toLocaleString()} 单`,
      backgroundColor: 'rgba(18, 43, 64, 0.96)',
      borderColor: 'rgba(147, 196, 218, 0.38)',
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: '#f7fbff', fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      name: '评分',
      nameLocation: 'middle',
      nameGap: 42,
      data: items.map((item) => item.score),
      axisLine: { lineStyle: { color: '#dbe6ef' } },
      axisTick: { show: false },
      axisLabel: {
        interval: labelInterval,
        rotate: scoreCount > 12 ? 38 : 0,
        color: '#617b92',
        fontSize: 12,
      },
    },
    yAxis: {
      type: 'value',
      name: '订单数',
      minInterval: 1,
      axisLabel: { color: '#617b92', fontSize: 12 },
      splitLine: { lineStyle: { color: '#edf2f6', type: 'dashed' } },
    },
    series: [
      {
        name: '订单数',
        type: 'bar',
        data: items.map((item) => item.orderCount),
        barMaxWidth: 42,
        itemStyle: {
          color: '#397de5',
          borderRadius: [6, 6, 0, 0],
          shadowBlur: 8,
          shadowColor: 'rgba(57, 125, 229, 0.2)',
        },
      },
    ],
  }
})
const withdrawSummaryTimezone = computed(
  () =>
    withdrawSummaryResponse.value?.businessTimezone ||
    selectedWithdrawSummarySource.value?.businessTimezone ||
    '盘口业务时区',
)
const withdrawSummarySourceName = computed(
  () =>
    withdrawSummaryResponse.value?.sourceDisplayName ||
    selectedWithdrawSummarySource.value?.displayName ||
    '所选盘口',
)
const withdrawSummaryLocalUpdatedText = computed(() =>
  withdrawSummaryResponse.value
    ? formatDateTime(withdrawSummaryResponse.value.localUpdatedAt)
    : '尚未查询',
)
const withdrawSummaryRangeText = computed(() => {
  const result = withdrawSummaryResponse.value
  if (!result) return '尚未查询'
  return `${result.startAt.replace('T', ' ')} 至 ${result.endAt.replace('T', ' ')}`
})
const withdrawSummaryStatusEntryByCode = computed(
  () => new Map((withdrawSummaryResponse.value?.statusDictionary || []).map((entry) => [entry.code, entry])),
)
const withdrawSummaryStatusColumns = computed(
  () => withdrawSummaryResponse.value?.statusColumns || [],
)
const scoringReviewImportFileLabel = computed(() => {
  const file = scoringReviewImportFile.value
  if (!file) return '尚未选择评分审核 .xlsx 文件'
  const sizeInMegabytes = file.size / (1024 * 1024)
  const sizeLabel =
    sizeInMegabytes >= 1
      ? `${sizeInMegabytes.toFixed(1)} MB`
      : `${Math.max(1, Math.round(file.size / 1024))} KB`
  return `${file.name} · ${sizeLabel}`
})
const channelSummaryHasMultipleDates = computed(
  () => new Set(channelSummaryRows.value.map((row) => row.date).filter(Boolean)).size > 1,
)
const selectedWithdrawChannelChartMetric = computed<WithdrawChannelChartMetricDefinition>(
  () =>
    WITHDRAW_CHANNEL_CHART_METRICS.find((metric) => metric.value === withdrawChannelChartMetric.value) ||
    WITHDRAW_CHANNEL_CHART_METRICS[0]!,
)
const withdrawChannelChartValues = computed(() => {
  const metric = selectedWithdrawChannelChartMetric.value
  return channelSummaryRows.value.map((row) => ({
    name: withdrawChannelChartName(row, channelSummaryHasMultipleDates.value),
    value: numericValue(metric.read(row)),
  }))
})
const withdrawChannelChartHeight = computed(() => {
  if (withdrawChannelChartDisplayType.value !== 'pie') return 300
  const channelCount = withdrawChannelChartValues.value.length
  if (channelCount >= 13) return 420
  if (channelCount >= 9) return 360
  return 300
})
const withdrawChannelPieLabelNames = computed(
  () => {
    const positiveItems = [...withdrawChannelChartValues.value]
      .filter((item) => item.value > 0)
      .sort((left, right) => right.value - left.value)
    const labelLimit =
      positiveItems.length <= PIE_DIRECT_LABEL_LIMIT
        ? positiveItems.length
        : positiveItems.length <= 12
          ? 10
          : PIE_DIRECT_LABEL_LIMIT
    return new Set(positiveItems.slice(0, labelLimit).map((item) => item.name))
  },
)
const withdrawChannelChartEmpty = computed(
  () => !withdrawChannelChartValues.value.some((item) => item.value > 0),
)
const withdrawChannelChartOption = computed<EChartsOption>(() => {
  const metric = selectedWithdrawChannelChartMetric.value
  const formatter = (value: unknown) => percentageChartValueText(value)
  if (withdrawChannelChartDisplayType.value === 'pie') {
    return {
      animationDuration: 420,
      animationDurationUpdate: 320,
      animationEasing: 'cubicOut',
      color: [
        metric.color,
        ...WITHDRAW_CHANNEL_CHART_COLORS.filter((color) => color !== metric.color),
      ],
      tooltip: {
        trigger: 'item',
        triggerOn: 'mousemove|click|mousewheel',
        confine: true,
        backgroundColor: 'rgba(18, 43, 64, 0.96)',
        borderColor: 'rgba(147, 196, 218, 0.38)',
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: '#f7fbff', fontSize: 12 },
        formatter: withdrawChannelPieTooltipText,
      },
      legend: {
        type: 'scroll' as const,
        bottom: 0,
        left: 12,
        right: 12,
        data: withdrawChannelChartValues.value.map((item) => item.name),
        itemWidth: 14,
        itemHeight: 10,
        itemGap: 14,
        pageButtonItemGap: 6,
        pageButtonGap: 12,
        pageIconColor: '#397de5',
        pageIconInactiveColor: '#c7d2df',
        pageTextStyle: { color: '#718399', fontSize: 12 },
        textStyle: {
          color: '#53657a',
          fontSize: 12,
          fontWeight: 600,
          width: 120,
          overflow: 'truncate',
          ellipsis: '…',
        },
      },
      title: {
        text: '渠道分布',
        subtext: `${withdrawChannelChartValues.value.filter((item) => item.value > 0).length} 个`,
        left: 'center',
        top: '37%',
        textAlign: 'center',
        textStyle: { color: '#31465d', fontSize: 13, fontWeight: 700 },
        subtextStyle: { color: '#8a9aab', fontSize: 11, lineHeight: 16 },
      },
      series: [
        {
          type: 'pie',
          radius: ['46%', '72%'],
          center: ['50%', withdrawChannelChartValues.value.length > 12 ? '42%' : '44%'],
          startAngle: 90,
          avoidLabelOverlap: true,
          minShowLabelAngle: 3,
          padAngle: 0,
          itemStyle: { borderWidth: 0, borderRadius: 0 },
          emphasis: {
            scale: true,
            scaleSize: 8,
            itemStyle: {
              shadowBlur: 16,
              shadowColor: 'rgba(31, 61, 90, 0.2)',
            },
          },
          label: {
            show: true,
            formatter: '{b}',
            color: '#38546f',
            fontSize: 12,
            fontWeight: 600,
          },
          labelLine: {
            show: true,
            length: 16,
            length2: 12,
            smooth: 0.18,
            lineStyle: { width: 1, opacity: 0.72 },
          },
          labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
          data: withdrawChannelChartValues.value.map((item) => {
            const showLabel = withdrawChannelPieLabelNames.value.has(item.name)
            return {
              ...item,
              label: { show: showLabel },
              labelLine: { show: showLabel },
            }
          }),
        },
      ],
    }
  }
  return {
    animationDuration: 420,
    animationDurationUpdate: 320,
    animationEasing: 'cubicOut',
    grid: { left: 28, right: 24, top: 20, bottom: 52, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: withdrawChannelChartDisplayType.value === 'bar' ? 'shadow' : 'line' },
      valueFormatter: formatter,
      backgroundColor: 'rgba(18, 43, 64, 0.96)',
      borderColor: 'rgba(147, 196, 218, 0.38)',
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: '#f7fbff', fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: withdrawChannelChartValues.value.map((item) => item.name),
      axisLine: { lineStyle: { color: '#dbe6ef' } },
      axisTick: { show: false },
      axisLabel: { interval: 0, rotate: 24, color: '#617b92', fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter, color: '#617b92', fontSize: 12 },
      splitLine: { lineStyle: { color: '#edf2f6', type: 'dashed' } },
    },
    series: [
      {
        type: withdrawChannelChartDisplayType.value,
        data: withdrawChannelChartValues.value.map((item) => item.value),
        smooth: withdrawChannelChartDisplayType.value === 'line',
        symbol: withdrawChannelChartDisplayType.value === 'line' ? 'circle' : undefined,
        itemStyle: {
          color: metric.color,
          borderRadius: withdrawChannelChartDisplayType.value === 'bar' ? [6, 6, 0, 0] : undefined,
          shadowBlur: withdrawChannelChartDisplayType.value === 'bar' ? 8 : 0,
          shadowColor: withdrawChannelChartDisplayType.value === 'bar' ? `${metric.color}33` : undefined,
        },
        lineStyle: withdrawChannelChartDisplayType.value === 'line' ? { width: 3 } : undefined,
        areaStyle: withdrawChannelChartDisplayType.value === 'line' ? { color: `${metric.color}22` } : undefined,
        barMaxWidth: withdrawChannelChartDisplayType.value === 'bar' ? 42 : undefined,
      },
    ],
  }
})
const channelOptions = computed(() => response.value?.channelDictionary || [])
const channelSummaryOptions = computed(
  () => {
    if (channelSummaryResponse.value?.sourceId === channelSummaryFilters.sourceId) {
      return channelSummaryResponse.value.channelDictionary
    }
    if (response.value?.sourceId === channelSummaryFilters.sourceId) {
      return channelOptions.value
    }
    return []
  },
)
function dateRangeShortcutsFor(source: SourceConfig | undefined) {
  const timeZone = source?.businessTimezone || 'Asia/Kolkata'
  return [
    { text: '昨天', value: () => businessFullDayRange(timeZone, 1) },
    { text: '前天', value: () => businessFullDayRange(timeZone, 2) },
    { text: '今天', value: () => businessFullDayRange(timeZone, 0) },
  ]
}
const orderDateRangeShortcuts = computed(() => dateRangeShortcutsFor(selectedOrderSource.value))
const channelSummaryDateRangeShortcuts = computed(() =>
  dateRangeShortcutsFor(selectedChannelSummarySource.value),
)
const operatorSummaryDateRangeShortcuts = computed(() =>
  dateRangeShortcutsFor(selectedOperatorSummarySource.value),
)
const withdrawSummaryDateRangeShortcuts = computed(() =>
  dateRangeShortcutsFor(selectedWithdrawSummarySource.value),
)
const localUpdatedText = computed(() =>
  response.value ? formatDateTime(response.value.localUpdatedAt) : '尚未查询',
)
const channelSummaryLocalUpdatedText = computed(() =>
  channelSummaryResponse.value
    ? formatDateTime(channelSummaryResponse.value.localUpdatedAt)
    : '尚未查询',
)
const channelSummarySourceName = computed(
  () =>
    channelSummaryResponse.value?.sourceDisplayName ||
    selectedChannelSummarySource.value?.displayName ||
    '所选盘口',
)
const channelSummaryTimezone = computed(
  () =>
    channelSummaryResponse.value?.businessTimezone ||
    selectedChannelSummarySource.value?.businessTimezone ||
    '盘口业务时区',
)
const operatorSummaryLocalUpdatedText = computed(() =>
  operatorSummaryResponse.value
    ? formatDateTime(operatorSummaryResponse.value.localUpdatedAt)
    : '尚未查询',
)
const operatorSummarySourceName = computed(
  () =>
    operatorSummaryResponse.value?.sourceDisplayName ||
    selectedOperatorSummarySource.value?.displayName ||
    '所选盘口',
)
const operatorSummaryTimezone = computed(
  () =>
    operatorSummaryResponse.value?.businessTimezone ||
    selectedOperatorSummarySource.value?.businessTimezone ||
    '盘口业务时区',
)
const refreshIsIncomplete = computed(
  () => response.value?.refreshStatus === 'succeeded' && response.value.complete === false,
)
const syncTimingText = computed(() => {
  if (response.value?.lastRefreshedAt) {
    if (refreshIsIncomplete.value) {
      return (
        '上次导出 ' +
        formatDateTime(response.value.lastRefreshedAt) +
        ' · 结果不完整，已保留本地缓存'
      )
    }
    return '上次成功导出 ' + formatDateTime(response.value.lastRefreshedAt)
  }
  if (queuedAt.value) return '请求于 ' + formatDateTime(queuedAt.value)
  return '尚未成功导出'
})
const normalizedRefreshStatus = computed(() => {
  const responseStatus = response.value?.refreshStatus
  const status =
    queuedAt.value && (!responseStatus || responseStatus === 'not_started')
      ? 'queued'
      : responseStatus || 'not_started'
  return status.trim().toLowerCase()
})
const refreshStatusLabel = computed(() => {
  if (refreshIsIncomplete.value) return '导出不完整'
  const labels: Record<string, string> = {
    not_started: '暂无同步记录',
    idle: '等待下次导出',
    queued: '已排队',
    pending: '已排队',
    running: '导出中',
    refreshing: '导出中',
    completed: '导出完成',
    succeeded: '导出完成',
    success: '导出完成',
    failed: '导出失败',
  }
  return labels[normalizedRefreshStatus.value] || response.value?.refreshStatus || '暂无同步记录'
})
const refreshStatusTagType = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  if (refreshIsIncomplete.value) return 'warning'
  if (['failed', 'error'].includes(normalizedRefreshStatus.value)) return 'danger'
  if (['queued', 'pending', 'running', 'refreshing'].includes(normalizedRefreshStatus.value)) {
    return 'warning'
  }
  if (['completed', 'succeeded', 'success'].includes(normalizedRefreshStatus.value)) return 'success'
  return 'info'
})
const refreshInProgress = computed(() =>
  ['queued', 'pending', 'running', 'refreshing'].includes(normalizedRefreshStatus.value),
)
const manualRefreshRangeDescription = computed(
  () =>
    MANUAL_REFRESH_RANGE_OPTIONS.find((option) => option.value === manualRefreshQueryRange.value)
      ?.description || '',
)
const operatorSummaryStatusOptions = computed(() => {
  const options = new Map<string, WithdrawStatusDictionaryEntry>()
  for (const entry of operatorSummaryDictionary.value) {
    if (isOperatorSummaryExcludedStatus(entry)) continue
    options.set(entry.code, entry)
  }
  for (const status of operatorSummaryStatusColumns.value) {
    if (operatorSummaryExcludedStatusCodes.value.has(status.trim())) continue
    if (!options.has(status)) {
      options.set(status, { code: status, label: '', active: true })
    }
  }
  for (const status of operatorSummaryFilters.statuses) {
    if (operatorSummaryExcludedStatusCodes.value.has(status.trim())) continue
    if (!options.has(status)) {
      options.set(status, { code: status, label: '', active: false })
    }
  }
  return [...options.values()].sort((left, right) =>
    left.code.localeCompare(right.code, undefined, { numeric: true }),
  )
})

function amountText(
  value: string | null | undefined,
  maximumFractionDigits = 2,
  currencyCode = currency.value,
): string {
  if (value === null || value === undefined || value === '') return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: currencyCode,
      maximumFractionDigits,
    }).format(amount)
  } catch {
    return amount.toLocaleString('en-IN', { maximumFractionDigits }) + ' ' + currencyCode
  }
}

function summaryAmountText(value: string | null | undefined): string {
  return amountText(value, 0)
}

function statusText(
  status: string,
  entries: Map<string, WithdrawStatusDictionaryEntry>,
): string {
  const code = status.trim()
  const label = entries.get(code)?.label?.trim()
  return label || code || '未填写状态'
}

function statusLabel(status: string): string {
  return statusText(status, statusEntryByCode.value)
}

function orderStatusLabel(row: WithdrawOrder): string {
  return row.statusLabel?.trim() || statusLabel(row.status)
}

function withdrawOrderStatusTagType(
  row: WithdrawOrder,
): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const label = orderStatusLabel(row).trim()
  if (label === '代付成功') return 'success'
  if (['待审核', '待审查'].includes(label)) return 'warning'
  if (['已提交代付', '提交中'].includes(label)) return 'primary'
  if (['审核拒绝', '代付失败', '提交三方失败'].includes(label)) return 'danger'
  return 'info'
}

function ratioText(value: string | null | undefined): string {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? `${numeric.toFixed(2)}%` : '—'
}

function numericValue(value: string | number | null | undefined): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function percentageChartValueText(value: unknown): string {
  const rawValue = Array.isArray(value) ? value[0] : value
  return `${numericValue(String(rawValue ?? 0)).toFixed(2)}%`
}

function escapeTooltipText(value: unknown): string {
  return String(value ?? '').replace(/[&<>"']/g, (character) => HTML_ESCAPE_MAP[character] || character)
}

function tooltipColor(value: unknown): string {
  const color = typeof value === 'string' ? value : ''
  return /^#[0-9a-f]{3,8}$/i.test(color) ? color : '#397de5'
}

function withdrawChannelPieTooltipText(params: unknown): string {
  const item = (Array.isArray(params) ? params[0] : params) as
    | { name?: unknown; value?: unknown; color?: unknown }
    | undefined
  if (!item) return ''
  return `<div style="min-width:156px;line-height:1.55"><div style="display:flex;align-items:center;gap:7px;font-weight:700"><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${tooltipColor(item.color)}"></span>${escapeTooltipText(item.name)}</div><div style="margin-top:5px;color:#c9d9e7"><span>${escapeTooltipText(selectedWithdrawChannelChartMetric.value.label)}</span><strong style="float:right;margin-left:18px;color:#fff">${escapeTooltipText(percentageChartValueText(item.value))}</strong></div></div>`
}

function withdrawChannelChartName(
  row: WithdrawChannelSummaryItem,
  includeDate = false,
): string {
  const channelName = row.payChannelName?.trim() || row.payChannel?.trim() || '未配置渠道'
  return includeDate && row.date ? `${row.date} · ${channelName}` : channelName
}

function withdrawChannelChartPreferenceKey(): string {
  return `${WITHDRAW_CHANNEL_CHART_PREFERENCE_KEY_PREFIX}:${currentUser.value?.id || 'current'}`
}

function loadWithdrawChannelChartPreferences(): void {
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(withdrawChannelChartPreferenceKey()) || '{}',
    ) as Record<string, unknown>
    withdrawChannelChartPreferences.value = Object.fromEntries(
      Object.entries(saved).filter(
        ([metric, chartType]) =>
          WITHDRAW_CHANNEL_CHART_METRICS.some((item) => item.value === metric) &&
          WITHDRAW_CHANNEL_CHART_DISPLAY_OPTIONS.some((item) => item.value === chartType),
      ),
    ) as Partial<Record<WithdrawChannelChartMetric, ChartDisplayType>>
  } catch {
    withdrawChannelChartPreferences.value = {}
  }
  withdrawChannelChartDisplayType.value =
    withdrawChannelChartPreferences.value[withdrawChannelChartMetric.value] || 'bar'
}

function handleWithdrawChannelChartMetricChange(value: WithdrawChannelChartMetric): void {
  withdrawChannelChartMetric.value = value
  withdrawChannelChartDisplayType.value = withdrawChannelChartPreferences.value[value] || 'bar'
}

function saveWithdrawChannelChartPreference(): void {
  withdrawChannelChartPreferences.value = {
    ...withdrawChannelChartPreferences.value,
    [withdrawChannelChartMetric.value]: withdrawChannelChartDisplayType.value,
  }
  try {
    window.localStorage.setItem(
      withdrawChannelChartPreferenceKey(),
      JSON.stringify(withdrawChannelChartPreferences.value),
    )
    const displayName = WITHDRAW_CHANNEL_CHART_DISPLAY_OPTIONS.find(
      (item) => item.value === withdrawChannelChartDisplayType.value,
    )?.label || '图表'
    ElMessage.success(`已保存“${selectedWithdrawChannelChartMetric.value.label}”的${displayName}偏好。`)
  } catch {
    ElMessage.error('图表偏好保存失败，请检查浏览器本地存储权限。')
  }
}

function firstWithdrawText(value: string | null | undefined): string {
  const normalized = (value || '').trim()
  if (!normalized) return '—'
  if (['1', 'true', 'yes', '是'].includes(normalized.toLowerCase())) return '是'
  if (['0', 'false', 'no', '否'].includes(normalized.toLowerCase())) return '否'
  return normalized
}

function scoringText(value: string | null | undefined): string {
  const normalized = value?.trim()
  return normalized || '—'
}

function hasScoringSupplement(row: WithdrawOrder): boolean {
  return row.scoringRecordImported
}

function virtualCellText(value: unknown): ReturnType<typeof h> {
  const text = value === null || value === undefined || value === '' ? '—' : String(value)
  return h('span', { class: 'withdraw-virtual-cell', title: text }, text)
}

function openScoringDetails(row: WithdrawOrder): void {
  selectedScoringDetailRow.value = row
  scoringDetailsVisible.value = true
}

const withdrawOrderTableColumns = computed<Column<WithdrawOrder>[]>(() => [
  {
    key: 'scoringDetails',
    title: '评分详情',
    width: 112,
    fixed: true,
    align: 'center',
    cellRenderer: ({ rowData }) =>
      h(
        ElButton,
        {
          text: true,
          type: 'primary',
          size: 'small',
          onClick: () => openScoringDetails(rowData),
        },
        { default: () => (hasScoringSupplement(rowData) ? '查看评分' : '评分详情') },
      ),
  },
  {
    key: 'id',
    dataKey: 'id',
    title: '订单 ID',
    width: 162,
    fixed: true,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.id),
  },
  {
    key: 'uid',
    dataKey: 'uid',
    title: '用户 UID',
    width: 142,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.uid),
  },
  {
    key: 'orderNum',
    dataKey: 'orderNum',
    title: '我方提现订单号',
    width: 204,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.orderNum),
  },
  {
    key: 'outTradeNo',
    dataKey: 'outTradeNo',
    title: '三方支付订单号',
    width: 204,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.outTradeNo),
  },
  {
    key: 'payChannelName',
    dataKey: 'payChannelName',
    title: '支付渠道名称',
    width: 182,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payChannelName),
  },
  {
    key: 'payChannel',
    dataKey: 'payChannel',
    title: '支付渠道代码',
    width: 162,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.payChannel),
  },
  {
    key: 'amount',
    title: '提现金额',
    width: 150,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.amount)),
  },
  {
    key: 'realAmount',
    title: '实际到账',
    width: 150,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.realAmount)),
  },
  {
    key: 'fee',
    title: '提现手续费',
    width: 150,
    align: 'right',
    cellRenderer: ({ rowData }) => virtualCellText(amountText(rowData.fee)),
  },
  {
    key: 'createTime',
    dataKey: 'createTime',
    title: '创建时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.createTime),
  },
  {
    key: 'submitTime',
    dataKey: 'submitTime',
    title: '提交时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.submitTime),
  },
  {
    key: 'updateTime',
    dataKey: 'updateTime',
    title: '完成时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.updateTime),
  },
  {
    key: 'isFirst',
    title: '是否首提',
    width: 112,
    cellRenderer: ({ rowData }) => virtualCellText(firstWithdrawText(rowData.isFirst)),
  },
  {
    key: 'channel',
    dataKey: 'channel',
    title: '用户渠道',
    width: 162,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.channel),
  },
  {
    key: 'auditAdmin',
    dataKey: 'auditAdmin',
    title: '操作人员',
    width: 152,
    cellRenderer: ({ rowData }) => virtualCellText(rowData.auditAdmin),
  },
  {
    key: 'scoringGlobalGate',
    title: '全局硬性条件',
    width: 156,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringGlobalGate)),
  },
  {
    key: 'scoringSceneReview',
    title: '场景审核',
    width: 142,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringSceneReview)),
  },
  {
    key: 'scoringScore',
    title: '评分审核',
    width: 126,
    align: 'center',
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringScore)),
  },
  {
    key: 'scoringDecisionStage',
    title: '决断阶段',
    width: 148,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringDecisionStage)),
  },
  {
    key: 'scoringFinalSuggestion',
    title: '最终审核建议',
    width: 192,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringFinalSuggestion)),
  },
  {
    key: 'scoringOperationResult',
    title: '操作结果',
    width: 148,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringOperationResult)),
  },
  {
    key: 'scoringReviewedAt',
    title: '审核完成时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringReviewedAt)),
  },
  {
    key: 'scoringReviewElapsed',
    title: '审核耗时',
    width: 132,
    align: 'center',
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringReviewElapsed)),
  },
  {
    key: 'scoringQueueElapsed',
    title: '队列中耗时',
    width: 144,
    align: 'center',
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringQueueElapsed)),
  },
  {
    key: 'scoringQueueEnteredAt',
    title: '进入队列时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringQueueEnteredAt)),
  },
  {
    key: 'scoringQueueExitedAt',
    title: '退出队列时间',
    width: 184,
    cellRenderer: ({ rowData }) => virtualCellText(scoringText(rowData.scoringQueueExitedAt)),
  },
  {
    key: 'status',
    title: '状态',
    width: 136,
    fixed: TableV2FixedDir.RIGHT,
    align: 'center',
    cellRenderer: ({ rowData }) =>
      h(
        ElTag,
        { type: withdrawOrderStatusTagType(rowData), effect: 'light', size: 'small' },
        { default: () => orderStatusLabel(rowData) },
      ),
  },
])

function operatorSummaryStatusLabel(status: string): string {
  return operatorSummaryStatusEntryByCode.value.get(status.trim())?.label?.trim() || '未配置状态'
}

function withdrawSummaryStatusLabel(status: string): string {
  const normalized = status.trim()
  return (
    withdrawSummaryStatusEntryByCode.value.get(normalized)?.label?.trim() ||
    normalized ||
    '未填写状态'
  )
}

function withdrawSummaryStatusCount(item: WithdrawScoringSummaryItem, status: string): number {
  return item.statusCounts.find((entry) => entry.status === status)?.count || 0
}

function withdrawSummaryOperatorDisplayName(item: WithdrawScoringSummaryItem): string {
  return item.auditAdminMissing || !item.auditAdmin.trim() ? '未记录操作人' : item.auditAdmin
}

function statusOptionsLabel(entry: WithdrawStatusDictionaryEntry): string {
  return statusLabel(entry.code) + (entry.active ? '' : ' · 已停用')
}

function operatorSummaryStatusOptionLabel(entry: WithdrawStatusDictionaryEntry): string {
  return operatorSummaryStatusLabel(entry.code) + (entry.active ? '' : ' · 已停用')
}

function mergeKnownStatuses(values: string[]): void {
  knownStatuses.value = [
    ...new Set([...knownStatuses.value, ...values.map((value) => value.trim()).filter(Boolean)]),
  ].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }))
}

const statusOptions = computed(() => {
  const options = new Map<string, WithdrawStatusDictionaryEntry>()
  for (const entry of statusDictionary.value) {
    if (entry.active || entry.code === filters.status) options.set(entry.code, entry)
  }
  for (const status of knownStatuses.value) {
    if (!options.has(status)) options.set(status, { code: status, label: '', active: true })
  }
  if (filters.status && !options.has(filters.status)) {
    options.set(filters.status, { code: filters.status, label: '', active: false })
  }
  return [...options.values()].sort((left, right) =>
    left.code.localeCompare(right.code, undefined, { numeric: true }),
  )
})

function validateFilters(): boolean {
  if (!filters.sourceId) {
    ElMessage.warning('请先选择盘口。')
    return false
  }
  return true
}

function validateOperatorSummaryFilters(): boolean {
  if (!operatorSummaryFilters.sourceId) {
    ElMessage.warning('请先选择需要汇总的盘口。')
    return false
  }
  return true
}

async function load(resetPage = false, quiet = false): Promise<void> {
  if (!validateFilters()) return
  if (resetPage) page.value = 1
  const requestId = ++orderQueryRequestId
  loading.value = true
  try {
    const [createTimeStart, createTimeEnd] = filters.createTimeRange || []
    const hasCreateTimeRange = Boolean(createTimeStart && createTimeEnd)
    const result = await queryWithdrawOrders({
      sourceId: filters.sourceId,
      createTimeStart: hasCreateTimeRange ? createTimeStart : undefined,
      createTimeEnd: hasCreateTimeRange ? createTimeEnd : undefined,
      uid: filters.uid || undefined,
      status: filters.status || undefined,
      auditAdmin: filters.auditAdmin || undefined,
      orderNum: filters.orderNum || undefined,
      outTradeNo: filters.outTradeNo || undefined,
      payChannel: filters.payChannel || undefined,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (requestId !== orderQueryRequestId) return
    response.value = result
    rows.value = result.items
    total.value = result.total
    mergeKnownStatuses(result.summary.statusDistribution.map((item) => item.status))
  } catch (error) {
    if (requestId === orderQueryRequestId && !quiet) {
      ElMessage.error(apiErrorMessage(error, '本地提现订单加载失败。'))
    }
  } finally {
    if (requestId === orderQueryRequestId) loading.value = false
  }
}

async function loadChannelSummary(resetPage = false): Promise<void> {
  if (!channelSummaryFilters.sourceId) {
    ElMessage.warning('请先选择需要汇总的盘口。')
    return
  }
  if (resetPage) channelSummaryPage.value = 1
  const requestId = ++channelSummaryRequestId
  channelSummaryLoading.value = true
  try {
    const [createTimeStart, createTimeEnd] = channelSummaryFilters.createTimeRange || []
    const hasCreateTimeRange = Boolean(createTimeStart && createTimeEnd)
    const result = await queryWithdrawChannelSummary({
      sourceId: channelSummaryFilters.sourceId,
      createTimeStart: hasCreateTimeRange ? createTimeStart : undefined,
      createTimeEnd: hasCreateTimeRange ? createTimeEnd : undefined,
      payChannel: channelSummaryFilters.payChannel || undefined,
      page: channelSummaryPage.value,
      pageSize: channelSummaryPageSize.value,
    })
    if (requestId !== channelSummaryRequestId) return
    channelSummaryResponse.value = result
  } catch (error) {
    if (requestId === channelSummaryRequestId) {
      ElMessage.error(apiErrorMessage(error, '支付渠道汇总加载失败。'))
    }
  } finally {
    if (requestId === channelSummaryRequestId) channelSummaryLoading.value = false
  }
}

async function loadOperatorSummary(resetPage = false): Promise<void> {
  if (!validateOperatorSummaryFilters()) return
  if (resetPage) operatorSummaryPage.value = 1
  const requestId = ++operatorSummaryRequestId
  operatorSummaryLoading.value = true
  try {
    const [createTimeStart, createTimeEnd] = operatorSummaryFilters.createTimeRange || []
    const hasCreateTimeRange = Boolean(createTimeStart && createTimeEnd)
    const result = await queryWithdrawOperatorSummary({
      sourceId: operatorSummaryFilters.sourceId,
      createTimeStart: hasCreateTimeRange ? createTimeStart : undefined,
      createTimeEnd: hasCreateTimeRange ? createTimeEnd : undefined,
      statuses: operatorSummaryFilters.statuses.length
        ? [...operatorSummaryFilters.statuses]
        : undefined,
      auditAdmin: operatorSummaryFilters.auditAdmin || undefined,
      page: operatorSummaryPage.value,
      pageSize: operatorSummaryPageSize.value,
    })
    if (requestId !== operatorSummaryRequestId) return
    operatorSummaryResponse.value = result
  } catch (error) {
    if (requestId === operatorSummaryRequestId) {
      ElMessage.error(apiErrorMessage(error, '操作人员汇总加载失败。'))
    }
  } finally {
    if (requestId === operatorSummaryRequestId) operatorSummaryLoading.value = false
  }
}

async function loadWithdrawSummary(): Promise<void> {
  if (!withdrawSummaryFilters.sourceId) {
    ElMessage.warning('请先选择需要汇总的盘口。')
    return
  }
  const [createTimeStart, createTimeEnd] = withdrawSummaryFilters.createTimeRange || []
  if (!createTimeStart || !createTimeEnd) {
    ElMessage.warning('请先选择提现订单汇总的创建时间范围。')
    return
  }
  const requestId = ++withdrawSummaryRequestId
  withdrawSummaryLoading.value = true
  try {
    const result = await queryWithdrawScoringSummary({
      sourceId: withdrawSummaryFilters.sourceId,
      createTimeStart,
      createTimeEnd,
    })
    if (requestId !== withdrawSummaryRequestId) return
    withdrawSummaryResponse.value = result
  } catch (error) {
    if (requestId === withdrawSummaryRequestId) {
      ElMessage.error(apiErrorMessage(error, '提现订单汇总加载失败。'))
    }
  } finally {
    if (requestId === withdrawSummaryRequestId) withdrawSummaryLoading.value = false
  }
}

function openScoringReviewImportFilePicker(): void {
  if (!withdrawSummaryFilters.sourceId) {
    ElMessage.warning('请先选择评分审核数据所属的盘口。')
    return
  }
  scoringReviewUploadInput.value?.click()
}

function handleScoringReviewImportFileSelected(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    scoringReviewImportFile.value = null
    input.value = ''
    ElMessage.warning('请选择评分审核导出的 .xlsx 文件。')
    return
  }
  scoringReviewImportFile.value = file
}

async function importScoringReviewWorkbook(): Promise<void> {
  const sourceId = withdrawSummaryFilters.sourceId
  const file = scoringReviewImportFile.value
  if (!sourceId) {
    ElMessage.warning('请先选择评分审核数据所属的盘口。')
    return
  }
  if (!file) {
    ElMessage.warning('请先选择评分审核导出的 .xlsx 文件。')
    return
  }
  if (scoringReviewImporting.value) return
  scoringReviewImporting.value = true
  try {
    const result = await importScoringReviewedCases(sourceId, file)
    ElMessage.success(
      `评分审核导入完成：源表 ${result.sourceRowCount.toLocaleString()} 条，匹配 ${result.matchedCount.toLocaleString()} 条，新建 ${result.createdCount.toLocaleString()} 条，更新 ${result.updatedCount.toLocaleString()} 条，未匹配 ${result.unmatchedCount.toLocaleString()} 条。`,
    )
    scoringReviewImportFile.value = null
    if (scoringReviewUploadInput.value) scoringReviewUploadInput.value.value = ''
    if (filters.sourceId === result.sourceId) {
      await load(false, true)
    }
    if (withdrawSummaryFilters.sourceId === result.sourceId) {
      await loadWithdrawSummary()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '评分审核 Excel 导入失败。'))
  } finally {
    scoringReviewImporting.value = false
  }
}

async function syncScoringReviewFromRemote(): Promise<void> {
  const sourceId = withdrawSummaryFilters.sourceId
  const [createTimeStart, createTimeEnd] = withdrawSummaryFilters.createTimeRange || []
  if (!sourceId || !createTimeStart || !createTimeEnd) {
    ElMessage.warning('请先选择盘口和评分审核同步的创建时间范围。')
    return
  }
  if (!scoringReviewApiReady.value) {
    ElMessage.warning('所选盘口尚未完成评分审核 API 配置或连接测试。')
    return
  }
  if (scoringReviewSyncing.value) return
  scoringReviewSyncing.value = true
  try {
    const result = await syncScoringReviewedCases({
      sourceId,
      createTimeStart,
      createTimeEnd,
    })
    ElMessage.success(
      `评分审核远端同步完成：拉取 ${result.sourceRowCount.toLocaleString()} 条，匹配 ${result.matchedCount.toLocaleString()} 条，新建 ${result.createdCount.toLocaleString()} 条，更新 ${result.updatedCount.toLocaleString()} 条，未匹配 ${result.unmatchedCount.toLocaleString()} 条。`,
    )
    if (filters.sourceId === result.sourceId) {
      await load(false, true)
    }
    if (withdrawSummaryFilters.sourceId === result.sourceId) {
      await loadWithdrawSummary()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '评分审核远端同步失败。'))
  } finally {
    scoringReviewSyncing.value = false
  }
}

function openManualRefreshDialog(): void {
  if (!validateFilters() || refreshStarting.value) return
  manualRefreshQueryRange.value = 'yesterday'
  manualRefreshDialogVisible.value = true
}

async function startRefresh(): Promise<void> {
  if (!validateFilters() || refreshStarting.value) return
  refreshStarting.value = true
  try {
    const result = await startWithdrawOrderRefresh({
      sourceId: filters.sourceId,
      queryRange: manualRefreshQueryRange.value,
    })
    queuedAt.value = result.requestedAt
    manualRefreshDialogVisible.value = false
    ElMessage.success(result.message || '已提交后台导出任务。')
    await load(false, true)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '提现订单后台导出启动失败。'))
  } finally {
    refreshStarting.value = false
  }
}

function resetLocalResult(): void {
  orderQueryRequestId += 1
  response.value = null
  rows.value = []
  total.value = 0
  knownStatuses.value = []
  queuedAt.value = null
}

function resetChannelSummaryResult(): void {
  channelSummaryRequestId += 1
  channelSummaryResponse.value = null
}

function resetOperatorSummaryResult(): void {
  operatorSummaryRequestId += 1
  operatorSummaryResponse.value = null
  selectedOperatorSummaryItem.value = null
  operatorSummaryChartVisible.value = false
}

function resetWithdrawSummaryResult(): void {
  withdrawSummaryRequestId += 1
  withdrawSummaryResponse.value = null
}

function handleSourceChange(): void {
  page.value = 1
  filters.createTimeRange = yesterdayFullDayRange(
    selectedOrderSource.value?.businessTimezone || 'Asia/Kolkata',
  )
  filters.status = ''
  filters.orderNum = ''
  filters.outTradeNo = ''
  filters.payChannel = ''
  resetLocalResult()
  void load(true)
}

function handleChannelSummarySourceChange(): void {
  channelSummaryPage.value = 1
  channelSummaryFilters.createTimeRange = yesterdayFullDayRange(
    selectedChannelSummarySource.value?.businessTimezone || 'Asia/Kolkata',
  )
  channelSummaryFilters.payChannel = ''
  resetChannelSummaryResult()
  void loadChannelSummary(true)
}

function handleOperatorSummarySourceChange(): void {
  operatorSummaryPage.value = 1
  operatorSummaryFilters.createTimeRange = yesterdayFullDayRange(
    selectedOperatorSummarySource.value?.businessTimezone || 'Asia/Kolkata',
  )
  operatorSummaryFilters.statuses = []
  operatorSummaryFilters.auditAdmin = ''
  resetOperatorSummaryResult()
  void loadOperatorSummary(true)
}

function handleWithdrawSummarySourceChange(): void {
  withdrawSummaryFilters.createTimeRange = yesterdayFullDayRange(
    selectedWithdrawSummarySource.value?.businessTimezone || 'Asia/Kolkata',
  )
  scoringReviewImportFile.value = null
  if (scoringReviewUploadInput.value) scoringReviewUploadInput.value.value = ''
  resetWithdrawSummaryResult()
}

function handlePageChange(nextPage: number): void {
  page.value = nextPage
  void load(false)
}

function handlePageSizeChange(nextPageSize: number): void {
  pageSize.value = nextPageSize
  void load(true)
}

function handleChannelSummaryPageChange(nextPage: number): void {
  channelSummaryPage.value = nextPage
  void loadChannelSummary(false)
}

function handleChannelSummaryPageSizeChange(nextPageSize: number): void {
  channelSummaryPageSize.value = nextPageSize
  void loadChannelSummary(true)
}

function handleOperatorSummaryPageChange(nextPage: number): void {
  operatorSummaryPage.value = nextPage
  void loadOperatorSummary(false)
}

function handleOperatorSummaryPageSizeChange(nextPageSize: number): void {
  operatorSummaryPageSize.value = nextPageSize
  void loadOperatorSummary(true)
}

function handleTabChange(nextTab: string | number): void {
  if (
    nextTab === 'channels' &&
    channelSummaryResponse.value?.sourceId !== channelSummaryFilters.sourceId &&
    channelSummaryFilters.sourceId
  ) {
    void loadChannelSummary(true)
  }
  if (
    nextTab === 'operators' &&
    operatorSummaryResponse.value?.sourceId !== operatorSummaryFilters.sourceId &&
    operatorSummaryFilters.sourceId
  ) {
    void loadOperatorSummary(true)
  }
  if (
    nextTab === 'withdraw-summary' &&
    withdrawSummaryResponse.value?.sourceId !== withdrawSummaryFilters.sourceId &&
    withdrawSummaryFilters.sourceId
  ) {
    void loadWithdrawSummary()
  }
}

function operatorDisplayName(item: WithdrawOperatorSummaryItem): string {
  return item.auditAdminMissing || !item.auditAdmin.trim()
    ? '系统'
    : item.auditAdmin
}

function operatorStatusCount(item: WithdrawOperatorSummaryItem, status: string): number {
  return item.statusCounts.find((entry) => entry.status === status)?.count || 0
}

const operatorChartData = computed(() => {
  const item = selectedOperatorSummaryItem.value
  if (!item) return []
  return operatorSummaryStatusColumns.value
    .map((status, index) => {
      return {
        name: operatorSummaryStatusLabel(status),
        value: operatorStatusCount(item, status),
        color: OPERATOR_CHART_COLORS[index % OPERATOR_CHART_COLORS.length]!,
      }
    })
    .filter((item) => item.value > 0)
})
const operatorChartEmpty = computed(() => operatorChartData.value.length === 0)
const operatorChartTitle = computed(() => {
  const item = selectedOperatorSummaryItem.value
  return item ? operatorDisplayName(item) + ' · 状态订单占比' : '状态订单占比'
})
function operatorChartPercentage(value: number): string {
  const total = selectedOperatorSummaryItem.value?.selectedTotal || 0
  if (!total) return '0%'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format((value / total) * 100) + '%'
}

const operatorChartOption = computed<EChartsOption>(() => {
  const selectedTotal = selectedOperatorSummaryItem.value?.selectedTotal || 0
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/><strong>{c}</strong> 单 · {d}%',
      backgroundColor: 'rgba(18, 44, 70, 0.94)',
      borderWidth: 0,
      padding: [9, 12],
      textStyle: { color: '#ffffff', fontSize: 12 },
    },
    title: {
      text: '订单合计',
      subtext: selectedTotal.toLocaleString() + ' 单',
      left: '50%',
      top: '42%',
      textAlign: 'center',
      textStyle: {
        color: '#7a91a8',
        fontSize: 11,
        fontWeight: 700,
      },
      subtextStyle: {
        color: '#17324d',
        fontSize: 20,
        fontWeight: 800,
        lineHeight: 28,
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['54%', '72%'],
        center: ['50%', '50%'],
        startAngle: 90,
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 4,
          borderRadius: 8,
        },
        emphasis: {
          scale: true,
          scaleSize: 7,
          itemStyle: {
            shadowBlur: 14,
            shadowColor: 'rgba(31, 61, 90, 0.18)',
          },
        },
        label: {
          show: false,
        },
        labelLine: { show: false },
        data: operatorChartData.value.map((item) => ({
          name: item.name,
          value: item.value,
          itemStyle: { color: item.color },
        })),
      },
    ],
  }
})

function openOperatorSummaryChart(item: WithdrawOperatorSummaryItem): void {
  selectedOperatorSummaryItem.value = item
  operatorSummaryChartVisible.value = true
}

onMounted(async () => {
  loadWithdrawChannelChartPreferences()
  sourcesLoading.value = true
  try {
    sources.value = await fetchEnabledSources()
    if (sources.value.length) {
      const firstSource = sources.value[0]!
      const firstSourceId = firstSource.sourceId
      filters.sourceId = firstSourceId
      filters.createTimeRange = yesterdayFullDayRange(firstSource.businessTimezone)
      channelSummaryFilters.sourceId = firstSourceId
      channelSummaryFilters.createTimeRange = yesterdayFullDayRange(firstSource.businessTimezone)
      operatorSummaryFilters.sourceId = firstSourceId
      operatorSummaryFilters.createTimeRange = yesterdayFullDayRange(firstSource.businessTimezone)
      withdrawSummaryFilters.sourceId = firstSourceId
      withdrawSummaryFilters.createTimeRange = yesterdayFullDayRange(firstSource.businessTimezone)
      await load(true)
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '可用盘口加载失败。'))
  } finally {
    sourcesLoading.value = false
  }
})
</script>

<template>
  <div class="page-stack withdraw-page">
    <header class="page-header">
      <div>
        <span class="page-eyebrow">WITHDRAWAL MONITOR</span>
        <h1>提现订单</h1>
        <p>从远端后台按日导出、解析并缓存提现订单；支持订单明细、渠道、操作人员和评分关联汇总。</p>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="withdraw-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="提现订单明细" name="orders">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>提现订单明细</h2>
              <p>仅查询本地已导出并缓存的提现订单；远端同步由后台工作进程按自然日执行。</p>
            </div>
            <div class="header-actions">
              <div class="refresh-state">
                <span class="refresh-state__dot" :class="{ 'is-live': refreshInProgress }" />
                <div>
                  <strong>后台导出：{{ refreshStatusLabel }}</strong>
                  <small>{{ syncTimingText }} · 本地更新 {{ localUpdatedText }}</small>
                </div>
              </div>
              <el-button
                :icon="Refresh"
                :loading="refreshStarting"
                :disabled="!filters.sourceId"
                @click="openManualRefreshDialog"
              >
                启动一次刷新
              </el-button>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field">
                <span>盘口</span>
                <el-select
                  v-model="filters.sourceId"
                  :loading="sourcesLoading"
                  placeholder="选择已启用盘口"
                  @change="handleSourceChange"
                >
                  <el-option
                    v-for="source in sources"
                    :key="source.sourceId"
                    :label="source.displayName"
                    :value="source.sourceId"
                  />
                </el-select>
              </label>
              <label class="query-field query-field--time-range">
                <span>创建时间（{{ selectedOrderSource?.businessTimezone || '盘口业务时区' }}）</span>
                <el-date-picker
                  v-model="filters.createTimeRange"
                  type="datetimerange"
                  :shortcuts="orderDateRangeShortcuts"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!filters.sourceId"
                  style="width: 100%"
                />
              </label>
              <label class="query-field">
                <span>用户 UID</span>
                <el-input v-model.trim="filters.uid" clearable placeholder="精确 UID" />
              </label>
              <label class="query-field">
                <span>我方提现订单号</span>
                <el-input v-model.trim="filters.orderNum" clearable placeholder="包含匹配" />
              </label>
              <label class="query-field">
                <span>三方支付订单号</span>
                <el-input v-model.trim="filters.outTradeNo" clearable placeholder="包含匹配" />
              </label>
              <label class="query-field">
                <span>支付渠道</span>
                <el-select v-model="filters.payChannel" clearable filterable placeholder="全部渠道">
                  <el-option
                    v-for="item in channelOptions"
                    :key="item.code"
                    :label="item.label"
                    :value="item.code"
                  />
                </el-select>
              </label>
              <label class="query-field">
                <span>状态</span>
                <el-select v-model="filters.status" clearable placeholder="全部状态">
                  <el-option
                    v-for="item in statusOptions"
                    :key="item.code"
                    :label="statusOptionsLabel(item)"
                    :value="item.code"
                  />
                </el-select>
              </label>
              <label class="query-field">
                <span>操作人员</span>
                <el-input v-model.trim="filters.auditAdmin" clearable placeholder="包含匹配" />
              </label>
            </div>
            <div class="query-card__footer">
              <span>筛选只作用于本地缓存；时间范围按盘口业务时区解释，不影响后台按日导出的范围。</span>
              <el-button type="primary" :icon="Search" :loading="loading" @click="load(true)">
                查询本地订单
              </el-button>
            </div>
          </section>

          <section class="metric-grid" aria-label="提现订单汇总">
            <article class="surface-card metric-card metric-card--orders">
              <span>订单总数</span>
              <strong>{{ summary.orderCount.toLocaleString() }}</strong>
              <small>当前本地筛选条件</small>
            </article>
            <article class="surface-card metric-card">
              <span>提现金额</span>
              <strong>{{ summaryAmountText(summary.amount) }}</strong>
              <small>amount 汇总</small>
            </article>
            <article class="surface-card metric-card">
              <span>实际到账</span>
              <strong>{{ summaryAmountText(summary.realAmount) }}</strong>
              <small>real_amount 汇总</small>
            </article>
            <article class="surface-card metric-card">
              <span>平均提现金额</span>
              <strong>{{ summaryAmountText(summary.averageAmount) }}</strong>
              <small>提现金额 / 订单数</small>
            </article>
          </section>

          <section class="surface-card table-card">
            <div class="section-heading">
              <div>
                <h2>提现订单列表</h2>
                <p>
                  共 {{ total.toLocaleString() }} 条；本地数据更新时间：{{ localUpdatedText }}。表格固定高度，仅在表格内滚动；评分审核的 11 个补充字段已直接展示，点击“评分详情”可查看摘要和当前状态。
                </p>
              </div>
              <el-tag :type="refreshStatusTagType" effect="plain">
                {{ refreshStatusLabel }}
              </el-tag>
            </div>
            <div
              v-loading="loading"
              class="withdraw-virtual-table"
              aria-label="提现订单明细虚拟化表格"
            >
              <el-auto-resizer>
                <template #default="{ height, width }">
                  <el-table-v2
                    :columns="withdrawOrderTableColumns"
                    :data="rows"
                    :height="height"
                    :width="width"
                    :header-height="52"
                    :row-height="58"
                    row-key="id"
                    fixed
                    scrollbar-always-on
                  >
                    <template #empty>
                      <el-empty description="当前本地数据中暂无提现订单" />
                    </template>
                  </el-table-v2>
                </template>
              </el-auto-resizer>
            </div>
            <div class="table-pagination">
              <el-pagination
                background
                layout="total, sizes, prev, pager, next, jumper"
                :total="total"
                :current-page="page"
                :page-size="pageSize"
                :page-sizes="[20, 50, 100]"
                @update:current-page="handlePageChange"
                @update:page-size="handlePageSizeChange"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="支付渠道汇总" name="channels">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>支付渠道汇总</h2>
              <p>按创建日期和支付渠道统计本地缓存数据；金额、手续费及占比均由服务端统一计算。</p>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field">
                <span>盘口</span>
                <el-select
                  v-model="channelSummaryFilters.sourceId"
                  :loading="sourcesLoading"
                  placeholder="选择已启用盘口"
                  @change="handleChannelSummarySourceChange"
                >
                  <el-option
                    v-for="source in sources"
                    :key="source.sourceId"
                    :label="source.displayName"
                    :value="source.sourceId"
                  />
                </el-select>
              </label>
              <label class="query-field query-field--time-range">
                <span>创建时间（{{ channelSummaryTimezone }}）</span>
                <el-date-picker
                  v-model="channelSummaryFilters.createTimeRange"
                  type="datetimerange"
                  :shortcuts="channelSummaryDateRangeShortcuts"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!channelSummaryFilters.sourceId"
                  style="width: 100%"
                />
              </label>
              <label class="query-field">
                <span>支付渠道</span>
                <el-select
                  v-model="channelSummaryFilters.payChannel"
                  clearable
                  filterable
                  placeholder="全部渠道"
                >
                  <el-option
                    v-for="item in channelSummaryOptions"
                    :key="item.code"
                    :label="item.label"
                    :value="item.code"
                  />
                </el-select>
              </label>
            </div>
            <div class="query-card__footer">
              <span>成功金额、成功手续费和比例仅按服务端定义的“代付成功”状态计算；分母为同一盘口、同一日期的全部渠道。</span>
              <el-button
                type="primary"
                :icon="Search"
                :loading="channelSummaryLoading"
                @click="loadChannelSummary(true)"
              >
                查询汇总
              </el-button>
            </div>
          </section>

          <section class="surface-card withdraw-channel-chart-card">
            <div class="withdraw-channel-chart-card__heading">
              <div>
                <h2>提现-渠道图表</h2>
                <p>
                  以当前列表页中的支付渠道为横坐标展示指标；跨多个日期时，图例会附带日期以避免渠道名称重复。保存后会默认使用当前指标的展示方式。
                </p>
              </div>
              <div class="withdraw-channel-chart-card__controls">
                <label>
                  <span>指标</span>
                  <el-select
                    :model-value="withdrawChannelChartMetric"
                    @update:model-value="handleWithdrawChannelChartMetricChange"
                  >
                    <el-option
                      v-for="metric in WITHDRAW_CHANNEL_CHART_METRICS"
                      :key="metric.value"
                      :label="metric.label"
                      :value="metric.value"
                    />
                  </el-select>
                </label>
                <label>
                  <span>展示方式</span>
                  <el-select v-model="withdrawChannelChartDisplayType">
                    <el-option
                      v-for="option in WITHDRAW_CHANNEL_CHART_DISPLAY_OPTIONS"
                      :key="option.value"
                      :label="option.label"
                      :value="option.value"
                    />
                  </el-select>
                </label>
                <el-button type="primary" plain @click="saveWithdrawChannelChartPreference">
                  保存偏好
                </el-button>
              </div>
            </div>
            <ChartPanel
              :title="selectedWithdrawChannelChartMetric.label"
              :option="withdrawChannelChartOption"
              :empty="withdrawChannelChartEmpty"
              :height="withdrawChannelChartHeight"
              :active="activeTab === 'channels'"
              plain
              :show-title="false"
            />
          </section>

          <section class="surface-card table-card channel-summary-table-card">
            <div class="section-heading">
              <div>
                <h2>支付渠道统计</h2>
                <p>
                  {{ channelSummarySourceName }} · 共
                  {{ (channelSummaryResponse?.total || 0).toLocaleString() }} 条渠道日期记录 · 本地数据更新时间：
                  {{ channelSummaryLocalUpdatedText }}。
                </p>
              </div>
              <el-tag type="info" effect="plain">{{ channelSummaryTimezone }}</el-tag>
            </div>
            <el-table
              v-loading="channelSummaryLoading"
              :data="channelSummaryRows"
              empty-text="当前本地筛选条件下暂无支付渠道统计"
            >
              <el-table-column label="日期" min-width="120" prop="date" fixed="left" />
              <el-table-column label="支付渠道名称" min-width="170" fixed="left" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.payChannelName || row.payChannel || '未配置渠道' }}
                </template>
              </el-table-column>
              <el-table-column label="支付渠道代码" min-width="148" prop="payChannel" show-overflow-tooltip />
              <el-table-column label="渠道成功订单占比" min-width="170" align="right">
                <template #default="{ row }">{{ ratioText(row.successfulOrderShare) }}</template>
              </el-table-column>
              <el-table-column label="渠道成功金额占比" min-width="170" align="right">
                <template #default="{ row }">{{ ratioText(row.successfulAmountShare) }}</template>
              </el-table-column>
              <el-table-column label="卡单率" min-width="112" align="right">
                <template #default="{ row }">{{ ratioText(row.stuckRate) }}</template>
              </el-table-column>
              <el-table-column label="代付成功率" min-width="125" align="right">
                <template #default="{ row }">{{ ratioText(row.successRate) }}</template>
              </el-table-column>
              <el-table-column label="提现总订单数" min-width="140" align="right">
                <template #default="{ row }">{{ row.orderCount.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="代付成功订单数" min-width="150" align="right">
                <template #default="{ row }">{{ row.successfulOrderCount.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="代付成功金额" min-width="165" align="right">
                <template #default="{ row }">
                  {{ amountText(row.successfulAmount, 2, channelSummaryCurrency) }}
                </template>
              </el-table-column>
              <el-table-column label="提现手续费（成功）" min-width="170" align="right">
                <template #default="{ row }">
                  {{ amountText(row.successfulFee, 2, channelSummaryCurrency) }}
                </template>
              </el-table-column>
              <el-table-column label="代付失败数" min-width="130" align="right">
                <template #default="{ row }">{{ row.failedOrderCount.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="已提交代付数" min-width="145" align="right">
                <template #default="{ row }">{{ row.submittedOrderCount.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="审核拒绝数" min-width="132" align="right">
                <template #default="{ row }">{{ (row.rejectedOrderCount || 0).toLocaleString() }}</template>
              </el-table-column>
            </el-table>
            <div class="table-pagination">
              <el-pagination
                background
                layout="total, sizes, prev, pager, next, jumper"
                :total="channelSummaryResponse?.total || 0"
                :current-page="channelSummaryPage"
                :page-size="channelSummaryPageSize"
                :page-sizes="[20, 50, 100]"
                @update:current-page="handleChannelSummaryPageChange"
                @update:page-size="handleChannelSummaryPageSizeChange"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="操作人员汇总" name="operators">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>操作人员汇总</h2>
              <p>按盘口和创建时间统计操作人员在所选状态下的提现订单数量。</p>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field">
                <span>盘口</span>
                <el-select
                  v-model="operatorSummaryFilters.sourceId"
                  :loading="sourcesLoading"
                  placeholder="选择已启用盘口"
                  @change="handleOperatorSummarySourceChange"
                >
                  <el-option
                    v-for="source in sources"
                    :key="source.sourceId"
                    :label="source.displayName"
                    :value="source.sourceId"
                  />
                </el-select>
              </label>
              <label class="query-field query-field--time-range">
                <span>创建时间（{{ operatorSummaryTimezone }}）</span>
                <el-date-picker
                  v-model="operatorSummaryFilters.createTimeRange"
                  type="datetimerange"
                  :shortcuts="operatorSummaryDateRangeShortcuts"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!operatorSummaryFilters.sourceId"
                  style="width: 100%"
                />
              </label>
              <label class="query-field">
                <span>操作人员</span>
                <el-input
                  v-model.trim="operatorSummaryFilters.auditAdmin"
                  clearable
                  placeholder="包含匹配"
                />
              </label>
              <label class="query-field operator-summary-status-field">
                <span>参与统计的状态</span>
                <el-select
                  v-model="operatorSummaryFilters.statuses"
                  multiple
                  :multiple-limit="20"
                  collapse-tags
                  collapse-tags-tooltip
                  clearable
                  placeholder="默认统计其余状态（最多 20 项）"
                >
                  <el-option
                    v-for="item in operatorSummaryStatusOptions"
                    :key="item.code"
                    :label="operatorSummaryStatusOptionLabel(item)"
                    :value="item.code"
                  />
                </el-select>
              </label>
            </div>
            <div class="query-card__footer">
              <span>仅统计本地缓存；待审核、待审查、提交中不参与统计或展示。空操作人员归为“系统”。</span>
              <el-button
                type="primary"
                :icon="Search"
                :loading="operatorSummaryLoading"
                @click="loadOperatorSummary(true)"
              >
                查询汇总
              </el-button>
            </div>
          </section>

          <section class="surface-card table-card operator-summary-table-card">
            <div class="section-heading">
              <div>
                <h2>操作人员状态统计</h2>
                <p>
                  {{ operatorSummarySourceName }} · 共
                  {{ (operatorSummaryResponse?.total || 0).toLocaleString() }} 名操作人员 · 已选状态订单
                  {{ (operatorSummaryResponse?.selectedOrderTotal || 0).toLocaleString() }} 单 · 本地数据更新时间：
                  {{ operatorSummaryLocalUpdatedText }}。
                </p>
              </div>
              <el-tag type="info" effect="plain">
                {{ operatorSummaryStatusColumns.length }} 个统计状态
              </el-tag>
            </div>
            <el-table
              v-loading="operatorSummaryLoading"
              :data="operatorSummaryResponse?.items || []"
              empty-text="当前本地筛选条件下暂无操作人员统计"
            >
              <el-table-column label="操作人员" min-width="200" fixed="left">
                <template #default="{ row }">
                  <div class="operator-name-cell">
                    <strong>{{ operatorDisplayName(row) }}</strong>
                  </div>
                </template>
              </el-table-column>
              <el-table-column
                v-for="status in operatorSummaryStatusColumns"
                :key="status"
                :min-width="136"
                align="center"
              >
                <template #header>
                  <span class="status-column-heading">
                    <strong>{{ operatorSummaryStatusLabel(status) }}</strong>
                  </span>
                </template>
                <template #default="{ row }">
                  <span class="operator-status-count">
                    {{ operatorStatusCount(row, status).toLocaleString() }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="已选合计" min-width="112" align="right" fixed="right">
                <template #default="{ row }">
                  <strong class="operator-selected-total">{{ row.selectedTotal.toLocaleString() }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button
                    text
                    type="primary"
                    :disabled="row.selectedTotal === 0"
                    @click="openOperatorSummaryChart(row)"
                  >
                    图表
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="table-pagination">
              <el-pagination
                background
                layout="total, sizes, prev, pager, next, jumper"
                :total="operatorSummaryResponse?.total || 0"
                :current-page="operatorSummaryPage"
                :page-size="operatorSummaryPageSize"
                :page-sizes="[20, 50, 100]"
                @update:current-page="handleOperatorSummaryPageChange"
                @update:page-size="handleOperatorSummaryPageSizeChange"
              />
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="提现订单汇总" name="withdraw-summary">
        <div class="tab-stack">
          <header class="tab-pane-header">
            <div>
              <h2>提现订单汇总</h2>
              <p>按远端管理后台的操作人员汇总已关联评分审核记录的提现订单，并展示评分区间和订单状态。</p>
            </div>
          </header>

          <section class="query-card surface-card">
            <div class="query-card__grid">
              <label class="query-field">
                <span>盘口</span>
                <el-select
                  v-model="withdrawSummaryFilters.sourceId"
                  :loading="sourcesLoading"
                  placeholder="选择已启用盘口"
                  @change="handleWithdrawSummarySourceChange"
                >
                  <el-option
                    v-for="source in sources"
                    :key="source.sourceId"
                    :label="source.displayName"
                    :value="source.sourceId"
                  />
                </el-select>
              </label>
              <label class="query-field query-field--time-range">
                <span>订单创建时间（{{ withdrawSummaryTimezone }}）</span>
                <el-date-picker
                  v-model="withdrawSummaryFilters.createTimeRange"
                  type="datetimerange"
                  :shortcuts="withdrawSummaryDateRangeShortcuts"
                  value-format="YYYY-MM-DD HH:mm:ss"
                  format="YYYY-MM-DD HH:mm:ss"
                  range-separator="至"
                  start-placeholder="开始时间"
                  end-placeholder="结束时间"
                  clearable
                  :disabled="!withdrawSummaryFilters.sourceId"
                  style="width: 100%"
                />
              </label>
              <label class="query-field scoring-review-import-field">
                <span>评分审核 Excel</span>
                <div class="scoring-review-import-picker">
                  <input
                    ref="scoringReviewUploadInput"
                    class="scoring-review-file-input"
                    type="file"
                    accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    @change="handleScoringReviewImportFileSelected"
                  />
                  <el-button
                    :icon="UploadFilled"
                    :disabled="!withdrawSummaryFilters.sourceId || scoringReviewImporting || scoringReviewSyncing"
                    @click="openScoringReviewImportFilePicker"
                  >
                    选择 .xlsx
                  </el-button>
                  <span :title="scoringReviewImportFile?.name" class="scoring-review-import-file-name">
                    {{ scoringReviewImportFileLabel }}
                  </span>
                </div>
              </label>
            </div>
            <div class="query-card__footer">
              <span>
                仅查询本地缓存；时间范围按所选盘口业务时区，以提现订单创建时间计算。已配置并测试通过的评分审核 API 会随提现订单刷新自动同步；也可在此补同步或导入 Excel。
              </span>
              <div class="query-card__footer-actions">
                <el-tooltip
                  content="请先在盘口配置中完成该盘口的评分审核 API Base URL、API Key 与连接测试。"
                  :disabled="scoringReviewApiReady"
                >
                  <span>
                    <el-button
                      :icon="Refresh"
                      :loading="scoringReviewSyncing"
                      :disabled="!withdrawSummaryFilters.sourceId || !scoringReviewApiReady || scoringReviewImporting"
                      @click="syncScoringReviewFromRemote"
                    >
                      从远端同步
                    </el-button>
                  </span>
                </el-tooltip>
                <el-button
                  :loading="scoringReviewImporting"
                  :disabled="!scoringReviewImportFile || !withdrawSummaryFilters.sourceId || scoringReviewSyncing"
                  @click="importScoringReviewWorkbook"
                >
                  导入评分 Excel
                </el-button>
                <el-button
                  type="primary"
                  :icon="Search"
                  :loading="withdrawSummaryLoading"
                  :disabled="!withdrawSummaryFilters.sourceId"
                  @click="loadWithdrawSummary"
                >
                  查询汇总
                </el-button>
              </div>
            </div>
          </section>

          <el-alert
            v-if="withdrawSummaryResponse"
            class="withdraw-summary-coverage-alert"
            type="warning"
            :closable="false"
            show-icon
          >
            <template #title>
              本表仅统计评分审核订单数据表中有记录且可关联到本地提现订单的订单。当前查询口径下，管理后台有
              {{ withdrawSummaryResponse.managementOrderCount.toLocaleString() }} 单，其中评分审核有记录
              {{ withdrawSummaryResponse.scoringRecordOrderCount.toLocaleString() }} 单；评分审核无记录
              {{ withdrawSummaryResponse.missingScoringRecordCount.toLocaleString() }} 单，不计入本表。
            </template>
          </el-alert>

          <section class="metric-grid scoring-review-metric-grid" aria-label="提现订单评分汇总指标">
            <article class="surface-card metric-card metric-card--orders">
              <span>评分审核有记录订单</span>
              <strong>{{ withdrawSummaryTotals.totalCount.toLocaleString() }}</strong>
              <small>三个评分档合计</small>
            </article>
            <article class="surface-card metric-card">
              <span>未进入评分/无分值</span>
              <strong>{{ withdrawSummaryTotals.notEnteredScoringCount.toLocaleString() }}</strong>
              <small>已计入 ≤30 分</small>
            </article>
            <article class="surface-card metric-card">
              <span>≤30 分</span>
              <strong>{{ withdrawSummaryTotals.scoreLte30Count.toLocaleString() }}</strong>
              <small>含评分字段未填写订单</small>
            </article>
            <article class="surface-card metric-card">
              <span>31–60 分</span>
              <strong>{{ withdrawSummaryTotals.score31To60Count.toLocaleString() }}</strong>
              <small>评分区间订单数</small>
            </article>
            <article class="surface-card metric-card">
              <span>≥61 分</span>
              <strong>{{ withdrawSummaryTotals.scoreGte61Count.toLocaleString() }}</strong>
              <small>评分区间订单数</small>
            </article>
          </section>

          <section class="surface-card withdraw-score-distribution-card">
            <div class="section-heading">
              <div>
                <h2>评分分值分布</h2>
                <p>
                  仅统计评分审核订单数据表有记录、可关联到本地提现订单且“评分审核”为有效数值的订单：
                  {{ (withdrawSummaryResponse?.numericScoreOrderCount || 0).toLocaleString() }} 单。评分表有记录但未进入评分或无分值的
                  {{ (withdrawSummaryResponse?.unscoredScoreRecordCount || 0).toLocaleString() }} 单不展示为具体分值；管理后台有但评分表无记录的
                  {{ (withdrawSummaryResponse?.missingScoringRecordCount || 0).toLocaleString() }} 单也不计入图表。
                </p>
              </div>
              <el-tag type="info" effect="plain">
                有效数值评分 {{ (withdrawSummaryResponse?.numericScoreOrderCount || 0).toLocaleString() }} 单
              </el-tag>
            </div>
            <ChartPanel
              title="评分分值分布"
              :option="withdrawScoreDistributionChartOption"
              :empty="withdrawScoreDistributionEmpty"
              :height="320"
              :active="activeTab === 'withdraw-summary'"
              plain
              :show-title="false"
            />
          </section>

          <section class="surface-card table-card scoring-review-table-card">
            <div class="section-heading">
              <div>
                <h2>操作人提现订单统计</h2>
                <p>
                  {{ withdrawSummarySourceName }} · 共 {{ withdrawSummaryRows.length.toLocaleString() }} 名操作人 ·
                  最近缓存更新：{{ withdrawSummaryLocalUpdatedText }} · 统计范围：{{ withdrawSummaryRangeText }}。
                </p>
              </div>
              <el-tag type="info" effect="plain">{{ withdrawSummaryTimezone }}</el-tag>
            </div>
            <el-table
              v-loading="withdrawSummaryLoading"
              :data="withdrawSummaryRows"
              empty-text="请先选择时间范围并查询提现订单汇总"
            >
              <el-table-column label="操作人" min-width="190" fixed="left">
                <template #default="{ row }">
                  <strong class="operator-selected-total">{{ withdrawSummaryOperatorDisplayName(row) }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="总单数" min-width="116" align="right">
                <template #default="{ row }">
                  <strong class="operator-selected-total">{{ row.totalCount.toLocaleString() }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="≤30评分单数" min-width="146" align="right">
                <template #default="{ row }">{{ row.scoreLte30Count.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="31–60评分单数" min-width="156" align="right">
                <template #default="{ row }">{{ row.score31To60Count.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column label="≥61评分单数" min-width="146" align="right">
                <template #default="{ row }">{{ row.scoreGte61Count.toLocaleString() }}</template>
              </el-table-column>
              <el-table-column
                v-for="status in withdrawSummaryStatusColumns"
                :key="status || 'blank-status'"
                :min-width="142"
                align="right"
              >
                <template #header>{{ withdrawSummaryStatusLabel(status) }}</template>
                <template #default="{ row }">
                  {{ withdrawSummaryStatusCount(row, status).toLocaleString() }}
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
      </el-tab-pane>

    </el-tabs>

    <el-drawer
      v-model="scoringDetailsVisible"
      title="评分审核补充信息"
      direction="rtl"
      size="min(520px, calc(100vw - 24px))"
      class="withdraw-scoring-drawer"
    >
      <template v-if="selectedScoringDetailRow">
        <div class="withdraw-scoring-drawer__heading">
          <div>
            <strong>订单 ID：{{ selectedScoringDetailRow.id }}</strong>
            <span>按评分 Excel 的案件号关联提现订单主键；不会覆盖提现主表字段。</span>
          </div>
          <el-tag
            :type="hasScoringSupplement(selectedScoringDetailRow) ? 'success' : 'info'"
            effect="plain"
          >
            {{ hasScoringSupplement(selectedScoringDetailRow) ? '已匹配评分记录' : '未匹配评分记录' }}
          </el-tag>
        </div>
        <p v-if="!hasScoringSupplement(selectedScoringDetailRow)" class="withdraw-scoring-details__empty">
          当前提现订单没有可关联的评分审核补充记录。
        </p>
        <dl v-else class="withdraw-scoring-details__grid">
          <div>
            <dt>全局硬性条件</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringGlobalGate) }}</dd>
          </div>
          <div>
            <dt>场景审核</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringSceneReview) }}</dd>
          </div>
          <div>
            <dt>评分审核</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringScore) }}</dd>
          </div>
          <div>
            <dt>决断阶段</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringDecisionStage) }}</dd>
          </div>
          <div>
            <dt>最终审核建议</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringFinalSuggestion) }}</dd>
          </div>
          <div>
            <dt>操作结果</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringOperationResult) }}</dd>
          </div>
          <div class="withdraw-scoring-details__wide">
            <dt>摘要</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringSummary) }}</dd>
          </div>
          <div>
            <dt>当前状态</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringCurrentStatus) }}</dd>
          </div>
          <div>
            <dt>审核完成时间</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringReviewedAt) }}</dd>
          </div>
          <div>
            <dt>审核耗时</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringReviewElapsed) }}</dd>
          </div>
          <div>
            <dt>队列中耗时</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringQueueElapsed) }}</dd>
          </div>
          <div>
            <dt>进入队列时间</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringQueueEnteredAt) }}</dd>
          </div>
          <div>
            <dt>退出队列时间</dt>
            <dd>{{ scoringText(selectedScoringDetailRow.scoringQueueExitedAt) }}</dd>
          </div>
        </dl>
      </template>
    </el-drawer>

    <el-dialog
      v-model="manualRefreshDialogVisible"
      title="选择本次提现订单刷新条件"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <p class="manual-refresh-dialog__intro">
        将为 {{ selectedOrderSource?.displayName || '所选盘口' }} 导出指定自然日的提现订单并更新本地缓存；本次选择不修改系统配置的定时导出日期。
      </p>
      <label class="manual-refresh-dialog__field">
        <span>刷新日期范围</span>
        <el-select
          v-model="manualRefreshQueryRange"
        >
          <el-option
            v-for="option in MANUAL_REFRESH_RANGE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </label>
      <p class="manual-refresh-dialog__help">{{ manualRefreshRangeDescription }}</p>
      <el-alert
        title="任务由后台工作进程执行；若该盘口正在导出，本次选择会在当前任务结束后生效。"
        type="info"
        :closable="false"
        show-icon
      />
      <template #footer>
        <el-button :disabled="refreshStarting" @click="manualRefreshDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="refreshStarting"
          @click="startRefresh"
        >
          确认并刷新
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="operatorSummaryChartVisible"
      :title="operatorChartTitle"
      width="min(640px, calc(100vw - 32px))"
      destroy-on-close
    >
      <p class="operator-chart-summary">
        已选状态合计
        <strong>{{ selectedOperatorSummaryItem?.selectedTotal.toLocaleString() || 0 }}</strong>
        单，占比仅按当前选中的状态计算。
      </p>
      <div class="operator-chart-layout">
        <ChartPanel
          title="状态订单占比"
          :option="operatorChartOption"
          :empty="operatorChartEmpty"
          :height="258"
          :active="operatorSummaryChartVisible"
          plain
          :show-title="false"
        />
        <aside v-if="!operatorChartEmpty" class="operator-chart-legend" aria-label="状态占比图例">
          <div v-for="entry in operatorChartData" :key="entry.name" class="operator-chart-legend__item">
            <span class="operator-chart-legend__dot" :style="{ backgroundColor: entry.color }" />
            <span class="operator-chart-legend__label">{{ entry.name }}</span>
            <strong>{{ entry.value.toLocaleString() }} 单</strong>
            <small>{{ operatorChartPercentage(entry.value) }}</small>
          </div>
        </aside>
      </div>
      <template #footer>
        <el-button @click="operatorSummaryChartVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.withdraw-page {
  min-width: 0;
}

.withdraw-tabs {
  min-width: 0;
}

.withdraw-tabs :deep(.el-tabs__header) {
  margin: 0;
}

.withdraw-tabs :deep(.el-tabs__item) {
  height: 52px;
  padding: 0 18px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 800;
}

.withdraw-tabs :deep(.el-tabs__item.is-active) {
  color: var(--teal);
}

.withdraw-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px 3px 0 0;
  background: var(--teal);
}

.withdraw-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--border);
}

.withdraw-tabs :deep(.el-tabs__content) {
  padding-top: 20px;
}

.tab-stack {
  display: grid;
  min-width: 0;
  gap: 20px;
}

.tab-pane-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}

.tab-pane-header h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 20px;
}

.tab-pane-header p {
  margin: 6px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
}

.refresh-state {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 240px;
}

.refresh-state__dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #a0aec0;
  box-shadow: 0 0 0 4px rgba(160, 174, 192, 0.12);
}

.refresh-state__dot.is-live {
  background: var(--teal);
  box-shadow: 0 0 0 4px rgba(42, 157, 143, 0.13);
}

.refresh-state > div {
  display: grid;
  gap: 2px;
}

.refresh-state strong {
  color: var(--ink);
  font-size: 13px;
}

.refresh-state small {
  color: var(--ink-muted);
  font-size: 11px;
}

.query-card {
  overflow: hidden;
}

.query-card__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 14px;
  padding: 18px;
}

.query-field {
  min-width: 0;
  display: grid;
  gap: 7px;
}

.query-field > span {
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
}

.query-field :deep(.el-select) {
  width: 100%;
}

.query-field--time-range {
  grid-column: span 2;
}

.operator-summary-status-field {
  grid-column: 1 / -1;
}

.query-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 18px;
  border-top: 1px solid var(--border);
  background: #f9fbfd;
}

.query-card__footer span {
  color: var(--ink-muted);
  font-size: 12px;
}

.withdraw-channel-chart-card {
  position: relative;
  overflow: hidden;
  padding: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f9fcfe 100%);
}

.withdraw-channel-chart-card::before {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--teal), #75c7bd, #d9f1ed);
  content: '';
}

.withdraw-channel-chart-card__heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}

.withdraw-channel-chart-card__heading h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 20px;
}

.withdraw-channel-chart-card__heading p {
  max-width: 760px;
  margin: 6px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
}

.withdraw-channel-chart-card__controls {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex: 0 0 auto;
}

.withdraw-channel-chart-card__controls label {
  display: grid;
  min-width: 146px;
  gap: 6px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 800;
}

.withdraw-channel-chart-card__controls :deep(.el-select) {
  width: 100%;
}

.metric-card {
  position: relative;
  overflow: hidden;
}

.metric-card::before {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--teal), #76c7bd);
  content: '';
}

.metric-card--orders::before {
  background: linear-gradient(90deg, var(--primary), #5d8fc5);
}

.metric-card strong {
  overflow: hidden;
  font-size: clamp(22px, 2vw, 30px);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scoring-review-metric-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.scoring-review-table-card {
  min-width: 0;
}

.withdraw-score-distribution-card {
  min-width: 0;
}

.withdraw-summary-coverage-alert :deep(.el-alert__title) {
  line-height: 1.65;
}

.query-card__footer-actions {
  display: flex;
  flex: 0 0 auto;
  gap: 10px;
}

.scoring-review-import-field {
  grid-column: span 1;
}

.scoring-review-import-picker {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.scoring-review-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.scoring-review-import-file-name {
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.withdraw-virtual-table {
  width: 100%;
  min-height: 360px;
  height: clamp(360px, calc(100vh - 430px), 720px);
  overflow: hidden;
  border: 1px solid #dce6ee;
  border-radius: 8px;
  background: #ffffff;
  --el-table-border-color: #dce6ee;
  --el-table-header-bg-color: #f5f8fb;
  --el-table-row-hover-bg-color: #f7fbfb;
  --el-table-text-color: #43576a;
  --el-table-header-text-color: #183955;
}

.withdraw-virtual-table :deep(.el-table-v2__header-cell) {
  padding: 0 14px;
  color: #183955;
  font-size: 12px;
  font-weight: 750;
}

.withdraw-virtual-table :deep(.el-table-v2__row-cell) {
  padding: 0 14px;
  color: #43576a;
  font-size: 12px;
}

.withdraw-virtual-table :deep(.el-table-v2__header-cell + .el-table-v2__header-cell),
.withdraw-virtual-table :deep(.el-table-v2__row-cell + .el-table-v2__row-cell) {
  border-left: 1px solid #dce6ee;
}

.withdraw-virtual-table :deep(.el-table-v2__row-cell .el-tag) {
  font-weight: 650;
}

.withdraw-virtual-cell {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.withdraw-scoring-drawer :deep(.el-drawer__body) {
  overflow-y: auto;
  padding: 4px 20px 24px;
}

.withdraw-scoring-drawer__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid #dce9ed;
  border-radius: 10px;
  background: linear-gradient(135deg, #f8fcfd 0%, #f7faff 100%);
}

.withdraw-scoring-drawer__heading > div {
  display: grid;
  gap: 4px;
}

.withdraw-scoring-drawer__heading strong {
  color: var(--ink-strong);
  font-size: 14px;
}

.withdraw-scoring-drawer__heading span,
.withdraw-scoring-details__empty {
  margin: 0;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.65;
}

.withdraw-scoring-details__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
  margin: 0;
}

.withdraw-scoring-details__grid > div {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #e5edf3;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.82);
}

.withdraw-scoring-details__grid dt {
  margin: 0 0 4px;
  color: #718399;
  font-size: 11px;
  font-weight: 700;
}

.withdraw-scoring-details__grid dd {
  overflow-wrap: anywhere;
  margin: 0;
  color: #38546f;
  font-size: 13px;
  line-height: 1.55;
}

.withdraw-scoring-details__grid .withdraw-scoring-details__wide {
  grid-column: span 2;
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px 10px;
  border-top: 1px solid var(--border);
}

.operator-summary-table-card {
  min-width: 0;
}

.operator-name-cell,
.status-column-heading {
  display: grid;
  gap: 3px;
}

.operator-name-cell strong,
.status-column-heading strong,
.operator-selected-total {
  color: var(--ink-strong);
}

.operator-name-cell small,
.status-column-heading small {
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 500;
}

.operator-status-count {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.operator-selected-total {
  font-variant-numeric: tabular-nums;
}

.operator-chart-summary {
  margin: 0 0 14px;
  color: #647e99;
  font-size: 13px;
}

.manual-refresh-dialog__intro,
.manual-refresh-dialog__help {
  margin: 0;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.7;
}

.manual-refresh-dialog__field {
  display: grid;
  gap: 8px;
  margin: 20px 0 8px;
}

.manual-refresh-dialog__field > span {
  color: var(--ink);
  font-size: 13px;
  font-weight: 800;
}

.manual-refresh-dialog__field :deep(.el-select) {
  width: 100%;
}

.manual-refresh-dialog__help {
  min-height: 24px;
  margin-bottom: 16px;
}

.operator-chart-summary strong {
  margin: 0 4px;
  color: #244867;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.operator-chart-layout {
  display: grid;
  grid-template-columns: minmax(220px, 0.9fr) minmax(0, 1.1fr);
  align-items: center;
  gap: 18px;
  min-height: 258px;
}

.operator-chart-legend {
  display: grid;
  gap: 9px;
  min-width: 0;
}

.operator-chart-legend__item {
  display: grid;
  grid-template-columns: 9px minmax(0, 1fr) auto auto;
  align-items: center;
  column-gap: 8px;
  min-height: 42px;
  padding: 8px 10px;
  border: 1px solid #e6eef5;
  border-radius: 10px;
  background: #f8fbfd;
}

.operator-chart-legend__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.operator-chart-legend__label {
  overflow: hidden;
  color: #38546f;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.operator-chart-legend__item strong {
  color: #23425f;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.operator-chart-legend__item small {
  min-width: 39px;
  color: #7890a6;
  font-size: 12px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1100px) {
  .query-card__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scoring-review-metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .operator-summary-status-field {
    grid-column: span 2;
  }

  .withdraw-scoring-details__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .tab-pane-header,
  .header-actions,
  .withdraw-channel-chart-card__heading,
  .withdraw-channel-chart-card__controls {
    align-items: flex-start;
    flex-direction: column;
  }

  .header-actions,
  .withdraw-channel-chart-card__controls {
    width: 100%;
  }

  .withdraw-channel-chart-card__controls label {
    min-width: 0;
    width: 100%;
  }

  .withdraw-channel-chart-card__controls .el-button {
    align-self: flex-start;
  }

  .refresh-state,
  .header-actions .el-button {
    width: 100%;
  }

  .query-card__footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .query-card__footer .el-button {
    width: 100%;
  }

  .query-card__footer-actions {
    width: 100%;
  }

  .query-card__footer-actions .el-button {
    flex: 1 1 0;
  }

  .scoring-review-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 640px) {
  .withdraw-tabs :deep(.el-tabs__item) {
    padding: 0 12px;
  }

  .query-card__grid {
    grid-template-columns: 1fr;
  }

  .query-field--time-range,
  .operator-summary-status-field {
    grid-column: span 1;
  }

  .scoring-review-metric-grid {
    grid-template-columns: 1fr;
  }

  .query-card__footer-actions,
  .scoring-review-import-picker,
  .withdraw-scoring-drawer__heading {
    align-items: stretch;
    flex-direction: column;
  }

  .scoring-review-import-file-name {
    white-space: normal;
  }

  .withdraw-virtual-table {
    min-height: 320px;
    height: min(56vh, 520px);
  }

  .withdraw-scoring-details__grid {
    grid-template-columns: 1fr;
  }

  .withdraw-scoring-details__grid .withdraw-scoring-details__wide {
    grid-column: span 1;
  }

  .table-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }

  .operator-chart-layout {
    grid-template-columns: 1fr;
  }
}
</style>
