/**
 * baseline JPEG 编码器（SOF0 顺序编码），**强制 4:4:4**，不做色度子采样。
 *
 * 为什么不直接用 `canvas.toBlob('image/jpeg', q)`：实测（Edge / Chromium，Blink 同一套
 * 编码器）**所有质量档**输出的 SOF0 采样因子都是 `2x2 1x1 1x1`，也就是写死 4:2:0 ——
 * 色度被砍到一半分辨率，彩色边缘串色，这正是「JPEG 看着糊」的主因。
 * 项目在 PC 端（Pillow，`subsampling=0`）实测过：关掉子采样只多 19% 体积，
 * 色度 PSNR 却涨 2.5 dB，是性价比最高的一刀。浏览器原生做不到，所以自己写。
 *
 * 只实现 baseline：三张 Huffman 表（DC/AC 各亮度色度）、单扫描、8 bit。
 * 渐进式、算术编码、重启间隔都不需要 —— miwear 的 JPEG 解码走 lodepng 同级的
 * 常规 baseline 路径，PC 端产物（Pillow 默认 baseline）已真机验过。
 *
 * 标准量化表与 Huffman 表是**从 libjpeg 的实际输出里解析出来的**（不是手抄规范），
 * 见 tests/jpeg.mjs 里的一致性断言。
 */

const INV_SQRT2 = 1 / Math.SQRT2;

/** zigzag 扫描顺序（自然序 → 扫描序的下标） */
const ZIGZAG = new Uint8Array([
  0, 1, 8, 16, 9, 2, 3, 10,
  17, 24, 32, 25, 18, 11, 4, 5,
  12, 19, 26, 33, 40, 48, 41, 34,
  27, 20, 13, 6, 7, 14, 21, 28,
  35, 42, 49, 56, 57, 50, 43, 36,
  29, 22, 15, 23, 30, 37, 44, 51,
  58, 59, 52, 45, 38, 31, 39, 46,
  53, 60, 61, 54, 47, 55, 62, 63,
]);

/** 标准亮度量化表（自然序，行优先） */
const STD_LUM_QT = new Uint8Array([
  16, 11, 10, 16, 24, 40, 51, 61,
  12, 12, 14, 19, 26, 58, 60, 55,
  14, 13, 16, 24, 40, 57, 69, 56,
  14, 17, 22, 29, 51, 87, 80, 62,
  18, 22, 37, 56, 68, 109, 103, 77,
  24, 35, 55, 64, 81, 104, 113, 92,
  49, 64, 78, 87, 103, 121, 120, 101,
  72, 92, 95, 98, 112, 100, 103, 99,
]);

/** 标准色度量化表（自然序） */
const STD_CHR_QT = new Uint8Array([
  17, 18, 24, 47, 99, 99, 99, 99,
  18, 21, 26, 66, 99, 99, 99, 99,
  24, 26, 56, 99, 99, 99, 99, 99,
  47, 66, 99, 99, 99, 99, 99, 99,
  99, 99, 99, 99, 99, 99, 99, 99,
  99, 99, 99, 99, 99, 99, 99, 99,
  99, 99, 99, 99, 99, 99, 99, 99,
  99, 99, 99, 99, 99, 99, 99, 99,
]);

/** 标准 Huffman 表（ITU T.81 Annex K，取自 libjpeg 实际输出） */
const DC_LUM_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0];
const DC_LUM_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const DC_CHR_BITS = [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0];
const DC_CHR_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const AC_LUM_BITS = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 125];
const AC_LUM_VALS = [
  1, 2, 3, 0, 4, 17, 5, 18, 33, 49, 65, 6, 19, 81, 97, 7,
  34, 113, 20, 50, 129, 145, 161, 8, 35, 66, 177, 193, 21, 82, 209, 240,
  36, 51, 98, 114, 130, 9, 10, 22, 23, 24, 25, 26, 37, 38, 39, 40,
  41, 42, 52, 53, 54, 55, 56, 57, 58, 67, 68, 69, 70, 71, 72, 73,
  74, 83, 84, 85, 86, 87, 88, 89, 90, 99, 100, 101, 102, 103, 104, 105,
  106, 115, 116, 117, 118, 119, 120, 121, 122, 131, 132, 133, 134, 135, 136, 137,
  138, 146, 147, 148, 149, 150, 151, 152, 153, 154, 162, 163, 164, 165, 166, 167,
  168, 169, 170, 178, 179, 180, 181, 182, 183, 184, 185, 186, 194, 195, 196, 197,
  198, 199, 200, 201, 202, 210, 211, 212, 213, 214, 215, 216, 217, 218, 225, 226,
  227, 228, 229, 230, 231, 232, 233, 234, 241, 242, 243, 244, 245, 246, 247, 248,
  249, 250,
];
const AC_CHR_BITS = [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 119];
const AC_CHR_VALS = [
  0, 1, 2, 3, 17, 4, 5, 33, 49, 6, 18, 65, 81, 7, 97, 113,
  19, 34, 50, 129, 8, 20, 66, 145, 161, 177, 193, 9, 35, 51, 82, 240,
  21, 98, 114, 209, 10, 22, 36, 52, 225, 37, 241, 23, 24, 25, 26, 38,
  39, 40, 41, 42, 53, 54, 55, 56, 57, 58, 67, 68, 69, 70, 71, 72,
  73, 74, 83, 84, 85, 86, 87, 88, 89, 90, 99, 100, 101, 102, 103, 104,
  105, 106, 115, 116, 117, 118, 119, 120, 121, 122, 130, 131, 132, 133, 134, 135,
  136, 137, 138, 146, 147, 148, 149, 150, 151, 152, 153, 154, 162, 163, 164, 165,
  166, 167, 168, 169, 170, 178, 179, 180, 181, 182, 183, 184, 185, 186, 194, 195,
  196, 197, 198, 199, 200, 201, 202, 210, 211, 212, 213, 214, 215, 216, 217, 218,
  226, 227, 228, 229, 230, 231, 232, 233, 234, 242, 243, 244, 245, 246, 247, 248,
  249, 250,
];

