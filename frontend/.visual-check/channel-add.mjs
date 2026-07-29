import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, ignoreHTTPSErrors: true })
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'verify-check-8516@blinkconnected.com')
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)
await p.goto('https://localhost/channels', { waitUntil: 'networkidle' })
await p.waitForTimeout(1500)
await p.screenshot({ path: '.visual-check/channels-list.png', fullPage: false })

// Open the add dialog and pick WhatsApp.
const addBtn = await p.$('button:has-text("Connect"), button:has-text("Add")')
if (addBtn) { await addBtn.click(); await p.waitForTimeout(900) }
const sel = await p.$('div.MuiSelect-select, [role="combobox"]')
if (sel) {
  await sel.click(); await p.waitForTimeout(400)
  const opts = await p.$$('[role="option"]')
  console.log('channel types:', await Promise.all(opts.map(o => o.textContent())))
  for (const o of opts) { const t = (await o.textContent()) || ''; if (/whatsapp/i.test(t)) { await o.click(); break } }
  await p.waitForTimeout(900)
}
const labels = await p.$$eval('label', els => els.map(e => e.textContent?.trim()).filter(Boolean))
console.log('fields asked for:', labels)
const body = await p.textContent('body')
console.log('mentions App Secret:', /app secret/i.test(body))
console.log('mentions where to find:', /developers\.facebook|dashboard|Meta/i.test(body))
await p.screenshot({ path: '.visual-check/channel-add-whatsapp.png', fullPage: false })
await b.close()
