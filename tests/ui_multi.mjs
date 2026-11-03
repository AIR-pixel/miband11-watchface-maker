/**
 * 多壁纸 UI 端到端：真浏览器里多选 3 个 GIF → 壁纸列表 → 选页预览确实换了 → 删一页 → 生成 → 存盘。
 *
 *   node tests/ui_multi.mjs
 *
 * 前置：node tests/serve.mjs 8765 已在跑。
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
// playwright 不在本仓库依赖里（零依赖项目），从托管 workspace 取；可用 PW 环境变量覆盖
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const py = process.env.PY || 'C:/Users/air/AppData/Local/Programs/Python/Python313/python.exe';
const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });

const GIFS = ['a.gif', 'b.gif', 'c.gif'].map((n) => join(ROOT, 'tests/golden-src', n));
const fail = [];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1240, height: 1000 }, deviceScaleFactor: 2 });
page.on('console', (m) => { if (m.type() === 'error') fail.push('console: ' + m.text()); });
page.on('pageerror', (e) => fail.push('pageerror: ' + e.message));
page.on('response', (r) => { if (r.status() >= 400) fail.push(`http ${r.status()} ${r.url()}`); });

const BASE = process.env.BASE || 'http://127.0.0.1:8765/';
await page.goto(BASE, { waitUntil: 'networkidle' });

/* 1. 四张一起选（3 张有效 + 1 个非 GIF 可以另测，这里先只放 3 张） */
await page.setInputFiles('#file', GIFS);
await page.waitForFunction(
  () => /张壁纸/.test(document.getElementById('srcInfo').textContent)
    || /失败|只支持/.test(document.getElementById('hint').textContent),
  null, { timeout: 30000 },
);
await page.waitForTimeout(600);

const srcInfo = await page.textContent('#srcInfo');
const rows = await page.$$eval('#wallList .wall', (els) => els.map((e) => ({
  idx: e.querySelector('.idx').textContent,
  name: e.querySelector('.nm').textContent,
  cnt: e.querySelector('.cnt').textContent,
  on: e.classList.contains('on'),
})));
if (rows.length !== 3) fail.push(`壁纸行数应为 3，实为 ${rows.length}`);
if (!rows[0] || !rows[0].on) fail.push('默认应选中第 1 页');
if (!/3 张壁纸/.test(srcInfo)) fail.push('状态栏未显示 3 张壁纸：' + srcInfo);
await page.screenshot({ path: join(OUT, 'multi-loaded.png') });

/* 2. 取画布快照的小工具 */
const snap = () => page.evaluate(() => {
  const c = document.getElementById('preview');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  return Array.from(d);
});
/** 变化像素占比（任一通道差 > 24 即算变了）—— 比全画面平均差稳，不会被大面积同色底吃掉 */
const changedRatio = (a, b) => {
  let n = 0;
  const total = a.length / 4;
  for (let i = 0; i < a.length; i += 4) {
    if (Math.abs(a[i] - b[i]) > 24 || Math.abs(a[i + 1] - b[i + 1]) > 24 || Math.abs(a[i + 2] - b[i + 2]) > 24) n++;
  }
  return n / total;
};
/**
 * 连拍 4 张（间隔 120ms，采样窗 ≈ 480ms ≈ 播放周期的一半以上）取「最接近的一对」，
 * 这样两张图的动画相位不同也不会误判。
 *
 * 前提：a.gif 和 b.gif 必须是**构图不同**的两张画。历史坑：b.gif 原来是 a.gif 的
 * 换帧数版本（frame0 像素完全一致），于是这条断言只能量到 0.86%，被误当成 app 的 bug。
 * 换页测试的素材不能是近重复图。
 */
async function wallSignature() {
  const shots = [];
  for (let i = 0; i < 4; i++) { shots.push(await snap()); await page.waitForTimeout(120); }
  return shots;
}
const sig0 = await wallSignature();

/* 3. 点第 2 页，预览应换成另一张图 */
await page.click('#wallList .wall[data-i="1"]');
await page.waitForTimeout(300);
const sig1 = await wallSignature();
let best = Infinity;
for (const a of sig0) for (const b of sig1) best = Math.min(best, changedRatio(a, b));
// 同一张 GIF 同一相位时该值≈0；换了一张构图不同的 GIF 应有 10%+ 的像素真的变了
if (best < 0.02) fail.push(`切到第 2 页后画布几乎没变（变化像素 ${(best * 100).toFixed(2)}%，应 > 2%）`);
const onAfterClick = await page.$$eval('#wallList .wall', (els) => els.map((e) => e.classList.contains('on')));
if (!onAfterClick[1] || onAfterClick[0]) fail.push('点击后高亮没跟到第 2 页');
await page.screenshot({ path: join(OUT, 'multi-wall2.png') });

/* 4. 删掉第 3 页 */
await page.click('#wallList .wall[data-i="2"] .rm');
await page.waitForTimeout(500);
const rowsAfterRm = await page.$$eval('#wallList .wall', (els) => els.length);
if (rowsAfterRm !== 2) fail.push(`删除后应剩 2 行，实为 ${rowsAfterRm}`);
const infoAfterRm = await page.textContent('#srcInfo');
if (!/2 张壁纸/.test(infoAfterRm)) fail.push('删除后状态栏未更新：' + infoAfterRm);
const hintAfterRm = await page.textContent('#hint');
if (!/8 \+ 12 帧/.test(hintAfterRm)) fail.push('删除后底部提示没重算：' + hintAfterRm);
await page.screenshot({ path: join(OUT, 'multi-after-rm.png') });

/* 5. 开息屏 → 体积里应出现息屏段 */
await page.click('#aodOn');
await page.waitForTimeout(700);
const aodCost = await page.textContent('#aodCost');
const aodRowHidden = await page.$eval('#aodRow', (e) => e.hidden);
if (aodRowHidden) fail.push('开了息屏但体积图例里没出现息屏项');
await page.screenshot({ path: join(OUT, 'multi-aod.png') });
await page.click('#viewTabs button[data-v="main"]');
await page.waitForTimeout(200);

const budget = await page.textContent('#budgetTotal');
const hint = await page.textContent('#hint');

/* 6. 生成 + 接下载 */
const [download] = await Promise.all([
  page.waitForEvent('download', { timeout: 120000 }),
  page.click('#build'),
]);
const facePath = join(OUT, download.suggestedFilename());
await download.saveAs(facePath);
await page.waitForTimeout(500);
await page.screenshot({ path: join(OUT, 'multi-done.png') });
const doneHint = await page.textContent('#hint');

console.log(JSON.stringify({
  srcInfo, rows, onAfterClick, rowsAfterRm, infoAfterRm, hintAfterRm,
  previewChangedPct: Number((best * 100).toFixed(2)),
  aodCost, budget, hint, doneHint,
  downloaded: download.suggestedFilename(),
  fail,
}, null, 2));

await browser.close();

/* 7. 产物用原仓库的独立校验器过一遍 */
if (!fail.length) {
  const out = execFileSync(py, [join(ROOT, '../tools/verify_face.py'), facePath], { encoding: 'utf8' });
  console.log('--- verify_face.py ---\n' + out.trim());
  if (!/结构正确/.test(out)) { console.log('VERDICT: 结构校验未通过'); process.exitCode = 1; }
  else console.log('VERDICT: OK');
} else {
  console.log('VERDICT: FAIL');
  process.exitCode = 1;
}
