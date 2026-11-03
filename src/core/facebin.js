/**
 * .face 二进制打包/解包核心 —— 零依赖 ESM，浏览器与 Node 都能跑。
 *
 * 端口自 watchface-android/core/face/FaceBuilder.java（该实现与本机 Compiler.exe
 * 产物做过逐字节比对）。布局与坑的完整说明见仓库 docs/face格式规范.md。
 *
 * 全部小端序。像素一律 BGRA8888、直通（非预乘）alpha。
 *
 * ┌ 布局（无 AOD）────────────────────────────────────────────┐
 * │ [0,172)        头部 + Title                              │
 * │ [172,272)      元数据（25 槽）                            │
 * │ [272,272+n*16) 索引表（n 条）                             │
 * │ [..,+16)       描述块（只剩一条 0x0500 哨兵）             │
 * │ [..,filesEnd)  文件数据区（条目起点 4 字节对齐，末条也补齐）│
 * │ [EOF-440972,EOF) 尾部预览（12 B 头 + 212*520*4 BGRA）     │
 * └──────────────────────────────────────────────────────────┘
 *
 * ┌ 布局（带 AOD）────────────────────────────────────────────┐
 * │ [0,172)          头部 + Title                            │
 * │ [172,260)        元数据·主屏（22 槽，索引基址 360、屏数 2）│
 * │ [260,360)        元数据·AOD 尾部（25 槽）                 │
 * │ [360,360+n*16)   索引表（n 条）                           │
 * │ [d0,descEnd)     描述块：锚 0x0000 → 位图 0x0200 →        │
 * │                  数组 0x0300 → 小件 0x0700 → 哨兵 0x0500  │
 * │ [descEnd,filesEnd)   文件数据区                           │
 * │ [filesEnd,assetsEnd) AOD 素材区（实排：锚→小件→位图→数组）│
 * │ [EOF-440972,EOF)     尾部预览（BGRA）                     │
 * └──────────────────────────────────────────────────────────┘
 */

export const PREVIEW_W = 212;
export const PREVIEW_H = 520;
/** 无 AOD 时的索引表起点 */
export const INDEX_START = 272;
/** 带 AOD 时的索引表起点（元数据区多 88 B） */
export const INDEX_START_AOD = 360;

const MAGIC = [0x5a, 0xa5, 0x34, 0x12];
const INDEX_ENTRY_SIZE = 16;
const ID_LEN = 10;
const TITLE_LEN = 16;
const TAG_SENTINEL = 0x0500;

/** 素材区实排顺序：锚 → 小件 → 位图 → 数组（同类保持相对次序） */
const TAG_PRIORITY = [0x0000, 0x0700, 0x0200, 0x0300];

const align4 = (x) => x + ((4 - (x % 4)) % 4);

class Writer {
  constructor(cap = 1 << 20) {
    this.buf = new Uint8Array(cap);
    this.view = new DataView(this.buf.buffer);
    this.len = 0;
  }
  _grow(n) {
    if (this.len + n <= this.buf.length) return;
    let cap = this.buf.length;
    while (cap < this.len + n) cap *= 2;
    const nb = new Uint8Array(cap);
    nb.set(this.buf.subarray(0, this.len));
    this.buf = nb;
    this.view = new DataView(nb.buffer);
  }
  u8(v) { this._grow(1); this.buf[this.len++] = v & 0xff; }
  u16(v) { this._grow(2); this.view.setUint16(this.len, v & 0xffff, true); this.len += 2; }
  u24(v) {
    this._grow(3);
    this.buf[this.len++] = v & 0xff;
    this.buf[this.len++] = (v >>> 8) & 0xff;
    this.buf[this.len++] = (v >>> 16) & 0xff;
  }
  u32(v) { this._grow(4); this.view.setUint32(this.len, v >>> 0, true); this.len += 4; }
  zeros(n) { this._grow(n); this.buf.fill(0, this.len, this.len + n); this.len += n; }
  bytes(b) { this._grow(b.length); this.buf.set(b, this.len); this.len += b.length; }
  /**
   * ASCII 定长字段：不足补 0，超长截断。
   *
   * **非 ASCII 字符一律换成 `?`**，与 PC 端 `_fixed_ascii`（Python
   * `s.encode("ascii", "replace")`）逐字节一致。别改成 TextEncoder（UTF-8）：
   * Title 只有 16 字节，一个汉字 3 字节，超长时会被截在半个汉字上，产物里留下
   * 非法 UTF-8 序列 —— 而且两端产物从此不一样。
   */
  ascii(s, len) {
    this._grow(len);
    const str = String(s);
    let n = 0;
    for (const ch of str) {           // 按码点遍历：一个汉字只换一个 '?'
      if (n >= len) break;
      const c = ch.codePointAt(0);
      this.buf[this.len + n++] = c < 0x80 ? c : 0x3f;
    }
    while (n < len) this.buf[this.len + n++] = 0;
    this.len += len;
  }
  finish() { return this.buf.slice(0, this.len); }
}

