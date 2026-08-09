import { chromium } from '@playwright/test'
const base = process.argv[2] || 'http://localhost:5173'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text().slice(0, 200))
})
// Seed an expired/garbage session the way a returning user would have one
await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
await page.evaluate(() => {
  localStorage.setItem('blinkengage.refreshToken', 'eyJhbGciOiJIUzI1NiJ9.invalid.invalid')
})
await page.goto(base + '/', { waitUntil: 'networkidle', timeout: 30000 })
await page.waitForTimeout(3000)
console.log('URL AFTER LOAD:', page.url())
console.log(
  'VISIBLE:',
  JSON.stringify(
    (
      await page
        .locator('body')
        .innerText()
        .catch(() => '')
    ).slice(0, 300),
  ),
)
console.log('ERRORS:', errors.length ? '\n  ' + errors.slice(0, 6).join('\n  ') : 'none')
await page.screenshot({ path: '.visual-check/stale.png' })
await browser.close()
