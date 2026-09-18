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
  if (result?.publicationState === 'COMPLETED' && result.configurations.some(item => item.state !== 'MATCHED')) return '配置待核对'
  if (hasError) return '下载异常'
  return result?.publicationState === 'COMPLETED' ? '待下载兑换码' : '等待发布核验'
}
