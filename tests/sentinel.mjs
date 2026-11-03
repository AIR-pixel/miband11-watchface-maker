/**
 * 打印"描述块哨兵"的 idx —— 在多壁纸场景下它不是 n-1，得单独看。
 *   node tests/sentinel.mjs <a.face> ...
 */
import { readFileSync } from 'node:fs';

for (const p of process.argv.slice(2)) {
  const b = new Uint8Array(readFileSync(p));
  const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const u16 = (o) => v.getUint16(o, true);
  const u32 = (o) => v.getUint32(o, true);
  const hasAod = u16(28) === 2;
  const n = u32(216);
  const idx = hasAod ? 360 : 272;
  const d0 = idx + n * 16;
  const frames = u32(0) ? 0 : 0;
  console.log(`${p.split(/[\\/]/).pop()}  n=${n} hasAod=${hasAod} sentinel.idx=${u16(d0)} tag=0x${u16(d0 + 2).toString(16)}`);
}
