/**
 * 手机尺寸截图：评审大概率用手机点链接，先看它在窄屏上长什么样。
 *
 *   node tests/mobile_shot.mjs
 *
 * 用真浏览器（Edge）按 iPhone 尺寸渲染，顺便量一下有没有横向溢出。
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);
const BASE = process.env.BASE || 'http://127.0.0.1:8765/';

const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });

const SIZES = [
  { name: 'iphone12', w: 390, h: 844 },
  { name: 'iphoneSE', w: 375, h: 667 },
];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
for (const s of SIZES) {
  const page = await browser.newPage({
    viewport: { width: s.w, height: s.h },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  const metrics = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    bodyW: document.body.scrollWidth,
    overflow: [...document.querySelectorAll('*')]
      .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
      .slice(0, 6)
      .map((e) => `${e.tagName.toLowerCase()}.${e.className || '-'}→${Math.round(e.getBoundingClientRect().right)}`),
  }));
  await page.screenshot({ path: join(OUT, `mobile-${s.name}.png`), fullPage: true });
  console.log(s.name, JSON.stringify(metrics));
  await page.close();
}
await browser.close();
