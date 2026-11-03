"""重新生成 tests/golden-src/ 里的三张测试素材。

    python tests/make_fixtures.py

为什么要有这个脚本：素材是二进制，光把 gif 塞进仓库等于不可复现。改了画法就重跑它。

- b.gif  13 帧 / 240×560 —— 「点第 2 页预览有没有换」这条测试用的对照图。
         **原来它和 a.gif 是同一张画（frame0 像素完全一致）**，于是那条断言只能量到
         0.86%，被误当成 app 的 bug。换页测试的素材不能是近重复图，所以重画成
         青绿圆环 + 绕行光点。帧数保持 13，`8 + 12 帧` 这类断言才不用改。
- w1.gif / w2.gif 12 帧 / 240×560 —— 只给投稿截图用（极光 / 波纹）。a/b/c.gif 是刻意
         画得简单的，拿来当展示图不好看。
- long.gif 30 帧 / 100ms 一帧 = 3.0s / 240×560 —— 专给「截取区间」测试用。之前三张素材
         都不到 1.1s，区间根本没地方裁。画面上有一条位置 = 帧号的亮条，所以「取的是不是
         区间里的帧」可以直接比字节判断，不用另做对照图。

画法要点：发光用 `ImageChops.screen`（加色）而不是 alpha 合成 —— alpha 盖在黑底上会把
整幅压暗，出来一片灰绿；screen 才是「亮的地方更亮」。
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden-src')
W, H, SS = 240, 560, 2
PERIOD_MS = 83
BLACK = Image.new('RGB', (W * SS, H * SS), (0, 0, 0))


# ── b.gif：青绿圆环 ────────────────────────────────────────────────
def ring_frame(i, n):
    w, h, ss = 240, 560, 3
    p = i / n
    im = Image.new('RGB', (w * ss, h * ss), (12, 18, 26))
    d = ImageDraw.Draw(im)
    # 顶部渐亮的面板（分 20 段画，色数少 → GIF 不抖，体积小一半）
    for y in range(0, 200, 10):
        t = 1 - y / 200
        d.rectangle([0, y * ss, w * ss, (y + 10) * ss],
                    fill=(int(12 + 26 * t), int(18 + 40 * t), int(26 + 46 * t)))
    cx, cy, r = 120, 300, 86
    # 呼吸 + 旋转的粗圆环（用扇形模拟描边）
    for k in range(48):
        a0 = 360 * k / 48 + 360 * p
        a = 0.35 + 0.65 * abs(math.sin(math.pi * (k / 48 + p)))
        d.arc([(cx - r) * ss, (cy - r) * ss, (cx + r) * ss, (cy + r) * ss],
              a0, a0 + 8.2, fill=(int(40 + 60 * a), int(150 + 90 * a), int(150 + 70 * a)),
              width=9 * ss)
    ang = 2 * math.pi * p
    px, py = cx + r * math.cos(ang), cy + r * math.sin(ang)
    d.ellipse([(px - 13) * ss, (py - 13) * ss, (px + 13) * ss, (py + 13) * ss],
              fill=(214, 255, 246))
    d.rectangle([0, 486 * ss, w * ss, h * ss], fill=(24, 74, 78))
    for x in range(0, w, 24):
        d.rectangle([x * ss, 486 * ss, (x + 12) * ss, 492 * ss], fill=(96, 210, 190))
    return im.resize((w, h), Image.LANCZOS).quantize(colors=48, method=Image.MEDIANCUT)


# ── w1 / w2：展示用 ────────────────────────────────────────────────
def bg():
    im = Image.new('RGB', (W * SS, H * SS))
    d = ImageDraw.Draw(im)
    for y in range(0, H * SS, 8):
        t = y / (H * SS)
        d.rectangle([0, y, W * SS, y + 8],
                    fill=(int(7 + 9 * t), int(10 + 13 * t), int(18 + 24 * t)))
    return im


def glow(im, mask, color, gain=1.0):
    """把 mask（L 图）当成发光遮罩，按 color 加色叠上去。"""
    tint = Image.new('RGB', im.size, color)
    layer = Image.composite(tint, BLACK, mask.point(lambda v: int(min(255, v * gain))))
    return ImageChops.screen(im, layer)


def aurora(i, n):
    p = i / n
    im = bg()
    for color, yc, amp, phase in [((70, 226, 240), 0.34, 26, 0.00),
                                  ((150, 130, 250), 0.52, 30, 0.22),
                                  ((80, 224, 150), 0.70, 24, 0.44)]:
        thick = 26 * SS
        core = Image.new('L', im.size, 0)
        dc = ImageDraw.Draw(core)
        for x in range(0, W * SS, 2):
            u = x / (W * SS)
            yy = yc * H * SS + amp * SS * math.sin(2 * math.pi * (u * 1.35 + p + phase))
            dc.rectangle([x, yy - thick / 2, x + 2, yy + thick / 2], fill=255)
        im = glow(im, core.filter(ImageFilter.GaussianBlur(26 * SS)), color, 0.62)
        im = glow(im, core.filter(ImageFilter.GaussianBlur(9 * SS)), color, 0.80)
        im = glow(im, core.filter(ImageFilter.GaussianBlur(2 * SS)),
                  (min(255, color[0] + 70), min(255, color[1] + 40),
                   min(255, color[2] + 40)), 0.55)
    return im


def ripples(i, n):
    p = i / n
    im = bg()
    cx, cy = W * SS / 2, H * SS * 0.52
    core = Image.new('L', im.size, 0)
    r0 = (34 + 12 * math.sin(2 * math.pi * p)) * SS
    ImageDraw.Draw(core).ellipse([cx - r0, cy - r0, cx + r0, cy + r0], fill=255)
    im = glow(im, core.filter(ImageFilter.GaussianBlur(30 * SS)), (40, 150, 190), 0.7)
    im = glow(im, core.filter(ImageFilter.GaussianBlur(6 * SS)), (120, 226, 244), 0.9)
    for k in range(4):
        q = (p + k / 4) % 1.0
        r = (30 + 210 * q) * SS
        layer = Image.new('L', im.size, 0)
        ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r],
                                      outline=int(255 * (1 - q) ** 1.1),
                                      width=max(2, int(5 * SS)))
        im = glow(im, layer.filter(ImageFilter.GaussianBlur(1.2 * SS)), (130, 236, 252), 1.0)
        im = glow(im, layer.filter(ImageFilter.GaussianBlur(10 * SS)), (56, 176, 214), 0.75)
    return im


def save(name, frames, period=PERIOD_MS):
    path = os.path.join(HERE, name)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=period, loop=0, optimize=True)
    print('->', name, len(frames), '帧', os.path.getsize(path), 'B')


# ── long.gif：给裁切测试用的 3 秒素材 ──────────────────────────────
def long_frame(i, n):
    im = Image.new('RGB', (W, H), (10, 12, 18))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 20):
        d.rectangle([0, y, W, y + 10], fill=(int(10 + y * 0.1), int(12 + y * 0.08), int(18 + y * 0.12)))
    # 竖向亮条的横坐标 = 帧序号：选到哪一帧，从字节上就能看出来
    x = int((W - 40) * i / max(1, n - 1))
    d.rectangle([x, 0, x + 40, H], fill=(90, 210, 190))
    return im.quantize(colors=32, method=Image.MEDIANCUT)


if __name__ == '__main__':
    save('b.gif', [ring_frame(i, 13) for i in range(13)])
    for name, fn in [('w1.gif', aurora), ('w2.gif', ripples)]:
        save(name, [fn(i, 12).resize((W, H), Image.LANCZOS)
                    .quantize(colors=64, method=Image.MEDIANCUT) for i in range(12)])
    save('long.gif', [long_frame(i, 30) for i in range(30)], period=100)