const asciiBytes = (s) => new TextEncoder().encode(s);

const count = (recs, tag) => recs.reduce((c, r) => c + (r.tag === tag ? 1 : 0), 0);

/** 返回该类第一条描述记录的**绝对**偏移；没有则 -1。别改成相对值。 */
function firstRecOff(recs, tag, d0) {
  for (let k = 0; k < recs.length; k++) if (recs[k].tag === tag) return d0 + k * INDEX_ENTRY_SIZE;
  return -1;
}

const orSentinel = (v, sentinelOff) => (v < 0 ? sentinelOff : v);

/**
 * @typedef {{ name: string, data: Uint8Array }} FaceFile
 * @typedef {{ idx: number, tag: number, payload: Uint8Array }} AodRec
 * @typedef {{ title: string, faceId: string, files: FaceFile[],
 *             previewBgra: Uint8Array, hasAod?: boolean, recs?: AodRec[] }} PackInput
 */

/**
 * 拼装 .face 字节流。
 * @param {PackInput} input
 * @returns {Uint8Array}
 */
export function packFace(input) {
  const { title = '', faceId = '', files, previewBgra, hasAod = false, recs = [] } = input;
  // [5] 是 ID 长度（单字节）。官方产物 + patch 之后是 10；写成 u16 的一半会让全文件错位 1 字节。
  const idLen = input.idLen == null ? ID_LEN : input.idLen;
  // 描述块哨兵的 idx：单壁纸时等于 n-1；**多壁纸时是「第一页帧数」**（实测 gF/gC/gE）。
  // 这个字段设备侧看起来不用，但要做到逐字节一致就得照抄。
  const sentinelIdx = input.sentinelIdx;
  const n = files.length;
  const idx = hasAod ? INDEX_START_AOD : INDEX_START;
  const d0 = idx + n * INDEX_ENTRY_SIZE; // 描述块起点
  const ndesc = recs.length + 1; // + 哨兵
  const descEnd = d0 + ndesc * INDEX_ENTRY_SIZE;

  // ---- 文件数据区：条目起点 4 字节对齐，末条也补齐 ----
  const offsets = new Int32Array(n);
  const sizes = new Int32Array(n);
  let cur = descEnd;
  for (let i = 0; i < n; i++) {
    const nbLen = asciiBytes(files[i].name).length;
    const size = 20 + nbLen + files[i].data.length;
    offsets[i] = cur;
    sizes[i] = size;
    cur = align4(cur + size); // 对齐与累加合并，别在循环外补 padding
  }
  const filesEnd = cur; // 已对齐

  // ---- AOD 素材区：紧随数据区；实排 锚 → 小件 → 位图 → 数组 ----
  const assetStart = filesEnd;
  const order = [];
  for (const tag of TAG_PRIORITY) {
    for (let k = 0; k < recs.length; k++) if (recs[k].tag === tag) order.push(k);
  }
  for (let k = 0; k < recs.length; k++) if (!order.includes(k)) order.push(k); // 兜底
  const blobOff = new Int32Array(recs.length);
  let assetLen = 0;
  for (const k of order) { blobOff[k] = assetStart + assetLen; assetLen += recs[k].payload.length; }
  const assetsEnd = assetStart + assetLen;
  const sentinelOff = d0 + (ndesc - 1) * INDEX_ENTRY_SIZE;

  // ---- 元数据里的 A 值 ----
  const firstBitmap = firstRecOff(recs, 0x0200, d0);
  let firstNonAnchor = -1;
  for (let k = 0; k < recs.length; k++) {
    if (recs[k].tag !== 0x0000) { firstNonAnchor = d0 + k * INDEX_ENTRY_SIZE; break; }
  }
  const A = firstBitmap >= 0 ? firstBitmap : firstNonAnchor >= 0 ? firstNonAnchor : sentinelOff;

  const o = new Writer(Math.max(1 << 16, assetsEnd + 440972 + 1024));

  // ---- 头部 64 B ----
  o.u8(MAGIC[0]); o.u8(MAGIC[1]); o.u8(MAGIC[2]); o.u8(MAGIC[3]);
  o.u8(0); o.u8(idLen);           // [4],[5] —— 两个独立字节，别当 u16 写
  o.zeros(10);
  o.u32(0x800);                  // [16]
  o.zeros(8);
  o.u16(hasAod ? 2 : 1);         // [28] 屏数
  o.u16(hasAod ? 4 : 0);         // [30]
  o.u32(assetsEnd);              // [32]
  o.zeros(4);
  o.ascii(String(faceId), ID_LEN); // [40]
  o.zeros(14);
  // ---- Title 区 ----
  o.zeros(40);
  o.ascii(String(title), TITLE_LEN); // [104]
  o.zeros(52);

  if (hasAod) {
    // [172,260) 主屏元数据 22 槽
    o.u32(assetsEnd); o.u32(1); o.u32(idx - 16); o.u32(0);
    o.u32(idx); o.u32(0); o.u32(idx); o.u32(0);
    o.u32(idx); o.u32(0); o.u32(idx);
    o.u32(n); o.u32(idx); o.u32(0);
    for (let k = 0; k < 4; k++) { o.u32(d0); o.u32(0); }
    // [260,360) AOD 尾部 25 槽
    o.u32(0xffffffff);
    o.u32(count(recs, 0x0000));
    o.u32(d0); o.u32(0);
    o.u32(A); o.u32(count(recs, 0x0200));
    o.u32(A); o.u32(count(recs, 0x0300));
    o.u32(orSentinel(firstRecOff(recs, 0x0300, d0), sentinelOff)); o.u32(0);
    const dOff = orSentinel(firstRecOff(recs, 0x0700, d0), sentinelOff);
    o.u32(dOff); o.u32(0);
    o.u32(dOff); o.u32(0);
    o.u32(dOff); o.u32(count(recs, 0x0700));
    o.u32(dOff); o.u32(0);
    o.u32(sentinelOff); o.u32(0);
    o.u32(sentinelOff); o.u32(0);
    o.u32(0);
    o.u32(sentinelOff);
    o.u32(INDEX_ENTRY_SIZE);
  } else {
    // 无 AOD：25 槽
    o.u32(assetsEnd); o.u32(1); o.u32(idx - 16); o.u32(0);
    o.u32(idx); o.u32(0); o.u32(idx); o.u32(0);
    o.u32(idx); o.u32(0); o.u32(idx);
    o.u32(n); o.u32(idx); o.u32(0);
    for (let k = 0; k < 4; k++) { o.u32(d0); o.u32(0); }
    o.u32(0); o.u32(d0); o.u32(INDEX_ENTRY_SIZE);
  }

  // ---- 索引表（n 条） ----
  for (let i = 0; i < n; i++) {
    o.u16(i); o.u16(TAG_SENTINEL); o.u32(0);
    o.u32(offsets[i]); o.u32(sizes[i]);
  }

  // ---- 描述块：有效记录 + 哨兵 ----
  for (let k = 0; k < recs.length; k++) {
    const r = recs[k];
    o.u16(r.idx); o.u16(r.tag); o.u32(0);
    o.u32(blobOff[k]); o.u32(r.payload.length);
  }
  o.u16(sentinelIdx == null ? n - 1 : sentinelIdx); o.u16(TAG_SENTINEL); o.u32(0); o.u32(0); o.u32(0);

  // ---- 文件数据区 ----
  for (let i = 0; i < n; i++) {
    const f = files[i];
    const nb = asciiBytes(f.name);
    o.u24(f.data.length);
    o.u8(nb.length);
    o.zeros(16);
    o.bytes(nb);
    o.bytes(f.data);
    const raw = offsets[i] + sizes[i];
    o.zeros(align4(raw) - raw);
  }

  // ---- AOD 素材 + 尾部预览 ----
  for (const k of order) o.bytes(recs[k].payload);
  o.zeros(4);
  o.u16(PREVIEW_W);
  o.u16(PREVIEW_H);
  o.u32(previewBgra.length);
  o.bytes(previewBgra);

  return o.finish();
}

