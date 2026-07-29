import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 950 }, ignoreHTTPSErrors: true })
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'verify-check-8516@blinkconnected.com')
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)

await p.click('button[aria-label="language menu"]')
await p.waitForTimeout(500)
await p.click('[role="menuitem"] >> nth=1')
await p.waitForTimeout(2500)

const paper = await p.$('.MuiDrawer-docked .MuiDrawer-paper')
const box = await paper.boundingBox()
const st = await paper.evaluate((el) => {
  const c = getComputedStyle(el)
  return { w: c.width, h: c.height, borderLeft: c.borderLeftWidth, borderRight: c.borderRightWidth,
           dir: getComputedStyle(document.documentElement).direction }
})
const of = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
console.log('RTL:', JSON.stringify({ x: Math.round(box.x), ...st, overflow: of }))
const main = await p.$('main')
if (main) { const m = await main.boundingBox(); console.log('main x/width:', Math.round(m.x), Math.round(m.width)) }
await p.screenshot({ path: '.visual-check/sidebar-rtl.png', fullPage: false })
await b.close()
