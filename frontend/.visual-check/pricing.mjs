import { chromium } from '@playwright/test'
const [, , base, email, password] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })
const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text())
})
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
await page.evaluate(() => {
  sessionStorage.clear()
  localStorage.clear()
})
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

await page.goto(base + '/platform/pricing', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
const rows = await page.locator('table').first().locator('tbody tr').allInnerTexts()
console.log('PRICING ROWS:')
for (const r of rows) console.log('  ', JSON.stringify(r.replace(/\n/g, ' | ')))
console.log(
  'WARNS ABOUT UNPRICED:',
  (await page.locator('body').innerText()).includes('No price is configured'),
)

// Edit the conversation price and confirm it persists + audits.
const row = page.locator('tbody tr', { hasText: 'Conversation' }).first()
await row.getByRole('button', { name: /edit/i }).click()
const dialog = page.getByRole('dialog')
const input = dialog.getByLabel(/price per unit/i)
await input.fill('0.0575')
await dialog.getByLabel(/reason/i).fill('Browser verification')
await dialog.getByRole('button', { name: /save price/i }).click()
await page.waitForTimeout(1800)
console.log('DIALOG CLOSED:', (await dialog.count()) === 0)

await page.reload({ waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const after = await page.locator('tbody tr', { hasText: 'Conversation' }).first().innerText()
console.log('AFTER RELOAD:', JSON.stringify(after.replace(/\n/g, ' | ')))
const tables = page.locator('table')
const historyText = await tables.nth(1).innerText()
console.log('HISTORY HAS THE CHANGE:', /Browser verification/.test(historyText))
console.log('HISTORY SHOWS OLD -> NEW:', /0\.05.*→.*0\.0575/s.test(historyText))
await page.screenshot({ path: '.visual-check/pricing.png', fullPage: true })
console.log('ERRORS:', errors.length ? errors.join(' | ') : 'none')
await browser.close()
