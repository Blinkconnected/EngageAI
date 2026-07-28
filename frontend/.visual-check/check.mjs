import { chromium } from '@playwright/test'
const url = process.argv[2] || 'http://localhost:5173/login'
const out = process.argv[3] || '/tmp/claude-0/-root/b61507cf-e9fc-403e-9a62-d929c70763f0/scratchpad/vis/shot.png'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
page.on('requestfailed', r => errors.push('REQFAIL: ' + r.url() + ' ' + (r.failure()?.errorText||'')))
const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 }).catch(e => { errors.push('GOTO: '+e.message); return null })
await page.waitForTimeout(1500)
console.log('HTTP:', resp ? resp.status() : 'n/a')
console.log('TITLE:', await page.title())
const bodyText = (await page.locator('body').innerText().catch(()=> '')).slice(0, 400)
console.log('VISIBLE TEXT:', JSON.stringify(bodyText))
console.log('ROOT CHILDREN:', await page.locator('#root > *').count())
console.log('ERRORS:', errors.length ? '\n  ' + errors.join('\n  ') : 'none')
await page.screenshot({ path: out, fullPage: false })
await browser.close()
