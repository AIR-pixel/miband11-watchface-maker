/**
 * 端到端：素材 → .face。不碰 Compiler.exe，也不生成 .fprj。
 *
 * 链路：选帧 → 裁到 212×520 → 调色板量化 → PNG → Lua → 拼容器。
 * 多壁纸时每张壁纸独立成页：第 1 张文件前缀 `face`，第 2 张起 `w2` / `w3`，
 * 由 Lua 里的 `WALLS` 表 + 短按切换驱动。
 *
 * 素材有两种来源，都收敛成「n 帧 RGBA + 播放节奏」：
 *   { kind: 'gif',   bytes }           GIF 字节，本模块自己解（可在 Worker 里跑）
 *   { kind: 'frames', frames, periodMs } 已经裁好的 RGBA 帧（视频抽帧走这条，
 *                                      因为 Worker 没有 <video>，抽帧只能在主线程做）
 */
import { decodeGif } from './gif.js';
import { coverRGBA } from './image.js';
import { quantize } from './quantize.js';
import { encodePNG } from './png.js';
import { encodeJPEG } from './jpeg.js';
import { generateLua } from './lua.js';
import { planAod, makeAodImages, buildAodRecs, estimateAodBytes } from './aod.js';
import { packFace, PREVIEW_W, PREVIEW_H } from './facebin.js';

export const LEVELS = {
  high: { colors: 256, label: 'P256 · 高画质' },
  balanced: { colors: 256, label: 'P256 · 均衡' },
  small: { colors: 128, label: 'P128 · 小体积' },
  tiny: { colors: 64, label: 'P64 · 极限' },
};

/**
 * 默认 JPEG 质量。界面上的档位（90/85/80/70/60）写在 index.html 里，编码器本身
 * 认任意 1..100 —— 不需要和这里保持同步，这里只给「没传参时用哪个」。
 */
export const JPG_QUALITY = 80;

/**
 * 编码一帧。
 *
 * PNG 走「量化到调色板 + 无损压缩」；JPEG 直接吃 RGBA 全彩 —— 它本身是有损的，
 * 再套一层 256 色量化纯属重复损失（PC 端也是这么分的：`high` 档 = RGB 直出，不量化）。
 */
export async function encodeFrame(rgba, colors, fmt, jpgQuality) {
  if (fmt === 'jpg') return encodeJPEG(rgba, PREVIEW_W, PREVIEW_H, jpgQuality);
  const { indices, palette } = quantize(rgba, colors, false);
  return encodePNG(indices, palette, PREVIEW_W, PREVIEW_H);
}

/**
 * 把「起始 / 时长」两个秒数换算成毫秒区间，并夹到素材实际长度内。
 * 与 PC 端一致：时长留空（或 0）= 取到结尾；起始超出长度则退化成全片。
 */
export function clipRange(durationMs, clipStart = 0, clipDur = 0) {
  const total = Math.max(1, durationMs);
  let s = Math.max(0, Number(clipStart) || 0) * 1000;
  if (s >= total) s = 0;
  let e = total;
  const d = Number(clipDur) || 0;
  if (d > 0) e = Math.min(total, s + d * 1000);
  if (e - s < 1000 / 30) e = Math.min(total, s + 1000 / 30);  // 至少留一帧的宽度
  return { startMs: s, endMs: e, spanMs: Math.max(1, e - s) };
}

/**
 * GIF 选帧：保时长、降帧率（帧数触顶时的两种取舍之一；另一种是快放，这里不做）。
 * 支持裁切：只在 `[startMs, endMs)` 里选帧。
 * @param {number[]} delays 每帧延时（ms）
 * @param {{startMs?:number,endMs?:number,spanMs?:number}} [clip] clipRange() 的返回值
 */
export function planFrames(delays, targetFps, maxFrames, clip = null) {
  const starts = [];
  let t = 0;
  for (const d of delays) { starts.push(t); t += d; }
  const total = t;

  const s = clip ? clip.startMs : 0;
  const e = clip ? clip.endMs : total;
  const spanMs = Math.max(1, e - s);

  // 只在区间内的帧里挑，别把区间外的帧选进来（那样等于没裁）
  const pool = [];
  for (let k = 0; k < starts.length; k++) {
    if (starts[k] >= s - 1e-6 && starts[k] < e - 1e-6) pool.push(k);
  }
  if (!pool.length) {
    // 区间比一帧还窄：退化成「离起点最近的那一帧」
    let best = 0, bestD = Infinity;
    for (let k = 0; k < starts.length; k++) {
      const d = Math.abs(starts[k] - s);
      if (d < bestD) { bestD = d; best = k; }
    }
    pool.push(best);
  }

  let periodMs = Math.round(1000 / targetFps);
  let count = Math.max(1, Math.floor(spanMs / periodMs));
  if (count > maxFrames) {
    periodMs = Math.round(spanMs / maxFrames);
    count = Math.max(1, Math.floor(spanMs / periodMs));
  }
  count = Math.min(count, maxFrames);

  const indices = [];
  for (let i = 0; i < count; i++) {
    const want = s + i * periodMs;
    let best = pool[0], bestD = Infinity;
    for (const k of pool) {
      const d = Math.abs(starts[k] - want);
      if (d < bestD) { bestD = d; best = k; }
    }
    indices.push(best);
  }
  return { indices, periodMs, durationMs: spanMs, clipStartMs: s };
}

