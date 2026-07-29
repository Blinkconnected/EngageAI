import { chromium } from '@playwright/test'
const [ , , base, email, password, convId ] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
await page.evaluate(() => { sessionStorage.clear(); localStorage.clear() })
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })

await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const messageWidth = async () => {
  const el = await page.locator('[role="tablist"]').first().boundingBox()
  return el ? Math.round(el.width) : null
}
console.log('SIDEBAR WIDTH:', Math.round((await page.locator('.MuiDrawer-docked .MuiDrawer-paper').first().boundingBox()).width))
const closedWidth = await messageWidth()
console.log('CHAT COLUMN WIDTH (details closed):', closedWidth)
console.log('STATUS FIELD VISIBLE BY DEFAULT:', await page.getByLabel(/^status/i).isVisible().catch(() => false))
await page.screenshot({ path: '.visual-check/details-closed.png' })

await page.getByRole('button', { name: /conversation actions/i }).click()
await page.getByRole('menuitem', { name: /conversation details/i }).click()
await page.waitForTimeout(900)
console.log('DETAILS OPEN:', await page.getByRole('presentation').filter({ hasText: 'Conversation details' }).count() > 0)
console.log('STATUS FIELD VISIBLE AFTER OPEN:', await page.getByLabel(/^status/i).first().isVisible())
const openWidth = await messageWidth()
console.log('CHAT COLUMN WIDTH (details open):', openWidth, '| unchanged:', openWidth === closedWidth)
await page.screenshot({ path: '.visual-check/details-open.png' })

await page.getByRole('button', { name: /close conversation details/i }).click()
await page.waitForTimeout(900)
console.log('CHAT COLUMN WIDTH (after close):', await messageWidth())
console.log('DOC SCROLLABLE:', await page.evaluate(() => document.documentElement.scrollHeight > window.innerHeight + 2))
console.log('ERRORS:', errors.length ? '\n  ' + errors.join('\n  ') : 'none')
await browser.close()
