export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'medium',
    hour12: false,
  }).format(new Date(value))
}

const statusNames: Record<string, string> = {
  awaiting_confirmation: '待确认',
  queued: '排队中',
  validating: '校验中',
  fetching_remote: '抓取远端',
  comparing: '比对中',
  rechecking: '精确复查',
  cancelling: '取消中',
  cancelled: '已取消',
  completed: '已完成',
  failed: '失败',
  comparison_incomplete: '不完整',
}

export function statusLabel(value: string): string {
  return statusNames[value] || value
}

const resultStatusNames: Record<string, string> = {
  matched: '已匹配',
  matched_after_recheck: '复查后匹配',
  amount_mismatch: '金额不一致',
  order_reference_conflict: '订单号冲突',
  duplicate_payment_conflict: '支付数据重复冲突',
  invalid_payment_row: '支付数据无效',
  remote_status_not_success: '远端状态异常',
  candidate_missing: '候选遗漏',
  confirmed_missing: '确认遗漏',
  recheck_inconclusive: '复查不确定',
}

export function resultStatusLabel(value: string): string {
  return resultStatusNames[value] || value
}

export function statusTagType(
  value: string,
): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (value === 'completed') return 'success'
  if (value === 'failed' || value === 'comparison_incomplete') return 'danger'
  if (value === 'cancelled') return 'info'
  if (value === 'awaiting_confirmation' || value === 'queued') return 'warning'
  return 'primary'
}
