import { chromium } from '@playwright/test'
const [, , base, email, password, convId, ...selectors] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })
await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
await page.evaluate(() => {
  sessionStorage.clear()
  localStorage.clear()
})
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

for (const sel of selectors) {
  const loc = page.locator(sel)
  const n = await loc.count()
  console.log(`\n=== ${sel} -> ${n} match(es) ===`)
  for (let i = 0; i < n; i++) {
    const el = loc.nth(i)
    const box = await el.boundingBox()
    const info = await el.evaluate((node) => ({
      tag: node.tagName,
      cls: node.className,
      text: (node.innerText || '').slice(0, 160),
      childTags: Array.from(node.children)
        .map((c) => c.tagName + '.' + String(c.className).split(' ').slice(0, 2).join('.'))
        .slice(0, 6),
      parent: node.parentElement
        ? node.parentElement.tagName + '.' + String(node.parentElement.className).slice(0, 60)
        : null,
    }))
    console.log(JSON.stringify({ ...info, box }, null, 1))
  }
}
await page.screenshot({ path: '.visual-check/identify.png' })
await browser.close()
