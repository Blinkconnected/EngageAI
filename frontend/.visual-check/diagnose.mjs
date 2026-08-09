import { chromium } from '@playwright/test'
const [, , base, email, password, convId] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1680, height: 900 } })
await page.goto(base + '/login', { waitUntil: 'networkidle' })
await page.locator('input').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.getByRole('button', { name: /sign in/i }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.goto(`${base}/conversations/${convId}`, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)
const chain = await page.evaluate(() => {
  const composer = document.querySelector('textarea, input[placeholder]')
  const rows = []
  let el = composer,
    depth = 0
  while (el && depth < 18) {
    const cs = getComputedStyle(el)
    rows.push({
      depth,
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 50),
      display: cs.display,
      flexDir: cs.flexDirection,
      h: el.clientHeight,
      scrollH: el.scrollHeight,
      minH: cs.minHeight,
      height: cs.height,
      overflowY: cs.overflowY,
      grow: cs.flexGrow,
    })
    el = el.parentElement
    depth++
  }
  return { rows, vh: window.innerHeight, docH: document.documentElement.scrollHeight }
})
console.log('viewport:', chain.vh, 'documentScrollHeight:', chain.docH)
for (const r of chain.rows)
  console.log(
    `  [${r.depth}] ${r.tag} h=${r.h}/${r.scrollH} ${r.display}/${r.flexDir} minH=${r.minH} height=${r.height} ovY=${r.overflowY} grow=${r.grow} ${r.cls}`,
  )
await browser.close()
