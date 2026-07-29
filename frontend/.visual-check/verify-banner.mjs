import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1400, height: 900 }, ignoreHTTPSErrors: true })
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))

// A brand-new, unverified workspace.
const email = `banner-check-${Date.now()}@blinkconnected.com`
await p.goto('https://localhost/register', { waitUntil: 'networkidle' })
const fields = await p.$$('input')
console.log('register fields:', fields.length)
await p.fill('input[name="company_name"], input[name="companyName"]', 'Banner Check Co').catch(()=>{})
await p.fill('input[name="owner_full_name"], input[name="fullName"]', 'Ban Ner').catch(()=>{})
await p.fill('input[type="email"]', email)
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4000)
console.log('url after signup:', p.url())
const body = await p.textContent('body')
console.log('banner shown:', body.includes('Confirm your email address'))
console.log('resend button:', body.includes('Resend link'))
await p.screenshot({ path: '.visual-check/verify-banner.png', fullPage: false })

// The verify page with a bad token.
await p.goto('https://localhost/verify-email?token=not-a-real-token', { waitUntil: 'networkidle' })
await p.waitForTimeout(1200)
const vp = await p.textContent('body')
console.log('invalid link message:', vp.includes("isn't valid"))
await p.screenshot({ path: '.visual-check/verify-page.png', fullPage: false })
console.log('page errors:', errs.length ? errs.slice(0,2) : 'none')
await b.close()
