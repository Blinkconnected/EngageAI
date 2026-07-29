import { chromium } from '@playwright/test'
const [ , , base, email, password ] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
await page.evaluate(() => { sessionStorage.clear(); localStorage.clear() })
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.waitForTimeout(1200)
const text = await page.locator('body').innerText()
const line = text.split('\n').find(l => l.includes('©')) || '(no copyright line found)'
console.log('FOOTER:', JSON.stringify(line.trim()))
console.log('SAYS BLINK CONNECTED:', /Blink Connected/.test(line))
console.log('STILL SAYS BLINK ENGAGE:', /©.*Blink Engage/.test(line))
await browser.close()
