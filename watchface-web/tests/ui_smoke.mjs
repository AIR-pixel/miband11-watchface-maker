/**
 * UI 冒烟：真浏览器打开页面 → 选 GIF → 点生成 → 接下载 → 存盘 → 截图。
 *
 *   node tests/ui_smoke.mjs [gif]
 *
 * 依赖工作区里的 playwright（NODE_PATH 由外部指定），用系统 Edge 跑。
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
// ESM 不认 NODE_PATH，直接按绝对路径 import 工作区里的 playwright（PW 可覆盖）
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });
const gif = process.argv[2] || join(ROOT, 'tests/golden-src/b.gif');

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1240, height: 900 }, deviceScaleFactor: 2 });
page.on('console', (m) => { if (m.type() === 'error') console.log('[console error]', m.text()); });
page.on('response', (r) => { if (r.status() >= 400) console.log('[http', r.status() + ']', r.url()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

await page.goto('http://127.0.0.1:8765/', { waitUntil: 'networkidle' });
await page.waitForTimeout(300);
await page.screenshot({ path: join(OUT, 'ui-empty.png') });

await page.setInputFiles('#file', gif);
await page.waitForFunction(() => /帧/.test(document.getElementById('srcInfo').textContent) || /失败|只支持/.test(document.getElementById('hint').textContent), null, { timeout: 20000 });
await page.waitForTimeout(700);
await page.screenshot({ path: join(OUT, 'ui-loaded.png') });

// 打开 AOD，切到息屏视图拍一张
await page.click('#aodOn');
await page.waitForTimeout(500);
await page.screenshot({ path: join(OUT, 'ui-aod.png') });
const aodCost = await page.textContent('#aodCost');

const info = await page.textContent('#srcInfo');
const hint = await page.textContent('#hint');
const budget = await page.textContent('#budgetTotal');

const [download] = await Promise.all([
  page.waitForEvent('download', { timeout: 60000 }),
  page.click('#build'),
]);
const facePath = join(OUT, download.suggestedFilename());
await download.saveAs(facePath);
await page.waitForTimeout(400);
await page.screenshot({ path: join(OUT, 'ui-done.png') });

console.log(JSON.stringify({ info, hint, budget, aodCost, downloaded: download.suggestedFilename() }, null, 2));
await browser.close();
