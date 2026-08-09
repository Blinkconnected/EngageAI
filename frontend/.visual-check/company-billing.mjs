import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1100 }, ignoreHTTPSErrors: true })
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))
p.on('console', (m) => m.type() === 'error' && errs.push(m.text()))

await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'superadmin@blinkengage.io')
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForURL(/platform/, { timeout: 15000 })
await p.waitForTimeout(1500)

const CO = process.argv[2]
await p.goto(`https://localhost/platform/companies/${CO}/billing`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2000)
const body = await p.textContent('body')
console.log('title:', body.includes('Billing'))
console.log('currency in subtitle JOD:', /billed in JOD/.test(body))
console.log('shows source column:', body.includes('Comes from'))
console.log('shows Global default:', body.includes('Global default'))
console.log('profile section:', body.includes('Pricing profile'))
console.log('preview section:', body.includes('Ask the engine'))
console.log('history section:', body.includes('Change history'))
await p.screenshot({ path: '.visual-check/company-billing.png', fullPage: true })
console.log('errors:', errs.length ? errs.slice(0, 3) : 'none')
await b.close()
