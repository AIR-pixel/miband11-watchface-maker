/**
 * 视频输入端到端：真浏览器里选 mp4 → 抽帧 → 生成 → 用 verify_face.py 验结构。
 *
 *   node tests/ui_video.mjs            # 打本地服务 8765
 *   BASE=https://... node tests/ui_video.mjs
 *
 * 同时验两件事：
 *   1) 视频壁纸 + GIF 壁纸混排（第 2 页是 GIF），多壁纸切换照常；
 *   2) 产物能被 Pillow 逐帧打开（抽帧出来的像素是真图，不是占位）。
 */
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { unpackFace } from '../src/core/facebin.js';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
// playwright 不在本仓库依赖里（零依赖项目），从托管 workspace 取；可用 PW 环境变量覆盖
const PW = process.env.PW
  || 'C:/Users/air/.workbuddy/binaries/node/workspace/node_modules/playwright/index.js';
const py = process.env.PY || 'C:/Users/air/AppData/Local/Programs/Python/Python313/python.exe';
const pw = await import(pathToFileURL(PW).href);
const chromium = pw.chromium || (pw.default && pw.default.chromium);

const OUT = join(ROOT, 'tests/out');
mkdirSync(OUT, { recursive: true });

const MP4 = join(ROOT, 'tests/golden-src/v1.mp4');
const GIF = join(ROOT, 'tests/golden-src/a.gif');
const fail = [];

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1240, height: 1000 }, deviceScaleFactor: 2 });
page.on('console', (m) => { if (m.type() === 'error') fail.push('console: ' + m.text()); });
page.on('pageerror', (e) => fail.push('pageerror: ' + e.message));
page.on('response', (r) => { if (r.status() >= 400) fail.push(`http ${r.status()} ${r.url()}`); });

const BASE = process.env.BASE || 'http://127.0.0.1:8765/';
await page.goto(BASE, { waitUntil: 'networkidle' });

/* 1. mp4 + gif 一起选 */
await page.setInputFiles('#file', [MP4, GIF]);
await page.waitForFunction(
  () => /张壁纸/.test(document.getElementById('srcInfo').textContent)
    || /失败|不是 GIF/.test(document.getElementById('hint').textContent),
  null, { timeout: 40000 },
);
await page.waitForTimeout(500);

const rows = await page.$$eval('#wallList .wall', (els) => els.map((e) => ({
  name: e.querySelector('.nm').textContent.replace(/\s+/g, ' ').trim(),
  cnt: e.querySelector('.cnt').textContent,
})));
const srcInfo = await page.textContent('#srcInfo');
if (rows.length !== 2) fail.push(`应有 2 行，实为 ${rows.length}`);
if (!rows[0] || !/视频/.test(rows[0].name)) fail.push('第 1 行没标「视频」：' + JSON.stringify(rows[0]));
if (!rows[0] || !/36 帧/.test(rows[0].cnt)) fail.push('3s @12fps 应为 36 帧，实为 ' + (rows[0] && rows[0].cnt));
await page.screenshot({ path: join(OUT, 'video-loaded.png') });

/* 2. 预览应该画出首帧（不是纯黑） */
const lum = await page.evaluate(() => {
  const c = document.getElementById('preview');
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let s = 0;
  for (let i = 0; i < d.length; i += 4) s += d[i] + d[i + 1] + d[i + 2];
  return s / (d.length / 4) / 3;
});
if (lum < 8) fail.push(`视频首帧预览几乎是黑的（平均亮度 ${lum.toFixed(1)}）`);

/* 3. 生成（会在主线程抽 36 帧，给足时间） */
const [download] = await Promise.all([
  page.waitForEvent('download', { timeout: 180000 }),
  page.click('#build'),
]);
const facePath = join(OUT, download.suggestedFilename());
await download.saveAs(facePath);
await page.waitForTimeout(400);
await page.screenshot({ path: join(OUT, 'video-done.png') });

const doneHint = await page.textContent('#hint');

/* 3b. 视频裁切：起点 2s、时长 1s → 12 帧，且抽到的首帧必须与不裁时不同。
       只验「帧数对了」不够 —— 帧数对但时间点没加偏移（还是从 0 抽）也一样是 12 帧。 */
