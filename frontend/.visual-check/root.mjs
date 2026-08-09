import { chromium } from '@playwright/test'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
const errs = []
p.on('pageerror', (e) => errs.push('PAGEERROR: ' + e.message))
p.on('console', (m) => {
  if (m.type() === 'error') errs.push('CONSOLE: ' + m.text().slice(0, 180))
})
await p.goto(process.argv[2], { waitUntil: 'networkidle' })
await p.waitForTimeout(2000)
console.log('final URL:', p.url())
console.log('text:', (await p.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 160))
console.log('errors:', errs.length ? errs.join(' | ') : 'none')
await b.close()
