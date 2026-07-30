import { chromium } from '@playwright/test'
const [, , base, email, password, lang = 'en'] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
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
if (lang !== 'en') {
  await page.evaluate((l) => {
    localStorage.setItem('blinkengage.language', l)
    localStorage.setItem('blinkengage.direction', l === 'ar' ? 'rtl' : 'ltr')
  }, lang)
}
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in|تسجيل الدخول/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

// --- The platform console no longer offers pricing ---------------------
await page.goto(base + '/platform', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const platformNav = await page.locator('nav').first().innerText()
console.log('PLATFORM NAV:', JSON.stringify(platformNav.replace(/\n/g, ' | ')))
console.log('DIR:', await page.evaluate(() => document.documentElement.dir))

// --- Cross into the billing console ------------------------------------
await page.locator('nav a', { hasText: /Billing Console|وحدة تحكم الفوترة/ }).first().click()
await page.waitForURL(/\/platform\/billing/, { timeout: 10000 })
await page.waitForTimeout(1500)
console.log('URL:', new URL(page.url()).pathname)
console.log('HEADER:', JSON.stringify((await page.locator('header').innerText()).replace(/\n/g, ' | ')))
const priceTable = page.locator('table[aria-label="Effective pricing"], table[aria-label="التسعير الساري"]')
const rows = await priceTable.locator('tbody tr').allInnerTexts()
console.log('CURRENCY SELECTOR:', await page.getByLabel(/^Currency|^العملة/).count())
console.log('PRICING ROWS:')
for (const r of rows) console.log('  ', JSON.stringify(r.replace(/\n/g, ' | ')))
await page.screenshot({ path: `.visual-check/billing-console-${lang}.png`, fullPage: true })

// --- The editor: flat, then tiered, previewed by the server ------------
const row = priceTable.locator('tbody tr', { hasText: /Billable message|رسالة قابلة للفوترة/ }).first()
await row.getByRole('button', { name: /edit|تعديل/i }).click()
const dialog = page.getByRole('dialog')
await dialog.waitFor()
await page.waitForTimeout(1800)
const previewFlat = await dialog.locator('[data-testid="pricing-preview"]').innerText()
console.log('PREVIEW (flat):', JSON.stringify(previewFlat.replace(/\n/g, ' | ')))

// Switch to volume tiers and check the table appears seeded with the
// current rate, with an open-ended last step.
await dialog.getByRole('combobox').first().click()
await page.locator('[role="option"][data-value="volume_tier"]').click()
await page.waitForTimeout(500)
const tierTable = dialog.locator('table')
console.log('TIER TABLE:', JSON.stringify((await tierTable.innerText()).replace(/\n/g, ' | ')))
await dialog.getByRole('combobox').first().click()
await page.waitForTimeout(400)
console.log(
  'MODELS OFFERED:',
  JSON.stringify(
    await page.locator('[role="option"]').evaluateAll((els) =>
      els.map((e) => e.textContent.trim() + (e.getAttribute('aria-disabled') === 'true' ? ' [disabled]' : '')),
    ),
  ),
)
await page.keyboard.press('Escape')
await page.waitForTimeout(300)

// Build the shipped three-step table and let the server price it.
await dialog.getByRole('button', { name: /Add a step|إضافة/i }).click()
await dialog.getByRole('button', { name: /Add a step|إضافة/i }).click()
await page.waitForTimeout(300)
const upTos = dialog.locator('table tbody tr input').nth(0)
const bounds = await dialog.locator('table tbody tr').count()
console.log('TIER ROWS:', bounds)
const inputs = dialog.locator('table tbody tr')
for (let i = 0; i < bounds - 1; i++) {
  const cells = inputs.nth(i).locator('input')
  await cells.nth(0).fill(['200', '500'][i] ?? '1000')
  await cells.nth(1).fill(['0.002', '0.0015'][i] ?? '0.001')
}
await inputs
  .nth(bounds - 1)
  .locator('input')
  .first()
  .fill('0.001')
await upTos.click()
await page.waitForTimeout(2000)
const previewTiered = await dialog.locator('[data-testid="pricing-preview"]').innerText()
console.log('PREVIEW (tiered):', JSON.stringify(previewTiered.replace(/\n/g, ' | ')))
console.log(
  'HISTORY NOTE SHOWN:',
  /never re-rates|لا يعيد تسعير/.test(await dialog.innerText()),
)
await page.screenshot({ path: `.visual-check/pricing-editor-${lang}.png`, fullPage: true })

// A refusal from the server, shown while typing rather than on save.
await inputs.nth(0).locator('input').nth(0).fill('900')
await page.waitForTimeout(2000)
console.log(
  'SERVER REFUSAL SHOWN:',
  JSON.stringify(
    (await dialog.locator('[data-testid="pricing-preview"]').innerText()).replace(/\n/g, ' | '),
  ),
)

await dialog.getByRole('button', { name: /Cancel|إلغاء/i }).click()

// --- A company's billing page moved with pricing -----------------------
await page.goto(base + '/platform', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
await page.locator('[role="row"] a, tbody a').filter({ hasText: /^Billing$|^الفواتير$/ }).first().click()
await page.waitForTimeout(2000)
console.log('COMPANY BILLING URL:', new URL(page.url()).pathname)
console.log(
  'COMPANY BILLING IN BILLING CONSOLE:',
  /Billing Console|وحدة تحكم الفوترة/.test(await page.locator('header').innerText()),
)

console.log('ERRORS:', errors.length ? errors.join(' | ') : 'none')
await browser.close()
