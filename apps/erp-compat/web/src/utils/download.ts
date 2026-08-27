import type { DownloadFile } from '@/api/types'

/** Trigger a browser download without keeping an object URL alive after use. */
export function saveDownloadedFile(file: DownloadFile) {
  const url = URL.createObjectURL(file.blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = file.filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}
