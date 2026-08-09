import { chromium } from '@playwright/test'
const [, , base, email, password] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1680, height: 900 } })
page.on('console', (m) => {
  if (m.type() === 'error') console.log('CONSOLE:', m.text().slice(0, 200))
})
page.on('response', (r) => {
  if (r.url().includes('/auth/login')) console.log('LOGIN RESPONSE:', r.status())
})
await page.goto(base + '/login', { waitUntil: 'networkidle' })
const inputs = await page.locator('input').count()
console.log('inputs found:', inputs)
await page.locator('input[type="email"], input[name="email"], input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForTimeout(4000)
console.log('URL:', page.url())
console.log('BODY:', (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 300))
await browser.close()
