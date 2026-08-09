import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1100 }, ignoreHTTPSErrors: true })
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'superadmin@blinkengage.io')
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForURL(/platform/, { timeout: 15000 })
await p.goto(`https://localhost/platform/companies/${process.argv[2]}/billing`, {
  waitUntil: 'networkidle',
})
await p.waitForTimeout(1800)

// Set a company override on Conversation.
await p.click('tr:has-text("Conversation") button:has-text("Set override")')
await p.waitForTimeout(700)
console.log(
  'dialog says which source it replaces:',
  /Currently using the/.test(await p.textContent('body')),
)
await p.fill('input[inputmode="decimal"], label:has-text("Price per unit") + div input', '0.028000')
await p.fill('textarea', 'Negotiated rate for launch partner')
await p.click('button:has-text("Save price")')
await p.waitForTimeout(2500)

const body = await p.textContent('body')
console.log('source now Company override:', body.includes('Company override'))
console.log('new price shown:', /0\.028/.test(body))
console.log('shadowed global visible:', /overridden/.test(body))
console.log('history now populated:', !body.includes('No pricing changes have been made'))
console.log('reason in history:', /Negotiated rate for launch partner/.test(body))

// Preview via the resolver.
// The preview card's own select — the page has two.
const previewCard = p.locator('div.MuiCard-root', { hasText: 'Ask the engine' })
await previewCard.locator('div.MuiSelect-select').click()
await p.waitForTimeout(400)
const opts = await p.$$('[role="option"]')
for (const o of opts) {
  if (/Conversation/.test((await o.textContent()) || '')) {
    await o.click()
    break
  }
}
await p.waitForTimeout(400)
await p.click('button:has-text("Ask the engine")')
await p.waitForTimeout(1800)
const after = await p.textContent('body')
console.log('resolver preview answered:', /per conversation, from the/.test(after))
console.log('preview agrees with table:', /0\.028000 JOD per conversation/.test(after))
await p.screenshot({ path: '.visual-check/company-billing-edited.png', fullPage: true })
console.log('errors:', errs.length ? errs.slice(0, 2) : 'none')
await b.close()
