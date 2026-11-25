// REAL Gemini through the browser UI (no mocks). Needs the backend with GEMINI_API_KEY + network.
//   node e2e/real-gemini.mjs [baseUrl] [outDir]
// Each assignment question is clicked in a fresh conversation; the displayed structured values
// are compared with the backend's deterministic endpoints (/api/rankings, /api/hubs/{id}/scores).
import { chromium } from '@playwright/test'
import fs from 'node:fs'

const base = process.argv[2] ?? 'http://localhost:5173'
const out = process.argv[3] ?? '../docs/screenshots'
fs.mkdirSync(out, { recursive: true })
const PACE_MS = 8000 // free-tier per-minute quota

const get = async (path) => (await fetch(`${base}${path}`)).json()
const results = []
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`))
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
await page.addInitScript(() => localStorage.clear())

async function ask(question, shot) {
  await page.goto(`${base}/#analyst`, { waitUntil: 'networkidle' })
  const newConv = page.getByRole('button', { name: 'New conversation' })
  if (await newConv.isEnabled()) await newConv.click()
  const t0 = Date.now()
  await page.getByRole('button', { name: question }).click()
  // loading state must appear immediately with the user's message
  await page.waitForSelector('.msg-user.pending', { timeout: 2000 })
  const loadingVisible = await page.isVisible('.waiting')
  const sendDisabled = await page.isDisabled('.btn-send')
  await page.waitForSelector('.answer, .msg-user.failed', { timeout: 180_000 })
  const seconds = (Date.now() - t0) / 1000
  const failed = await page.$('.msg-user.failed')
  if (failed) {
    const text = await failed.textContent()
    await page.screenshot({ path: `${out}/${shot}.png`, fullPage: true })
    return { question, ok: false, seconds, loadingVisible, sendDisabled, error: text }
  }
  await page.waitForTimeout(400)
  const answer = await page.$eval('.answer', (el) => el.innerText)
  await page.screenshot({ path: `${out}/${shot}.png`, fullPage: true })
  return { question, ok: true, seconds, loadingVisible, sendDisabled, answer }
}

const textRows = (sel) =>
  page.$$eval(sel, (trs) => trs.map((tr) => [...tr.querySelectorAll('td,th')].map((c) => c.textContent?.trim())))

// 1 — Midwest winter
{
  const r = await ask('Which hubs in the Midwest are most exposed to winter disruption?', 'real-gemini-1-midwest-winter')
  if (r.ok) {
    const rows = await textRows('.evidence .table tbody tr')
    const exp = await get('/api/rankings?hazard=winter&region=Midwest')
    r.displayed = rows.map((x) => [x[1], x[2]])
    r.expected = exp.ranked.map((e) => [e.display_name.replace(/ Hub$/, ''), e.score_display])
    r.matches = JSON.stringify(r.displayed) === JSON.stringify(r.expected)
  }
  results.push(r)
}
await page.waitForTimeout(PACE_MS)
// 2 — Miami vs Houston
{
  const r = await ask('Compare Miami and Houston in terms of hurricane and flood exposure.', 'real-gemini-2-miami-houston')
  if (r.ok) {
    const rows = await textRows('.evidence .table-scroll .table tbody tr')
    const miami = await get('/api/hubs/miami_fl/scores')
    const houston = await get('/api/hubs/houston_tx/scores')
    r.displayed = rows
    r.expected = ['hurricane', 'flood'].map((h) => [h, miami.hazards[h].score_display, houston.hazards[h].score_display])
    r.matches = r.expected.every(([, m, h]) => rows.some((row) => row.join(' ').includes(m) && row.join(' ').includes(h)))
  }
  results.push(r)
}
await page.waitForTimeout(PACE_MS)
// 3 — Denver snowfall
{
  const r = await ask('What percentage of days in Denver last year had snowfall?', 'real-gemini-3-denver-snow')
  if (r.ok) {
    r.displayed = await page.$$eval('.evidence.stat', (els) => els.map((e) => e.innerText.replace(/\s+/g, ' ')))
    r.matches = r.displayed.some((t) => t.includes('7.14%') && t.includes('26 of 364')) && r.displayed.some((t) => t.includes('12.36%'))
    r.note = 'expected values from the deterministic engine: measurable 7.14% (26/364), trace-inclusive 12.36% (45/364), 2025'
  }
  results.push(r)
}
await page.waitForTimeout(PACE_MS)
// 4 — Dallas
{
  const r = await ask("Why is the Dallas hub's weather disruption risk high?", 'real-gemini-4-dallas')
  if (r.ok) {
    const dallas = await get('/api/hubs/dallas_tx/scores')
    const head = await page.$eval('.evidence .explain-head', (e) => e.textContent?.replace(/\s+/g, ' '))
    r.premiseBanner = await page.$eval('.premise-banner', (e) => e.textContent).catch(() => null)
    r.displayed = head
    r.expected = `${dallas.overall_score_display} ${dallas.overall_band}`
    r.matches = head.includes(dallas.overall_score_display) && head.includes(dallas.overall_band) && !!r.premiseBanner
  }
  results.push(r)
}
await page.waitForTimeout(PACE_MS)
// Desktop docked panel next to the dashboard: ask from Dallas profile
{
  await page.goto(`${base}/#overview`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /^Dallas/ }).first().click()
  await page.getByRole('button', { name: 'Ask the AI Analyst' }).click()
  const docked = await page.isVisible('.dock')
  await page.waitForSelector('.dock .answer, .dock .msg-user.failed', { timeout: 180_000 })
  await page.screenshot({ path: `${out}/real-gemini-5-docked-panel.png` })
  results.push({ question: 'Ask the AI Analyst (from Dallas profile, docked panel)', ok: docked, docked })
}

await browser.close()
const summary = { base, at: new Date().toISOString(), errors, results }
fs.writeFileSync(`${out}/real-gemini-results.json`, JSON.stringify(summary, null, 2))
console.log(JSON.stringify(results.map(({ answer: _answer, ...r }) => r), null, 2))
console.log('console/page errors:', errors)
