import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 950 }, ignoreHTTPSErrors: true })
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'verify-check-8516@blinkconnected.com')
await p.fill('input[type="password"]', 'correct-horse-battery-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)

const measure = async (label) => {
  const paper = await p.$('.MuiDrawer-docked .MuiDrawer-paper')
  const box = await paper.boundingBox()
  const st = await paper.evaluate((el) => {
    const c = getComputedStyle(el)
    return { w: c.width, h: c.height, bl: c.borderLeftWidth, br: c.borderRightWidth,
             blc: c.borderLeftColor, brc: c.borderRightColor, dir: getComputedStyle(document.documentElement).direction }
  })
  const of = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  console.log(label, JSON.stringify({ x: Math.round(box.x), ...st, overflow: of }))
}
await measure('LTR light: ')

// Dark mode
await p.click('button[aria-label*="dark" i], button[aria-label*="theme" i]').catch(async () => {
  const btns = await p.$$('header button'); if (btns[3]) await btns[3].click()
})
await p.waitForTimeout(1200)
await measure('LTR dark:  ')
await p.screenshot({ path: '.visual-check/sidebar-dark.png', fullPage: false })

// Arabic (RTL)
await p.click('button[aria-label*="language" i]').catch(async () => {
  const btns = await p.$$('header button'); if (btns[2]) await btns[2].click()
})
await p.waitForTimeout(600)
await p.click('li:has-text("العربية"), [role="menuitem"]:has-text("العربية")').catch(()=>{})
await p.waitForTimeout(2000)
await measure('RTL dark:  ')
await p.screenshot({ path: '.visual-check/sidebar-rtl.png', fullPage: false })
await b.close()
