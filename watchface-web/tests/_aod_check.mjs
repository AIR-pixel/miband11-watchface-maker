/**
 * 把 .face 里的 AOD 描述块摊平，检查分组顺序、偏移是否落在素材区里。
 * 纯检查用，不做修复。
 */
import { readFileSync } from 'node:fs';

export function unfoldAod(bytes) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u16 = (o) => v.getUint16(o, true);
  const u32 = (o) => v.getUint32(o, true);
  const hasAod = u16(28) === 2;
  if (!hasAod) return [];
  const n = u32(216);
  const idx = 360;
  const d0 = idx + n * 16;
  const records = [];
  for (let p = d0; p < bytes.length; p += 16) {
    const tag = u16(p + 2);
    if (tag === 0x0500) break;
    records.push({ idx: u16(p), tag, off: u32(p + 8), size: u32(p + 12) });
  }
  return records;
}

if (process.argv[2]) {
  const bytes = new Uint8Array(readFileSync(process.argv[2]));
  const recs = unfoldAod(bytes);
  const names = { 0x0000: '锚点', 0x0200: '位图', 0x0300: '数组', 0x0700: '小件' };
  console.log(`AOD 描述记录 ${recs.length} 条`);
  for (const r of recs) {
    console.log(`  ${names[r.tag] || '?'} idx=${r.idx} off=${r.off} size=${r.size}`);
  }
}
