/**
 * 息屏显示（AOD）子工程：控件规划 + 描述记录推导 + 素材绘制。
 *
 * 三条硬事实（都是实测出来的，别推翻）：
 *  1. **AOD 屏不支持 Lua。** 只能是 Shape=30（静态图）与 Shape=32（数字位图 + Value_Src）。
 *  2. Value_Src 里的数据源 ID 编译器不校验，设备侧 dataman 运行期解析 —— 所以照抄 ID 即可。
 *  3. AOD 上的 Shape=30 便宜（`w*h*4 + 60`）；主屏上的才会被合成为整屏位图（+441 KB）。
 *
 * 设计取舍：时分共用同一张 11 图列表，只付一次位图钱；冒号单独一张小图（12×64 ≈ 3 KB），
 * 比再建一张数字列表划算。默认不放全屏黑底 —— AMOLED 黑像素不发光。
 *
 * 端口自 watchface-android/core/face/AodGen.java（与 Python 侧做过 12 例 × 13 字段对拍）。
 */

export const SCREEN_W = 212;
export const SCREEN_H = 520;

export const TIME_DIGIT_W = 46;
export const TIME_DIGIT_H = 64;
export const DATE_DIGIT_W = 20;
export const DATE_DIGIT_H = 28;
export const COLON_W = 12;
/** 官方样本的 BitmapList 是 11 张：0..9 再补一张 0。照抄数量规避"某位不显示"。 */
export const DIGIT_IMAGE_COUNT = 11;

export const SRC = { HOUR: '0811', MINUTE: '1011', MONTH: '1012', DAY: '1812' };

export const TAG = { ANCHOR: 0x0000, BITMAP: 0x0200, ARRAY: 0x0300, SMALL: 0x0700 };

const digitFile = (time, i) => (time ? `aod_t_${String(i).padStart(2, '0')}` : `aod_d_${String(i).padStart(2, '0')}`);

/** 10 张 + 补一张 0 = 11 项；时分共用同一份 */
export function digitList(time) {
  const l = [];
  for (let i = 0; i < 10; i++) l.push(digitFile(time, i));
  l.push(digitFile(time, 0));
  return l;
}

/** 按配置算出控件列表，顺序：底图 → 时 → 冒号 → 分 → 月 → 冒号 → 日 */
export function planAod(cfg) {
  const c = {
    enabled: true, bgMode: 'none', timeMode: 'time',
    timeY: 200, dateY: 300, color: '#FFFFFF',
    timeDigitW: TIME_DIGIT_W, timeDigitH: TIME_DIGIT_H,
    dateDigitW: DATE_DIGIT_W, dateDigitH: DATE_DIGIT_H, colonW: COLON_W,
    ...cfg,
  };
  const ws = [];
  const hasBg = c.enabled && (c.bgMode === 'black' || c.bgMode === 'custom');
  if (hasBg) ws.push({ kind: 30, name: 'aod_bg', img: 'aod_bg', x: 0, y: 0, w: SCREEN_W, h: SCREEN_H });

  const t = c.timeMode === 'time' || c.timeMode === 'both';
  const d = c.timeMode === 'both';
  if (t) {
    const tw = c.timeDigitW * 2 + c.colonW + c.timeDigitW * 2;
    const x0 = Math.floor((SCREEN_W - tw) / 2);
    ws.push({
      kind: 32, name: 'aod_hour', x: x0, y: c.timeY,
      w: c.timeDigitW * 2, h: c.timeDigitH,
      digitW: c.timeDigitW, digitH: c.timeDigitH, digits: 2,
      valueSrc: SRC.HOUR, bitmapList: digitList(true),
    });
    ws.push({
      kind: 30, name: 'aod_colon', img: 'aod_colon',
      x: x0 + c.timeDigitW * 2, y: c.timeY, w: c.colonW, h: c.timeDigitH,
    });
    ws.push({
      kind: 32, name: 'aod_min', x: x0 + c.timeDigitW * 2 + c.colonW, y: c.timeY,
      w: c.timeDigitW * 2, h: c.timeDigitH,
      digitW: c.timeDigitW, digitH: c.timeDigitH, digits: 2,
      valueSrc: SRC.MINUTE, bitmapList: digitList(true),
    });
  }
  if (d) {
    const dw = c.dateDigitW * 2 + c.colonW + c.dateDigitW * 2;
    const dx = Math.floor((SCREEN_W - dw) / 2);
    ws.push({
      kind: 32, name: 'aod_month', x: dx, y: c.dateY,
      w: c.dateDigitW * 2, h: c.dateDigitH,
      digitW: c.dateDigitW, digitH: c.dateDigitH, digits: 2,
      valueSrc: SRC.MONTH, bitmapList: digitList(false),
    });
    ws.push({
      kind: 30, name: 'aod_dcolon', img: 'aod_dcolon',
      x: dx + c.dateDigitW * 2, y: c.dateY, w: c.colonW, h: c.dateDigitH,
    });
    ws.push({
      kind: 32, name: 'aod_day', x: dx + c.dateDigitW * 2 + c.colonW, y: c.dateY,
      w: c.dateDigitW * 2, h: c.dateDigitH,
      digitW: c.dateDigitW, digitH: c.dateDigitH, digits: 2,
      valueSrc: SRC.DAY, bitmapList: digitList(false),
    });
  }
  return ws;
}

