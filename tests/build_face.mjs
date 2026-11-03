/**
 * 端到端冒烟：拿一份 GIF 走完整链路产出 .face，写到临时目录。
 *
 *   node tests/build_face.mjs [in.gif] [out.face] [--level tiny] [--fps 8] [--max 48]
 *
 * 不给参数就用 tests/golden-src/a.gif（可直接 `node tests/build_face.mjs` 跑）。
 * 产物要再用仓库的 tools/verify_face.py 独立验一遍结构（另一步，见 README）。
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildFaceFromGif, asciiField, faceFileName } from '../src/core/build.js';
import { unpackFace } from '../src/core/facebin.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

const args = process.argv.slice(2);
const gifPath = args[0] || here('./golden-src/a.gif');
const outPath = args[1] || here('./out/build_face.face');
// out/ 是 gitignore 里的可再生产物目录，新克隆时不存在 —— 自己建，别依赖它先天就在
mkdirSync(dirname(outPath), { recursive: true });
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : dflt;
};

const gifBytes = new Uint8Array(readFileSync(gifPath));
const t0 = Date.now();
const res = await buildFaceFromGif({
  gifBytes,
  fps: Number(opt('fps', 8)),
  maxFrames: Number(opt('max', 48)),
  level: opt('level', 'balanced'),
  showDate: args.includes('--date'),
  title: opt('title', 'WebFace'),
  faceId: opt('id', '1000000001'),
  onProgress: (r, msg) => { if (!process.env.QUIET) console.log((r * 100).toFixed(0).padStart(3), msg); },
});
writeFileSync(outPath, res.face);

// ---- 自检：容器能被自己拆开，且结构对得上 ----
const u = unpackFace(res.face);
const frames = u.files.filter((f) => /^lua\/face_\d+\.png$/.test(f.name)).length;
const pngs = u.files.filter((f) => /\.png$/.test(f.name)).length;
const hasLua = u.files.some((f) => /main\.lua$/.test(f.name));

const fail = [];
if (!hasLua) fail.push('缺 main.lua');
if (frames !== res.stats.frames) fail.push(`face_ 帧图 ${frames} 与 stats.frames ${res.stats.frames} 不符`);
if (!pngs) fail.push('没有帧图');
if (u.sentinelIdx !== res.stats.frames) fail.push(`哨兵 idx=${u.sentinelIdx}，应为帧数 ${res.stats.frames}`);
if (res.stats.bytes !== res.face.length) fail.push('stats.bytes 与实际长度不符');

// ---- Title / ID 是定长 ASCII 字段：非 ASCII 要逐字符变 '?' ----
// 规则必须与 PC 端 `_fixed_ascii`（Python encode("ascii","replace")）一致，
// 否则两端同参数产出的字节会不一样。
const zh = await buildFaceFromGif({
  gifBytes, fps: 8, maxFrames: 3, level: 'tiny',
  title: '表盘Ab', faceId: '1234567890',
});
const uz = unpackFace(zh.face);
// "表盘Ab" 是 4 个码点 → 前两个汉字各换一个 '?'，得到 "??Ab"（不是 4 个 '?'，
// 也不是 UTF-8 的 6 字节）。这条同时锁住了「按码点替换」这个细节。
if (uz.title !== '??Ab') fail.push(`中文 Title 应变成 "??Ab"，实为 "${uz.title}"`);
if (uz.faceId !== '1234567890') fail.push(`ID 回读不对："${uz.faceId}"`);
if (uz.idLen !== 10) fail.push(`[5] ID 长度应为 10，实为 ${uz.idLen}`);
// 文件名走另一条规则：保留中文，只清非法字符
if (zh.faceName !== '表盘Ab.face') fail.push(`文件名应保留中文，实为 "${zh.faceName}"`);
if (faceFileName('a/b:c') !== 'a_b_c.face') fail.push(`非法字符没清：${faceFileName('a/b:c')}`);
if (faceFileName('   ') !== 'MyFace.face') fail.push('空名应回退 MyFace');
if (asciiField('x'.repeat(20), 16) !== 'x'.repeat(16)) fail.push('ASCII 超长没截断');

console.log(JSON.stringify({
  src: gifPath,
  ...res.stats,
  ms: Date.now() - t0,
  out: outPath,
  unpacked: { files: u.files.length, frames, hasLua, sentinelIdx: u.sentinelIdx, title: u.title, faceId: u.faceId },
  asciiTitle: { input: '表盘Ab', stored: uz.title, faceId: uz.faceId, idLen: uz.idLen },
  fail,
}, null, 2));
process.exit(fail.length ? 1 : 0);
