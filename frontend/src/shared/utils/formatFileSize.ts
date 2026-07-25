const UNITS = ['B', 'KB', 'MB', 'GB'] as const

/** "245 KB", "1.3 MB" — used anywhere an attachment's byte size needs to
 * read naturally (chat attachments, future file lists) without a
 * formatting library. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`

  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < UNITS.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${UNITS[unitIndex]}`
}
