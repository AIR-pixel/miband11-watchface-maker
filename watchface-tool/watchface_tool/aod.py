# -*- coding: utf-8 -*-
"""息屏显示（AOD）子工程生成。

## 结构

AOD 是主工程的**同级子工程**，不单独编译（无论是走官方编译器还是本项目的纯代码打包，
它都随主工程一起进同一个 `.face`）：

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

from PIL import Image

from . import aod_font
from .constants import (AOD_COLON_W, AOD_DATE_DIGIT_H,
                        AOD_DATE_DIGIT_W,
                        AOD_TIME_DIGIT_H, AOD_TIME_DIGIT_W, DATA_SOURCES,
                        DEVICE_TYPE, SCREEN_H, SCREEN_W)

# 官方样本（手环 8 Pro）的 BitmapList 是 11 张：00..09 再补一张 00。
# 照抄这个数量，避免"少一张导致某位数字不显示"这类玄学问题。
DIGIT_IMAGE_COUNT = 11


# --------------------------------------------------------------------------- 数字位图

def _colored(alpha, w, h, color):
    """把 alpha 灰度图按指定颜色合成 RGBA 直通 alpha（RGB 已着色，alpha=遮罩）。"""
    base = Image.new("RGBA", (w, h), color[:3] + (0,))
    base.putalpha(Image.frombytes("L", (w, h), alpha))
    return base


def render_digit_images(digit_w, digit_h, color=(255, 255, 255, 255)):
    """生成 0-9 的单数字位图（透明底、居中），返回 list[Image]，共 10 张。

    字形来自内嵌字库（aod_font），不再读系统字体 —— 两端的 AOD 数字因此完全一致，
    且 fit() 缩放结果可以被 `tools/diff_face.py --stage font` 逐像素对拍。
    每个数字占 `digit_w x digit_h` 的独立画布，控件宽度 = digit_w * Digits
    （官方样本 27x27 数字 → 2 位宽 54）。
    """
    out = []
    for d in range(10):
        alpha = aod_font.fit(aod_font.glyph(d), aod_font.GLYPH_W, aod_font.GLYPH_H,
                             digit_w, digit_h)
        out.append(_colored(alpha, digit_w, digit_h, color))
    return out


def render_colon_image(w=AOD_COLON_W, h=AOD_TIME_DIGIT_H, color=(255, 255, 255, 255)):
    """时:分之间的冒号（单独一张 Shape=30 小图）。"""
    alpha = aod_font.fit(aod_font.colon(), aod_font.COLON_W, aod_font.COLON_H, w, h)
    return _colored(alpha, w, h, color)


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


def widgets_to_xml(widgets):
    """控件表 → fprj 里的 Widget 片段（与结构化布局一一对应）。"""
    out = []
    for w in widgets:
        if w["kind"] == 30:
            out.append(_w_image(w["name"], w["img"], w["x"], w["y"], w["w"], w["h"]))
        else:
            out.append(_w_digits(w["name"], w["x"], w["y"], w["dw"], w["dh"],
                                 w["digits"], w["src"], w["list"]))
    return "".join(out)


def needed_images(widgets):
    """控件表 → {文件名: (宽, 高)}。打包时按它去 images/ 读像素。"""
    m = {}
    for w in widgets:
        if w["kind"] == 30:
            m[w["img"]] = (w["w"], w["h"])
        else:
            for f in w["list"]:
                m[f] = (w["dw"], w["dh"])
    return m


def generate_aod_fprj(widgets_xml, title="AOD"):
    xml = (_AOD_HEAD.format(device=DEVICE_TYPE, title=title)
           + widgets_xml + _AOD_TAIL)
    return xml.encode("utf-16")


def plan_aod_widgets(cfg):
    """算出 AOD 屏的**控件表**（结构化 dict），不产 XML、不落盘。

    打包器据此推导描述块，`build_aod()` 据此写素材与 fprj —— 两边共用同一份布局，
    不会出现「fprj 里声明的图没打进包」这类漂移。

    每项：
        {'kind': 30, 'name','x','y','w','h','img'}
        {'kind': 32, 'name','x','y','dw','dh','digits','src','list'}
    """
    widgets = []
    bg_mode = cfg.get("bg_mode", "none")
    has_bg = bg_mode == "black" or bool(
        bg_mode == "custom" and cfg.get("bg_image") and os.path.isfile(cfg["bg_image"]))
    if has_bg:
        widgets.append({"kind": 30, "name": "aod_bg", "x": 0, "y": 0,
                        "w": SCREEN_W, "h": SCREEN_H, "img": "aod_bg.png"})

    parts, _need = plan_aod_layout(cfg)
    for kind, payload in parts:
        if kind == "img":
            name, fname, x, y, w, h, _group = payload
            widgets.append({"kind": 30, "name": name, "x": x, "y": y,
                            "w": w, "h": h, "img": fname})
        else:
            name, x, y, dw, dh, digits, src, files, _group = payload
            # BitmapList 补一张 0 凑成 11 项（官方样本就是 11 张）
            widgets.append({"kind": 32, "name": name, "x": x, "y": y,
                            "dw": dw, "dh": dh, "digits": digits, "src": src,
                            "list": list(files) + [files[0]]})
    return widgets


# --------------------------------------------------------------------------- 组装

def plan_aod_layout(cfg):
    """算出各控件的位置，返回 (parts, need)。

    time/日期水平居中：先算总宽，再定起点 X。

    parts 里每个元素是 `(kind, payload)`，payload **末位是分组标记**
    （"time" / "date"）—— 下游靠它选位图尺寸与复用数字图，
    不要再拿「高度等于某个常量」去猜属于哪一行。
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
                                 2, DATA_SOURCES["hour"], digit_files, "time")))
        parts.append(("img", ("aod_colon", "aod_colon.png",
                              x0 + AOD_TIME_DIGIT_W * 2, y0, AOD_COLON_W, AOD_TIME_DIGIT_H,
                              "time")))
        parts.append(("digits", ("aod_min", x0 + AOD_TIME_DIGIT_W * 2 + AOD_COLON_W, y0,
                                 AOD_TIME_DIGIT_W, AOD_TIME_DIGIT_H, 2,
                                 DATA_SOURCES["minute"], digit_files, "time")))
        need.append(("digit_time", None))

    # ---- 日期行（月/日）----
    if date_files:
        dw = AOD_DATE_DIGIT_W * 2 + AOD_COLON_W + AOD_DATE_DIGIT_W * 2
        dx = (W - dw) // 2
        dy = cfg.get("date_y", 300)
        parts.append(("digits", ("aod_month", dx, dy, AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H,
                                 2, DATA_SOURCES["month"], date_files, "date")))
        parts.append(("img", ("aod_dcolon", "aod_dcolon.png",
                              dx + AOD_DATE_DIGIT_W * 2, dy, AOD_COLON_W, AOD_DATE_DIGIT_H,
                              "date")))
        parts.append(("digits", ("aod_day", dx + AOD_DATE_DIGIT_W * 2 + AOD_COLON_W, dy,
                                 AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H, 2,
                                 DATA_SOURCES["day"], date_files, "date")))
        need.append(("digit_date", None))

    return parts, need


