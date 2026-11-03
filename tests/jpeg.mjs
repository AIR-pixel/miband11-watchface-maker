/**
 * JPEG 编码器验收。
 *
 *   1. 结构自检：量化表 / Huffman 表结构、ZIGZAG 是 0..63 的排列
 *   2. 码流自检：SOI / EOI 齐全，SOF0 三分量采样因子必须全是 0x11（= 4:4:4）
 *   3. 交给 Pillow 独立解码：尺寸要对，亮度 PSNR 达有损码正常水平，
 *      **色度 PSNR 不能塌**（4:2:0 的典型症状就是色度明显低于亮度）
 *   4. 同一张图让 Pillow 存成 4:2:0 做对照 —— 自研 4:4:4 的色度必须赢它
 *
 *   node tests/jpeg.mjs
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { encodeJPEG, _tables } from '../src/core/jpeg.js';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const OUT = join(ROOT, 'tests/out');
const OUT_PY = OUT.replace(/\\/g, '/');
mkdirSync(OUT, { recursive: true });

const W = 212, H = 520;
const QS = [90, 85, 80, 70, 60];
const fail = [];

/**
 * 造图：**纯整数运算**，Python 端用同一套公式重算，两边必须逐像素相同。
 * 每 13 行压两道纯绿细边 —— 色度子采样在这里最容易串色。
 */
function makeImage(w, h) {
  const rgba = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const p = (y * w + x) * 4;
      let r = (x * 253) % 256;
      let g = (y * 7) % 256;
      let b = ((x >> 3) ^ (y >> 3)) & 255;
      if (y % 13 < 2) { r = 0; g = 255; b = 0; }
      rgba[p] = r; rgba[p + 1] = g; rgba[p + 2] = b; rgba[p + 3] = 255;
    }
  }
  return rgba;
}

// ---------- 1. 表结构 ----------
const zig = Array.from(_tables.ZIGZAG).sort((a, b) => a - b);
if (zig.join(',') !== Array.from({ length: 64 }, (_, i) => i).join(',')) {
  fail.push('ZIGZAG 不是 0..63 的排列');
}
for (const [name, qt] of [['亮度', _tables.STD_LUM_QT], ['色度', _tables.STD_CHR_QT]]) {
  if (qt.length !== 64) fail.push(`${name}量化表长度 ${qt.length}`);
  for (const v of qt) if (v < 1 || v > 255) { fail.push(`${name}量化表越界值 ${v}`); break; }
}
for (const [name, bits, expect] of [
  ['DC亮度', _tables.DC_LUM_BITS, 12], ['DC色度', _tables.DC_CHR_BITS, 12],
  ['AC亮度', _tables.AC_LUM_BITS, 162], ['AC色度', _tables.AC_CHR_BITS, 162],
]) {
  if (bits.length !== 16) fail.push(`${name} BITS 长度 ${bits.length}`);
  const sum = bits.reduce((a, b) => a + b, 0);
  if (sum !== expect) fail.push(`${name} BITS 之和 ${sum}，应为 ${expect}`);
}

// ---------- 2. 编码 + 码流自检 ----------
const rgba = makeImage(W, H);
const cases = [];
for (const q of QS) {
  const t0 = process.hrtime.bigint();
  const jpg = encodeJPEG(rgba, W, H, q);
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  writeFileSync(join(OUT, `jpeg_q${q}.jpg`), jpg);
  cases.push({ q, bytes: jpg.length, kb: +(jpg.length / 1024).toFixed(1), ms: +ms.toFixed(1), jpg });

  if (!(jpg[0] === 0xff && jpg[1] === 0xd8)) fail.push(`q${q}: 缺 SOI`);
  if (!(jpg[jpg.length - 2] === 0xff && jpg[jpg.length - 1] === 0xd9)) fail.push(`q${q}: 缺 EOI`);

  // 按 marker 链跳，**不能逐字节扫**：量化表里就有 0xFF（值 255），
  // 逐字节扫会把它当成 marker 起点，读到垃圾长度后整条链跑飞。
  // 熵数据的起点是 SOS 段**之后**，别从 SOS marker 自己开始扫。
  let i = 2, sof = null, sosStart = -1;
  while (i + 3 < jpg.length) {
    if (jpg[i] !== 0xff) break;
    const m = jpg[i + 1];
    if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }
    const len = (jpg[i + 2] << 8) | jpg[i + 3];
    if (m === 0xd9) break;
    if (m === 0xda) { sosStart = i + 2 + len; break; }
    if (m === 0xc0) {
      const n = jpg[i + 9];
      const comps = [];
      for (let k = 0; k < n; k++) {
        const o = i + 10 + k * 3;
        comps.push({ id: jpg[o], hv: jpg[o + 1], tq: jpg[o + 2] });
      }
      sof = { h: (jpg[i + 5] << 8) | jpg[i + 6], w: (jpg[i + 7] << 8) | jpg[i + 8], comps };
    }
    i += 2 + len;
  }
  if (!sof) { fail.push(`q${q}: 没有 SOF0（不是 baseline）`); continue; }
  if (sof.w !== W || sof.h !== H) fail.push(`q${q}: SOF0 尺寸 ${sof.w}x${sof.h}`);
  if (sof.comps.length !== 3) fail.push(`q${q}: 分量数 ${sof.comps.length}`);
  for (const c of sof.comps) {
    if (c.hv !== 0x11) {
      fail.push(`q${q}: 分量 ${c.id} 采样因子 0x${c.hv.toString(16)}，应为 0x11（4:4:4）`);
    }
  }
  // 熵编码段不能出现未转义的 0xFF（后面必须跟 0x00）
  if (sosStart > 0) {
    for (let k = sosStart; k < jpg.length - 2; k++) {
      if (jpg[k] === 0xff && jpg[k + 1] !== 0x00) {
        fail.push(`q${q}: 熵段第 ${k} 字节 0xFF 后面没有填充（会破坏解码）`);
        break;
      }
    }
  }
}

