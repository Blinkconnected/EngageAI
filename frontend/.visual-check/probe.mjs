import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1500, height: 1000 }, ignoreHTTPSErrors: true })
await p.goto('https://localhost/login', { waitUntil: 'networkidle' })
await p.fill('input[type="email"]', 'owner@blinkdemo.io')
await p.fill('input[type="password"]', 'media-check-horse-9')
await p.click('button[type="submit"]')
await p.waitForTimeout(4500)
await p.goto(`https://localhost/conversations/${process.argv[2]}`, { waitUntil: 'networkidle' })
await p.waitForTimeout(2000)
await p.evaluate(() => {
  ;[...document.querySelectorAll('*')]
    .filter((e) => e.scrollHeight > e.clientHeight + 50)
    .forEach((e) => {
      e.scrollTop = e.scrollHeight
    })
})
await p.waitForTimeout(2500)

// What did the last message actually render?
const info = await p.evaluate(() => {
  const media = [...document.querySelectorAll('img[alt], video, audio, [aria-label*="Download"]')]
  return {
    imgs: [...document.querySelectorAll('img[alt]')].map((e) => e.alt),
    videos: document.querySelectorAll('video').length,
    audios: document.querySelectorAll('audio').length,
    mediaButtons: [...document.querySelectorAll('button[aria-label]')]
      .map((e) => e.getAttribute('aria-label'))
      .filter((l) => /view |download /i.test(l)),
    bodyHasClip: document.body.innerText.includes('clip.mp4'),
    bodyHasWide: document.body.innerText.includes('wide.png'),
  }
})
console.log(JSON.stringify(info, null, 1))
await b.close()