await page.fill('#clipStart', '2');
await page.fill('#clipDur', '1');
await page.waitForTimeout(600);
const clipHint = await page.textContent('#hint');
// 多壁纸时提示是「每张壁纸 12 + 8 帧」，单壁纸是「保留 12 帧」—— 两种都认
if (!/12 \+ 8 帧|保留 12 帧/.test(clipHint)) fail.push('视频裁到 1s 应为 12 帧：' + clipHint);
const [download2] = await Promise.all([
  page.waitForEvent('download', { timeout: 180000 }),
  page.click('#build'),
]);
const clipFacePath = join(OUT, 'clip_' + download2.suggestedFilename());
await download2.saveAs(clipFacePath);
const clipDoneHint = await page.textContent('#hint');
await page.screenshot({ path: join(OUT, 'video-clip.png') });

await browser.close();

/* 4. 抽出来的帧必须真的是不同画面。
     重复帧 = seek 没生效 / drawImage 拿到旧帧 —— 产物结构完全正常，只是变成了幻灯片，
      只有比对帧内容才看得出来。测试视频是 testsrc2（每帧都变），所以要求 0 重复。 */
const faceBytes = new Uint8Array(readFileSync(facePath));
const vFrames = unpackFace(faceBytes).files.filter((f) => /^lua\/face_\d+\.png$/.test(f.name));
const sameBytes = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const dups = [];
for (let i = 1; i < vFrames.length; i++) {
  if (sameBytes(vFrames[i - 1].data, vFrames[i].data)) dups.push(i);
}
if (vFrames.length < 2) fail.push(`视频只抽出 ${vFrames.length} 帧`);
if (dups.length) fail.push(`相邻帧有 ${dups.length} 对字节完全相同（第 ${dups.join(',')} 帧）—— seek 没生效`);
const perFrameAvg = vFrames.length
  ? +(vFrames.reduce((a, f) => a + f.data.length, 0) / vFrames.length).toFixed(0)
  : 0;

// 裁切后的那一次：12 帧，首帧必须与不裁的首帧不同（证明时间点真的加了偏移）
const cFrames = unpackFace(new Uint8Array(readFileSync(clipFacePath)))
  .files.filter((f) => /^lua\/face_\d+\.png$/.test(f.name));
if (cFrames.length !== 12) fail.push(`视频裁到 1s 应抽出 12 帧，实为 ${cFrames.length}`);
if (cFrames.length && vFrames.length && sameBytes(cFrames[0].data, vFrames[0].data)) {
  fail.push('裁切后的首帧与不裁的首帧字节相同 —— 时间点没加起点偏移');
}

console.log(JSON.stringify({ srcInfo, rows, previewLuma: +lum.toFixed(1), doneHint,
  videoFrames: vFrames.length, dupPairs: dups.length, avgFrameBytes: perFrameAvg,
  clip: { hint: clipHint, done: clipDoneHint, frames: cFrames.length }, fail }, null, 2));

/* 5. 结构 + 逐帧可解码 */
if (!fail.length) {
  const out = execFileSync(py, [join(ROOT, '../tools/verify_face.py'), facePath], { encoding: 'utf8' });
  console.log('--- verify_face.py ---\n' + out.trim());
  if (!/结构正确/.test(out)) { console.log('VERDICT: 结构校验未通过'); process.exitCode = 1; }
  else {
    // 直接用仓库的 facebin 解包 + Pillow 逐帧开
    const py2 = `
import sys, io
sys.path.insert(0, r"${join(ROOT, '../watchface-tool').replace(/\\/g, '/')}")
from watchface_tool import facebin
from PIL import Image
d = open(r"${facePath.replace(/\\/g, '/')}", "rb").read()
f = facebin.unpack_face(d)
frames = [(n, b) for n, b in f["files"] if n.startswith("lua/face_")]
bad = 0
for n, b in frames:
    try:
        im = Image.open(io.BytesIO(b))
        if im.size != (212, 520) or im.mode != "P":
            print("  尺寸/模式不对", n, im.size, im.mode); bad += 1
    except Exception as e:
        print("  打不开", n, e); bad += 1
print("帧图 %d 张，坏图 %d 张" % (len(frames), bad))
sys.exit(1 if bad else 0)
`;
    const out2 = execFileSync(py, ['-c', py2], { encoding: 'utf8' });
    console.log('--- Pillow 逐帧 ---\n' + out2.trim());
    console.log(out2.includes('坏图 0 张') ? 'VERDICT: OK' : 'VERDICT: FAIL');
    if (!out2.includes('坏图 0 张')) process.exitCode = 1;
  }
} else {
  console.log('VERDICT: FAIL');
  process.exitCode = 1;
}
