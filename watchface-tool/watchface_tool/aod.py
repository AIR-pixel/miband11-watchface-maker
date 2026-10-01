# -*- coding: utf-8 -*-
"""息屏显示（AOD）子工程生成。

## 结构

AOD 是主工程的**同级子工程**，不单独编译：

    工程目录/
      MyFace.fprj + images/ + app/lua/
      AOD/
        AOD.fprj          ← 目录名与文件名都固定
        AOD.fprj 同级放 images/
      output/

`Compiler.exe` 内建这条路径（字符串表里有 `\\AOD`、`\\AOD\\images`、
`AOD face file is not found`），不是第三方工具的约定。

## 实测结论（2026-10-01，本机差分实验 + Compiler.exe 真实产物对拍）

1. **AOD 屏不支持 Lua。** 在 AOD.fprj 里写 `Shape=34` 挂载点，
   无论挂到 `main.lua` 还是自定义文件名，AOD 的 lua 都**不会入包**
   （产物只多 88 B；`AOD_MARKER` 在产物里搜不到；换名与不换名产物字节相同）。
   → AOD 只能靠 `Shape=30`（静态图）/ `Shape=32`（数字位图 + `Value_Src`）驱动。

2. **`Shape=32` 的数据源是真的。** `Value_Src` 写数据源 ID（见 constants.DATA_SOURCES），
   编译器只把数字原样存下、不校验，由设备侧 dataman 在运行期解析。
   官方样本（手环 8 Pro）用 `Value_Src="811"` 显示小时，与本表 `0811` 一致。

3. **代价模型**（AOD 屏逐项差分实测）：

   | 项 | 代价 |
   |---|---|
   | AOD 空屏 | +88 B |
   | 每个 `Shape=30` | `w*h*4 + 60` B |
   | 每个 `Shape=32` | `图宽*图高*4 * 图数`（共用同一 BitmapList 只算一次） |

   注意：**主屏**上的 `Shape=30` 会被合成为整屏位图（+441 KB/个），AOD 屏不会。
   所以"AOD 上放小图标很便宜"与"主屏上放小图标很贵"并不矛盾。

## 设计取舍

- 时分共用同一张 11 图数字列表（`Digits="2"` 各一位），只付一次位图钱。
- 冒号用 `Shape=30`（12x64 ≈ 3 KB），比再建一张 Shape=32 列表划算。
- 默认不放全屏黑底：AMOLED 黑像素不发光，省下 431 KB。
  想要保险可在 GUI 里选「纯黑底图」。
"""
import os

from PIL import Image, ImageDraw, ImageFont

from .constants import (AOD_BG_MODES, AOD_COLON_W, AOD_DATE_DIGIT_H,
                        AOD_DATE_DIGIT_W, AOD_FONT_CANDIDATES,
                        AOD_TIME_DIGIT_H, AOD_TIME_DIGIT_W, DATA_SOURCES,
                        DEVICE_TYPE, SCREEN_H, SCREEN_W)

# 官方样本（手环 8 Pro）的 BitmapList 是 11 张：00..09 再补一张 00。
# 照抄这个数量，避免"少一张导致某位数字不显示"这类玄学问题。
DIGIT_IMAGE_COUNT = 11


# --------------------------------------------------------------------------- 字体

def find_font(font_path=None):
    """找一个可用的 TTF。找不到返回 None（退回 PIL 位图字体）。"""
    for p in ([font_path] if font_path else []) + AOD_FONT_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


def _load_font(size, font_path=None):
    path = find_font(font_path)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:                            # noqa: BLE001
            pass
    return ImageFont.load_default()


# --------------------------------------------------------------------------- 数字位图

