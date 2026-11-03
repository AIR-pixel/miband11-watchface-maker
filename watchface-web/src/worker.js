/**
 * 生成任务的 Worker：编解码都在这里跑，主线程只管画预览，避免几百帧把界面卡死。
 *
 * 收 `sources`：
 *   { kind: 'gif',    bytes }               —— 自己解 GIF
 *   { kind: 'frames', frames, periodMs }    —— 视频抽好的 RGBA 帧（Transferable）
 */
import { buildFace } from './core/build.js';

self.onmessage = async (e) => {
  const { type, sources, opts } = e.data;
  if (type !== 'build') return;
  try {
    const res = await buildFace({
      ...opts,
      sources,
      onProgress: (ratio, msg) => self.postMessage({ type: 'progress', ratio, msg }),
    });
    const buf = res.face.buffer;
    self.postMessage(
      { type: 'done', face: new Uint8Array(buf), faceName: res.faceName, stats: res.stats },
      [buf],
    );
  } catch (err) {
    self.postMessage({ type: 'error', message: err && err.message ? err.message : String(err) });
  }
};
