import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, ignoreHTTPSErrors: true })
const reqs = []
p.on('request', (r) => { if (r.url().includes('/media?')) reqs.push(r.url().split('/media?')[0].slice(-12)) })
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'owner@blinkdemo.io')
await p.fill('input[type="password"]', 'media-check-horse-9')
await p.click('button[type="submit"]'); await p.waitForTimeout(4500)
await p.goto(`https://localhost/conversations/${process.argv[2]}`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2000)

const pane = await p.evaluateHandle(() => [...document.querySelectorAll('*')].find(e => e.scrollHeight > e.clientHeight + 200 && e.querySelector('img[alt$=".png"], [aria-label*="full screen"]')))
console.log('--- before scrolling to the media (lazy) ---')
console.log('media requests so far:', reqs.length)

// Bring the video into view.
await p.evaluate(() => {
  const btn = [...document.querySelectorAll('button[aria-label*="wide.png"]')][0]
  btn?.scrollIntoView({ block: 'center' })
})
await p.waitForTimeout(2500)
console.log('--- after scrolling up to wide.png + clip.mp4 ---')
console.log('videos now:', (await p.$$('video')).length)
console.log('wide.png decoded:', await p.$$eval('img[alt="wide.png"]', e => e.map(x => `${x.naturalWidth}x${x.naturalHeight}`)))
console.log('media requests now:', reqs.length)
await p.screenshot({ path: '.visual-check/media-scrolled.png', fullPage: false })

console.log('video error state shown:', (await p.textContent('body')).includes("can't play this video"))

// The lightbox is a fullScreen Dialog labelled with the filename — the
// conversation details drawer is also role=dialog, so target by label.
const viewer = () => p.$('[role="dialog"][aria-label*="Viewing"]')
await p.click('button[aria-label*="wide.png"]')
await p.waitForTimeout(1500)
let dlg = await viewer()
console.log('--- lightbox ---')
console.log('opened:', !!dlg)
if (dlg) {
  console.log('label:', (await dlg.getAttribute('aria-label')).slice(0, 60))
  console.log('shows position:', /of \d/.test(await dlg.textContent()))
  console.log('has download + open buttons:',
    !!(await dlg.$('[aria-label*="Download"]')), !!(await dlg.$('[aria-label*="new tab"]')))
  await p.screenshot({ path: '.visual-check/inbox-lightbox.png', fullPage: false })
  await p.keyboard.press('ArrowRight'); await p.waitForTimeout(1000)
  const after = await viewer()
  console.log('ArrowRight moved to:', (await after.getAttribute('aria-label')).match(/Viewing ([^.]+)/)?.[1])
  await p.keyboard.press('Escape'); await p.waitForTimeout(1200)
  console.log('closed after Escape:', !(await viewer()))
}
await b.close()
