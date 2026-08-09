import { chromium } from '@playwright/test'
const [, , base, email, password, convId] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1680, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)

const takeover = page.getByRole('button', { name: /take over from ai/i })
console.log('takeover button visible:', await takeover.isVisible().catch(() => false))
await page.screenshot({ path: '.visual-check/takeover-before.png' })

await takeover.click()
await page.waitForTimeout(2500)
console.log('after click — takeover gone:', !(await takeover.isVisible().catch(() => false)))
console.log(
  'after click — Ask AI back:',
  await page
    .getByRole('button', { name: /ask ai to reply/i })
    .isVisible()
    .catch(() => false),
)
console.log('errors:', errors.length ? errors.join('; ') : 'none')
await page.screenshot({ path: '.visual-check/takeover-after.png' })
await browser.close()
