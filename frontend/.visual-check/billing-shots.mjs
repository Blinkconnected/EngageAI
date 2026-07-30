// Screenshots of the whole billing page. The app scrolls an inner container,
// so `fullPage` only ever captures the viewport — a tall viewport is what
// actually shows the page end to end.
import { chromium } from '@playwright/test'

const [, , base, email, password] = process.argv
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1500, height: 2600 } })
const page = await context.newPage()

await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.goto(base + '/billing', { waitUntil: 'networkidle' })
await page.waitForTimeout(3000)
await page.screenshot({ path: '.visual-check/billing-full.png' })

// Scrolled to the estimates/invoices boundary — the one line on the page that
// must never blur.
await page.evaluate(() => {
  const heading = [...document.querySelectorAll('h2')].find((h) =>
    /issued invoices/i.test(h.textContent || ''),
  )
  heading?.scrollIntoView({ block: 'center' })
})
await page.waitForTimeout(800)
await page.screenshot({ path: '.visual-check/billing-official.png' })

// Arabic, dark, RTL.
await page.evaluate(() => {
  localStorage.setItem('blinkengage.language', 'ar')
  localStorage.setItem('blinkengage.themeMode', 'dark')
  localStorage.setItem('blinkengage.direction', 'rtl')
})
await page.goto(base + '/billing', { waitUntil: 'networkidle' })
await page.waitForTimeout(3000)
await page.screenshot({ path: '.visual-check/billing-rtl-dark.png' })

console.log('OK')
await browser.close()
