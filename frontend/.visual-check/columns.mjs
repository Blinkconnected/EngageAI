import { chromium } from '@playwright/test'
const [ , , base, email, password, convId, wStr ] = process.argv
const width = Number(wStr || 1680)
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width, height: 900 } })
const errors = []
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2200)

const report = await page.evaluate(() => {
  const scrollables = [...document.querySelectorAll('*')].filter(el => {
    const cs = getComputedStyle(el)
    return /(auto|scroll)/.test(cs.overflowY) && el.clientHeight > 120 && el.clientWidth > 100
  }).map(el => ({
    left: Math.round(el.getBoundingClientRect().left),
    width: Math.round(el.getBoundingClientRect().width),
    h: el.clientHeight, scrollH: el.scrollHeight,
    overflows: el.scrollHeight > el.clientHeight + 1,
    text: (el.textContent||'').replace(/\s+/g,' ').trim().slice(0,38),
  })).sort((a,b) => a.left - b.left)
  return {
    doc: document.documentElement.scrollHeight > document.documentElement.clientHeight + 1,
    vh: window.innerHeight, scrollables,
    filtersVisible: !!document.querySelector('nav[aria-label*="ilters"]'),
  }
})
console.log(`--- viewport ${width}x900 ---`)
console.log('page scrolls (must be false):', report.doc, '| filters column present:', report.filtersVisible)
for (const s of report.scrollables)
  console.log(`  col@${s.left}px w=${s.width} h=${s.h}/${s.scrollH} ${s.overflows?'SCROLLING':'fits'} "${s.text}"`)
console.log('errors:', errors.length ? errors.join('; ') : 'none')
await page.screenshot({ path: `.visual-check/cols-${width}.png` })
await browser.close()
