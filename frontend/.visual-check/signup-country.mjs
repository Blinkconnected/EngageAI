import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1200, height: 950 }, ignoreHTTPSErrors: true })
const errs = []
p.on('pageerror', (e) => errs.push(String(e)))
await p.goto('https://localhost/register', { waitUntil: 'networkidle' })
await p.waitForTimeout(1200)

const body = await p.textContent('body')
console.log('country field present:', body.includes('Country'))
console.log('currency hint present:', body.includes("Sets the currency"))

// Pick Jordan and check the hint names JOD.
await p.click('#mui-component-select-country, [role="combobox"]').catch(async () => {
  await p.click('div.MuiSelect-select')
})
await p.waitForTimeout(400)
const opts = await p.$$('[role="option"]')
console.log('options offered:', opts.length)
for (const o of opts) { if ((await o.textContent())?.trim() === 'Jordan') { await o.click(); break } }
await p.waitForTimeout(500)
const after = await p.textContent('body')
console.log('JOD hint after picking Jordan:', after.includes('JOD'))
await p.screenshot({ path: '.visual-check/signup-country.png', fullPage: false })
console.log('page errors:', errs.length ? errs.slice(0,2) : 'none')
await b.close()
