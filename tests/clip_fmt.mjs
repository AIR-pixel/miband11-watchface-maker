/**
 * 截取区间 × 编码格式 × 多壁纸 —— 三件事一起验。
 *
 * 为什么要放一个文件里：这三项互相咬合。裁切决定帧数，帧数决定体积，
 * 格式决定扩展名（而扩展名又会写进 Lua 的 `EXT`，写错手环直接黑屏）。
 * 分开验能过、合起来错，是最容易漏的一类。
 *
 *   node tests/clip_fmt.mjs
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { buildFace, clipRange, planFrames, planUniform, encodeFrame } from '../src/core/build.js';
import { unpackFace, PREVIEW_W, PREVIEW_H } from '../src/core/facebin.js';
import { decodeGif } from '../src/core/gif.js';
import { coverRGBA } from '../src/core/image.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const load = (n) => new Uint8Array(readFileSync(here(`./golden-src/${n}`)));
// out/ 是 gitignore 里的可再生产物目录，新克隆时不存在 —— 自己建，别依赖它先天就在
mkdirSync(here('./out'), { recursive: true });

const fail = [];
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail.push(`${label}：得到 ${JSON.stringify(got)}，应为 ${JSON.stringify(want)}`);
  return ok;
};
const ok = (label, cond, detail = '') => {
  if (!cond) fail.push(`${label}${detail ? '：' + detail : ''}`);
};

/* ───────── 1. clipRange：秒 → 毫秒区间，带夹取 ───────── */

const D = 8000;
eq('全片', clipRange(D, 0, 0), { startMs: 0, endMs: 8000, spanMs: 8000 });
eq('留空字符串', clipRange(D, '', ''), { startMs: 0, endMs: 8000, spanMs: 8000 });
eq('起点 2s 时长 3s', clipRange(D, 2, 3), { startMs: 2000, endMs: 5000, spanMs: 3000 });
eq('时长超出尾部（夹到结尾）', clipRange(D, 7, 5), { startMs: 7000, endMs: 8000, spanMs: 1000 });
eq('起点超出全长（退化成全片）', clipRange(D, 99, 0), { startMs: 0, endMs: 8000, spanMs: 8000 });
eq('只给起点', clipRange(D, 1.5, 0), { startMs: 1500, endMs: 8000, spanMs: 6500 });
eq('负数当 0', clipRange(D, -3, -1), { startMs: 0, endMs: 8000, spanMs: 8000 });

/* ───────── 2. 选帧：只在区间里挑，帧数按区间算 ───────── */

const long = decodeGif(load('long.gif'));
const delays = long.frames.map((f) => f.delayMs);
const totalMs = delays.reduce((a, b) => a + b, 0);
eq('素材总长', totalMs, 3000);

const starts = (() => { const out = []; let t = 0; for (const d of delays) { out.push(t); t += d; } return out; })();

const full = planFrames(delays, 12, 96, clipRange(totalMs, 0, 0));
const clipped = planFrames(delays, 12, 96, clipRange(totalMs, 1.5, 1.0));

ok('不裁时帧数按全长算', full.indices.length === 36, `得到 ${full.indices.length}，应为 36`);
ok('裁 1s 时帧数按区间算', clipped.indices.length === 12, `得到 ${clipped.indices.length}，应为 12`);
eq('区间原样传出', { s: clipped.clipStartMs, d: clipped.durationMs }, { s: 1500, d: 1000 });

const picked = clipped.indices.map((k) => starts[k]);
ok('选中的帧全部落在区间内',
  picked.every((t) => t >= 1500 - 1e-6 && t < 2500 - 1e-6), JSON.stringify(picked));
ok('首帧就在区间起点附近', Math.abs(picked[0] - 1500) <= 100, `首帧 ${picked[0]}ms`);
ok('裁切前后的帧确实不同', JSON.stringify(full.indices.slice(0, 12)) !== JSON.stringify(clipped.indices),
  '两组下标完全一样，说明没真裁');