/**
 * 解包：把一份 .face 拆成 packFace 的输入，用于往返对拍与结构校验。
 * @param {Uint8Array} bytes
 */
export function unpackFace(bytes) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u16 = (p) => v.getUint16(p, true);
  const u32 = (p) => v.getUint32(p, true);
  for (let i = 0; i < 4; i++) {
    if (bytes[i] !== MAGIC[i]) throw new Error('magic 不符，不是 .face');
  }
  const screens = u16(28);
  const hasAod = screens === 2;
  const n = u32(216);
  const idx = hasAod ? INDEX_START_AOD : INDEX_START;

  const idLen = bytes[5];
  const faceId = new TextDecoder().decode(bytes.subarray(40, 40 + ID_LEN)).replace(/\0.*$/, '');
  const title = new TextDecoder().decode(bytes.subarray(104, 104 + TITLE_LEN)).replace(/\0.*$/, '');

  // 索引表
  const idxEntries = [];
  for (let i = 0; i < n; i++) {
    const p = idx + i * INDEX_ENTRY_SIZE;
    idxEntries.push({ index: u16(p), tag: u16(p + 2), off: u32(p + 8), size: u32(p + 12) });
  }

  // 描述块：读到哨兵（tag 0x0500）为止
  const d0 = idx + n * INDEX_ENTRY_SIZE;
  const recs = [];
  let p = d0;
  let sentinelInfo = null;
  for (let guard = 0; guard < 100000; guard++) {
    const ridx = u16(p), tag = u16(p + 2), off = u32(p + 8), size = u32(p + 12);
    if (tag === TAG_SENTINEL) { sentinelInfo = { idx: ridx, off, size }; break; }
    recs.push({ idx: ridx, tag, payload: bytes.subarray(off, off + size) });
    p += INDEX_ENTRY_SIZE;
  }
  if (!sentinelInfo) throw new Error('没找到描述块哨兵');
  const descEnd = p + INDEX_ENTRY_SIZE;

  // 文件数据区
  const files = [];
  let cur = descEnd;
  for (const e of idxEntries) {
    const nameLen = bytes[e.off + 3];
    const name = new TextDecoder().decode(bytes.subarray(e.off + 20, e.off + 20 + nameLen));
    const dataLen = e.size - 20 - nameLen;
    const start = e.off + 20 + nameLen;
    files.push({ name, data: bytes.subarray(start, start + dataLen) });
    cur = align4(e.off + e.size);
  }

  // 尾部预览
  const previewLen = 12 + PREVIEW_W * PREVIEW_H * 4;
  const pStart = bytes.length - previewLen;
  const pw = u16(pStart + 4), ph = u16(pStart + 6), plen = u32(pStart + 8);
  const previewBgra = bytes.subarray(pStart + 12, pStart + 12 + plen);

  return {
    title, faceId, idLen, hasAod, screens, n, idx, d0, descEnd,
    sentinelIdx: sentinelInfo.idx,
    filesEnd: cur, assetsEnd: u32(32), preview: { w: pw, h: ph, len: plen },
    files, recs, previewBgra, bytes,
  };
}

/** 结构化摘要，给校验面板用 */
export function describeFace(bytes) {
  const f = unpackFace(bytes);
  const tags = {};
  for (const r of f.recs) tags[r.tag] = (tags[r.tag] || 0) + 1;
  const frames = f.files.filter((x) => /^lua\/face_\d+\.(png|jpg|jpeg)$/i.test(x.name)).length;
  return {
    title: f.title, faceId: f.faceId, hasAod: f.hasAod, fileCount: f.n,
    frameCount: frames, aodTags: tags,
    size: bytes.length, assetsEnd: f.assetsEnd, preview: f.preview,
  };
}
