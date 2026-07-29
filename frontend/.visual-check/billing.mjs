import { chromium } from '@playwright/test'
const [ , , base, email, password ] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })
console.log('LANDED ON:', new URL(page.url()).pathname)

// --- Plans page ---
await page.goto(base + '/platform/plans', { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
console.log('PLANS TEXT:', JSON.stringify((await page.locator('body').innerText()).slice(0, 300)))
await page.screenshot({ path: '.visual-check/billing-plans.png' })

// --- Companies grid: plan column + Features button ---
await page.goto(base + '/platform', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const headers = await page.locator('[role="columnheader"]').allInnerTexts()
console.log('COMPANY COLUMNS:', JSON.stringify(headers))
const featuresBtn = page.getByRole('button', { name: /^features$/i }).first()
console.log('FEATURES BUTTON PRESENT:', await featuresBtn.count() > 0)

// --- Feature dialog round trip ---
await featuresBtn.click()
await page.waitForTimeout(1200)
const dialog = page.getByRole('dialog')
console.log('DIALOG TITLE:', await dialog.locator('h2').innerText())
const switches = dialog.getByRole('switch')
const n = await switches.count()
console.log('FEATURE SWITCHES:', n)
const first = switches.first()
const before = await first.isChecked()
await first.click()
await dialog.getByRole('button', { name: /^save$/i }).click()
await page.waitForTimeout(1500)
console.log('DIALOG CLOSED AFTER SAVE:', await dialog.count() === 0)

// reopen and confirm it persisted
await page.getByRole('button', { name: /^features$/i }).first().click()
await page.waitForTimeout(1200)
const after = await page.getByRole('dialog').getByRole('switch').first().isChecked()
console.log(`TOGGLE PERSISTED: before=${before} after=${after} changed=${before !== after}`)
console.log('SOURCE CHIPS:', JSON.stringify(await page.getByRole('dialog').locator('.MuiChip-label').allInnerTexts()))
await page.screenshot({ path: '.visual-check/billing-features.png' })

// restore it
await page.getByRole('dialog').getByRole('button', { name: /follow plan/i }).first().click()
await page.getByRole('dialog').getByRole('button', { name: /^save$/i }).click()
await page.waitForTimeout(1200)
console.log('RESTORED:', await page.getByRole('dialog').count() === 0)

console.log('ERRORS:', errors.length ? '\n  ' + errors.join('\n  ') : 'none')
await browser.close()