/** 一维 DCT 的余弦表：COS[u*8+x] = cos((2x+1)·u·π/16) */
const COS = new Float64Array(64);
for (let u = 0; u < 8; u++) {
  for (let x = 0; x < 8; x++) COS[u * 8 + x] = Math.cos(((2 * x + 1) * u * Math.PI) / 16);
}

/** 从 BITS/VALS 建「值 → (码字, 码长)」查表，编码时按值直接取 */
function buildHuff(bits, vals) {
  const tbl = new Int32Array(256);   // code << 8 | len
  let code = 0;
  let k = 0;
  for (let len = 1; len <= 16; len++) {
    for (let i = 0; i < bits[len - 1]; i++) {
      tbl[vals[k++]] = (code << 8) | len;
      code++;
    }
    code <<= 1;
  }
  return tbl;
}

const H_DC_LUM = buildHuff(DC_LUM_BITS, DC_LUM_VALS);
const H_AC_LUM = buildHuff(AC_LUM_BITS, AC_LUM_VALS);
const H_DC_CHR = buildHuff(DC_CHR_BITS, DC_CHR_VALS);
const H_AC_CHR = buildHuff(AC_CHR_BITS, AC_CHR_VALS);

/**
 * 按 libjpeg 的规则缩放量化表。
 * quality < 50 时 scale = 5000/q（压得更狠），>= 50 时 scale = 200-2q。
 */
function scaleQT(base, quality) {
  const q = Math.min(100, Math.max(1, quality));
  const scale = q < 50 ? Math.floor(5000 / q) : 200 - q * 2;
  const out = new Uint8Array(64);
  for (let i = 0; i < 64; i++) {
    const v = Math.floor((base[i] * scale + 50) / 100);
    out[i] = Math.min(255, Math.max(1, v));
  }
  return out;
}

/** 位流写入器：JPEG 熵编码段遇到 0xFF 必须紧跟一个 0x00 填充字节 */
class BitWriter {
  constructor(cap = 1 << 16) {
    this.buf = new Uint8Array(cap);
    this.n = 0;
    this.acc = 0;     // 位累加器
    this.cnt = 0;     // 已累加位数
  }

  _push(b) {
    if (this.n >= this.buf.length) {
      const nb = new Uint8Array(this.buf.length * 2);
      nb.set(this.buf);
      this.buf = nb;
    }
    this.buf[this.n++] = b;
  }

  write(code, len) {
    this.acc = (this.acc << len) | code;
    this.cnt += len;
    while (this.cnt >= 8) {
      this.cnt -= 8;
      const b = (this.acc >>> this.cnt) & 0xff;
      this._push(b);
      if (b === 0xff) this._push(0x00);
    }
    this.acc &= (1 << this.cnt) - 1;
  }

  flush() {
    if (this.cnt > 0) {
      // 末尾补 1（全 1 填充，解码器会忽略）
      this.write((1 << (8 - this.cnt)) - 1, 8 - this.cnt);
    }
  }

  bytes() {
    return this.buf.subarray(0, this.n);
  }
}

/** 8×8 前向 DCT：分离成「先做行、再做列」，每块 1024 次乘加（朴素 2D 要 4096） */
const tmpBlock = new Float64Array(64);

