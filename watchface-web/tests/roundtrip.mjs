/**
 * 往返回归：把每份真实 .face 拆开再用我们自己的打包器重新拼回去，逐字节比对。
 *
 * 这是「纯代码打包器能不能替代 Compiler.exe」的最强证据 —— 样本全是
 * 官方编译器产物（含 AOD、多壁纸、对齐 0/1/2/3 四种余数），一份都不能差。
 *
 *   node tests/roundtrip.mjs [样本目录]
 *
 * 默认目录是 `../../../face-exp/pc-golden`（外部样本，不入仓库：仓库规矩是不提交 *.face）。
 * 找不到就打印跳过、退出码 0，别让「样本不在」变成假红灯。
 *
 * ⚠️ 别拿 face-exp/out 当回归基线：那里混着 10-01 AOD 分层实验期的产物
 *    （只有锚点记录、没有位图的空壳 AOD），形状不在本打包器覆盖范围内，
 *    报差异不代表回归。本脚本只对 pc-golden 那一份负责。
 */
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { packFace, unpackFace } from '../src/core/facebin.js';

const ROOT = process.argv[2] || fileURLToPath(new URL('../../../face-exp/pc-golden', import.meta.url));

if (!existsSync(ROOT)) {
  console.log(`跳过：样本目录不存在 —— ${ROOT}`);
  console.log('（需要外部 golden 样本，仓库里不存 *.face）');
  process.exit(0);
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    let st;
    try { st = statSync(p); } catch { continue; }
    if (st.isDirectory()) walk(p, out);
    else if (/\.face$/i.test(name)) out.push(p);
  }
  return out;
}

const files = walk(ROOT);
let ok = 0;
const bad = [];

for (const f of files) {
  const raw = new Uint8Array(readFileSync(f));
  let u;
  try {
    u = unpackFace(raw);
    const again = packFace({
      title: u.title,
      faceId: u.faceId,
      idLen: u.idLen,
      sentinelIdx: u.sentinelIdx,
      files: u.files,
      previewBgra: u.previewBgra,
      hasAod: u.hasAod,
      recs: u.recs,
    });
    if (again.length !== raw.length) throw new Error(`长度不同 ${again.length} vs ${raw.length}`);
    let diff = -1;
    for (let i = 0; i < raw.length; i++) if (again[i] !== raw[i]) { diff = i; break; }
    if (diff >= 0) throw new Error(`字节差异 @${diff} (0x${diff.toString(16)})`);
    ok++;
  } catch (e) {
    bad.push([f.replace(ROOT, '.'), e.message]);
  }
}

console.log(`样本 ${files.length} 份，通过 ${ok}，失败 ${bad.length}`);
for (const [p, m] of bad) console.log(`  ✗ ${p}: ${m}`);
process.exit(bad.length ? 1 : 0);