def render_digit_images(digit_w, digit_h, color=(255, 255, 255, 255), font_path=None):
    """生成 0-9 的单数字位图（透明底、居中），返回 list[Image]，共 10 张。

    每个数字占 `digit_w x digit_h` 的独立画布 —— 这是 bitmaplist 的惯例，
    控件宽度 = digit_w * Digits（官方样本 27x27 数字 → 2 位宽 54）。
    """
    out = []
    # 字号按高度取，留 8% 上下边距；再按实际 bbox 居中。
    font = _load_font(max(6, int(digit_h * 0.92)), font_path)
    for d in range(10):
        im = Image.new("RGBA", (digit_w, digit_h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        ch = str(d)
        try:
            bbox = dr.textbbox((0, 0), ch, font=font)
        except Exception:                            # noqa: BLE001
            bbox = (0, 0, digit_w, digit_h)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # 超宽时按比例缩字号（比如字号比画布还宽）
        if tw > digit_w * 0.96 and tw > 0:
            scale = (digit_w * 0.96) / tw
            font = _load_font(max(6, int(digit_h * 0.92 * scale)), font_path)
            try:
                bbox = dr.textbbox((0, 0), ch, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except Exception:                        # noqa: BLE001
                pass
        x = (digit_w - tw) / 2.0 - bbox[0]
        y = (digit_h - th) / 2.0 - bbox[1]
        dr.text((x, y), ch, font=font, fill=color)
        out.append(im)
    return out


def render_colon_image(w=AOD_COLON_W, h=AOD_TIME_DIGIT_H, color=(255, 255, 255, 255),
                       font_path=None):
    """时:分之间的冒号（单独一张 Shape=30 小图）。"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    r = max(2, int(w * 0.32))
    cx = w // 2
    for cy in (int(h * 0.34), int(h * 0.66)):
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    return im


def render_static_text(text, w, h, color=(255, 255, 255, 200), font_path=None):
    """一段静态文字（AOD 上不能有 Lua，但静态文字可以画进底图/小图）。"""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    font = _load_font(max(6, int(h * 0.88)), font_path)
    try:
        bbox = dr.textbbox((0, 0), text, font=font)
    except Exception:                                # noqa: BLE001
        bbox = (0, 0, w, h)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    dr.text(((w - tw) / 2.0 - bbox[0], (h - th) / 2.0 - bbox[1]), text,
            font=font, fill=color)
    return im


# --------------------------------------------------------------------------- 体积模型

def estimate_aod_bytes(cfg):
    """按实测模型估算 AOD 给整个 .face 增加多少字节。cfg 见 build_aod。"""
    if not cfg.get("enabled"):
        return 0
    n = 88                                        # AOD 空屏本身
    if cfg.get("bg_mode") == "black" or cfg.get("bg_mode") == "custom":
        n += SCREEN_W * SCREEN_H * 4 + 60         # 全屏底图
    if cfg.get("time_mode") in ("time", "both"):
        n += DIGIT_IMAGE_COUNT * AOD_TIME_DIGIT_W * AOD_TIME_DIGIT_H * 4
        n += AOD_COLON_W * AOD_TIME_DIGIT_H * 4 + 60
    if cfg.get("time_mode") == "both":
        n += DIGIT_IMAGE_COUNT * AOD_DATE_DIGIT_W * AOD_DATE_DIGIT_H * 4
        n += AOD_COLON_W * AOD_DATE_DIGIT_H * 4 + 60
    return n


# --------------------------------------------------------------------------- fprj

_AOD_HEAD = ('<?xml version="1.0" encoding="utf-16" ?>\n'
             '<FaceProject DeviceType="{device}">\n'
             '    <Screen Title="{title}" Bitmap="preview.png">\n')
_AOD_TAIL = '    </Screen>\n</FaceProject>\n'


def _w_image(name, bitmap, x, y, w, h, alpha=255):
    return ('        <Widget Shape="30" Name="%s" X="%d" Y="%d" Width="%d" Height="%d" '
            'Alpha="%d" Visible_Src="0" Bitmap="%s" />\n'
            % (name, x, y, w, h, alpha, bitmap))


def _w_digits(name, x, y, digit_w, digit_h, digits, value_src, bitmap_list):
    return ('        <Widget Shape="32" Name="%s" X="%d" Y="%d" Width="%d" Height="%d" '
            'Alpha="255" Digits="%d" Alignment="1" Spacing="0" Blanking="0" Visible_Src="0" '
            'Value_Src="%s" BitmapList="%s" />\n'
            % (name, x, y, digit_w * digits, digit_h, digits,
               value_src, "|".join(bitmap_list)))


def generate_aod_fprj(widgets_xml, title="AOD"):
    xml = (_AOD_HEAD.format(device=DEVICE_TYPE, title=title)
           + widgets_xml + _AOD_TAIL)
    return xml.encode("utf-16")


# --------------------------------------------------------------------------- 组装

def plan_aod_layout(cfg):
    """算出各控件的位置，返回 (widgets_xml, 需要的图片文件列表)。

    时间/日期水平居中：先算总宽，再定起点 X。
    """
    tmode = cfg.get("time_mode", "time")
    W = SCREEN_W
    parts = []            # (kind, payload)
    need = []             # (文件名, 生成函数参数)

    digit_files = None
    date_files = None
    if tmode in ("time", "both"):
        digit_files = ["aod_t_%02d.png" % i for i in range(10)]
    if tmode == "both":
        date_files = ["aod_d_%02d.png" % i for i in range(10)]

    # ---- 时间行 ----
    if digit_files:
        tw = AOD_TIME_DIGIT_W * 2 + AOD_COLON_W + AOD_TIME_DIGIT_W * 2
        x0 = (W - tw) // 2
        y0 = cfg.get("time_y", 200)
        parts.append(("digits", ("aod_hour", x0, y0, AOD_TIME_DIGIT_W, AOD_TIME_DIGIT_H,
                                 2, DATA_SOURCES["hour"], digit_files)))
        parts.append(("img", ("aod_colon", "aod_colon.png",
                              x0 + AOD_TIME_DIGIT_W * 2, y0, AOD_COLON_W, AOD_TIME_DIGIT_H)))
        parts.append(("digits", ("aod_min", x0 + AOD_TIME_DIGIT_W * 2 + AOD_COLON_W, y0,
                                 AOD_TIME_DIGIT_W, AOD_TIME_DIGIT_H, 2,
                                 DATA_SOURCES["minute"], digit_files)))
        need.append(("digit_time", None))

    # ---- 日期行（月/日）----
    if date_files:
        dw = AOD_DATE_DIGIT_W * 2 + AOD_COLON_W + AOD_DATE_DIGIT_W * 2
        dx = (W - dw) // 2
        dy = cfg.get("date_y", 300)
        parts.append(("digits", ("aod_month", dx, dy, AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H,
                                 2, DATA_SOURCES["month"], date_files)))
        parts.append(("img", ("aod_dcolon", "aod_dcolon.png",
                              dx + AOD_DATE_DIGIT_W * 2, dy, AOD_COLON_W, AOD_DATE_DIGIT_H)))
        parts.append(("digits", ("aod_day", dx + AOD_DATE_DIGIT_W * 2 + AOD_COLON_W, dy,
                                 AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H, 2,
                                 DATA_SOURCES["day"], date_files)))
        need.append(("digit_date", None))

    return parts, need


def build_aod(workdir, cfg, progress=None):
    """在工程目录下写出 AOD 子工程。返回实际写入的图片数量。

    cfg 字段：
        enabled      bool
        bg_mode      'none' | 'black' | 'custom'
        bg_image     自定义底图的源路径（bg_mode='custom'）
        time_mode    'none' | 'time' | 'both'
        time_y       时间行 Y（像素）
        date_y       日期行 Y（像素）
        color        '#RRGGBB' 数字/冒号颜色
        font_path    自定义 TTF
    """
    if not cfg.get("enabled"):
        return 0

    aod_dir = os.path.join(workdir, "AOD")
    img_dir = os.path.join(aod_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(os.path.join(aod_dir, "output"), exist_ok=True)

    color = _hex_to_rgba(cfg.get("color", "#FFFFFF"))
    font_path = cfg.get("font_path")
    widgets = []
    n_written = 0

    # ---- 底图 ----
    bg_mode = cfg.get("bg_mode", "none")
    if bg_mode == "black":
        Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0)).save(
            os.path.join(img_dir, "aod_bg.png"))
        widgets.append(_w_image("aod_bg", "aod_bg.png", 0, 0, SCREEN_W, SCREEN_H))
        n_written += 1
    elif bg_mode == "custom" and cfg.get("bg_image") and os.path.isfile(cfg["bg_image"]):
        im = Image.open(cfg["bg_image"]).convert("RGB").resize(
            (SCREEN_W, SCREEN_H), Image.LANCZOS)
        im.save(os.path.join(img_dir, "aod_bg.png"))
        widgets.append(_w_image("aod_bg", "aod_bg.png", 0, 0, SCREEN_W, SCREEN_H))
        n_written += 1

    # ---- 数字与冒号 ----
    parts, _need = plan_aod_layout(cfg)
    made_digits = set()
    for kind, payload in parts:
        if kind == "img":
            name, fname, x, y, w, h = payload
            if fname == "aod_colon.png":
                render_colon_image(AOD_COLON_W, AOD_TIME_DIGIT_H, color, font_path).save(
                    os.path.join(img_dir, fname))
            else:
                render_colon_image(AOD_COLON_W, AOD_DATE_DIGIT_H, color, font_path).save(
                    os.path.join(img_dir, fname))
            widgets.append(_w_image(name, fname, x, y, w, h))
            n_written += 1
        else:
            name, x, y, dw, dh, digits, src, files = payload
            key = "t" if dh == AOD_TIME_DIGIT_H else "d"
            if key not in made_digits:
                # 10 张数字图（0..9）落盘；BitmapList 里再补一张 0 凑成 11 项
                # —— 官方样本就是 11 张，照抄数量规避「某位数字不显示」。
                imgs = render_digit_images(dw, dh, color, font_path)
                for i, im in enumerate(imgs):
                    im.save(os.path.join(img_dir, files[i]))
                made_digits.add(key)
                n_written += len(imgs)
            widgets.append(_w_digits(name, x, y, dw, dh, digits, src, files + [files[0]]))

    # 预览图（AOD 屏的 preview 实测不入包，但 fprj 声明了它，写上更安全）
    Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0)).save(
        os.path.join(img_dir, "preview.png"))

    fprj = generate_aod_fprj("".join(widgets))
    with open(os.path.join(aod_dir, "AOD.fprj"), "wb") as f:
        f.write(fprj)

    if progress:
        progress(f"AOD 子工程已写入（{n_written} 张素材）")
    return n_written


def _hex_to_rgba(s):
    s = (s or "#FFFFFF").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:                                # noqa: BLE001
        r = g = b = 255
    return (r, g, b, 255)


def render_preview(cfg, sample_time="09:41", sample_date="07/18"):
    """给 GUI 用的 AOD 效果预览（212x520 RGBA）。与 build_aod 用同一套布局参数。"""
    base = Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0))
    bg_mode = cfg.get("bg_mode", "none")
    if bg_mode == "custom" and cfg.get("bg_image") and os.path.isfile(cfg["bg_image"]):
        try:
            base = Image.open(cfg["bg_image"]).convert("RGB").resize(
                (SCREEN_W, SCREEN_H), Image.LANCZOS)
        except Exception:                            # noqa: BLE001
            pass
    elif bg_mode not in ("black", "custom"):
        # 预览里把"无底图"画成深灰，好让用户看出这块是屏幕底而不是我们加的图
        base = Image.new("RGB", (SCREEN_W, SCREEN_H), (8, 8, 10))

    color = _hex_to_rgba(cfg.get("color", "#FFFFFF"))
    font_path = cfg.get("font_path")
    tmode = cfg.get("time_mode", "time")
    parts, _ = plan_aod_layout(cfg)

    tdig = render_digit_images(AOD_TIME_DIGIT_W, AOD_TIME_DIGIT_H, color, font_path)
    ddig = render_digit_images(AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H, color, font_path)
    colon_t = render_colon_image(AOD_COLON_W, AOD_TIME_DIGIT_H, color, font_path)
    colon_d = render_colon_image(AOD_COLON_W, AOD_DATE_DIGIT_H, color, font_path)

    text_t = [c for c in sample_time if c.isdigit()]
    text_d = [c for c in sample_date if c.isdigit()]

    for kind, payload in parts:
        if kind == "img":
            name, fname, x, y, w, h = payload
            im = colon_t if fname == "aod_colon.png" else colon_d
            base.paste(im, (x, y), im)
            continue
        name, x, y, dw, dh, digits, src, _files = payload
        if src == DATA_SOURCES["hour"]:
            seq, arr = text_t[:2], tdig
        elif src == DATA_SOURCES["minute"]:
            seq, arr = text_t[2:4], tdig
        elif src == DATA_SOURCES["month"]:
            seq, arr = text_d[:2], ddig
        else:
            seq, arr = text_d[2:4], ddig
        for k, ch in enumerate(seq):
            if ch.isdigit():
                im = arr[int(ch)]
                base.paste(im, (x + k * dw, y), im)

    return base


def aod_modes():
    """给 GUI 用的下拉项。"""
    return AOD_BG_MODES