function fdct(block, out) {
  // 行变换
  for (let y = 0; y < 8; y++) {
    const o = y * 8;
    for (let u = 0; u < 8; u++) {
      const co = u * 8;
      let s = 0;
      for (let x = 0; x < 8; x++) s += block[o + x] * COS[co + x];
      tmpBlock[o + u] = s * (u === 0 ? INV_SQRT2 : 1) * 0.5;
    }
  }
  // 列变换
  for (let x = 0; x < 8; x++) {
    for (let v = 0; v < 8; v++) {
      const co = v * 8;
      let s = 0;
      for (let y = 0; y < 8; y++) s += tmpBlock[y * 8 + x] * COS[co + y];
      out[v * 8 + x] = s * (v === 0 ? INV_SQRT2 : 1) * 0.5;
    }
  }
}

/** 整数转「位数 + 位模式」：JPEG 的 VLI 表示（负数用按位补码） */
function vli(v) {
  if (v === 0) return { len: 0, bits: 0 };
  const a = Math.abs(v);
  let len = 0;
  while (a >> len) len++;
  // 负数取 (v - 1) 的低 len 位，等价于「反码」
  return { len, bits: v > 0 ? v : v + (1 << len) - 1 };
}

/**
 * 编码一帧。
 * @param {Uint8Array} rgba 长度 w*h*4，RGBA 交错
 * @param {number} w
 * @param {number} h
 * @param {number} [quality=80] 1..100
 * @returns {Uint8Array} 完整 JPEG 文件字节
 */
