#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 AOD 内嵌字库（数字 0-9 + 冒号 + 句点），同时写出 Java 与 Python 两侧。

## 为什么要有这个

AOD 的数字位图原来是**两端各自用系统字体渲染**的：PC 端 PIL + Arial Bold，
安卓端 Canvas + Roboto Bold。后果有两个：

1. 同一个配置在两端生成的 AOD 数字**长得不一样**（字形不同）；
2. 跨语言差分回归只能比控件表和记录，**比不了像素** —— 安卓的渲染依赖
   `android.graphics`，在 JVM 上根本跑不起来。

改成内嵌点阵字库后：数据是同一份（本脚本一次生成两侧常量），缩放算法两端
各写一份但**可以被像素级对拍**（见 `tools/diff_face.py` 的 `font` 阶段）。

顺带去掉了对系统字体的依赖：Linux / macOS 上生成的 AOD 也和 Windows 一致。

## 用法

    python tools/gen_aod_font.py            # 重新生成两侧字库
    python tools/gen_aod_font.py --check    # 只校验两侧是否与生成结果一致

字形来源：Windows 的 Arial Bold（`C:\\Windows\\Fonts\\arialbd.ttf`）。
找不到就退回 PIL 内置字体（那时要重新跑一次本脚本，让两端同步）。
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

JAVA_OUT = os.path.join(REPO, "watchface-android", "core", "face", "AodFont.java")
PY_OUT = os.path.join(REPO, "watchface-tool", "watchface_tool", "aod_font.py")

# 字模画布。数字取 40x64（覆盖最大的 AOD 时间数字 46x64 的高度），
# 冒号/句点共用 12x64（对应 AOD_COLON_W=12）。缩放时按高度等比，不变形。
GLYPH_W, GLYPH_H = 40, 64
COLON_W, COLON_H = 12, 64

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# 抗锯齿超采样倍数：字形边缘更干净，且它是**生成期**的事，不影响运行期一致性
SS = 4


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:                        # noqa: BLE001
                pass
    return ImageFont.load_default()


