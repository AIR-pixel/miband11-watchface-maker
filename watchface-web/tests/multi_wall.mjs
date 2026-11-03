/**
 * 多壁纸冒烟：2~3 张 GIF → 多页表盘，检查页数、帧分配、哨兵 idx、Lua 的 WALLS 表。
 *
 *   node tests/multi_wall.mjs <out.face> <a.gif> <b.gif> [c.gif ...]
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildFaceFromGif } from '../src/core/build.js';
import { unpackFace } from '../src/core/facebin.js';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const [, , outArg, ...gifArgs] = process.argv;
// 不给参数就用 golden-src 里的三张 GIF（可直接 `node tests/multi_wall.mjs` 跑）
const outPath = outArg || here('./out/multi_wall.face');
// out/ 是 gitignore 里的可再生产物目录，新克隆时不存在 —— 自己建，别依赖它先天就在
mkdirSync(dirname(outPath), { recursive: true });
const gifs = gifArgs.length ? gifArgs
  : ['a', 'b', 'c'].map((n) => here(`./golden-src/${n}.gif`));
const sources = gifs.map((p) => new Uint8Array(readFileSync(p)));
const t0 = Date.now();

const res = await buildFaceFromGif({
  gifs: sources,
  fps: 8,
  maxFrames: 24,
  level: 'tiny',
  showDate: true,
  title: 'MultiWall',
  faceId: '3000000001',
});
writeFileSync(outPath, res.face);

const u = unpackFace(res.face);
const lua = new TextDecoder().decode(u.files.find((f) => /main\.lua$/.test(f.name)).data);
const pageRows = [...lua.matchAll(/\{ prefix = "([^"]+)", count = (\d+), period = (\d+) \}/g)]
  .map((m) => ({ prefix: m[1], count: Number(m[2]), period: Number(m[3]) }));

const prefixCounts = {};
for (const f of u.files) {
  const m = /^lua\/(\w+?)_\d+\.png$/.exec(f.name);
  if (m) prefixCounts[m[1]] = (prefixCounts[m[1]] || 0) + 1;
}

const report = {
  walls: res.stats.walls,
  framesPerWall: res.stats.framesPerWall,
  filePrefixCounts: prefixCounts,
  luaPages: pageRows,
  luaHasCycle: /showWall\(activeWall % #wallObjs \+ 1\)/.test(lua),
  sentinelIdx: u.sentinelIdx,
  expectSentinel: res.stats.framesPerWall[0],
  bytes: res.face.length,
  ms: Date.now() - t0,
  out: outPath,
};

const fail = [];
if (report.walls !== sources.length) fail.push('页数不对');
if (JSON.stringify(pageRows.map((p) => p.count)) !== JSON.stringify(report.framesPerWall)) fail.push('Lua 里的页帧数与实际不符');
if (report.sentinelIdx !== report.expectSentinel) fail.push(`哨兵 idx=${report.sentinelIdx}，应为第一页帧数 ${report.expectSentinel}`);
for (const [prefix, n] of Object.entries(prefixCounts)) {
  const row = pageRows.find((p) => p.prefix === prefix);
  if (!row || row.count !== n) fail.push(`前缀 ${prefix} 的文件数 ${n} 与 Lua 不符`);
}
if (sources.length > 1 && !report.luaHasCycle) fail.push('多壁纸没有短按切换');

console.log(JSON.stringify({ ...report, fail }, null, 2));
process.exit(fail.length ? 1 : 0);
