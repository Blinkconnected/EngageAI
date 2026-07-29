import { chromium } from '@playwright/test'
const [ , , base, email, password ] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForTimeout(5000)
console.log('URL after sign-in:', page.url())
const text = (await page.locator('body').innerText().catch(()=>'')).replace(/\s+/g,' ')
console.log('page text:', JSON.stringify(text.slice(0, 260)))
console.log('rows visible:', await page.locator('[role="row"]').count())
console.log('errors:', errors.length ? errors.slice(0,3).join(' | ') : 'none')
await page.screenshot({ path: '.visual-check/platform.png' })
await browser.close()