// 视频那条路：时间点必须带起点偏移，否则抽出来还是全片开头
const uni = planUniform(totalMs, 12, 96, clipRange(totalMs, 1.5, 1.0));
eq('视频 12 个时间点', uni.times.length, 12);
ok('视频时间点从 1500 开始', uni.times[0] === 1500, `得到 ${uni.times[0]}`);
ok('视频时间点不超过区间末尾', uni.times.every((t) => t < 2500), JSON.stringify(uni.times));

/* ───────── 3. 端到端：JPEG + 裁切 ───────── */

const t0 = Date.now();
const jpgRes = await buildFace({
  sources: [{ kind: 'gif', bytes: load('long.gif'), clip: clipRange(totalMs, 1.5, 1.0) }],
  fps: 12, maxFrames: 96, fmt: 'jpg', jpgQuality: 80,
  showTime: true, title: 'ClipJpg', faceId: '4000000001',
});
writeFileSync(here('./out/clip_jpg.face'), jpgRes.face);
const jpgMs = Date.now() - t0;

const u = unpackFace(jpgRes.face);
const lua = new TextDecoder().decode(u.files.find((f) => /main\.lua$/.test(f.name)).data);
const imgFiles = u.files.filter((f) => /^lua\/.*\.(png|jpg)$/.test(f.name));

ok('JPEG 帧扩展名', imgFiles.every((f) => f.name.endsWith('.jpg')),
  imgFiles.map((f) => f.name).filter((n) => !n.endsWith('.jpg')).join(', '));
ok('Lua 的 EXT 跟着改成 jpg', /local EXT = "jpg"/.test(lua),
  (lua.match(/local EXT = "(\w+)"/) || [])[1] || '没找到 EXT');
eq('产物里帧数 = 裁切后帧数', imgFiles.length, 12);
eq('stats 记的格式', { fmt: jpgRes.stats.fmt, q: jpgRes.stats.jpgQuality }, { fmt: 'jpg', q: 80 });
ok('每帧都是完整 JPEG（SOI…EOI）',
  imgFiles.every((f) => f.data[0] === 0xff && f.data[1] === 0xd8
    && f.data[f.data.length - 2] === 0xff && f.data[f.data.length - 1] === 0xd9));
ok('文件按名字升序进索引表',
  u.files.map((f) => f.name).join() === [...u.files.map((f) => f.name)].sort().join());

// 同一段素材、换个起点：首帧字节必须变 —— 这才是「裁到的是另一段」的铁证
const jpgRes2 = await buildFace({
  sources: [{ kind: 'gif', bytes: load('long.gif'), clip: clipRange(totalMs, 0, 1.0) }],
  fps: 12, maxFrames: 96, fmt: 'jpg', jpgQuality: 80,
  showTime: true, title: 'ClipJpg2', faceId: '4000000002',
});
const firstFrame = (res) => unpackFace(res.face).files.find((f) => /^lua\/face_01\./.test(f.name)).data;
ok('不同起点抽到的首帧不同',
  Buffer.compare(Buffer.from(firstFrame(jpgRes)), Buffer.from(firstFrame(jpgRes2))) !== 0,
  '两段裁切的首帧字节完全一样');

/* ───────── 4. 端到端：多壁纸 + 各自裁切 ───────── */

