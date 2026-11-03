/**
 * UI 端到端：JPEG + 截取区间 + 多壁纸，三件一起开。
 *
 * 单测（tests/clip_fmt.mjs）验的是 core；这个文件验的是「界面上的三个控件真的接上了」——
 * 体积预算会不会跟着格式/质量动、提示里的帧数会不会跟着裁切动、产物扩展名与 Lua 的 EXT
 * 会不会跟着格式动。三件事各自能过、串起来错，是最容易漏的一类。
 *
 *   node tests/ui_fmt_clip.mjs
 *
 * 前置：node tests/serve.mjs 8765 已在跑。
 */
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { unpackFace } from '../src/core/facebin.js';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const py = process.env.PY || 'C:/Users/air/AppData/Local/Programs/Python/Python313/python.exe';
const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });
const fail = [];
const ok = (label, cond, detail = '') => { if (!cond) fail.push(`${label}${detail ? '：' + detail : ''}`); };

// long.gif 3.0s（裁得出东西）、a.gif 0.72s（起点 1.5s 已超长 → 应退化成全片）
const FILES = ['long.gif', 'a.gif'].map((n) => join(ROOT, 'tests/golden-src', n));

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1240, height: 1100 }, deviceScaleFactor: 2 });
page.on('console', (m) => { if (m.type() === 'error') fail.push('console: ' + m.text()); });
page.on('pageerror', (e) => fail.push('pageerror: ' + e.message));
page.on('response', (r) => { if (r.status() >= 400) fail.push(`http ${r.status()} ${r.url()}`); });

await page.goto(process.env.BASE || 'http://127.0.0.1:8765/', { waitUntil: 'networkidle' });

/* 1. 两张素材 */
await page.setInputFiles('#file', FILES);
await page.waitForFunction(
  () => /张壁纸/.test(document.getElementById('srcInfo').textContent)
    || /失败|只支持/.test(document.getElementById('hint').textContent),
  null, { timeout: 30000 },
);
await page.waitForTimeout(500);
const srcInfo = await page.textContent('#srcInfo');
ok('两张素材都进来了', /2 张壁纸/.test(srcInfo), srcInfo);
const pngHint = await page.textContent('#hint');
const pngBudget = await page.textContent('#budgetTotal');
// PNG 模式下 JPEG 质量那行必须是隐藏的。这条之前漏了：`.row{display:flex}` 会盖掉
// 浏览器默认的 `[hidden]{display:none}`，于是那行一直显示着，只有看截图才发现。
ok('PNG 模式下不显示 JPEG 质量', await page.$eval('#jpgRow', (e) => e.hidden
  && getComputedStyle(e).display === 'none'),
  `hidden=${await page.$eval('#jpgRow', (e) => e.hidden)} display=${await page.$eval('#jpgRow', (e) => getComputedStyle(e).display)}`);
await page.screenshot({ path: join(OUT, 'fmtclip-1-loaded.png') });

/* 2. 切 JPEG：质量行出现、画质档位置灰、预算跟着变 */
await page.click('#fmt button[data-v="jpg"]');
await page.waitForTimeout(600);
const jpgRowHidden = await page.$eval('#jpgRow', (e) => e.hidden);
ok('JPEG 质量行应出现', !jpgRowHidden);
const levelDisabled = await page.$$eval('#level button', (els) => els.every((b) => b.disabled));
ok('JPEG 下调色板档位应置灰', levelDisabled);
const jpgBudget = await page.textContent('#budgetTotal');
ok('换格式后体积预算变了', pngBudget !== jpgBudget, `PNG ${pngBudget} / JPEG ${jpgBudget}`);
await page.screenshot({ path: join(OUT, 'fmtclip-2-jpg.png') });

/* 3. 降到 q60：预算应再变小 */
await page.selectOption('#jpgQuality', '60');
await page.waitForTimeout(600);
const q60Budget = await page.textContent('#budgetTotal');
ok('降低质量后预算变小', parseInt(q60Budget.replace(/\D/g, ''), 10) < parseInt(jpgBudget.replace(/\D/g, ''), 10),
  `q80 ${jpgBudget} / q60 ${q60Budget}`);
await page.selectOption('#jpgQuality', '70');
await page.waitForTimeout(500);

/* 3b. 切回 PNG 再切回 JPEG：质量行要能真的收起来（这就是上面那个 CSS 坑的现场） */
await page.click('#fmt button[data-v="png"]');
await page.waitForTimeout(250);
ok('切回 PNG 后质量行重新收起', await page.$eval('#jpgRow', (e) => e.hidden
  && getComputedStyle(e).display === 'none'),
  `display=${await page.$eval('#jpgRow', (e) => getComputedStyle(e).display)}`);
