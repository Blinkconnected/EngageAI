import { chromium } from '@playwright/test'
const [, , base, email, password, lang = 'en'] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 950 } })
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

await page.goto(base + '/channels', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
console.log('DIR:', await page.evaluate(() => document.documentElement.dir))

await page
  .getByRole('button', { name: /^connect channel$|^توصيل قناة$/i })
  .first()
  .click()
await page.waitForTimeout(2000)
const dialog = page.getByRole('dialog')
const text = await dialog.innerText()
console.log('PICKER:')
for (const line of text.split('\n').filter(Boolean).slice(0, 26)) console.log('   ', line)

// Raw keys are the failure this milestone exists to prevent.
const raw = text.match(
  /\b(?:connect|certification|diagnostics|wizard|picker|lifecycle|check)\.[a-zA-Z0-9_.]+/g,
)
console.log('RAW KEYS IN PICKER:', raw ? [...new Set(raw)] : 'none')
await page.screenshot({ path: `.visual-check/wizard-picker-${lang}.png`, fullPage: true })

// Telegram: the full no-OAuth flow.
await page
  .locator('[role="dialog"] .MuiCard-root', { hasText: /Telegram/i })
  .first()
  .click()
await page.waitForTimeout(2500)
const wiz = page.getByRole('dialog')
console.log('\nWIZARD (telegram):')
for (const line of (await wiz.innerText()).split('\n').filter(Boolean).slice(0, 20))
  console.log('   ', line)
await page.screenshot({ path: `.visual-check/wizard-form-${lang}.png`, fullPage: true })

// A bad token -> the checklist, in the customer's language.
const secret = wiz.locator('input[type="password"]').first()
if (await secret.count()) {
  await secret.fill('123:FAKE')
  await wiz.getByRole('button', { name: /continue|متابعة/i }).click()
  await page.waitForTimeout(3000)
  const after = await wiz.innerText()
  console.log('\nCHECKLIST:')
  for (const line of after.split('\n').filter(Boolean).slice(0, 16)) console.log('   ', line)
  const rawAfter = after.match(
    /\b(?:connect|certification|diagnostics|wizard|picker|lifecycle|check)\.[a-zA-Z0-9_.]+/g,
  )
  console.log('RAW KEYS IN CHECKLIST:', rawAfter ? [...new Set(rawAfter)] : 'none')
  await page.screenshot({ path: `.visual-check/wizard-checklist-${lang}.png`, fullPage: true })
}
console.log('\nERRORS:', errors.length ? errors.slice(0, 3).join(' | ') : 'none')
await browser.close()
