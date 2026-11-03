/**
 * 内置示例壁纸：程序化画出来的动画，**不加载任何素材文件**。
 *
 * 存在的理由：评审或第一次打开的人手里没有 GIF/视频，看到一个空预览根本不知道
 * 这东西能干什么。所以首屏直接播一段示例，拖入自己的素材时自动让位。
 *
 * 全部是纯函数（给定帧序号就画出确定的一帧），不依赖时间戳，所以两次生成结果一致 ——
 * 这点很重要：示例页如果每次刷新都不一样，看起来就像在偷懒加载什么远端资源。
 */

const TAU = Math.PI * 2;

export const DEMOS = [
  { id: 'aurora', name: '极光' },
  { id: 'rings', name: '波纹' },
  { id: 'grid', name: '网格' },
];

export const DEMO_COUNT = 24;
export const DEMO_PERIOD_MS = 83; // ≈ 12fps

/** 画一帧。p = 0..1 表示一个完整循环里的位置。 */
function drawAurora(ctx, w, h, p) {
  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, '#06121f');
  bg.addColorStop(0.55, '#08111b');
  bg.addColorStop(1, '#04070c');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const bands = [
    { rgb: '64,220,255', y: 0.30, amp: 30, k: 1, lw: 30, a: 0.55 },
    { rgb: '150,120,255', y: 0.46, amp: 46, k: -1, lw: 26, a: 0.45 },
    { rgb: '90,255,190', y: 0.62, amp: 24, k: 2, lw: 22, a: 0.38 },
  ];
  ctx.lineCap = 'round';
  for (const b of bands) {
    const stroke = ctx.createLinearGradient(0, h * b.y - b.amp - 40, 0, h * b.y + b.amp + 40);
    stroke.addColorStop(0, `rgba(${b.rgb},0)`);
    stroke.addColorStop(0.5, `rgba(${b.rgb},${b.a})`);
    stroke.addColorStop(1, `rgba(${b.rgb},0)`);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = b.lw;
    ctx.shadowColor = `rgba(${b.rgb},0.55)`;
    ctx.shadowBlur = 18;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 3) {
      const y = h * b.y
        + Math.sin((x / w) * TAU * 1.4 + p * TAU * b.k) * b.amp
        + Math.sin((x / w) * TAU * 0.7 - p * TAU) * b.amp * 0.4;
      if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.shadowBlur = 0;

  // 左上角冷光：把上半屏的空档填掉（时间字就压在这片光上）
  const top = ctx.createRadialGradient(w * 0.18, h * 0.1, 0, w * 0.18, h * 0.1, w * 0.9);
  top.addColorStop(0, 'rgba(70,150,220,0.22)');
  top.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = top;
  ctx.fillRect(0, 0, w, h * 0.5);

  // 底部一点地面反光，避免下半屏空得发死
  const fl = ctx.createLinearGradient(0, h * 0.72, 0, h);
  fl.addColorStop(0, 'rgba(40,90,140,0)');
  fl.addColorStop(1, 'rgba(46,104,158,0.30)');
  ctx.fillStyle = fl;
  ctx.fillRect(0, h * 0.72, w, h * 0.28);
}

function drawRings(ctx, w, h, p) {
  ctx.fillStyle = '#05070a';
  ctx.fillRect(0, 0, w, h);
  const cx = w / 2;
  const cy = h * 0.44;
  const R = Math.hypot(w, h) * 0.62;

  // 中心呼吸光
  const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.55);
  const pulse = 0.34 + 0.10 * Math.sin(p * TAU);
  glow.addColorStop(0, `rgba(120,200,255,${pulse})`);
  glow.addColorStop(0.4, `rgba(80,140,220,${pulse * 0.35})`);
  glow.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  for (let k = 0; k < 4; k++) {
    const t = (p + k / 4) % 1;
    const r = t * R;
    const a = (1 - t) * 0.55;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, TAU);
    ctx.strokeStyle = `rgba(140,215,255,${a})`;
    ctx.lineWidth = 2 + (1 - t) * 3;
    ctx.shadowColor = 'rgba(120,200,255,0.5)';
    ctx.shadowBlur = 12;
    ctx.stroke();
  }
  ctx.shadowBlur = 0;

  // 一条缓慢转动的刻度弧，给静止感一点方向
  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.72, p * TAU, p * TAU + 1.2);
  ctx.strokeStyle = 'rgba(255,255,255,0.20)';
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

function drawGrid(ctx, w, h, p) {
  ctx.fillStyle = '#07090d';
  ctx.fillRect(0, 0, w, h);

  const step = 22;
  ctx.lineWidth = 1;
  for (let x = 0; x <= w; x += step) {
    const a = 0.09 + 0.13 * (0.5 + 0.5 * Math.sin((x / w) * TAU * 2 + p * TAU));
    ctx.strokeStyle = `rgba(90,180,255,${a})`;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = 0; y <= h; y += step) {
    const a = 0.09 + 0.13 * (0.5 + 0.5 * Math.sin((y / h) * TAU * 3 - p * TAU));
    ctx.strokeStyle = `rgba(90,180,255,${a})`;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  // 两个沿对角线巡游的光斑
  for (let k = 0; k < 2; k++) {
    const t = (p + k * 0.5) % 1;
    const x = w * (k ? 1 - t : t);
    const y = h * (0.2 + 0.6 * t);
    const g = ctx.createRadialGradient(x, y, 0, x, y, 90);
    g.addColorStop(0, k ? 'rgba(120,255,210,0.44)' : 'rgba(90,170,255,0.48)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }
}

const PAINTERS = { aurora: drawAurora, rings: drawRings, grid: drawGrid };

/**
 * 生成一整套示例帧（212×520 RGBA，每帧独立 buffer —— 后面要按 Transferable 传给 Worker）。
 * @param {string} id
 * @param {number} w
 * @param {number} h
 * @param {number} [count]
 */
export function renderDemoFrames(id, w, h, count = DEMO_COUNT) {
  const paint = PAINTERS[id] || drawAurora;
  const cv = new OffscreenCanvas(w, h);
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  const out = [];
  for (let i = 0; i < count; i++) {
    ctx.clearRect(0, 0, w, h);
    paint(ctx, w, h, i / count);
    out.push(new Uint8Array(ctx.getImageData(0, 0, w, h).data.buffer));
  }
  return out;
}
