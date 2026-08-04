import { describe, expect, it } from 'vitest'
import { formatCountdown, relativeTime } from './format'

describe('AeroOS time formatting', () => {
  const now = Date.parse('2026-07-22T10:00:00Z')

  it('formats the mist countdown and clamps elapsed schedules', () => {
    expect(formatCountdown('2026-07-22T10:05:09Z', now)).toBe('05:09')
    expect(formatCountdown('2026-07-22T09:59:00Z', now)).toBe('00:00')
    expect(formatCountdown(null, now)).toBe('--:--')
  })

  it('formats capture age deterministically', () => {
    expect(relativeTime('2026-07-22T09:59:40Z', now)).toBe('just now')
    expect(relativeTime('2026-07-22T09:47:00Z', now)).toBe('13 min ago')
  })
})
