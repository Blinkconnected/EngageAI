import { chromium } from '@playwright/test'
const base = process.argv[2]
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
const resp = await page.goto(base + '/changelog', { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
console.log('HTTP:', resp?.status())
const text = await page.locator('body').innerText()
console.log('PAGE RENDERED:', text.length > 200)
console.log('HAS REMOVED SECTION:', /Removed/i.test(text))
console.log('MENTIONS SUBSCRIPTION REMOVAL:', /Subscription plans and recurring/i.test(text))
console.log('ERRORS:', errors.length ? errors.join(' | ') : 'none')
await page.screenshot({ path: '.visual-check/changelog-removed.png' })
await browser.close()