/** 控件表引用到的素材：名字 → 尺寸 */
export function neededImages(ws) {
  const m = new Map();
  for (const w of ws) {
    if (w.kind === 30) m.set(w.img, { w: w.w, h: w.h });
    else for (const f of w.bitmapList) m.set(f, { w: w.digitW, h: w.digitH });
  }
  return m;
}

/* ───────────────── 素材绘制 ───────────────── */

/** 纯 BGRA：整块不透明 */
function solidBgra(w, h, r, g, b) {
  const out = new Uint8Array(w * h * 4);
  for (let o = 0; o < out.length; o += 4) {
    out[o] = b; out[o + 1] = g; out[o + 2] = r; out[o + 3] = 255;
  }
  return out;
}

/** 灰度遮罩 → 直通 alpha 的 BGRA（等价于 PIL「透明画布 + 单色填充」） */
export function maskToBgra(mask, r, g, b) {
  const out = new Uint8Array(mask.length * 4);
  for (let i = 0; i < mask.length; i++) {
    out[i * 4] = b;
    out[i * 4 + 1] = g;
    out[i * 4 + 2] = r;
    out[i * 4 + 3] = mask[i];
  }
  return out;
}

/** 用 OffscreenCanvas 把单个字符画成灰度遮罩（字色不影响遮罩） */
function canvasMask(ch, w, h) {
  if (typeof OffscreenCanvas === 'undefined') {
    throw new Error('当前环境没有 OffscreenCanvas，无法绘制 AOD 数字');
  }
  const cv = new OffscreenCanvas(w, h);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#fff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  // 让字形贴近卡片高度：字号 ≈ 0.92h，字体族用系统无衬线
  const size = Math.round(h * 0.92);
  ctx.font = `600 ${size}px "Helvetica Neue", Arial, "PingFang SC", sans-serif`;
  ctx.fillText(ch, w / 2, h / 2 + Math.round(h * 0.02));
  const img = ctx.getImageData(0, 0, w, h).data;
  const mask = new Uint8Array(w * h);
  for (let i = 0; i < mask.length; i++) mask[i] = img[i * 4 + 3];
  return mask;
}

/** 往遮罩里盖一个抗锯齿圆点（用距离场做边缘，比字形可靠） */
function blob(mask, w, h, cx, cy, r) {
  for (let y = cy - r; y <= cy + r; y++) {
    for (let x = cx - r; x <= cx + r; x++) {
      if (x < 0 || y < 0 || x >= w || y >= h) continue;
      const d = Math.hypot(x - cx, y - cy);
      const a = Math.max(0, Math.min(1, r + 0.5 - d));
      if (a <= 0) continue;
      const o = y * w + x;
      mask[o] = Math.max(mask[o], Math.round(a * 255));
    }
  }
  return mask;
}