const aGif = load('a.gif');
const aTotal = decodeGif(aGif).frames.reduce((s, f) => s + f.delayMs, 0);
const multi = await buildFace({
  sources: [
    // 起点 1.5s：只有 long.gif 有（3s），a.gif 只有 0.72s → 已超长，退化成全片
    { kind: 'gif', bytes: load('long.gif'), clip: clipRange(totalMs, 1.5, 1.0) },
    { kind: 'gif', bytes: aGif, clip: clipRange(aTotal, 1.5, 1.0) },
  ],
  fps: 12, maxFrames: 96, fmt: 'jpg', jpgQuality: 80,
  showTime: true, title: 'ClipMulti', faceId: '4000000003',
});
writeFileSync(here('./out/clip_multi.face'), multi.face);
const mu = unpackFace(multi.face);
const mLua = new TextDecoder().decode(mu.files.find((f) => /main\.lua$/.test(f.name)).data);
const pageRows = [...mLua.matchAll(/\{ prefix = "([^"]+)", count = (\d+), period = (\d+) \}/g)]
  .map((m) => ({ prefix: m[1], count: Number(m[2]) }));

eq('两张壁纸各按自己的长度裁', multi.stats.framesPerWall, [12, 8]);
eq('Lua 页数与帧数对上', pageRows.map((p) => [p.prefix, p.count]), [['face', 12], ['w2', 8]]);
ok('多壁纸默认短按切换', /showWall\(activeWall % #wallObjs \+ 1\)/.test(mLua));
eq('哨兵 idx = 第一页帧数', mu.sentinelIdx, 12);
ok('每页的文件数都对得上',
  ['face', 'w2'].every((p) => mu.files.filter((f) => new RegExp(`^lua/${p}_\\d+\\.jpg$`).test(f.name)).length
    === pageRows.find((r) => r.prefix === p).count));

/* ───────── 5. PNG 这条老路没被改坏 ───────── */

const pngRes = await buildFace({
  sources: [{ kind: 'gif', bytes: load('long.gif'), clip: clipRange(totalMs, 0, 1.0) }],
  fps: 12, maxFrames: 96, fmt: 'png', level: 'tiny',
  showTime: true, title: 'ClipPng', faceId: '4000000004',
});
const pu = unpackFace(pngRes.face);
const pLua = new TextDecoder().decode(pu.files.find((f) => /main\.lua$/.test(f.name)).data);
ok('PNG 帧仍是 .png', pu.files.filter((f) => /^lua\/.*\.(png|jpg)$/.test(f.name)).every((f) => f.name.endsWith('.png')));
ok('PNG 的 EXT 仍是 png', /local EXT = "png"/.test(pLua));
eq('PNG 的 jpgQuality 置空', pngRes.stats.jpgQuality, null);

// JPEG 的体积优势只在「画面上真的有连续色调」时成立。long.gif 只有 32 色调色板、
// 大片纯色，PNG 能压到 1.3 KB/帧，拿它比等于给 JPEG 判死刑 —— 这里换 w2.gif（波纹光晕，
// 典型渐变画面），同一帧比 P256 PNG 与 q80 JPEG。
const rich = decodeGif(load('w2.gif'));
const richRgba = coverRGBA(rich.frames[0].rgba, rich.width, rich.height, PREVIEW_W, PREVIEW_H);
const pngP256 = (await encodeFrame(richRgba, 256, 'png')).length;
const jpgQ80 = (await encodeFrame(richRgba, 256, 'jpg', 80)).length;
ok('连续色调画面上 JPEG q80 比 P256 PNG 小', jpgQ80 < pngP256,
  `JPEG ${(jpgQ80 / 1024).toFixed(1)} KB vs PNG P256 ${(pngP256 / 1024).toFixed(1)} KB`);

/* ───────── 报告 ───────── */

const report = {
  clip: { totalMs, fullFrames: full.indices.length, clippedFrames: clipped.indices.length },
  jpg: {
    frames: jpgRes.stats.frames,
    imageBytes: jpgRes.stats.imageBytes,
    perFrameKB: +(jpgRes.stats.imageBytes / jpgRes.stats.frames / 1024).toFixed(1),
    totalKB: +(jpgRes.face.length / 1024).toFixed(0),
    ms: jpgMs,
  },
  multi: { framesPerWall: multi.stats.framesPerWall, bytes: multi.face.length },
  png: { frames: pngRes.stats.frames, imageBytes: pngRes.stats.imageBytes },
  fail,
};
console.log(JSON.stringify(report, null, 2));
process.exit(fail.length ? 1 : 0);