ok('切回 PNG 后档位恢复可点', !(await page.$$eval('#level button', (els) => els.some((b) => b.disabled))));
await page.click('#fmt button[data-v="jpg"]');
await page.waitForTimeout(300);

/* 4. 设截取区间 1.5s 起、1.0s 长 */
await page.fill('#clipStart', '1.5');
await page.fill('#clipDur', '1.0');
await page.waitForTimeout(700);
const clipHint = await page.textContent('#hint');
// long.gif 3.0s → 12 帧；a.gif 0.72s（起点超长退化成全片）→ 8 帧
ok('帧数按裁切后算（12 + 8）', /12 \+ 8 帧/.test(clipHint), clipHint);
ok('提示里写了截取区间', /截取 1\.5s 起 1\.0s/.test(clipHint), clipHint);
const clipBudget = await page.textContent('#budgetTotal');
ok('裁切后预算跟着降', parseInt(clipBudget.replace(/\D/g, ''), 10) < parseInt(jpgBudget.replace(/\D/g, ''), 10),
  `未裁 ${jpgBudget} / 裁后 ${clipBudget}`);
await page.screenshot({ path: join(OUT, 'fmtclip-3-clip.png') });

/* 5. 生成 */
const [download] = await Promise.all([
  page.waitForEvent('download', { timeout: 120000 }),
  page.click('#build'),
]);
const facePath = join(OUT, download.suggestedFilename());
await download.saveAs(facePath);
await page.waitForTimeout(400);
const doneHint = await page.textContent('#hint');
await page.screenshot({ path: join(OUT, 'fmtclip-4-done.png') });

/* 6. 产物独立核对 */
const u = unpackFace(new Uint8Array(readFileSync(facePath)));
const lua = new TextDecoder().decode(u.files.find((f) => /main\.lua$/.test(f.name)).data);
const imgFiles = u.files.filter((f) => /^lua\/.*\.(png|jpg)$/.test(f.name));
const pages = [...lua.matchAll(/\{ prefix = "([^"]+)", count = (\d+), period = (\d+) \}/g)]
  .map((m) => ({ prefix: m[1], count: Number(m[2]) }));

ok('产物帧全是 .jpg', imgFiles.length > 0 && imgFiles.every((f) => f.name.endsWith('.jpg')),
  imgFiles.filter((f) => !f.name.endsWith('.jpg')).map((f) => f.name).join(', '));
ok('Lua 的 EXT = jpg', /local EXT = "jpg"/.test(lua),
  (lua.match(/local EXT = "(\w+)"/) || [])[1] || '没找到');
ok('产物帧数 = 12 + 8', imgFiles.length === 20, `得到 ${imgFiles.length}`);
ok('Lua 页数与帧数对得上',
  JSON.stringify(pages.map((p) => [p.prefix, p.count])) === JSON.stringify([['face', 12], ['w2', 8]]),
  JSON.stringify(pages));
ok('多壁纸有短按切换', /showWall\(activeWall % #wallObjs \+ 1\)/.test(lua));
ok('哨兵 idx = 第一页帧数', u.sentinelIdx === 12, `得到 ${u.sentinelIdx}`);
ok('每帧 JPEG 完整（SOI…EOI）',
  imgFiles.every((f) => f.data[0] === 0xff && f.data[1] === 0xd8
    && f.data[f.data.length - 2] === 0xff && f.data[f.data.length - 1] === 0xd9));
ok('完成提示里报了格式与帧数', /20 帧/.test(doneHint) && /JPEG q70/.test(doneHint), doneHint);

console.log(JSON.stringify({
  srcInfo, pngHint, pngBudget, jpgBudget, q60Budget, clipHint, clipBudget, doneHint,
  downloaded: download.suggestedFilename(),
  files: imgFiles.map((f) => f.name),
  pages,
  sentinelIdx: u.sentinelIdx,
  bytesKB: +(imgFiles.reduce((a, f) => a + f.data.length, 0) / 1024).toFixed(0),
  fail,
}, null, 2));

await browser.close();

/* 7. 原仓库的独立校验器 */
if (!fail.length) {
  const out = execFileSync(py, [join(ROOT, '../tools/verify_face.py'), facePath], { encoding: 'utf8' });
  console.log('--- verify_face.py ---\n' + out.trim());
  if (/结构正确/.test(out)) console.log('VERDICT: OK');
  else { console.log('VERDICT: 结构校验未通过'); process.exitCode = 1; }
} else {
  console.log('VERDICT: FAIL');
  process.exitCode = 1;
}