/** 冒号：用两个圆点画，比字形可靠（12 px 宽的字形常常糊成一团） */
function colonMask(w, h) {
  const mask = new Uint8Array(w * h);
  const r = Math.max(1, Math.round(w * 0.28));
  const cx = Math.floor(w / 2);
  for (const cy of [Math.round(h * 0.34), Math.round(h * 0.68)]) blob(mask, w, h, cx, cy, r);
  return mask;
}

/** 日期分隔句点：一个点，落在数字基线上（对应 PC / 安卓字库里的 DOT 字模） */
function dotMask(w, h) {
  const mask = new Uint8Array(w * h);
  const r = Math.max(1, Math.round(w * 0.28));
  return blob(mask, w, h, Math.floor(w / 2), Math.round(h * 0.83), r);
}

/**
 * 生成 AOD 需要的全部素材。
 * @param {ReturnType<typeof planAod>} ws
 * @param {{color?:string, renderMask?:(ch:string,w:number,h:number)=>Uint8Array}} opts
 * @returns {Map<string, {w:number,h:number,bgra:Uint8Array}>}
 */
export function makeAodImages(ws, opts = {}) {
  const [r, g, b] = parseColor(opts.color || '#FFFFFF');
  const renderMask = opts.renderMask || canvasMask;
  const need = neededImages(ws);
  const out = new Map();
  const cache = new Map();

  for (const [name, size] of need) {
    const key = `${name}@${size.w}x${size.h}`;
    if (cache.has(key)) { out.set(name, cache.get(key)); continue; }

    let img;
    if (name === 'aod_bg') {
      img = { w: size.w, h: size.h, bgra: solidBgra(size.w, size.h, 0, 0, 0) };
    } else if (name === 'aod_dcolon') {
      // 日期分隔：一个句点（文件名沿用 dcolon，和 PC / 安卓一致）
      img = { w: size.w, h: size.h, bgra: maskToBgra(dotMask(size.w, size.h), r, g, b) };
    } else if (name === 'aod_colon') {
      img = { w: size.w, h: size.h, bgra: maskToBgra(colonMask(size.w, size.h), r, g, b) };
    } else {
      const digit = Number(name.slice(-2));
      img = { w: size.w, h: size.h, bgra: maskToBgra(renderMask(String(digit), size.w, size.h), r, g, b) };
    }
    cache.set(key, img);
    out.set(name, img);
  }
  return out;
}

/* ───────────────── 描述记录 ───────────────── */

const hex2bin = (hex) => [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16)];

/**
 * 由控件列表推导描述记录。顺序固定：
 * 锚(0x0000)×控件数 → 位图(0x0200) → 位图数组(0x0300) → 小件(0x0700)
 *
 * 两个必须记牢的点：
 *  - 记录 idx：锚是**控件序号**，其余是**该类内序号**，各自独立计数。
 *  - 锚 payload 首字段也是**类内序号**（按 refTag 0x0200 / 0x0700 分别计数）。
 */
