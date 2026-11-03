/**
 * 最小 GIF 解码器（LZW + 帧合成），零依赖。
 *
 * 只做表盘需要的事：把每一帧解成 RGBA8888 的整屏位图，处理 disposal 2/3 与透明索引。
 * 不追求覆盖 GIF89a 的所有边角（比如逐帧 local palette 之外的怪样本）。
 */

/** @returns {{ width:number, height:number, frames:{rgba:Uint8Array, delayMs:number}[] }} */
export function decodeGif(bytes) {
  let p = 0;
  const u8 = () => bytes[p++];
  const u16 = () => bytes[p++] | (bytes[p++] << 8);
  const sig = String.fromCharCode(...bytes.subarray(0, 6));
  if (sig !== 'GIF89a' && sig !== 'GIF87a') throw new Error('不是 GIF 文件');
  p = 6;

  const width = u16();
  const height = u16();
  const packed = u8();
  p += 2; // background index + pixel aspect，各 1 字节
  let gct = null;
  if (packed & 0x80) {
    const n = 2 << (packed & 7);
    gct = readPalette(bytes, p, n);
    p += n * 3;
  }

  const canvas = new Uint8Array(width * height * 4); // 合成画布
  const frames = [];
  let gce = { disposal: 0, delay: 0, transparent: -1 };
  let prevDisposal = 0;
  let prevRect = null;

  while (p < bytes.length) {
    const block = u8();
    if (block === 0x3b) break; // trailer

    if (block === 0x21) {
      // 扩展块
      p += 1; // label
      if (bytes[p - 1] === 0xf9) {
        const size = u8();
        const flags = u8();
        const delay = u16();
        const tIdx = u8();
        p += 1; // block terminator
        if (size !== 4) p += size - 4;
        gce = {
          disposal: (flags >> 2) & 7,
          delay: delay * 10,
          transparent: flags & 1 ? tIdx : -1,
        };
        continue;
      }
      // 其它扩展：跳子块
      while (bytes[p] !== 0) p += bytes[p] + 1;
      p += 1;
      continue;
    }

    if (block !== 0x2c) { p += 1; continue; } // 未知块，跳过

    // 图像描述符
    const left = u16(), top = u16(), w = u16(), h = u16();
    const ipacked = u8();
    const interlaced = !!(ipacked & 0x40);
    let lct = null;
    if (ipacked & 0x80) {
      const n = 2 << (ipacked & 7);
      lct = readPalette(bytes, p, n);
      p += n * 3;
    }
    const minCode = u8();
    const data = readSubBlocks(bytes, () => p, (v) => { p = v; });
    const idx = lzwDecode(data, minCode, w * h);

    // 处理上一帧的 disposal
    if (prevDisposal === 2 && prevRect) clearRect(canvas, width, prevRect);
    if (prevDisposal === 3 && prevRect) restoreRect(canvas, width, prevRect.saved, prevRect);

    const pal = lct || gct;
    if (!pal) throw new Error('GIF 缺少调色板');
    const saved = prevDisposal === 3 ? snapshotRect(canvas, width, { left, top, w, h }) : null;
    drawFrame(canvas, width, height, { left, top, w, h, idx, pal, transparent: gce.transparent, interlaced });

    frames.push({ rgba: canvas.slice(), delayMs: gce.delay || 40 });
    prevDisposal = gce.disposal;
    prevRect = { left, top, w, h, saved };
  }

  return { width, height, frames };
}

function readPalette(bytes, off, n) {
  const pal = new Uint8Array(n * 3);
  for (let i = 0; i < n * 3; i++) pal[i] = bytes[off + i];
  return pal;
}

function readSubBlocks(bytes, getP, setP) {
  const parts = [];
  let p = getP();
  for (;;) {
    const len = bytes[p];
    p += 1;
    if (!len) break;
    parts.push(bytes.subarray(p, p + len));
    p += len;
  }
  setP(p);
  let total = 0;
  for (const q of parts) total += q.length;
  const out = new Uint8Array(total);
  let o = 0;
  for (const q of parts) { out.set(q, o); o += q.length; }
  return out;
}

function lzwDecode(data, minCodeSize, pixelCount) {
  const out = new Uint8Array(pixelCount);
  const clear = 1 << minCodeSize;
  const eoi = clear + 1;
  let codeSize = minCodeSize + 1;
  let dict = [];
  const reset = () => {
    dict = new Array(clear + 2);
    for (let i = 0; i < clear; i++) dict[i] = [i];
    dict[clear] = null;
    dict[eoi] = null;
    codeSize = minCodeSize + 1;
  };
  reset();

  let bitPos = 0;
  const readCode = () => {
    if (bitPos + codeSize > data.length * 8) return eoi;
    let v = 0;
    for (let i = 0; i < codeSize; i++) {
      const bi = bitPos + i;
      const bit = (data[bi >> 3] >> (bi & 7)) & 1;
      v |= bit << i;
    }
    bitPos += codeSize;
    return v;
  };

  let prev = null;
  let o = 0;
  for (;;) {
    const code = readCode();
    if (code === eoi || o >= pixelCount) break;
    if (code === clear) { reset(); prev = null; continue; }
    let entry;
    if (code < dict.length && dict[code]) entry = dict[code];
    else if (prev) entry = prev.concat(prev[0]);
    else break;
    for (let i = 0; i < entry.length && o < pixelCount; i++) out[o++] = entry[i];
    if (prev) {
      dict.push(prev.concat(entry[0]));
      if (dict.length === (1 << codeSize) && codeSize < 12) codeSize++;
    }
    prev = entry;
  }
  return out;
}

function drawFrame(canvas, cw, ch, f) {
  const rows = [];
  if (f.interlaced) {
    const passes = [[0, 8], [4, 8], [2, 4], [1, 2]];
    for (const [start, step] of passes) for (let y = start; y < f.h; y += step) rows.push(y);
  } else {
    for (let y = 0; y < f.h; y++) rows.push(y);
  }
  let src = 0;
  for (const y of rows) {
    const dy = f.top + y;
    for (let x = 0; x < f.w; x++) {
      const ci = f.idx[src++];
      if (ci === f.transparent) continue;
      const dx = f.left + x;
      if (dx >= cw || dy >= ch) continue;
      const o = (dy * cw + dx) * 4;
      canvas[o] = f.pal[ci * 3];
      canvas[o + 1] = f.pal[ci * 3 + 1];
      canvas[o + 2] = f.pal[ci * 3 + 2];
      canvas[o + 3] = 255;
    }
  }
}

function clearRect(canvas, cw, r) {
  for (let y = r.top; y < r.top + r.h; y++) {
    const o = (y * cw + r.left) * 4;
    canvas.fill(0, o, o + r.w * 4);
  }
}

function snapshotRect(canvas, cw, r) {
  const buf = new Uint8Array(r.w * r.h * 4);
  for (let y = 0; y < r.h; y++) {
    const s = ((r.top + y) * cw + r.left) * 4;
    buf.set(canvas.subarray(s, s + r.w * 4), y * r.w * 4);
  }
  return buf;
}

function restoreRect(canvas, cw, saved, r) {
  for (let y = 0; y < r.h; y++) {
    const d = ((r.top + y) * cw + r.left) * 4;
    canvas.set(saved.subarray(y * r.w * 4, (y + 1) * r.w * 4), d);
  }
}
