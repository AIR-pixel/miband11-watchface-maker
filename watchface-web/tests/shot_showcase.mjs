/**
 * 出一套「作品展示」图：投稿和社媒用。
 *
 *   node tests/shot_showcase.mjs [--base https://...]
 *
 * 产出到 tests/out/：
 *   showcase-hero.png     设备特写（首屏示例在播）—— 适合当封面
 *   showcase-aod.png      息屏特写
 *   showcase-desktop.png  桌面整页
 *   showcase-loaded.png   拖入素材后的状态（列表 + 预览）
 *   showcase-done.png     生成完成的状态
 *   showcase-mobile.png   手机整页 390px
 *
 * 注意：这些图是**重绘 + 真截图**的混合体 —— 页面是真的，示例动画是代码画的。
 * 写文案时别把它说成"真机截图"。
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const BASE = (process.argv.includes('--base') ? process.argv[process.argv.indexOf('--base') + 1] : null)
  || process.env.BASE || 'http://127.0.0.1:8765/';
const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });

const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);
const browser = await chromium.launch({ channel: 'msedge', headless: true });

/* ── 1. 桌面：首屏（示例在播）── */
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);

const band = page.locator('.band');
// 截图里把表盘名改成有意义的（默认 MyFace 太像占位符）——顺便证明 ASCII 名一路通到底
await page.fill('#title', 'Aurora');
await page.waitForTimeout(200);
await band.screenshot({ path: join(OUT, 'showcase-hero.png') });
await page.screenshot({ path: join(OUT, 'showcase-desktop.png'), fullPage: true });

/* ── 2. 息屏特写 ── */
await page.click('#viewTabs button[data-v="aod"]');
await page.waitForTimeout(300);
// 息屏默认未启用，先打开才有内容
const aodOn = await page.isChecked('#aodOn');
if (!aodOn) { await page.check('#aodOn'); await page.waitForTimeout(400); }
// 展示用：时间 + 日期，青色数字。月日分隔是句点（10.22），不会再跟时间行撞脸
await page.selectOption('#aodMode', 'both');
await page.fill('#aodColor', '#7FE7D8');
await page.dispatchEvent('#aodColor', 'input');
await page.click('#viewTabs button[data-v="aod"]');
await page.waitForTimeout(700);
await band.screenshot({ path: join(OUT, 'showcase-aod.png') });
await page.click('#viewTabs button[data-v="main"]');

/* ── 3. 换一个示例，确认切换真的换画面 ── */
const before = await page.evaluate(() => {
  const c = document.getElementById('preview');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] + d[i + 1] + d[i + 2];
  return s / (d.length / 4) / 3;
});
await page.click('.wall [data-swap]');
await page.waitForTimeout(700);
const after = await page.evaluate(() => {
  const c = document.getElementById('preview');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] + d[i + 1] + d[i + 2];
  return s / (d.length / 4) / 3;
});
const demoName = await page.textContent('.wall .nm');
console.log(JSON.stringify({ lumaBefore: +before.toFixed(1), lumaAfter: +after.toFixed(1), demoName }));

/* ── 4. 拖入素材后的状态 ── */
// 用 w1/w2（专为展示画的极光 / 波纹）而不是测试用的 a/b.gif —— 后者是刻意画简单的色块
const GIFS = ['w1.gif', 'w2.gif'].map((n) => join(ROOT, 'tests/golden-src', n));
await page.setInputFiles('#file', GIFS);
await page.waitForFunction(() => /张壁纸/.test(document.getElementById('srcInfo').textContent), null, { timeout: 30000 });
// 选第 2 张（波纹）再截图：封面已经是极光了，整页图换个构图，一组图才有层次
await page.click('#wallList .wall[data-i="1"]');
await page.waitForTimeout(900);
await page.screenshot({ path: join(OUT, 'showcase-loaded.png'), fullPage: true });
const rows = await page.$$eval('#wallList .wall .nm', (els) => els.map((e) => e.textContent.trim()));

/* ── 5. 生成完成的提示（真跑一次，不下载也行）── */
const [dl] = await Promise.all([
  page.waitForEvent('download', { timeout: 120000 }),
  page.click('#build'),
]);
await page.waitForTimeout(600);
await page.screenshot({ path: join(OUT, 'showcase-done.png'), fullPage: true });
const hint = await page.textContent('#hint');
console.log(JSON.stringify({ rows, downloaded: dl.suggestedFilename(), hint }, null, 1));
await page.close();

/* ── 6. 手机整页 ── */
const m = await browser.newPage({
  viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
});
await m.goto(BASE, { waitUntil: 'networkidle' });
await m.waitForTimeout(1500);
await m.locator('.band').screenshot({ path: join(OUT, 'showcase-hero-mobile.png') });
await m.screenshot({ path: join(OUT, 'showcase-mobile.png'), fullPage: true });
const overflow = await m.evaluate(() => ({
  scrollW: document.documentElement.scrollWidth,
  clientW: document.documentElement.clientWidth,
}));
console.log(JSON.stringify({ mobile: overflow }));
await m.close();

await browser.close();
console.log('done ->', OUT);