export function buildAodRecs(ws, images) {
  const recs = [];

  // 锚
  let seq200 = 0, seq700 = 0;
  ws.forEach((w, i) => {
    const refTag = w.kind === 30 ? TAG.BITMAP : TAG.SMALL;
    const anchorX = w.kind === 30 ? w.x : w.x + w.digitW;
    const seq = w.kind === 30 ? seq200++ : seq700++;
    const p = new Uint8Array(16);
    const dv = new DataView(p.buffer);
    dv.setUint16(0, seq, true);
    dv.setUint16(2, refTag, true);
    dv.setUint16(4, anchorX, true);
    dv.setUint16(6, w.y, true);
    recs.push({ idx: i, tag: TAG.ANCHOR, payload: p });
  });

  // 位图
  let k = 0;
  for (const w of ws) {
    if (w.kind !== 30) continue;
    const im = images.get(w.img);
    if (!im) throw new Error(`缺素材：${w.img}`);
    const p = new Uint8Array(12 + im.bgra.length);
    const dv = new DataView(p.buffer);
    dv.setUint16(4, im.w, true);
    dv.setUint16(6, im.h, true);
    dv.setUint32(8, im.bgra.length, true);
    p.set(im.bgra, 12);
    recs.push({ idx: k++, tag: TAG.BITMAP, payload: p });
  }

  // 位图数组（按 BitmapList 去重）
  let ak = 0;
  const arrOf = new Map();
  for (const w of ws) {
    if (w.kind !== 32) continue;
    const key = w.bitmapList.join('|');
    if (arrOf.has(key)) continue;
    const n = w.bitmapList.length;
    const data = new Uint8Array(w.digitW * w.digitH * 4 * n);
    let off = 0;
    for (const f of w.bitmapList) {
      const im = images.get(f);
      if (!im) throw new Error(`缺素材：${f}`);
      data.set(im.bgra, off);
      off += im.bgra.length;
    }
    const p = new Uint8Array(12 + data.length);
    const dv = new DataView(p.buffer);
    p[1] = n; // u8 图数
    dv.setUint16(4, w.digitW, true);
    dv.setUint16(6, w.digitH, true);
    dv.setUint32(8, w.digitW * w.digitH * 4 * n, true);
    p.set(data, 12);
    arrOf.set(key, ak);
    recs.push({ idx: ak++, tag: TAG.ARRAY, payload: p });
  }

  // 小件（每个 Shape=32 一条）
  let sk = 0;
  for (const w of ws) {
    if (w.kind !== 32) continue;
    const ai = arrOf.get(w.bitmapList.join('|'));
    if (ai === undefined) throw new Error(`未找到位图数组：${w.name}`);
    const p = new Uint8Array(20);
    const dv = new DataView(p.buffer);
    const [hi, lo] = hex2bin(w.valueSrc);
    p[0] = hi; p[1] = lo;
    p[2] = w.digits;
    p[3] = 0x16;
    dv.setUint16(8, ai, true);
    dv.setUint16(10, TAG.ARRAY, true);
    recs.push({ idx: sk++, tag: TAG.SMALL, payload: p });
  }

  return recs;
}

/** 体积（与实测模型一致：AOD 空屏 +88 B；Shape30 `w*h*4+60`；数组按图数算） */
export function estimateAodBytes(cfg) {
  const c = { bgMode: 'none', timeMode: 'time', ...cfg };
  if (!c.enabled) return 0;
  let n = 88;
  if (c.bgMode === 'black' || c.bgMode === 'custom') n += SCREEN_W * SCREEN_H * 4 + 60;
  if (c.timeMode === 'time' || c.timeMode === 'both') {
    n += DIGIT_IMAGE_COUNT * TIME_DIGIT_W * TIME_DIGIT_H * 4;
    n += COLON_W * TIME_DIGIT_H * 4 + 60;
  }
  if (c.timeMode === 'both') {
    n += DIGIT_IMAGE_COUNT * DATE_DIGIT_W * DATE_DIGIT_H * 4;
    n += COLON_W * DATE_DIGIT_H * 4 + 60;
  }
  return n;
}

/** 描述记录条数：锚×控件数 + 位图(每个 Shape30) + 数组(去重后的清单数) + 小件(每个 Shape32) */
export function aodRecCount(ws) {
  const bitmaps = ws.filter((w) => w.kind === 30).length;
  const smalls = ws.filter((w) => w.kind === 32).length;
  const arrays = new Set(ws.filter((w) => w.kind === 32).map((w) => w.bitmapList.join('|'))).size;
  return ws.length + bitmaps + arrays + smalls;
}

/** '#RRGGBB' / '#RGB' → [r,g,b]，非法则白色 */
export function parseColor(s) {
  let t = (s || '').trim();
  if (t.startsWith('#')) t = t.slice(1);
  if (t.length === 3) t = t.split('').map((ch) => ch + ch).join('');
  if (!/^[0-9a-fA-F]{6}$/.test(t)) return [255, 255, 255];
  return [parseInt(t.slice(0, 2), 16), parseInt(t.slice(2, 4), 16), parseInt(t.slice(4, 6), 16)];
}
