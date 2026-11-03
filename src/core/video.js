/**
 * 视频抽帧：mp4 / webm / mov → 212×520 的 RGBA 帧。
 *
 * 为什么不在 Worker 里做：Worker 没有 `<video>`，也就没有解码器。所以视频这条路是
 * **主线程抽帧 → 把 RGBA 帧按 Transferable 传给 Worker**。GIF 那条路相反（传字节、
 * Worker 自己解），因为 GIF 解码是纯 JS。
 *
 * 抽帧方式是 seek + drawImage，不是 `requestVideoFrameCallback` 顺序播——
 * 后者必须实时播放，8 秒素材就要等 8 秒，而且抽第 60 帧得先播过前 59 帧。
 * seek 每次都跳到目标时间，总耗时只和帧数有关。
 */

/** 视频元信息 + 一个可直接复用的 <video>（停在首帧） */
export async function probeVideo(file) {
  const url = URL.createObjectURL(file);
  const v = document.createElement('video');
  v.preload = 'auto';
  v.muted = true;
  v.playsInline = true;
  v.src = url;
  // **必须挂进 DOM**：detached <video> 不进渲染管线，`requestVideoFrameCallback`
  // 基本不触发，seeked 之后合成器也可能还没拿到新帧 —— drawImage 会画出上一帧。
  // 1×1 + opacity 0.01 + z-index -1：在视口内（才会被合成）但肉眼不可见、不吃点击。
  Object.assign(v.style, {
    position: 'fixed', top: '0', left: '0', width: '1px', height: '1px',
    opacity: '0.01', pointerEvents: 'none', zIndex: '-1',
  });
  document.body.appendChild(v);

  try {
    await new Promise((res, rej) => {
      const ok = () => { cleanup(); res(); };
      const bad = () => { cleanup(); rej(new Error('浏览器解不了这个视频格式')); };
      const cleanup = () => {
        v.removeEventListener('loadeddata', ok);
        v.removeEventListener('error', bad);
      };
      v.addEventListener('loadeddata', ok);
      v.addEventListener('error', bad);
      v.load();
    });
  } catch (e) {
    v.remove();
    URL.revokeObjectURL(url);
    throw e;
  }

  const duration = Number.isFinite(v.duration) ? v.duration : 0;
  if (!duration) {
    v.remove();
    URL.revokeObjectURL(url);
    throw new Error('读不出视频时长（可能是流式 webm）');
  }
  return { url, el: v, durationMs: Math.round(duration * 1000), width: v.videoWidth, height: v.videoHeight };
}

/**
 * 等一帧真正被提交出来。`seeked` 只保证「位置到了」，不保证「新帧可画」——
 * Chrome 硬件解码下常见，直接 drawImage 会拿到上一帧。所以要先注册
 * `requestVideoFrameCallback`（新帧提交时回调）**再**改 currentTime。
 * 不支持 rVFC 的浏览器退回 rAF。
 */
function waitNewFrame(v, timeoutMs = 900) {
  return new Promise((res) => {
    let settled = false;
    let timer = 0;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      res();
    };
    timer = setTimeout(finish, timeoutMs);
    if (typeof v.requestVideoFrameCallback === 'function') {
      try { v.requestVideoFrameCallback(finish); } catch { finish(); }
    } else {
      requestAnimationFrame(() => requestAnimationFrame(finish));
    }
  });
}

/**
 * 跳到一个时间点并等这一帧真的可画。
 *
 * 兜底超时是必须的（个别容器不触发 `seeked`），但**超时 ≠ 成功**：超时后要
 * 回头核一遍 `currentTime` 是否真的到位。不核的话会拿着上一帧去 drawImage，
 * 静默产出一堆重复帧 —— 这种坏产物看起来完全正常，事后极难发现。
 */
async function seekTo(v, t) {
  const target = Math.max(0, Math.min(t, Math.max(0, v.duration - 0.05)));
  if (Math.abs(v.currentTime - target) < 1e-3 && v.readyState >= 2) return;

  for (let attempt = 0; attempt < 2; attempt++) {
    const awaiting = waitNewFrame(v);
    await new Promise((res) => {
      const done = () => { v.removeEventListener('seeked', done); res(); };
      v.addEventListener('seeked', done);
      setTimeout(done, 900);
      v.currentTime = target;
    });
    await awaiting;
    // 容差 0.1 s：比最长的播放 period（83ms）还宽，但足以识别「根本没跳过去」
    if (Math.abs(v.currentTime - target) < 0.1) return;
  }
  throw new Error(`跳到 ${target.toFixed(2)}s 失败（视频可能损坏，或解码跟不上抽帧速度）`);
}

/** 居中裁剪 + 缩放到目标尺寸（cover），直接用 drawImage 一步做完，不产生中间大图 */
function makeCtx(w, h) {
  const cv = new OffscreenCanvas(w, h);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  return { cv, ctx };
}

function drawCover(ctx, img, sw, sh, dw, dh) {
  const scale = Math.max(dw / sw, dh / sh);
  const cw = dw / scale;
  const ch = dh / scale;
  ctx.drawImage(img, (sw - cw) / 2, (sh - ch) / 2, cw, ch, 0, 0, dw, dh);
}

/**
 * 按给定时间点抽帧，返回 RGBA（212×520）数组。
 * @param {{el: HTMLVideoElement, width:number, height:number}} video
 * @param {number[]} timesMs
 * @param {(done:number,total:number)=>void} [onStep]
 */
export async function extractFrames(video, timesMs, dw, dh, onStep) {
  const { el, width, height } = video;
  const { ctx } = makeCtx(dw, dh);
  const out = [];
  for (let i = 0; i < timesMs.length; i++) {
    await seekTo(el, timesMs[i] / 1000);
    if (el.readyState < 2) throw new Error('视频解码中断（seek 后没有可用帧）');
    drawCover(ctx, el, width, height, dw, dh);
    const img = ctx.getImageData(0, 0, dw, dh);
    out.push(new Uint8Array(img.data.buffer));
    if (onStep) onStep(i + 1, timesMs.length);
  }
  return out;
}

/** 只取首帧当预览（静止画面 + 一句「生成时抽帧」） */
export async function firstFrame(video, dw, dh) {
  const [f] = await extractFrames(video, [0], dw, dh);
  return f;
}

export function releaseVideo(video) {
  if (!video) return;
  try { video.el.pause(); } catch { /* 没在播 */ }
  try { video.el.removeAttribute('src'); video.el.load(); } catch { /* 忽略 */ }
  try { video.el.remove(); } catch { /* 不在 DOM 里也无妨 */ }
  if (video.url) URL.revokeObjectURL(video.url);
}
