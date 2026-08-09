// Verifies the tenant billing dashboard against the running stack.
//
// Checks the things a screenshot alone would not prove: that the live refresh
// really re-requests the estimate, that switching the projection method asks
// the server rather than recomputing in the browser, that the chart windows
// refetch, and that the page holds together on a phone and in Arabic/RTL.
import { chromium } from '@playwright/test'

const [, , base, email, password] = process.argv
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

const errors = []
const requests = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text())
})
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
page.on('request', (r) => {
  const url = new URL(r.url())
  if (url.pathname.startsWith('/api/v1/billing')) {
    requests.push(url.pathname.replace('/api/v1', '') + (url.search || ''))
  }
})

await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

// --- The sidebar entry exists and routes there -----------------------
const navLink = page.getByRole('link', { name: /^billing$/i }).first()
await navLink.waitFor({ timeout: 10000 })
console.log('SIDEBAR BILLING LINK:', (await navLink.count()) > 0)
await navLink.click()
await page.waitForURL(/\/billing$/, { timeout: 10000 })
await page.waitForTimeout(2500)

const text = await page.locator('body').innerText()
const has = (needle) => text.includes(needle)
console.log('FIRST PAINT REQUESTS:', JSON.stringify(requests))

// --- The five questions ---------------------------------------------
for (const [label, cardId] of [
  ['Spent today', 'card-today'],
  ['This billing period', 'card-mtd'],
  ['Projected invoice', 'card-projection'],
  ['Outstanding balance', 'card-outstanding'],
]) {
  const card = page.getByTestId(cardId)
  console.log(
    `CARD ${cardId}:`,
    JSON.stringify((await card.innerText()).replace(/\n/g, ' | ')),
    'label ok:',
    has(label),
  )
}
console.log(
  'STATUS BANNER:',
  JSON.stringify((await page.getByTestId('billing-status').innerText()).replace(/\n/g, ' | ')),
)
console.log('LIVE CHIP:', JSON.stringify(await page.getByTestId('live-chip').innerText()))
console.log(
  'PROJECTION CARD:',
  JSON.stringify((await page.getByTestId('projection-card').innerText()).replace(/\n/g, ' | ')),
)

// --- Estimates and invoices are visibly separate ---------------------
console.log('ISSUED HEADING:', has('Issued invoices'))
console.log('OFFICIAL WORDING:', has('official documents'))
console.log('ESTIMATE WORDING:', has('Estimated, updates through the day'))

// --- The chart, and its windows --------------------------------------
const chartBars = await page.locator('svg rect').count()
console.log('CHART RECTS:', chartBars)
requests.length = 0
await page.getByRole('button', { name: '7 days' }).click()
await page.waitForTimeout(1200)
console.log('AFTER 7d CLICK:', JSON.stringify(requests))
await page.getByRole('button', { name: 'This period' }).click()
await page.waitForTimeout(1200)
console.log('AFTER PERIOD CLICK:', JSON.stringify(requests))

// --- A different projection method is a question for the server ------
requests.length = 0
await page.getByRole('combobox', { name: /projection method/i }).click()
await page.getByRole('option', { name: /Linear Projection/i }).click()
await page.waitForTimeout(1500)
console.log('AFTER METHOD CHANGE:', JSON.stringify(requests))
console.log(
  'PROJECTION AFTER CHANGE:',
  JSON.stringify((await page.getByTestId('projection-card').innerText()).replace(/\n/g, ' | ')),
)

// --- Invoice lines load on demand ------------------------------------
requests.length = 0
const toggle = page.getByRole('button', { name: /show what invoice/i }).first()
if ((await toggle.count()) > 0) {
  await toggle.click()
  await page.waitForTimeout(1200)
  console.log('AFTER EXPAND:', JSON.stringify(requests))
}

await page.screenshot({ path: '.visual-check/billing-dashboard.png', fullPage: true })

// --- Live refresh: the estimate re-requests itself -------------------
// Long, because the interval is 45s and the whole point is that a customer
// does not have to reload. Watched rather than assumed.
requests.length = 0
console.log('WAITING 50s FOR THE LIVE REFRESH…')
await page.waitForTimeout(50000)
console.log('POLLED REQUESTS:', JSON.stringify(requests))

// --- Mobile ----------------------------------------------------------
const phone = await context.newPage()
await phone.setViewportSize({ width: 390, height: 844 })
await phone.goto(base + '/billing', { waitUntil: 'networkidle' })
await phone.waitForTimeout(2500)
const overflow = await phone.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
)
console.log('MOBILE HORIZONTAL OVERFLOW:', overflow)
await phone.screenshot({ path: '.visual-check/billing-dashboard-mobile.png', fullPage: true })

// --- Arabic / RTL / dark --------------------------------------------
await phone.evaluate(() => {
  localStorage.setItem('blinkengage.language', 'ar')
  localStorage.setItem('blinkengage.themeMode', 'dark')
  localStorage.setItem('blinkengage.direction', 'rtl')
})
await phone.setViewportSize({ width: 1440, height: 1000 })
await phone.goto(base + '/billing', { waitUntil: 'networkidle' })
await phone.waitForTimeout(2500)
const dir = await phone.evaluate(() => getComputedStyle(document.documentElement).direction)
const arabic = await phone.locator('body').innerText()
console.log('RTL DIR:', dir)
console.log('ARABIC HEADING PRESENT:', arabic.includes('الفواتير'))
console.log(
  'UNTRANSLATED KEYS:',
  /\b(page|overview|usage|projection|chart|invoices|prices|configuration)\.[a-zA-Z]+/.test(arabic),
)
await phone.screenshot({ path: '.visual-check/billing-dashboard-rtl.png', fullPage: true })

console.log('ERRORS:', JSON.stringify(errors))
await browser.close()
