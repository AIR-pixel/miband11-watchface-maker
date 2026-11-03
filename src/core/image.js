/**
 * 图像基础操作：把任意尺寸的 RGBA 缩放 / 居中裁剪到 212×520。
 *
 * 缩小用面积平均（box），放大用双线性。表盘素材基本都在缩小，box 的质量够用且快。
 */

/**
 * @param {Uint8Array} src RGBA8888
 * @returns {Uint8Array} RGBA8888，dw*dh*4
 */
export function resizeRGBA(src, sw, sh, dw, dh) {
  const out = new Uint8Array(dw * dh * 4);
  const xr = sw / dw;
  const yr = sh / dh;
  for (let dy = 0; dy < dh; dy++) {
    const y0 = dy * yr;
    const y1 = y0 + yr;
    for (let dx = 0; dx < dw; dx++) {
      const x0 = dx * xr;
      const x1 = x0 + xr;
      let r = 0, g = 0, b = 0, a = 0, wsum = 0;
      for (let y = Math.floor(y0); y < Math.ceil(y1); y++) {
        const wy = Math.min(y + 1, y1) - Math.max(y, y0);
        if (wy <= 0) continue;
        const rowOff = Math.min(y, sh - 1) * sw;
        for (let x = Math.floor(x0); x < Math.ceil(x1); x++) {
          const wx = Math.min(x + 1, x1) - Math.max(x, x0);
          if (wx <= 0) continue;
          const w = wx * wy;
          const o = (rowOff + Math.min(x, sw - 1)) * 4;
          r += src[o] * w; g += src[o + 1] * w; b += src[o + 2] * w; a += src[o + 3] * w;
          wsum += w;
        }
      }
      const o = (dy * dw + dx) * 4;
      if (wsum > 0) {
        out[o] = Math.round(r / wsum);
        out[o + 1] = Math.round(g / wsum);
        out[o + 2] = Math.round(b / wsum);
        out[o + 3] = Math.round(a / wsum);
      }
    }
  }
  return out;
}

/** 居中裁剪到目标宽高比后再缩放（保持画面不变形） */
export function coverRGBA(src, sw, sh, dw, dh) {
  const targetRatio = dw / dh;
  const srcRatio = sw / sh;
  let cw = sw, ch = sh, ox = 0, oy = 0;
  if (srcRatio > targetRatio) {
    cw = Math.round(sh * targetRatio);
    ox = Math.floor((sw - cw) / 2);
  } else if (srcRatio < targetRatio) {
    ch = Math.round(sw / targetRatio);
    oy = Math.floor((sh - ch) / 2);
  }
  const crop = new Uint8Array(cw * ch * 4);
  for (let y = 0; y < ch; y++) {
    const s = ((oy + y) * sw + ox) * 4;
    crop.set(src.subarray(s, s + cw * 4), y * cw * 4);
  }
  return resizeRGBA(crop, cw, ch, dw, dh);
}