// ---------- 3. Pillow 独立解码 ----------
const PY = 'C:/Users/air/AppData/Local/Programs/Python/Python313/python.exe';
const py = `
import json, os
import numpy as np
from PIL import Image

W, H = ${W}, ${H}
OUT = r"${OUT_PY}"

xs, ys = np.arange(W), np.arange(H)
X, Y = np.meshgrid(xs, ys)
r = (X * 253) % 256
g = (Y * 7) % 256
b = ((X >> 3) ^ (Y >> 3)) & 255
edge = (Y % 13) < 2
r = np.where(edge, 0, r)
g = np.where(edge, 255, g)
b = np.where(edge, 0, b)
src = np.stack([r, g, b], axis=-1).astype(np.uint8)

def ycc(a):
    a = a.astype(np.float64)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    return (0.299*R + 0.587*G + 0.114*B,
            -0.168736*R - 0.331264*G + 0.5*B + 128.0,
             0.5*R - 0.418688*G - 0.081312*B + 128.0)

ry, rcb, rcr = ycc(src)

def psnr(a, b):
    mse = float(np.mean((a - b) ** 2))
    return 99.0 if mse == 0.0 else 10.0 * np.log10(255.0 * 255.0 / mse)

files = []
for q in ${JSON.stringify(QS)}:
    p = os.path.join(OUT, "jpeg_q%d.jpg" % q)
    im = Image.open(p)
    im.load()
    y, cb, cr = ycc(np.asarray(im.convert("RGB")))
    lay = getattr(im, "layer", None)
    l0 = None
    if isinstance(lay, list) and lay:
        first = lay[0]
        l0 = list(first) if isinstance(first, (tuple, list)) else [int(first)]
    files.append({
        "q": q,
        "size": list(im.size),
        "layer0": l0,
        "psnr_y": round(psnr(ry, y), 2),
        "psnr_cb": round(psnr(rcb, cb), 2),
        "psnr_cr": round(psnr(rcr, cr), 2),
    })

p420 = os.path.join(OUT, "jpeg_q80_420.jpg")
Image.fromarray(src, "RGB").save(p420, "JPEG", quality=80, subsampling=2)
y, cb, cr = ycc(np.asarray(Image.open(p420).convert("RGB")))
control = {
    "psnr_y": round(psnr(ry, y), 2),
    "psnr_cb": round(psnr(rcb, cb), 2),
    "psnr_cr": round(psnr(rcr, cr), 2),
}

print(json.dumps({"files": files, "control_420": control}))
`;

let report = null;
try {
  const stdout = execFileSync(PY, ['-c', py], { maxBuffer: 1 << 26, encoding: 'utf8' });
  report = JSON.parse(stdout.trim().split('\n').pop());
} catch (e) {
  fail.push(`Pillow 校验失败：${(e.stderr || e.message || '').toString().slice(0, 400)}`);
}

if (report) {
  for (const f of report.files) {
    if (f.size[0] !== W || f.size[1] !== H) fail.push(`q${f.q}: Pillow 读出尺寸 ${f.size}`);
    if (f.psnr_y < 32) fail.push(`q${f.q}: 亮度 PSNR ${f.psnr_y} 太低（有损码正常 >= 35）`);
    if (f.psnr_cb < 30 || f.psnr_cr < 30) {
      fail.push(`q${f.q}: 色度 PSNR ${f.psnr_cb}/${f.psnr_cr} 偏低（4:2:0 的典型症状）`);
    }
    // layer0 是 Pillow 从 SOF 解析出的首分量采样因子：[1,1] 才是 4:4:4
    if (f.layer0 && (f.layer0[0] !== 1 || f.layer0[1] !== 1)) {
      fail.push(`q${f.q}: Pillow 判定的采样因子 ${JSON.stringify(f.layer0)}，应为 [1,1]（4:4:4）`);
    }
  }
  const mine = report.files.find((f) => f.q === 80);
  const ctl = report.control_420;
  if (mine && ctl) {
    if (!(mine.psnr_cb > ctl.psnr_cb + 1.0)) {
      fail.push(`q80 色度未明显优于 4:2:0 对照（${mine.psnr_cb} vs ${ctl.psnr_cb} dB），4:4:4 可能没生效`);
    }
  }
}

console.log(JSON.stringify({
  cases: cases.map((c) => ({ q: c.q, kb: c.kb, ms: c.ms })),
  pillow: report,
  out: OUT,
  fail,
}, null, 2));

process.exitCode = fail.length ? 1 : 0;
