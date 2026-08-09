import { chromium } from 'playwright'
const b = await chromium.launch()

async function session(width, height, label) {
  const p = await b.newPage({ viewport: { width, height }, ignoreHTTPSErrors: true })
  await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
  await p.fill('input[type="email"]', 'owner@blinkdemo.io')
  await p.fill('input[type="password"]', 'media-check-horse-9')
  await p.click('button[type="submit"]')
  await p.waitForTimeout(4500)
  await p.goto(`https://localhost/conversations/${process.argv[2]}`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(2000)
  await p.evaluate(() => {
    const btn = [...document.querySelectorAll('button[aria-label*="landscape.png"]')][0]
    btn?.scrollIntoView({ block: 'center' })
  })
  await p.waitForTimeout(2200)
  const overflow = await p.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  const imgBox = await p.evaluate(() => {
    const el = document.querySelector('img[alt="landscape.png"]')
    if (!el) return null
    const r = el.getBoundingClientRect()
    return {
      w: Math.round(r.width),
      h: Math.round(r.height),
      ratio: +(r.width / r.height).toFixed(2),
    }
  })
  console.log(`${label}: horizontal overflow=${overflow}px, image box=${JSON.stringify(imgBox)}`)
  await p.screenshot({ path: `.visual-check/media-${label}.png`, fullPage: false })
  return p
}

// Phone width — media must fit and not force the page sideways.
await session(390, 844, 'mobile')

// RTL: the nav arrows and the expand button use logical properties, so they
// should mirror without a second set of rules.
const p = await session(1400, 900, 'rtl-before')
await p.click('button[aria-label="language menu"]').catch(() => {})
await p.waitForTimeout(500)
await p.click('[role="menuitem"] >> nth=1').catch(() => {})
await p.waitForTimeout(2500)
await p.evaluate(() => {
  const btn = [
    ...document.querySelectorAll(
      'button[aria-label*="landscape.png"], button[aria-label*="landscape"]',
    ),
  ][0]
  btn?.scrollIntoView({ block: 'center' })
})
await p.waitForTimeout(1500)
console.log('dir:', await p.evaluate(() => getComputedStyle(document.documentElement).direction))
const btn = await p.$('button[aria-label*="landscape"]')
if (btn) {
  await btn.click()
  await p.waitForTimeout(1500)
  const dlg = await p.$('[role="dialog"][aria-label*="landscape"]')
  console.log('RTL lightbox opened:', !!dlg)
  if (dlg) {
    const arrows = await p.evaluate(() => {
      const prev = document.querySelector('[aria-label*="السابق"], [aria-label*="Previous"]')
      const next = document.querySelector('[aria-label*="التالي"], [aria-label*="Next"]')
      return prev && next
        ? {
            prevX: Math.round(prev.getBoundingClientRect().x),
            nextX: Math.round(next.getBoundingClientRect().x),
          }
        : null
    })
    console.log('arrow positions (prev should be on the RIGHT in RTL):', JSON.stringify(arrows))
    await p.screenshot({ path: '.visual-check/media-rtl-lightbox.png', fullPage: false })
  }
}
console.log(
  'horizontal overflow in RTL:',
  await p.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  ),
)
await b.close()
