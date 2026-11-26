import { describe, expect, it } from 'vitest'
import { ApiError, describeChatError } from './client'

describe('describeChatError — public-demo limits', () => {
  it('explains rate limits, daily cap and busy states with the server detail', () => {
    const rl = describeChatError(new ApiError(429, 'rate_limited', 'Please wait about 30 s.', true))
    expect(rl.title).toMatch(/Too many questions/)
    expect(rl.detail).toBe('Please wait about 30 s.')
    expect(rl.retryable).toBe(true)
    expect(describeChatError(new ApiError(429, 'daily_limit_reached', 'resets at 00:00 UTC', false)).retryable).toBe(false)
    expect(describeChatError(new ApiError(503, 'busy', 'try again', true)).title).toMatch(/busy/)
  })

  it('does not repeat the "still works" hint', () => {
    const d = describeChatError(new ApiError(503, 'llm_unavailable', 'Not available. The dashboard and methodology still work.', false))
    expect(d.detail.match(/still work/g)).toHaveLength(1)
  })
})