def build_aod(workdir, cfg, progress=None):
    """在工程目录下写出 AOD 子工程（素材 + AOD.fprj）。返回写入的图片数量。

    cfg 字段：
        enabled      bool
        bg_mode      'none' | 'black' | 'custom'
        bg_image     自定义底图的源路径（bg_mode='custom'）
        time_mode    'none' | 'time' | 'both'
        time_y       时间行 Y（像素）
        date_y       日期行 Y（像素）
        color        '#RRGGBB' 数字/冒号颜色

    布局全部来自 `plan_aod_widgets()` —— 打包器读的是同一份控件表，
    所以这里只负责把控件需要的图**画出来存盘**。
    """
    if not cfg.get("enabled"):
        return 0

    aod_dir = os.path.join(workdir, "AOD")
    img_dir = os.path.join(aod_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(os.path.join(aod_dir, "output"), exist_ok=True)

    color = _hex_to_rgba(cfg.get("color", "#FFFFFF"))
    widgets = plan_aod_widgets(cfg)
    n_written = 0
    digits_done = set()          # 同一 (dw, dh) 的 10 张数字图只画一次

    for w in widgets:
        if w["kind"] == 30:
            if w["img"] == "aod_bg.png":
                _save_bg(img_dir, cfg)
            else:
                render_colon_image(w["w"], w["h"], color).save(os.path.join(img_dir, w["img"]))
            n_written += 1
            continue

        key = (w["dw"], w["dh"])
        if key not in digits_done:
            files = w["list"][:-1]           # 末位是补的重复 0，不单独落盘
            for i, im in enumerate(render_digit_images(w["dw"], w["dh"], color)):
                im.save(os.path.join(img_dir, files[i]))
            digits_done.add(key)
            n_written += len(files)

    # 预览图（AOD 屏的 preview 实测不入包，但 fprj 声明了它，写上更安全）
    Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0)).save(
        os.path.join(img_dir, "preview.png"))

    fprj = generate_aod_fprj(widgets_to_xml(widgets))
    with open(os.path.join(aod_dir, "AOD.fprj"), "wb") as f:
        f.write(fprj)

    if progress:
        progress(f"AOD 子工程已写入（{n_written} 张素材）")
    return n_written


