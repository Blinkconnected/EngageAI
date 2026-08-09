import { chromium } from '@playwright/test'
const [, , base, email, password, convId] = process.argv
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1680, height: 900 } })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text().slice(0, 160))
})

await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)

// 1. Does the PAGE scroll? (mandatory: it must not)
const pageScroll = await page.evaluate(() => ({
  docScrollable: document.documentElement.scrollHeight > document.documentElement.clientHeight + 1,
  bodyScrollable: document.body.scrollHeight > document.body.clientHeight + 1,
}))

// 2. Find every element that is actually a scroll container, and name it
const columns = await page.evaluate(() => {
  const out = []
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el)
    const scrolls = /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 1
    if (!scrolls) continue
    out.push({
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 45),
      h: el.clientHeight,
      scrollH: el.scrollHeight,
      rect: Math.round(el.getBoundingClientRect().left) + 'px from left',
    })
  }
  return out
})

// 3. Composer stays put while the message history scrolls
const composer = page.getByPlaceholder(/write a reply/i)
const before = await composer.boundingBox()
const thread = page.locator('[role="gridcell"], .MuiStack-root').first()
const scrolled = await page.evaluate(() => {
  const containers = [...document.querySelectorAll('*')].filter((el) => {
    const cs = getComputedStyle(el)
    return /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 40
  })
  // the widest scrollable = the message thread
  const target = containers.sort((a, b) => b.clientWidth - a.clientWidth)[0]
  if (!target) return null
  const start = target.scrollTop
  target.scrollTop = 0
  return { movedFrom: start, movedTo: target.scrollTop, width: target.clientWidth }
})
await page.waitForTimeout(600)
const after = await composer.boundingBox()

console.log('PAGE SCROLLABLE (must be false):', pageScroll)
console.log('SCROLL CONTAINERS:', columns.length)
for (const c of columns)
  console.log('   -', c.rect, `h=${c.h}/${c.scrollH}`, JSON.stringify(c.text))
console.log('THREAD SCROLL TEST:', scrolled)
console.log(
  'COMPOSER y before/after scroll:',
  before?.y,
  '/',
  after?.y,
  before && after && Math.abs(before.y - after.y) < 2 ? 'STATIONARY ✓' : 'MOVED ✗',
)
console.log('ERRORS:', errors.length ? '\n  ' + errors.slice(0, 5).join('\n  ') : 'none')
await page.screenshot({ path: '.visual-check/workspace-1680.png' })
await browser.close()
