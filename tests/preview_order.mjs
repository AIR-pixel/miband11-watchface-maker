// 校验尾部预览位图的通道序：拿 Compiler 产物和我们自己的产物对比通道均值。
// 素材背景是深蓝 (12,14,24) → 若存成 BGRA，则 byte0 均值 > byte2 均值。
import { readFileSync } from 'node:fs';
const stat = (p) => {
  const b = new Uint8Array(readFileSync(p));
  const pv = b.subarray(b.length - 440960);
  let s0 = 0, s1 = 0, s2 = 0;
  for (let i = 0; i < pv.length; i += 4) { s0 += pv[i]; s1 += pv[i + 1]; s2 += pv[i + 2]; }
  const n = pv.length / 4;
  return [s0 / n, s1 / n, s2 / n].map((v) => v.toFixed(1)).join(' / ');
};
for (const p of process.argv.slice(2)) console.log(p.split(/[\\/]/).pop(), 'byte0/1/2 =', stat(p));
