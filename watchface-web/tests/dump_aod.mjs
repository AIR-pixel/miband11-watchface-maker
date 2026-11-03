/**
 * 把 .face 里的 AOD 数字位图摊出来看一眼（白字黑底），确认字形没被裁掉、位置正常。
 *   node tests/dump_aod.mjs <x.face> <out.png>
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { unpackFace } from '../src/core/facebin.js';
import { quantize } from '../src/core/quantize.js';
import { encodePNG } from '../src/core/png.js';

const [, , facePath, outPath] = process.argv;
const u = unpackFace(new Uint8Array(readFileSync(facePath)));
if (!u.hasAod) throw new Error('这份 .face 没有 AOD');

const arr = u.recs.find((r) => r.tag === 0x0300);
if (!arr) throw new Error('没有位图数组');
const p = arr.payload;
const dv = new DataView(p.buffer, p.byteOffset, p.byteLength);
const count = p[1];
const w = dv.getUint16(4, true);
const h = dv.getUint16(6, true);
const px = p.subarray(12);

// 拼成一行 count 张，黑底白字
const W = w * count;
const H = h;
const rgba = new Uint8Array(W * H * 4);
for (let i = 0; i < W * H; i++) {
  rgba[i * 4] = 10; rgba[i * 4 + 1] = 10; rgba[i * 4 + 2] = 12; rgba[i * 4 + 3] = 255;
}
for (let g = 0; g < count; g++) {
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const src = (g * w * h + y * w + x) * 4;
      const a = px[src + 3] / 255;
      const o = (y * W + g * w + x) * 4;
      rgba[o] = Math.round(10 + (px[src + 2] - 10) * a);
      rgba[o + 1] = Math.round(10 + (px[src + 1] - 10) * a);
      rgba[o + 2] = Math.round(12 + (px[src] - 12) * a);
    }
  }
}
const { indices, palette } = quantize(rgba, 32, false);
writeFileSync(outPath, await encodePNG(indices, palette, W, H));
console.log(`AOD 数字 ${count} 张 ${w}×${h} → ${outPath}`);
