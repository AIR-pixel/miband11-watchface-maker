/**
 * 把 .face 里的文件项全部导出来（帧图 + main.lua），用于肉眼检查或第三方解码验证。
 *   node tests/extract_files.mjs <x.face> <outDir>
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, basename } from 'node:path';
import { unpackFace } from '../src/core/facebin.js';

const [, , facePath, outDir] = process.argv;
const u = unpackFace(new Uint8Array(readFileSync(facePath)));
mkdirSync(outDir, { recursive: true });
for (const f of u.files) {
  const name = basename(f.name);
  writeFileSync(join(outDir, name), f.data);
}
console.log(`导出 ${u.files.length} 个文件 → ${outDir}`);
