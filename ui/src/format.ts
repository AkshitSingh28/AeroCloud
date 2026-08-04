export function formatCountdown(timestamp: string | null | undefined, now = Date.now()): string {
  if (!timestamp) return '--:--'
  const total = Math.max(0, Math.floor((new Date(timestamp).getTime() - now) / 1000))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

export function relativeTime(value: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - new Date(value).getTime()) / 60000))
  return minutes < 1 ? 'just now' : `${minutes} min ago`
}
