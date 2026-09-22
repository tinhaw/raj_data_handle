export interface PublicationVerification {
  remotePublishTaskId: string
  remoteStatus: number | null
  publicationState: 'WAITING' | 'RUNNING' | 'FAILED' | 'COMPLETED' | 'CANCELLED' | 'UNKNOWN'
  canCancel: boolean
  configurations: Array<{ configurationId: string; state: 'MATCHED' | 'MISSING' | 'MISMATCH' | 'UNKNOWN' }>
  configurationError?: string
  checkedAt: string
}
export function publicationLabel(result?: PublicationVerification) {
  const labels = { WAITING: '等待远端执行', RUNNING: '远端执行中', FAILED: '远端发布异常', COMPLETED: '发布完成', CANCELLED: '远端已撤销', UNKNOWN: '发布待核验' }
  return result ? labels[result.publicationState] : '发布待核验'
}
export function acquisitionLabel(imported: boolean, hasError: boolean, result?: PublicationVerification) {
  if (imported) return '兑换码已入库'
  if (result?.publicationState === 'COMPLETED' && result.configurations.some(item => item.state === 'MISSING')) return '远端未找到配置'
  if (result?.publicationState === 'COMPLETED' && result.configurations.some(item => item.state !== 'MATCHED')) return '配置待核对'
  if (hasError) return '下载异常'
  return result?.publicationState === 'COMPLETED' ? '待下载兑换码' : '等待发布核验'
}

export function configurationVerificationSummary(result?: PublicationVerification, error?: string,
  issues: Array<{ remoteConfigurationId?: string; remoteConfigurationName?: string; remoteConfigurationRemark?: string }> = []) {
  if (error) return `本次查询失败：${error}。尚未发起下载，请稍后刷新状态。`
  if (!result) return '正在查询远端发布任务和兑换码配置…'
  if (result.publicationState !== 'COMPLETED') return `当前状态：${publicationLabel(result)}。尚未确认发布完成，暂不能下载。`
  if (result.configurationError) return `发布已完成，但配置查询失败：${result.configurationError}。请先恢复配置查询。`
  const missing = result.configurations.filter(item => item.state === 'MISSING')
  const mismatch = result.configurations.filter(item => item.state === 'MISMATCH')
  const unknown = result.configurations.filter(item => item.state === 'UNKNOWN')
  const missingDescriptions = missing.map((item) => {
    const issue = issues.find((candidate) => candidate.remoteConfigurationId === item.configurationId)
    return `${issue?.remoteConfigurationName || '名称未记录'}（备注：${issue?.remoteConfigurationRemark || '未记录'}；原 ID：${item.configurationId}）`
  })
  const problems = [
    missing.length ? `${missing.length} 个配置在当前远端列表中未找到：${missingDescriptions.join('、')}` : '',
    mismatch.length ? `${mismatch.length} 个配置的兑换码组或数量不匹配` : '',
    unknown.length ? `${unknown.length} 个配置尚未完成核验` : '',
  ].filter(Boolean)
  return problems.length
    ? `发布已完成；${problems.join('；')}。这些配置暂不能下载。刷新状态只会重新查询，不会恢复配置或重新发布。请核对原配置是否仍在远端后台；不能直接用同日期的新配置替代。`
    : '发布已完成，关联配置已匹配，可以下载兑换码。'
}