def render_digit(d):
    """把数字 d 渲染成 (GLYPH_W x GLYPH_H) 的灰度 alpha，字形在画布内居中。"""
    size = max(6, int(GLYPH_H * 0.92))
    big_w, big_h = GLYPH_W * SS, GLYPH_H * SS
    im = Image.new("L", (big_w, big_h), 0)
    dr = ImageDraw.Draw(im)
    font = load_font(size * SS)
    ch = str(d)
    bbox = dr.textbbox((0, 0), ch, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # 超宽时等比缩字号（与旧实现同规则）
    if tw > big_w * 0.96 and tw > 0:
        font = load_font(max(6, int(size * SS * (big_w * 0.96) / tw)))
        bbox = dr.textbbox((0, 0), ch, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (big_w - tw) / 2.0 - bbox[0]
    y = (big_h - th) / 2.0 - bbox[1]
    dr.text((x, y), ch, font=font, fill=255)
    return im.resize((GLYPH_W, GLYPH_H), Image.LANCZOS)


def render_colon():
    """时:分 之间的冒号：上下两个圆点。"""
    big_w, big_h = COLON_W * SS, COLON_H * SS
    im = Image.new("L", (big_w, big_h), 0)
    dr = ImageDraw.Draw(im)
    r = max(2, int(COLON_W * 0.32)) * SS
    cx = big_w / 2.0
    for cy in (int(big_h * 0.34), int(big_h * 0.66)):
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return im.resize((COLON_W, COLON_H), Image.LANCZOS)


def render_dot():
    """月.日 之间的句点：一个圆点，**底边压在数字基线上**。

    以前月日之间复用冒号，显示成 `10:22`，看着像第二行时间。
    半径与冒号那两个点一致（不重新起一套视觉），只把它挪到基线：
    数字墨迹实测占第 8..55 行，所以点占 50..56 行。
    """
    big_w, big_h = COLON_W * SS, COLON_H * SS
    im = Image.new("L", (big_w, big_h), 0)
    dr = ImageDraw.Draw(im)
    r = max(2, int(COLON_W * 0.32)) * SS
    cx = big_w / 2.0
    cy = int(big_h * 0.875) - r
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return im.resize((COLON_W, COLON_H), Image.LANCZOS)


def hex_of(im):
    return im.tobytes().hex()


def chunks(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)]


def fmt_java_str_list(hexstr, per_line=96, indent="            "):
    parts = chunks(hexstr, per_line)
    return "\n".join('%s"%s" +' % (indent, p) for p in parts)


def gen_java(digits_hex, colon_hex, dot_hex):
    def const(name, hexstr, w, h):
        body = fmt_java_str_list(hexstr)
        body = body.rstrip(" +")          # 最后一段去掉 " +"
        return ('    /** %d x %d 的 alpha 遮罩（%d 字节，十六进制）。 */\n'
                '    private static final String %s =\n%s;\n'
                % (w, h, w * h, name, body))

    digit_consts = "\n".join(
        const("D%d" % d, digits_hex[d], GLYPH_W, GLYPH_H) for d in range(10))
    arr = ",\n".join("        D%d" % d for d in range(10))
    return JAVA_TEMPLATE.format(
        glyph_w=GLYPH_W, glyph_h=GLYPH_H, colon_w=COLON_W, colon_h=COLON_H,
        digit_consts=digit_consts, colon_const=const("COLON", colon_hex, COLON_W, COLON_H),
        dot_const=const("DOT", dot_hex, COLON_W, COLON_H),
        digits_array=arr)


def gen_py(digits_hex, colon_hex, dot_hex):
    def const(name, hexstr, per_line=96):
        parts = chunks(hexstr, per_line)
        return '%s = (\n%s\n)' % (name, "\n".join('    "%s"' % p for p in parts))

    lines = [const("D%d" % d, digits_hex[d]) for d in range(10)]
    lines.append(const("COLON", colon_hex))
    lines.append(const("DOT", dot_hex))
    return PY_TEMPLATE.format(
        glyph_w=GLYPH_W, glyph_h=GLYPH_H, colon_w=COLON_W, colon_h=COLON_H,
        digit_consts="\n\n".join(lines))


JAVA_TEMPLATE = '''package face;

/**
 * AOD 数字字库：**内嵌点阵**，两端同源。
 *
 * <p>以前数字是两端各自用系统字体画的（PC 端 Arial Bold、安卓端 Roboto Bold），
 * 同一个配置生成的 AOD 数字长得不一样，而且像素没法做跨语言对拍 —— 安卓的渲染
 * 依赖 {{@code android.graphics}}，JVM 上跑不起来。
 *
 * <p>现在字形是数据：由 {{@code tools/gen_aod_font.py}} 一次性生成，
 * 同时写出本文件与 Python 侧的 {{@code watchface_tool/aod_font.py}}。
 * 缩放算法两端各有一份实现，但结果可以被
 * {{@code tools/diff_face.py --stage font}} **逐像素对拍**。
 *
 * <p>顺带不再依赖系统字体：Linux / macOS 生成的 AOD 与 Windows 一致。
 */
public final class AodFont {{

    /** 数字字模画布尺寸。 */
    public static final int GLYPH_W = {glyph_w}, GLYPH_H = {glyph_h};
    /** 冒号字模画布尺寸。 */
    public static final int COLON_W = {colon_w}, COLON_H = {colon_h};

{digit_consts}

{colon_const}

{dot_const}

    private static final String[] DIGITS = {{
{digits_array},
    }};

    private AodFont() {{}}

    /** 数字 d 的 alpha 遮罩（GLYPH_W x GLYPH_H，0-255）。 */
    public static byte[] glyph(int d) {{
        return decodeHex(DIGITS[d]);
    }}

    /** 冒号的 alpha 遮罩（COLON_W x COLON_H，0-255）。 */
    public static byte[] colon() {{
        return decodeHex(COLON);
    }}

    /** 句点的 alpha 遮罩（与冒号同画布，只有一个点，底边压在数字基线上）。 */
    public static byte[] dot() {{
        return decodeHex(DOT);
    }}

    /**
     * 把 sw x sh 的字模**按高度等比**缩放并居中到 w x h，返回 w*h 的 alpha。
     *
     * <p>先按高度算缩放；只有宽度撑不下时才改按宽度算 —— 这样字号只跟高度走，
     * 数字不会被横向拉胖。与 Python 侧 {{@code aod_font.fit}} 逐行对应。
     */
    public static byte[] fit(byte[] src, int sw, int sh, int w, int h) {{
        double scale = (double) h / (double) sh;
        double dw = sw * scale;
        if (dw > w * 0.96) {{
            scale = (w * 0.96) / sw;
            dw = sw * scale;
        }}
        double dh = sh * scale;
        double x0 = (w - dw) / 2.0;
        double y0 = (h - dh) / 2.0;

        byte[] out = new byte[w * h];
        for (int y = 0; y < h; y++) {{
            double sy = ((y + 0.5) - y0) / scale - 0.5;
            int yf = (int) Math.floor(sy);
            double fy = sy - yf;
            for (int x = 0; x < w; x++) {{
                double sx = ((x + 0.5) - x0) / scale - 0.5;
                int xf = (int) Math.floor(sx);
                double fx = sx - xf;
                double a = sample(src, sw, sh, xf, yf);
                double b = sample(src, sw, sh, xf + 1, yf);
                double c = sample(src, sw, sh, xf, yf + 1);
                double d = sample(src, sw, sh, xf + 1, yf + 1);
                double v = a * (1 - fx) * (1 - fy) + b * fx * (1 - fy)
                         + c * (1 - fx) * fy + d * fx * fy;
                out[y * w + x] = (byte) (int) (v + 0.5);
            }}
        }}
        return out;
    }}

    /** 双线性采样的四角取值；越界一律当作全透明。 */
    private static double sample(byte[] src, int sw, int sh, int x, int y) {{
        if (x < 0 || y < 0 || x >= sw || y >= sh) return 0.0;
        return src[y * sw + x] & 0xFF;
    }}

    private static byte[] decodeHex(String hex) {{
        int n = hex.length() / 2;
        byte[] out = new byte[n];
        for (int i = 0; i < n; i++) {{
            int hi = Character.digit(hex.charAt(i * 2), 16);
            int lo = Character.digit(hex.charAt(i * 2 + 1), 16);
            out[i] = (byte) ((hi << 4) | lo);
        }}
        return out;
    }}
}}
'''

PY_TEMPLATE = '''# -*- coding: utf-8 -*-
"""AOD 内嵌字库（与 ``face.AodFont`` 同源）—— 由 tools/gen_aod_font.py 生成，勿手改。

字形从系统字体渲染一次后固化成点阵：PC 端不再依赖 Arial Bold 是否存在，
安卓端也不再用 Roboto Bold，两端的 AOD 数字因此**完全一致**，
且缩放结果能被 ``tools/diff_face.py --stage font`` 逐像素对拍。
"""
GLYPH_W = {glyph_w}      # 数字字模画布
GLYPH_H = {glyph_h}
COLON_W = {colon_w}      # 冒号字模画布
COLON_H = {colon_h}

{digit_consts}

DIGITS = (D0, D1, D2, D3, D4, D5, D6, D7, D8, D9)


def glyph(d):
    """数字 d 的 alpha 遮罩（GLYPH_W x GLYPH_H，0-255）。"""
    return bytes.fromhex(DIGITS[d])


def colon():
    """冒号的 alpha 遮罩（COLON_W x COLON_H，0-255）。"""
    return bytes.fromhex(COLON)


def dot():
    """句点的 alpha 遮罩（与冒号同画布，只有一个点，底边压在数字基线上）。"""
    return bytes.fromhex(DOT)


def fit(src, sw, sh, w, h):
    """把 sw x sh 的字模按高度等比缩放并居中到 w x h，返回 w*h 的 alpha。

    与 Java 侧 ``AodFont.fit`` 逐行对应 —— 两边算出的像素必须一模一样。
    """
    scale = float(h) / float(sh)
    dw = sw * scale
    if dw > w * 0.96:
        scale = (w * 0.96) / sw
        dw = sw * scale
    dh = sh * scale
    x0 = (w - dw) / 2.0
    y0 = (h - dh) / 2.0

    out = bytearray(w * h)
    for y in range(h):
        sy = ((y + 0.5) - y0) / scale - 0.5
        yf = int(sy // 1)
        fy = sy - yf
        for x in range(w):
            sx = ((x + 0.5) - x0) / scale - 0.5
            xf = int(sx // 1)
            fx = sx - xf
            v = (_sample(src, sw, sh, xf, yf) * (1 - fx) * (1 - fy)
                 + _sample(src, sw, sh, xf + 1, yf) * fx * (1 - fy)
                 + _sample(src, sw, sh, xf, yf + 1) * (1 - fx) * fy
                 + _sample(src, sw, sh, xf + 1, yf + 1) * fx * fy)
            out[y * w + x] = int(v + 0.5) & 0xFF
    return bytes(out)


def _sample(src, sw, sh, x, y):
    if x < 0 or y < 0 or x >= sw or y >= sh:
        return 0.0
    return float(src[y * sw + x])
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="只校验两侧文件是否与当前生成结果一致")
    args = ap.parse_args()

    digits_hex = [hex_of(render_digit(d)) for d in range(10)]
    colon_hex = hex_of(render_colon())
    dot_hex = hex_of(render_dot())
    java_src = gen_java(digits_hex, colon_hex, dot_hex)
    py_src = gen_py(digits_hex, colon_hex, dot_hex)

    if args.check:
        ok = True
        for path, src in ((JAVA_OUT, java_src), (PY_OUT, py_src)):
            cur = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else ""
            same = cur == src
            ok = ok and same
            print(("  PASS  " if same else "  FAIL  ") + os.path.relpath(path, REPO))
        print("字库两侧同步" if ok else "字库两侧不同步，请重跑本脚本")
        return 0 if ok else 1

    for path, src in ((JAVA_OUT, java_src), (PY_OUT, py_src)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        print("写出 %s（%.0f KB）" % (os.path.relpath(path, REPO), len(src) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
