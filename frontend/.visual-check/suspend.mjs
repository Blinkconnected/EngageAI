import { chromium } from '@playwright/test'
const [ , , base, email, password ] = process.argv
const b = await chromium.launch()
const page = await b.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push(e.message))
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL('**/platform', { timeout: 20000 })
await page.waitForTimeout(2500)

const firstRow = page.locator('[role="row"]').nth(1)
const name = (await firstRow.innerText()).split('\n')[0]
console.log('target company:', name)
await firstRow.getByRole('button', { name: /suspend/i }).click()
await page.waitForTimeout(700)
console.log('confirm dialog:', JSON.stringify((await page.locator('[role="dialog"]').innerText()).replace(/\s+/g,' ').slice(0,150)))
await page.locator('[role="dialog"]').getByRole('button', { name: /^suspend$/i }).click()
await page.waitForTimeout(2500)
const rowNow = (await page.locator('[role="row"]').nth(1).innerText()).replace(/\s+/g,' ')
console.log('row after suspend:', JSON.stringify(rowNow.slice(0,110)))
// put it back
await page.locator('[role="row"]').nth(1).getByRole('button', { name: /reactivate/i }).click()
await page.waitForTimeout(700)
await page.locator('[role="dialog"]').getByRole('button', { name: /^reactivate$/i }).click()
await page.waitForTimeout(2500)
console.log('row after reactivate:', JSON.stringify((await page.locator('[role="row"]').nth(1).innerText()).replace(/\s+/g,' ').slice(0,110)))
console.log('errors:', errors.length ? errors.join(' | ') : 'none')
await page.screenshot({ path: '.visual-check/suspend.png' })
await b.close()
