import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1400, height: 1000 }, ignoreHTTPSErrors: true })
const errors = []
p.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
p.on('pageerror', (e) => errors.push(String(e)))

await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[name="email"], input[type="email"]', 'superadmin@blinkengage.io')
await p.fill('input[name="password"], input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForURL(/platform/, { timeout: 15000 })

await p.goto('https://localhost/platform/mail', { waitUntil: 'networkidle' })
await p.waitForTimeout(800)
await p.screenshot({ path: '.visual-check/mail-settings.png', fullPage: true })

const body = await p.textContent('body')
console.log('title present:', body.includes('Email delivery'))
console.log('env banner:', body.includes("environment configuration"))
console.log('host field:', await p.inputValue('input[value="greenmail"]').catch(() => 'NOT FOUND'))

// Send a real test message through the form.
await p.fill('input[type="email"]:below(:text("Send a test message"))', 'browser-check@blinkconnected.com')
await p.click('button:has-text("Send test")')
await p.waitForTimeout(2500)
const after = await p.textContent('body')
console.log('test result shown:', after.includes('Test message sent') ? 'DELIVERED' : after.includes('refused') ? 'REFUSED' : 'no result')
await p.screenshot({ path: '.visual-check/mail-settings-tested.png', fullPage: true })
console.log('console errors:', errors.length ? errors.slice(0,3) : 'none')
await b.close()
