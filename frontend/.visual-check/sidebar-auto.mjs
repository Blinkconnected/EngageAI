import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 950 }, ignoreHTTPSErrors: true })
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))

await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'verify-check-8516@blinkconnected.com').catch(()=>{})
await p.fill('input[type="password"]', 'correct-horse-battery-9').catch(()=>{})
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)
console.log('url:', p.url())

const paper = await p.$('.MuiDrawer-docked .MuiDrawer-paper')
if (!paper) { console.log('NO DOCKED DRAWER (not signed in?)'); await b.close(); process.exit(0) }
const box = await paper.boundingBox()
const styles = await paper.evaluate((el) => {
  const c = getComputedStyle(el)
  return { width: c.width, position: c.position, borderRight: c.borderRightWidth + ' ' + c.borderRightStyle + ' ' + c.borderRightColor }
})
console.log('paper box:', JSON.stringify(box))
console.log('computed:', JSON.stringify(styles))

// Does the main content start immediately after the sidebar (no gap, no overlap)?
const main = await p.$('main, [role="main"]')
const mainBox = main ? await main.boundingBox() : null
console.log('main box:', JSON.stringify(mainBox))
if (box && mainBox) console.log('gap/overlap px:', Math.round(mainBox.x - (box.x + box.width)))

// Horizontal page scroll would mean the layout burst its bounds.
const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
console.log('horizontal overflow:', overflow)
await p.screenshot({ path: '.visual-check/sidebar-auto.png', fullPage: false })
console.log('page errors:', errs.length ? errs.slice(0,2) : 'none')
await b.close()
