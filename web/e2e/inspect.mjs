// Real-browser inspection (Chromium via Playwright) of the running app. No LLM calls.
//   node e2e/inspect.mjs [baseUrl] [outDir]
// Checks: console errors, page errors, failed requests, horizontal overflow, key content.
import { chromium } from '@playwright/test'
import fs from 'node:fs'

const base = process.argv[2] ?? 'http://localhost:5173'
const out = process.argv[3] ?? '../docs/screenshots'
fs.mkdirSync(out, { recursive: true })

const VIEWPORTS = [
  { name: 'desktop-1440', width: 1440, height: 900 },
  { name: 'laptop-1024', width: 1024, height: 768 },
  { name: 'mobile-390', width: 390, height: 844 },
]

const browser = await chromium.launch()
const results = []
for (const vp of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2 })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`))
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`))
  await page.addInitScript(() => localStorage.clear())

  const overflow = async () =>
    page.evaluate(() => {
      const w = document.documentElement.clientWidth
      const offenders = [...document.querySelectorAll('body *')]
        .filter((el) => el.getBoundingClientRect().right > w + 1 && getComputedStyle(el).position !== 'fixed')
        .filter((el) => !el.closest('.table-scroll, .segmented, .tabs, .chat-log'))
        .slice(0, 5)
        .map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].join('.')}`)
      return { scrollWidth: document.documentElement.scrollWidth, clientWidth: w, offenders }
    })

  // Overview
  await page.goto(`${base}/#overview`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.ranking-table tbody tr')
  await page.waitForSelector('.usmap-hub')
  const kpis = await page.$$eval('.kpi', (els) => els.map((e) => e.textContent?.replace(/\s+/g, ' ').trim()))
  const rows = await page.$$eval('.ranking-table tbody tr', (trs) =>
    trs.map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent?.trim())),
  )
  const hubDots = await page.$$eval('.usmap-hub', (g) => g.length)
  const ovOverflow = await overflow()
  await page.screenshot({ path: `${out}/${vp.name}-overview.png`, fullPage: vp.width < 600 })

  // select Denver (boundary case) and Miami (partial)
  await page.getByRole('button', { name: /^Denver/ }).first().click()
  await page.waitForSelector('.profile .table')
  const denverProfile = await page.$eval('.profile-score', (e) => e.textContent?.replace(/\s+/g, ' ').trim())
  await page.screenshot({ path: `${out}/${vp.name}-overview-denver.png`, fullPage: true })
  await page.getByRole('button', { name: /^Miami/ }).first().click()
  await page.waitForSelector('.profile .callout-warn')
  const miamiProfile = await page.$eval('.profile-score', (e) => e.textContent?.replace(/\s+/g, ' ').trim())
  const profOverflow = await overflow()
  await page.screenshot({ path: `${out}/${vp.name}-overview-miami.png`, fullPage: true })

  // hurricane filter: Miami must be ranked
  await page.getByRole('tab', { name: 'Hurricane' }).click()
  await page.waitForFunction(() => document.querySelector('.ranking-table tbody tr td:nth-child(2)')?.textContent?.includes('Miami'))
  const hurricaneTop = await page.$eval('.ranking-table tbody tr td:nth-child(2)', (e) => e.textContent?.trim())

  // Methodology
  await page.goto(`${base}/#methodology`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.read h1')
  const methOverflow = await overflow()
  await page.screenshot({ path: `${out}/${vp.name}-methodology.png`, fullPage: true })

  // Analyst (empty state)
  await page.goto(`${base}/#analyst`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.examples')
  const chatOverflow = await overflow()
  await page.screenshot({ path: `${out}/${vp.name}-analyst-empty.png` })

  results.push({
    viewport: vp.name,
    kpis,
    rankingRows: rows.length,
    firstRow: rows[0],
    hubDots,
    denverProfile,
    miamiProfile,
    hurricaneTop,
    overflow: { overview: ovOverflow, profile: profOverflow, methodology: methOverflow, analyst: chatOverflow },
    errors,
  })
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${out}/inspect-results.json`, JSON.stringify(results, null, 2))
console.log(JSON.stringify(results, null, 2))
