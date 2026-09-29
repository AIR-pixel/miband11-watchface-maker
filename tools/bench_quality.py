#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体积/画质实测脚本 —— 复现 docs/体积与画质实测.md 里的数字。

用法：
    python bench_quality.py <素材路径> [--frame 中间]
                           [--out 输出目录（可选，看图用）]

素材可以是任意图片或 GIF（取中间帧）。会把画面缩放/裁切到 212×520 后，
测各种编码设置下的体积与分通道 PSNR。

输出三张表：
    1. 各色深档位（PNG 调色板量化）
    2. JPEG 各质量档（含 4:2:0 vs 4:4:4 对照）
    3. JPEG 与 PNG 的体积对照

依赖：Pillow
"""
import argparse
import io
import math
import os
import sys

try:
    from PIL import Image, ImageSequence
except ImportError:
    print("需要 Pillow：pip install Pillow")
    sys.exit(2)

W, H = 212, 520
PALETTE_LEVELS = [("P256", 256), ("P128", 128), ("P64", 64),
                  ("P32", 32), ("P16", 16), ("P8", 8)]
JPEG_QUALITIES = [95, 90, 85, 80, 75, 70, 60]


def load_frame(path, which="mid"):
    """取一帧并缩放到 212x520（保持比例后居中裁切）。"""
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    if which == "mid" and n > 1:
        idx = n // 2
        for i, f in enumerate(ImageSequence.Iterator(im)):
            if i == idx:
                im = f
                break
    im = im.convert("RGB")

    # 居中裁切到 212:520 比例，再缩放
    sw, sh = im.size
    target = W / H
    if sw / sh > target:
        nw = int(sh * target)
        im = im.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
    else:
        nh = int(sw / target)
        im = im.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
    return im.resize((W, H), Image.LANCZOS)


def comps(rgb):
    """RGB 字节 → (Y, Cb, Cr) 三个列表。"""
    Y, Cb, Cr = [], [], []
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        Y.append(0.299 * r + 0.587 * g + 0.114 * b)
        Cb.append(-0.168736 * r - 0.331264 * g + 0.5 * b + 128)
        Cr.append(0.5 * r - 0.418688 * g - 0.081312 * b + 128)
    return Y, Cb, Cr


def psnr(a, b):
    se = 0.0
    for x, y in zip(a, b):
        d = x - y
        se += d * d
    mse = se / len(a)
    return 99.0 if mse <= 1e-9 else 10 * math.log10(255 * 255 / mse)


def encode_png_palette(img, colors):
    q = img.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE)
    buf = io.BytesIO()
    info = dict(q.info)
    info.pop("transparency", None)
    q.save(buf, format="PNG", optimize=True, **info)
    return buf.getvalue(), q.convert("RGB")


def encode_jpeg(img, quality, subsampling):
    buf = io.BytesIO()
    kw = {"format": "JPEG", "quality": quality, "optimize": True}
    if subsampling is not None:
        kw["subsampling"] = subsampling
    img.save(buf, **kw)
    data = buf.getvalue()
    return data, Image.open(io.BytesIO(data)).convert("RGB")


def encode_png_rgb(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="素材路径（图片或 GIF）")
    ap.add_argument("--frame", default="mid", choices=["mid", "first"])
    ap.add_argument("--out", default=None, help="把这些编码结果落盘，方便肉眼比对")
    args = ap.parse_args()

    if not os.path.isfile(args.src):
        print(f"素材不存在：{args.src}")
        return 2

    print(f"素材：{args.src}")
    frame = load_frame(args.src, args.frame)
    ref = frame.tobytes()
    rY, rCb, rCr = comps(ref)
    print(f"取样帧：{W}×{H}（已缩放裁切）\n")

    rows = []          # (名称, 字节数, 解码后 RGB)

    data, dec = encode_png_rgb(frame)
    rows.append(("PNG 真彩 RGB（无损）", data, dec))
    for name, colors in PALETTE_LEVELS:
        data, dec = encode_png_palette(frame, colors)
        rows.append((f"PNG {name}", data, dec))
    for q in JPEG_QUALITIES:
        data, dec = encode_jpeg(frame, q, subsampling=0)
        rows.append((f"JPEG q{q} 4:4:4", data, dec))

    base_p64 = next(len(d) for n, d, _ in rows if n == "PNG P64")
    base_rgb = len(rows[0][1])

    def report(title, sel):
        print(title)
        print(f"{'配置':<22}{'每帧':>10}{'vs P64':>9}{'Y':>9}{'Cb':>9}{'Cr':>9}")
        print("-" * 70)
        for name, data, dec in sel:
            dY, dCb, dCr = comps(dec.tobytes())
            print(f"{name:<22}{len(data) / 1024:>9.1f}K"
                  f"{len(data) / base_p64:>9.2f}"
                  f"{psnr(rY, dY):>9.2f}{psnr(rCb, dCb):>9.2f}"
                  f"{psnr(rCr, dCr):>9.2f}")
        print()

    print(f"基准：PNG P64 = {base_p64 / 1024:.1f} KB，"
          f"PNG 真彩 = {base_rgb / 1024:.1f} KB\n")

    report("① 色深档位（PNG 调色板量化，无损存储）",
           [r for r in rows if r[0].startswith("PNG")])

    # 4:2:0 对照
    print("② JPEG 质量档（4:4:4）＋ 色度子采样对照")
    print(f"{'配置':<22}{'每帧':>10}{'vs P64':>9}{'Y':>9}{'Cb':>9}{'Cr':>9}")
    print("-" * 70)
    for q in JPEG_QUALITIES:
        for sub, tag in ((0, "4:4:4"), (-1, "4:2:0")):
            data, dec = encode_jpeg(frame, q, subsampling=sub)
            dY, dCb, dCr = comps(dec.tobytes())
            print(f"{f'JPEG q{q} {tag}':<22}{len(data) / 1024:>9.1f}K"
                  f"{len(data) / base_p64:>9.2f}"
                  f"{psnr(rY, dY):>9.2f}{psnr(rCb, dCb):>9.2f}"
                  f"{psnr(rCr, dCr):>9.2f}")
    print()

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        for name, data, _ in rows:
            safe = name.replace(" ", "_").replace("(", "").replace(")", "")
            safe = safe.replace("：", "_").replace("，", "_")
            ext = "png" if name.startswith("PNG") else "jpg"
            with open(os.path.join(args.out, f"{safe}.{ext}"), "wb") as f:
                f.write(data)
        print(f"已落盘到 {args.out}，可以肉眼比对差异。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