export function encodeJPEG(rgba, w, h, quality = 80) {
  if (w <= 0 || h <= 0) throw new Error('JPEG: 尺寸不能为 0');
  if (rgba.length < w * h * 4) throw new Error('JPEG: RGBA 数据长度不足');

  const qLum = scaleQT(STD_LUM_QT, quality);
  const qChr = scaleQT(STD_CHR_QT, quality);

  // ---- 输出容器 ----
  // 头部（SOI..SOS）用普通数组：marker 里的 0xFF **不能**补 0x00，
  // 那条例外规则只属于熵编码段，所以两者必须分开写。
  const head = [];
  const put = (b) => head.push(b);
  const putW = (v) => { head.push((v >> 8) & 0xff, v & 0xff); };
  const putMarker = (m, payloadLen) => { head.push(0xff, m); putW(payloadLen + 2); };

  // SOI
  put(0xff); put(0xd8);

  // APP0 / JFIF 1.01（无缩略图，density 1:1）
  putMarker(0xe0, 14);
  for (const c of [0x4a, 0x46, 0x49, 0x46, 0x00]) put(c);  // "JFIF\0"
  put(1); put(1); put(0);                                   // ver 1.1, aspect unit 0
  putW(1); putW(1);                                         // x/y density
  put(0); put(0);                                           // 无缩略图

  // DQT：两张表一起写（Pq=0 表示 8 bit 精度，Tq 是表号）
  // payload 是「表的字节数」= (1 + 64) × 2 = 130；Lq 由 putMarker 补成 132。
  // 这里写成 `2 + 65*2` 会多报 2 字节，解析器就会把 SOF0 的 marker 当成表数据吞掉。
  putMarker(0xdb, 65 * 2);
  put(0x00);
  for (let i = 0; i < 64; i++) put(qLum[ZIGZAG[i]]);
  put(0x01);
  for (let i = 0; i < 64; i++) put(qChr[ZIGZAG[i]]);

  // SOF0：三个分量**全部 1×1**（这就是 4:4:4，也是这个编码器存在的理由）
  // payload = P(1)+Y(2)+X(2)+Nf(1)+3×3 = 15，Lf 由 putMarker 补成 17（规范值）
  putMarker(0xc0, 6 + 3 * 3);
  put(8);              // 精度 8 bit
  putW(h); putW(w);
  put(3);              // 分量数
  put(1); put(0x11); put(0);   // Y:  h=1 v=1, 量化表 0
  put(2); put(0x11); put(1);   // Cb: h=1 v=1, 量化表 1
  put(3); put(0x11); put(1);   // Cr: h=1 v=1, 量化表 1

  // DHT：四张表
  const putDHT = (cls, id, bits, vals) => {
    putMarker(0xc4, 1 + 16 + vals.length);
    put((cls << 4) | id);
    for (const b of bits) put(b);
    for (const v of vals) put(v);
  };
  putDHT(0, 0, DC_LUM_BITS, DC_LUM_VALS);
  putDHT(1, 0, AC_LUM_BITS, AC_LUM_VALS);
  putDHT(0, 1, DC_CHR_BITS, DC_CHR_VALS);
  putDHT(1, 1, AC_CHR_BITS, AC_CHR_VALS);

  // SOS：Y 用 0 号表，Cb/Cr 用 1 号表，单扫描覆盖 0..63
  // payload = Ns(1)+2×3+Ss/Se/AhAl(3) = 10，Ls 由 putMarker 补成 12（规范值）
  putMarker(0xda, 4 + 2 * 3);
  put(3);
  put(1); put(0x00);
  put(2); put(0x11);
  put(3); put(0x11);
  put(0); put(63); put(0);

  // ---- 熵编码 ----
  const bw = new BitWriter(w * h);
  const block = new Float64Array(64);
  const coef = new Float64Array(64);
  const quant = new Int32Array(64);
  let prevY = 0, prevCb = 0, prevCr = 0;

  const mcuW = Math.ceil(w / 8);
  const mcuH = Math.ceil(h / 8);

  /** 取一个分量的 8×8 块并减 128（JPEG 的 level shift） */
  const loadBlock = (plane, bx, by) => {
    for (let y = 0; y < 8; y++) {
      const sy = Math.min(h - 1, by * 8 + y);       // 边缘按复制处理
      const row = sy * w;
      for (let x = 0; x < 8; x++) {
        const sx = Math.min(w - 1, bx * 8 + x);
        block[y * 8 + x] = plane[row + sx] - 128;
      }
    }
  };

  /**
   * 对已填好的 block 做 DCT+量化+熵编码。
   * @returns 新的 DC 预测值
   */
  const encodeBlock = (huffDC, huffAC, qt, prevDC) => {
    fdct(block, coef);
    for (let i = 0; i < 64; i++) quant[i] = Math.round(coef[i] / qt[i]);

    // DC：与前一块的差值
    const diff = quant[0] - prevDC;
    const d = vli(diff);
    let e = huffDC[d.len];
    bw.write(e >> 8, e & 0xff);
    if (d.len) bw.write(d.bits, d.len);

    // AC：按 zigzag 序，RLE + EOB
    let run = 0;
    for (let k = 1; k < 64; k++) {
      const v = quant[ZIGZAG[k]];
      if (v === 0) { run++; continue; }
      while (run > 15) {           // ZRL：16 个连零
        e = huffAC[0xf0];
        bw.write(e >> 8, e & 0xff);
        run -= 16;
      }
      const a = vli(v);
      e = huffAC[(run << 4) | a.len];
      bw.write(e >> 8, e & 0xff);
      bw.write(a.bits, a.len);
      run = 0;
    }
    if (run > 0) {                 // EOB
      e = huffAC[0x00];
      bw.write(e >> 8, e & 0xff);
    }
    return quant[0];
  };

  // 4:4:4 → 每个 MCU 就是三个 8×8 块，不需要交错采样
  const planeY = new Uint8Array(w * h);
  const planeCb = new Uint8Array(w * h);
  const planeCr = new Uint8Array(w * h);
  const clamp8 = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);
  for (let i = 0, p = 0; i < w * h; i++, p += 4) {
    const r = rgba[p], g = rgba[p + 1], b = rgba[p + 2];
    // 用四舍五入而不是 |0：负数会被向零截断，端到端会引入半个色阶的系统偏差
    planeY[i] = clamp8(Math.round(0.299 * r + 0.587 * g + 0.114 * b));
    planeCb[i] = clamp8(Math.round(-0.168736 * r - 0.331264 * g + 0.5 * b + 128));
    planeCr[i] = clamp8(Math.round(0.5 * r - 0.418688 * g - 0.081312 * b + 128));
  }

  for (let by = 0; by < mcuH; by++) {
    for (let bx = 0; bx < mcuW; bx++) {
      loadBlock(planeY, bx, by);
      prevY = encodeBlock(H_DC_LUM, H_AC_LUM, qLum, prevY);
      loadBlock(planeCb, bx, by);
      prevCb = encodeBlock(H_DC_CHR, H_AC_CHR, qChr, prevCb);
      loadBlock(planeCr, bx, by);
      prevCr = encodeBlock(H_DC_CHR, H_AC_CHR, qChr, prevCr);
    }
  }
  bw.flush();

  // EOI 必须跟在熵数据**之后**（head 是 SOS 之前的头部，别写进去）
  const tail = bw.bytes();
  const all = new Uint8Array(head.length + tail.length + 2);
  all.set(head, 0);
  all.set(tail, head.length);
  all[head.length + tail.length] = 0xff;
  all[head.length + tail.length + 1] = 0xd9;
  return all;
}

/** 供测试用：暴露标准表，方便与 libjpeg 输出逐项对齐 */
export const _tables = {
  ZIGZAG, STD_LUM_QT, STD_CHR_QT,
  DC_LUM_BITS, DC_LUM_VALS, DC_CHR_BITS, DC_CHR_VALS,
  AC_LUM_BITS, AC_LUM_VALS, AC_CHR_BITS, AC_CHR_VALS,
};