/**
 * 视频（等间隔）选帧：与 GIF 同一条规矩 —— 帧数触顶就降帧率、保住时长。
 * 返回的时间点是**绝对时间**（已含裁切起点），直接喂给 extractFrames。
 */
export function planUniform(durationMs, targetFps, maxFrames, clip = null) {
  const s = clip ? clip.startMs : 0;
  const spanMs = clip ? clip.spanMs : Math.max(1, durationMs);

  let periodMs = Math.round(1000 / targetFps);
  let count = Math.max(1, Math.floor(spanMs / periodMs));
  if (count > maxFrames) {
    periodMs = Math.round(spanMs / maxFrames);
    count = Math.max(1, Math.floor(spanMs / periodMs));
  }
  count = Math.min(count, maxFrames);
  const times = [];
  for (let i = 0; i < count; i++) times.push(s + i * periodMs);
  return { times, count, periodMs, durationMs: spanMs, clipStartMs: s };
}

const rgbaToBgra = (rgba) => {
  const out = new Uint8Array(rgba.length);
  for (let i = 0; i < rgba.length; i += 4) {
    out[i] = rgba[i + 2];
    out[i + 1] = rgba[i + 1];
    out[i + 2] = rgba[i];
    out[i + 3] = rgba[i + 3];
  }
  return out;
};

/**
 * 定长 ASCII 字段（Title 16 B / ID 10 B）：**按码点**把非 ASCII 换成 `?`，
 * 再按字节截断。与 PC 端 `s.encode("ascii","replace")` 结果逐字节相同。
 *
 * 别用 `TextEncoder`：一个汉字 3 字节，16 字节的 Title 会被截在半个汉字上，
 * 产物里留下非法 UTF-8 序列。
 */
export function asciiField(s, len) {
  let out = '';
  for (const ch of String(s)) {
    if (out.length >= len) break;
    out += ch.codePointAt(0) < 0x80 ? ch : '?';
  }
  return out;
}

/**
 * 下载文件名：**保留用户输入的原样**（中文名当文件名没问题，只是不能进 Title 字段），
 * 只清掉各系统的非法字符。
 */
export function faceFileName(title) {
  const base = String(title || '').trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, '_') || 'MyFace';
  return `${base}.face`;
}

/**
 * @param {object} cfg
 * @param {Array<{kind:'gif',bytes:Uint8Array,clip?:object}|{kind:'frames',frames:Uint8Array[],periodMs:number}>} cfg.sources
 * @param {number} [cfg.fps=12]
 * @param {number} [cfg.maxFrames=96] **每张壁纸**的帧数上限
 * @param {'high'|'balanced'|'small'|'tiny'} [cfg.level='balanced']
 * @param {'png'|'jpg'} [cfg.fmt='png'] 编码格式
 * @param {number} [cfg.jpgQuality=80] JPEG 质量（仅 fmt='jpg' 时有意义）
 * @param {boolean} [cfg.showTime=true]
 * @param {boolean} [cfg.showDate=false]
 * @param {string} [cfg.title='MyFace']
 * @param {string} [cfg.faceId='1000000001']
 * @param {'none'|'cycle'|'info'|'anim'} [cfg.tap='none']
 * @param {{enabled:boolean,timeMode?:'time'|'both',timeY?:number,dateY?:number,
 *          color?:string,bgMode?:'none'|'black'}} [cfg.aod]
 * @param {(ch:string,w:number,h:number)=>Uint8Array} [cfg.renderMask] 数字字形遮罩（测试注入用）
 * @param {(r:number, msg:string)=>void} [cfg.onProgress]
 */
