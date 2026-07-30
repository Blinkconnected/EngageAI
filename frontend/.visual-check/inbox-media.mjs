import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, ignoreHTTPSErrors: true })
const errs = []; const mediaReqs = []
p.on('pageerror', (e) => errs.push(String(e)))
p.on('console', (m) => m.type() === 'error' && errs.push(m.text()))
p.on('request', (r) => { if (r.url().includes('/media?')) mediaReqs.push(r.url()) })

await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'owner@blinkdemo.io')
await p.fill('input[type="password"]', 'media-check-horse-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)

await p.goto(`https://localhost/conversations/${process.argv[2]}`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2500)
// Scroll to the newest message where the media is.
await p.evaluate(() => {
  const panes = [...document.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 50)
  panes.forEach(e => { e.scrollTop = e.scrollHeight })
})
await p.waitForTimeout(2500)

const imgs = await p.$$eval('img[alt$=".png"]', els => els.map(e => ({
  alt: e.alt, natural: `${e.naturalWidth}x${e.naturalHeight}`, complete: e.complete,
})))
console.log('images decoded:', JSON.stringify(imgs))
console.log('video elements:', (await p.$$('video')).length)
console.log('audio elements:', (await p.$$('audio')).length)
console.log('media requests made:', mediaReqs.length)
await p.screenshot({ path: '.visual-check/inbox-media.png', fullPage: false })

// Click the landscape image → lightbox.
const btn = await p.$('button[aria-label*="landscape.png"]')
if (btn) {
  await btn.click(); await p.waitForTimeout(1500)
  const dlg = await p.$('[role="dialog"]')
  console.log('lightbox opened:', !!dlg)
  if (dlg) {
    const txt = await dlg.textContent()
    console.log('shows filename + position:', /landscape\.png/.test(txt), /of \d/.test(txt))
    await p.screenshot({ path: '.visual-check/inbox-lightbox.png', fullPage: false })
    await p.keyboard.press('ArrowRight'); await p.waitForTimeout(900)
    console.log('arrow moved on:', !(await (await p.$('[role="dialog"]')).textContent()).includes('landscape.png'))
    await p.keyboard.press('Escape'); await p.waitForTimeout(700)
    console.log('escape closed:', !(await p.$('[role="dialog"]')))
  }
} else { console.log('landscape button NOT FOUND') }
console.log('errors:', errs.length ? errs.slice(0,3) : 'none')
await b.close()
