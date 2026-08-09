import { chromium } from '@playwright/test'
const [, , base, email, password, companyId, adminEmail, adminPassword] = process.argv
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 950 } })
const errors = []
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text())
})
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message))

async function login(e, p) {
  // Clear the session first: a second `goto('/login')` while still
  // authenticated redirects straight to `/`, so there is no form to fill.
  await page.goto(base + '/login', { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    sessionStorage.clear()
    localStorage.clear()
  })
  await page.goto(base + '/login', { waitUntil: 'networkidle' })
  await page.locator('input').first().fill(e)
  await page.locator('input[type="password"]').first().fill(p)
  await page.getByRole('button', { name: /sign in/i }).click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
}

await login(email, password)
const navBefore = (await page.getByRole('navigation').first().innerText())
  .split('\n')
  .filter(Boolean)
console.log('TENANT NAV (all features):', JSON.stringify(navBefore))

await page.goto(base + '/settings/billing', { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)
console.log(
  'BILLING PAGE:',
  JSON.stringify((await page.locator('body').innerText()).split('\n').filter(Boolean).slice(-6)),
)
await page.screenshot({ path: '.visual-check/tenant-billing.png' })

// SLA is reachable today
await page.goto(base + '/sla', { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
console.log(
  'SLA PAGE BEFORE:',
  (await page.locator('body').innerText()).includes('403') ? 'BLOCKED' : 'REACHABLE',
)

// --- Revoke SLA as the platform admin, via the API with a real token ---
const tokenResp = await page.request.post(base + '/api/v1/auth/login', {
  data: { email: adminEmail, password: adminPassword },
})
const { access_token } = await tokenResp.json()
const put = await page.request.put(`${base}/api/v1/platform/companies/${companyId}/features`, {
  headers: { Authorization: `Bearer ${access_token}` },
  data: { overrides: { sla: false } },
})
console.log('REVOKE SLA:', put.status())

// --- Back as the tenant ---
await login(email, password)
await page.waitForTimeout(1200)
const navAfter = (await page.getByRole('navigation').first().innerText())
  .split('\n')
  .filter(Boolean)
console.log('TENANT NAV (sla revoked):', JSON.stringify(navAfter))
console.log('SLA WAS IN NAV BEFORE:', navBefore.join('|').includes('SLA'))
console.log('SLA GONE FROM NAV AFTER:', !navAfter.join('|').includes('SLA'))

const api = await page.request.get(base + '/api/v1/sla-policies', {
  headers: {
    Authorization:
      'Bearer ' + (await page.evaluate(() => sessionStorage.getItem('blinkengage.accessToken'))),
  },
})
console.log('SLA API STATUS:', api.status(), JSON.stringify((await api.text()).slice(0, 120)))

console.log('ERRORS:', errors.length ? '\n  ' + errors.join('\n  ') : 'none')
await browser.close()