export async function buildFace(cfg) {
  const {
    sources = [], fps = 12, maxFrames = 96, level = 'balanced',
    fmt = 'png', jpgQuality = JPG_QUALITY,
    showTime = true, showDate = false,
    title = 'MyFace', faceId = '1000000001', faceName = null,
    timeOfs = [0, 30], timeSize = 48, timeColor = 0xffffff, timeFmt = '%H:%M',
    dateOfs = [0, 86], dateSize = 16, dateColor = 0xeeeeee, dateFmt = '%m/%d',
    tap = 'none', aod = null, renderMask = null, onProgress = () => {},
  } = cfg;

  if (!sources.length) throw new Error('没有素材');
  const colors = (LEVELS[level] || LEVELS.balanced).colors;
  const ext = fmt === 'jpg' ? 'jpg' : 'png';
  // Title / ID 是定长 ASCII 字段，这里统一收口（PC 端同样的规则见 facebin.py 的 _fixed_ascii）
  const titleField = asciiField(title, 16);
  const idField = String(faceId).replace(/\D/g, '').slice(0, 10) || '1000000001';

  // ---- 先把每张壁纸的帧数与取帧方式定下来，才能给出准确的总进度 ----
  onProgress(0.02, sources.length > 1 ? `准备 ${sources.length} 张壁纸…` : '准备素材…');
  const pages = sources.map((src, wi) => {
    const prefix = wi === 0 ? 'face' : `w${wi + 1}`;
    if (src.kind === 'frames') {
      if (!src.frames || !src.frames.length) throw new Error(`第 ${wi + 1} 张壁纸没有帧`);
      return { prefix, count: src.frames.length, periodMs: src.periodMs,
        frame: (i) => src.frames[i] };
    }
    const gif = decodeGif(src.bytes);
    if (!gif.frames.length) throw new Error(`第 ${wi + 1} 张壁纸没有帧`);
    // 每张壁纸各自按自己的区间选帧（多壁纸时裁切是逐张独立的）
    const plan = planFrames(gif.frames.map((f) => f.delayMs), fps, maxFrames, src.clip);
    return { prefix, count: plan.indices.length, periodMs: plan.periodMs,
      frame: (i) => coverRGBA(gif.frames[plan.indices[i]].rgba, gif.width, gif.height,
        PREVIEW_W, PREVIEW_H) };
  });
  const totalFrames = pages.reduce((a, p) => a + p.count, 0);
  onProgress(0.06, `${totalFrames} 帧 @ ${(1000 / pages[0].periodMs).toFixed(1)}fps`);

  // ---- 逐页编码 ----
  const files = [];
  const perFrame = [];
  let firstRgba = null;
  let done = 0;
  for (const page of pages) {
    for (let i = 0; i < page.count; i++) {
      const rgba = page.frame(i);
      const data = await encodeFrame(rgba, colors, fmt, jpgQuality);
      files.push({ name: `lua/${page.prefix}_${String(i + 1).padStart(2, '0')}.${ext}`, data });
      perFrame.push(data.length);
      if (!firstRgba) firstRgba = rgba;
      done += 1;
      onProgress(0.06 + 0.84 * (done / totalFrames), `编码帧 ${done}/${totalFrames}`);
    }
  }

  // ---- AOD 息屏子工程 ----
  let recs = [];
  let hasAod = false;
  let aodBytes = 0;
  if (aod && aod.enabled) {
    onProgress(0.9, '绘制息屏数字…');
    const ws = planAod(aod);
    const images = makeAodImages(ws, { color: aod.color || '#FFFFFF', renderMask });
    recs = buildAodRecs(ws, images);
    hasAod = true;
    aodBytes = estimateAodBytes({ enabled: true, ...aod });
  }

  onProgress(0.93, '生成脚本…');
  const walls = pages.map((p) => ({ prefix: p.prefix, count: p.count, periodMs: p.periodMs }));
  // 多壁纸默认给「短按切换」——不然多张壁纸只有第一张能看到
  const tapFinal = tap === 'none' && walls.length > 1 ? 'cycle' : tap;
  const lua = generateLua({
    walls, ext, showTime, showDate,
    timeOfs, timeSize, timeColor, timeFmt,
    dateOfs, dateSize, dateColor, dateFmt,
    tap: tapFinal,
    desc: walls.length > 1
      ? `${walls.length} 张壁纸 / 共 ${totalFrames} 帧`
      : `${totalFrames} 帧 / ${(1000 / walls[0].periodMs).toFixed(1)}fps`,
  });
  // 文件按**名字升序**进索引表 —— 官方编译器就是这么排的（face_* → main.lua → w2_*）
  files.push({ name: 'lua/main.lua', data: new TextEncoder().encode(lua) });
  files.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));

  onProgress(0.97, '打包 .face…');
  const face = packFace({
    title: titleField,
    faceId: idField,
    files,
    previewBgra: rgbaToBgra(firstRgba),
    hasAod,
    recs,
    // 哨兵 idx = **第一页帧数**（多壁纸时不是 n-1，实测过）
    sentinelIdx: walls[0].count,
  });

  onProgress(1, '完成');
  return {
    face,
    // 文件名保留用户输入原样（中文名可以当文件名，只是进不了 Title 字段）
    faceName: faceName || faceFileName(title),
    stats: {
      frames: totalFrames,
      walls: walls.length,
      framesPerWall: walls.map((w) => w.count),
      periodMs: walls[0].periodMs,
      fps: +(1000 / walls[0].periodMs).toFixed(2),
      bytes: face.length,
      imageBytes: perFrame.reduce((a, b) => a + b, 0),
      perFrame,
      overhead: face.length - perFrame.reduce((a, b) => a + b, 0),
      colors,
      fmt,
      jpgQuality: fmt === 'jpg' ? jpgQuality : null,
      hasAod,
      aodBytes,
      recs: recs.length,
      tap: tapFinal,
    },
  };
}

/**
 * 兼容入口：只吃 GIF 字节的旧签名（测试与老代码在用）。
 * @deprecated 新代码用 `buildFace({ sources })`
 */
export async function buildFaceFromGif(cfg) {
  const { gifs, gifBytes, ...rest } = cfg;
  const list = (gifs && gifs.length ? gifs : [gifBytes]).filter(Boolean);
  return buildFace({ ...rest, sources: list.map((bytes) => ({ kind: 'gif', bytes })) });
}
