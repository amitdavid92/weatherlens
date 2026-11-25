import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { deferred, fixtures, json, mockApi } from './test/mockApi'

beforeEach(() => {
  localStorage.clear()
  window.location.hash = ''
})
afterEach(() => vi.unstubAllGlobals())

describe('Overview dashboard', () => {
  it('renders KPIs and the ranking from API data, with backend display strings', async () => {
    mockApi()
    render(<App />)
    const kpis = await screen.findByRole('region', { name: 'Portfolio summary' })
    const o = fixtures.overview
    expect(within(kpis).getByText(String(o.counts.hubs))).toBeInTheDocument()
    expect(within(kpis).getByText(o.highest!.score_display)).toBeInTheDocument()
    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(fixtures.rankings.ranked.length)
    // Denver near the Low/Moderate boundary keeps the backend's band-safe display
    const denver = rows.find((r) => r.textContent?.includes('Denver'))!
    expect(denver).toHaveTextContent('39.98')
    expect(denver).toHaveTextContent('Low')
    expect(denver).not.toHaveTextContent('40.0')
    // Dallas: rank 2 but Moderate
    const dallas = rows.find((r) => r.textContent?.includes('Dallas'))!
    expect(dallas).toHaveTextContent('2')
    expect(dallas).toHaveTextContent('Moderate')
  })

  it('shows Miami as partial and not ranked overall, but ranked for hurricane', async () => {
    const { calls } = mockApi()
    render(<App />)
    const notRanked = await screen.findByText('Not ranked: incomplete data')
    const block = notRanked.parentElement!
    expect(within(block).getByText('Miami')).toBeInTheDocument()
    expect(within(block).getByText(/Partial data/)).toBeInTheDocument()
    expect(within(block).getByText(/too few valid observations/)).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).queryByText('Miami')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Hurricane' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/rankings?hazard=hurricane')).toBe(true))
    await waitFor(() => {
      const first = within(screen.getByRole('table')).getAllByRole('row')[1]
      expect(first).toHaveTextContent('Miami')
    })
  })

  it('opens a hub profile with completeness, sources and an Ask action', async () => {
    mockApi()
    render(<App />)
    const btn = await screen.findAllByRole('button', { name: 'Miami' })
    await userEvent.click(btn[0])
    const profile = await screen.findByRole('region', { name: 'Miami Hub profile' })
    expect(within(profile).getByText(/Overall score is partial/)).toBeInTheDocument()
    expect(await within(profile).findByText('Data completeness')).toBeInTheDocument()
    expect(within(profile).getAllByText('Below 90%').length).toBeGreaterThan(0)
    expect(within(profile).getByText('FEMA National Risk Index')).toBeInTheDocument()
    expect(within(profile).getByRole('button', { name: /Ask the AI Analyst/ })).toBeEnabled()
  })

  it('renders an error state when analytics are unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ error: 'data_unavailable', detail: 'Data unavailable' }, 503)))
    render(<App />)
    expect(await screen.findByText('Analytical data is unavailable')).toBeInTheDocument()
  })
})

describe('AI Analyst', () => {
  const goToAnalyst = async () => {
    await userEvent.click(await screen.findByRole('button', { name: 'AI Analyst' }))
  }

  it('shows the message immediately, a loading state, blocks duplicates, then renders structured results', async () => {
    const d = deferred<Response>()
    const { fetchMock } = mockApi({ chat: () => d.promise })
    render(<App />)
    await goToAnalyst()
    await userEvent.click(await screen.findByRole('button', { name: 'What percentage of days in Denver last year had snowfall?' }))
    expect(screen.getByText('What percentage of days in Denver last year had snowfall?')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('The AI Analyst is working on your question')
    expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled()
    // pressing Enter in the composer while a request is pending does not send another request
    await userEvent.type(screen.getByRole('textbox'), 'Compare Miami and Houston{Enter}')
    expect(fetchMock.mock.calls.filter(([u]) => u === '/api/chat')).toHaveLength(1)
    expect(screen.getByRole('textbox')).toHaveValue('Compare Miami and Houston') // draft kept, not lost

    d.resolve(json(fixtures.chatDenver))
    const answer = await screen.findByRole('article', { name: 'AI Analyst answer' })
    const stats = fixtures.chatDenver.analysis.weather_stats
    for (const s of stats) expect(answer).toHaveTextContent(s.value_display!)
    expect(answer).toHaveTextContent(`${stats[0].event_days} of ${stats[0].coverage.valid_days} valid days`)
    expect(answer).toHaveTextContent('Facts verified')
    expect(answer).toHaveTextContent('NOAA GHCN-Daily')
    expect(answer.querySelector('script')).toBeNull()
  })

  it('renders ranking evidence from the structured payload and sends follow-ups in the same session', async () => {
    const { calls } = mockApi({ chat: () => json(fixtures.chatMidwest) })
    render(<App />)
    await goToAnalyst()
    await userEvent.click(await screen.findByRole('button', { name: 'Which hubs in the Midwest are most exposed to winter disruption?' }))
    const answer = await screen.findByRole('article', { name: 'AI Analyst answer' })
    const ranked = fixtures.chatMidwest.analysis.rankings[0].ranked
    const rows = within(answer).getAllByRole('row')
    expect(rows[0]).toHaveTextContent(ranked[0].display_name.replace(/ Hub$/, ''))
    expect(rows[0]).toHaveTextContent(ranked[0].score_display!)
    const follow = fixtures.chatMidwest.follow_up_suggestions[0]
    await userEvent.click(within(answer).getByRole('button', { name: follow }))
    await waitFor(() => expect(calls.filter((c) => c.url === '/api/chat')).toHaveLength(2))
    const second = calls.filter((c) => c.url === '/api/chat')[1].body as { session_id?: string }
    expect(second.session_id).toBe(fixtures.chatMidwest.session_id)
  })

  it('shows a friendly 429 error and retries without duplicating the turn', async () => {
    let n = 0
    const { calls } = mockApi({
      chat: () =>
        ++n === 1
          ? json({ error: 'llm_quota_exceeded', detail: 'Gemini quota or rate limit exceeded (HTTP 429)', retryable: true }, 429)
          : json(fixtures.chatDenver),
    })
    render(<App />)
    await goToAnalyst()
    const q = 'What percentage of days in Denver last year had snowfall?'
    await userEvent.click(await screen.findByRole('button', { name: q }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The AI provider is rate-limiting requests')
    await userEvent.click(within(alert).getByRole('button', { name: /Retry/ }))
    await screen.findByRole('article', { name: 'AI Analyst answer' })
    expect(screen.getAllByText(q)).toHaveLength(1) // one user turn, not two
    expect(calls.filter((c) => c.url === '/api/chat').map((c) => (c.body as { message: string }).message)).toEqual([q, q])
  })

  it('handles network errors', async () => {
    mockApi({ chat: () => Promise.reject(new TypeError('Failed to fetch')) })
    render(<App />)
    await goToAnalyst()
    await userEvent.click(await screen.findByRole('button', { name: 'What percentage of days in Denver last year had snowfall?' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection problem')
  })

  it('makes missing LLM configuration explicit while deterministic views keep working', async () => {
    mockApi({ llmAvailable: false })
    render(<App />)
    expect(await screen.findByText(/AI agent unavailable/)).toBeInTheDocument()
    expect(await screen.findByText(/Analytics available/)).toBeInTheDocument()
    await goToAnalyst()
    expect(await screen.findByText('AI Analyst unavailable')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'What percentage of days in Denver last year had snowfall?' })).toBeDisabled()
  })
})
