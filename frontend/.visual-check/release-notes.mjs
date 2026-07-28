import { chromium } from '@playwright/test'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push(e.message))
await page.goto(process.argv[2] + '/changelog', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)
console.log('TEXT:', (await page.locator('body').innerText()).replace(/\s+/g,' ').slice(0, 320))
console.log('errors:', errors.length ? errors.join('; ') : 'none')
await page.screenshot({ path: '.visual-check/release-notes.png' })
await browser.close()