def _save_bg(img_dir, cfg):
    """AOD 底图：纯黑 or 自定义图（缩到整屏）。"""
    path = os.path.join(img_dir, "aod_bg.png")
    if cfg.get("bg_mode") == "custom" and cfg.get("bg_image"):
        Image.open(cfg["bg_image"]).convert("RGB").resize(
            (SCREEN_W, SCREEN_H), Image.LANCZOS).save(path)
    else:
        Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0)).save(path)


def _hex_to_rgba(s):
    s = (s or "#FFFFFF").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except Exception:                                # noqa: BLE001
        r = g = b = 255
    return (r, g, b, 255)


_GLYPH_CACHE = {"key": None, "val": None}


def _glyph_set(color):
    """一组数字/冒号位图，按 color 缓存。

    GUI 预览每动一下 Y 滑块就要重画一次，不缓存的话每次都要渲染 22 张 PIL 图
    （10 时间数字 + 10 日期数字 + 2 个冒号），拖滑块会明显卡。
    调用方只读取（paste），不会改这些位图，所以共享是安全的。
    """
    key = (tuple(color),)
    if _GLYPH_CACHE["key"] == key and _GLYPH_CACHE["val"] is not None:
        return _GLYPH_CACHE["val"]
    val = (
        render_digit_images(AOD_TIME_DIGIT_W, AOD_TIME_DIGIT_H, color),
        render_digit_images(AOD_DATE_DIGIT_W, AOD_DATE_DIGIT_H, color),
        render_colon_image(AOD_COLON_W, AOD_TIME_DIGIT_H, color),
        render_colon_image(AOD_COLON_W, AOD_DATE_DIGIT_H, color),
    )
    _GLYPH_CACHE["key"], _GLYPH_CACHE["val"] = key, val
    return val


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
    tmode = cfg.get("time_mode", "time")
    parts, _ = plan_aod_layout(cfg)

    tdig, ddig, colon_t, colon_d = _glyph_set(color)

    text_t = [c for c in sample_time if c.isdigit()]
    text_d = [c for c in sample_date if c.isdigit()]

    for kind, payload in parts:
        if kind == "img":
            name, fname, x, y, w, h, group = payload
            im = colon_t if group == "time" else colon_d
            base.paste(im, (x, y), im)
            continue
        name, x, y, dw, dh, digits, src, _files, group = payload
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
