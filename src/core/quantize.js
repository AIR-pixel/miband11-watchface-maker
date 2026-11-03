/**
 * 调色板量化：中位切分（median cut）+ 可选 Floyd–Steinberg 抖动。
 *
 * 表盘的 P64 / P128 / P256 三档就是这么来的 —— 调的只是调色板颜色数。
 * 体积上的杠杆不在色深（P256→P64 每帧只降 38%），而在线性帧数和编码格式，
 * 所以这里的调色板分配不必过度追求质量：不加抖动的中位切分已经够看。
 */

/**
 * @param {Uint8Array} rgba RGBA8888
 * @param {number} maxColors 2..256
 * @param {boolean} dither 是否抖动
 * @returns {{ indices: Uint8Array, palette: Uint8Array }}
 */
export function quantize(rgba, maxColors, dither = false) {
  const hist = new Map(); // key = r<<16|g<<8|b
  const nPix = rgba.length >> 2;
  for (let i = 0; i < nPix; i++) {
    const o = i * 4;
    if (rgba[o + 3] === 0) continue;
    const k = (rgba[o] << 16) | (rgba[o + 1] << 8) | rgba[o + 2];
    const e = hist.get(k);
    if (e) e.n++;
    else hist.set(k, { r: rgba[o], g: rgba[o + 1], b: rgba[o + 2], n: 1 });
  }
  const colors = [...hist.values()];
  const palette = colors.length <= maxColors ? uniqueColors(colors) : medianCut(colors, maxColors);

  const indices = dither
    ? ditherToIndices(rgba, palette)
    : directToIndices(rgba, palette);
  return { indices, palette };
}

function uniqueColors(colors) {
  const pal = new Uint8Array(colors.length * 3);
  colors.forEach((c, i) => {
    pal[i * 3] = c.r; pal[i * 3 + 1] = c.g; pal[i * 3 + 2] = c.b;
  });
  return pal;
}

function medianCut(colors, maxColors) {
  let boxes = [makeBox(colors)];
  while (boxes.length < maxColors) {
    // 选「体积 × 像素数」最大的盒子继续切
    let best = -1, bestScore = -1;
    for (let i = 0; i < boxes.length; i++) {
      const b = boxes[i];
      if (b.list.length < 2) continue;
      const score = b.range * b.total;
      if (score > bestScore) { bestScore = score; best = i; }
    }
    if (best < 0) break;
    const b = boxes[best];
    const axis = b.axis;
    b.list.sort((p, q) => p[axis] - q[axis]);
    const total = b.total;
    let acc = 0, cut = 1;
    for (let i = 0; i < b.list.length - 1; i++) {
      acc += b.list[i].n;
      if (acc >= total / 2) { cut = i + 1; break; }
    }
    const left = b.list.slice(0, cut);
    const right = b.list.slice(cut);
    boxes.splice(best, 1, makeBox(left), makeBox(right));
  }

  const pal = new Uint8Array(boxes.length * 3);
  boxes.forEach((b, i) => {
    let r = 0, g = 0, bl = 0, n = 0;
    for (const c of b.list) { r += c.r * c.n; g += c.g * c.n; bl += c.b * c.n; n += c.n; }
    pal[i * 3] = Math.round(r / n);
    pal[i * 3 + 1] = Math.round(g / n);
    pal[i * 3 + 2] = Math.round(bl / n);
  });
  return pal;
}

function makeBox(list) {
  let rmin = 255, rmax = 0, gmin = 255, gmax = 0, bmin = 255, bmax = 0, total = 0;
  for (const c of list) {
    if (c.r < rmin) rmin = c.r; if (c.r > rmax) rmax = c.r;
    if (c.g < gmin) gmin = c.g; if (c.g > gmax) gmax = c.g;
    if (c.b < bmin) bmin = c.b; if (c.b > bmax) bmax = c.b;
    total += c.n;
  }
  const dr = rmax - rmin, dg = gmax - gmin, db = bmax - bmin;
  const axis = dr >= dg && dr >= db ? 'r' : dg >= db ? 'g' : 'b';
  return { list, axis, range: Math.max(dr, dg, db), total };
}

/** 最近色查找：15 位 RGB 立方缓存，避免每像素暴力搜索 */
function makeFinder(palette) {
  const n = palette.length / 3;
  const cache = new Int16Array(32768).fill(-1);
  return (r, g, b) => {
    const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
    const hit = cache[key];
    if (hit >= 0) return hit;
    let best = 0, bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const dr = r - palette[i * 3], dg = g - palette[i * 3 + 1], db = b - palette[i * 3 + 2];
      const d = dr * dr + dg * dg + db * db;
      if (d < bestD) { bestD = d; best = i; if (!d) break; }
    }
    cache[key] = best;
    return best;
  };
}

function directToIndices(rgba, palette) {
  const find = makeFinder(palette);
  const nPix = rgba.length >> 2;
  const out = new Uint8Array(nPix);
  for (let i = 0; i < nPix; i++) {
    const o = i * 4;
    out[i] = rgba[o + 3] === 0 ? 0 : find(rgba[o], rgba[o + 1], rgba[o + 2]);
  }
  return out;
}

/** Floyd–Steinberg 误差扩散（表盘素材大多是渐变，抖动对观感提升有限，默认关掉） */
function ditherToIndices(rgba, palette) {
  const n = palette.length / 3;
  const w = 212, h = Math.floor(rgba.length / 4 / 212);
  const find = makeFinder(palette);
  const buf = new Float32Array(rgba.length);
  for (let i = 0; i < rgba.length; i++) buf[i] = rgba[i];
  const out = new Uint8Array(w * h);
  const spread = (o, er, eg, eb, k) => {
    buf[o] += er * k; buf[o + 1] += eg * k; buf[o + 2] += eb * k;
  };
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4;
      const r = Math.max(0, Math.min(255, buf[o]));
      const g = Math.max(0, Math.min(255, buf[o + 1]));
      const b = Math.max(0, Math.min(255, buf[o + 2]));
      const ci = find(r, g, b);
      out[y * w + x] = ci;
      const er = r - palette[ci * 3], eg = g - palette[ci * 3 + 1], eb = b - palette[ci * 3 + 2];
      if (x + 1 < w) spread(o + 4, er, eg, eb, 7 / 16);
      if (y + 1 < h) {
        const d = o + w * 4;
        if (x > 0) spread(d - 4, er, eg, eb, 3 / 16);
        spread(d, er, eg, eb, 5 / 16);
        if (x + 1 < w) spread(d + 4, er, eg, eb, 1 / 16);
      }
    }
  }
  return out;
}
