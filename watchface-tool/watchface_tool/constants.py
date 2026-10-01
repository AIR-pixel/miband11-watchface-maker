# -*- coding: utf-8 -*-
"""常量与格式定义（小米手环 11 动态表盘）。"""

# 屏幕物理分辨率（手环 11 = 212 x 520）
SCREEN_W = 212
SCREEN_H = 520
ASPECT = SCREEN_W / SCREEN_H          # ≈ 0.4077，裁切比例锁定值

# Vela 表盘项目元数据
DEVICE_TYPE = "466"                   # Mi Band 10 / 11（212x520）
WIDGET_SHAPE = "34"

# .face 二进制头（Compiler.exe 产物）
FACE_MAGIC = b"\x5a\xa5\x34\x12"      # 5A A5 34 12
FACE_ID_OFFSET = 40
FACE_ID_SIZE = 10

# 约束
MAX_FRAMES = 240
# 默认帧率下调到 12：24fps 在 8s 素材上会产生 192 帧，即使 P64 也有 7.8MB
DEFAULT_FPS = 12
# 默认总帧数上限：体积的第一杠杆（色深只是次要杠杆）
DEFAULT_MAX_FRAMES = 96
DEFAULT_BUDGET_MB = 3.5               # 手环表盘体积预算（超出会提醒）

# 压缩等级：mode=RGB 原图，mode=P 走调色板量化（体积显著变小）
# 每帧实测（212x520，8s@8fps=64 帧换算）：RGB 147KB / P256 67KB / P128 53KB
#   / P64 41.5KB / P32 31.6KB / P16 20.4KB
COMPRESS_LEVELS = {
    "high":     {"label": "高画质 RGB",   "mode": "RGB"},
    "balanced": {"label": "均衡 P256",    "mode": "P", "colors": 256, "dither": True},
    "small":    {"label": "小体积 P128",  "mode": "P", "colors": 128, "dither": True},
    "tiny":     {"label": "极限 P64",     "mode": "P", "colors": 64,  "dither": False},
    "micro":    {"label": "极小 P32",     "mode": "P", "colors": 32,  "dither": False},
    "nano":     {"label": "微缩 P16",     "mode": "P", "colors": 16,  "dither": False},
}

# 编码格式：PNG 走 miwear 内置 lodepng；JPEG 已真机验证可正常显示，是正式选项而非实验项
ENCODE_FORMATS = {
    "png": {"label": "PNG（无损调色板）", "ext": "png"},
    "jpg": {"label": "JPEG（有损，体积小很多）", "ext": "jpg"},
}

# JPEG 质量：默认 80。实测 212x520 单帧（4:4:4）：
#   q95 60.3K / q90 41.4K / q85 32.7K / q80 27.5K / q70 21.4K / q60 17.7K
#   对照 P64 PNG 41.5K —— q90 与它持平，q80 只有它的 0.66 倍。
#   JPEG q90 以上体积反超 P64 PNG，而 P64 是无损调色板，所以 80~85 才是甜点区。
JPG_QUALITY = 80
JPG_QUALITY_OPTIONS = [90, 85, 80, 70, 60]

# 色度子采样：0=4:4:4（全分辨率色度）。PIL 默认（-1）会落到 4:2:0，
# 把色度砍到 106x260，彩色边缘明显串色 —— 这是「JPEG 看着糊」的主因。
# 实测关掉它（4:4:4）只多 19% 体积，色度 PSNR 却涨 2.5dB，是性价比最高的一刀。
# 注意：Android 的 Bitmap.compress 固定 4:2:0，改不了，安卓端质量天花板低于 PC 端。
JPG_SUBSAMPLING = 0

# 帧率档位
FPS_OPTIONS = [30, 24, 20, 16, 12, 8, 6]


# ============================================================================
# 表盘功能自定义（fprj 控件层）—— 2026-10-01 实测
# ============================================================================
#
# 【关键前提】Lua 表盘的 `.fprj` 只有一个 Shape=34 全透明挂载点，
# 主屏的一切（时间/日期/点击交互）都由 Lua 决定，改 fprj 没用。
# 但 **息屏屏（AOD）不支持 Lua**（实测：AOD.fprj 里写 Shape=34，其 lua 不入包），
# 所以 AOD 的时间/日期必须走 fprj 控件层的数据源绑定。

# ---------------------------------------------------------------------------
# 数据源 ID（fprj 的 Value_Src 字段）
#
# 来源：Mi-Create（ooflet/Mi-Create）src/data/sources.json 里 `xiaomi_band_10` 一栏，
# 即本工具使用的 DeviceType=466 对应的机型。ID 是**十六进制字面量去掉 0x 与前置零**。
# 该字段编译器只存数字、不校验语义，由设备侧 dataman 在运行期解析。
DATA_SOURCES = {
    "hour":      "0811",   # 时 0-23（两位整体）
    "hour_high": "1000911",
    "hour_low":  "0911",
    "minute":    "1011",   # 分 0-59（两位整体）
    "minute_high": "1211",
    "minute_low":  "1111",
    "second":    "1811",
    "day":       "1812",   # 日
    "day_high":  "1001912",
    "day_low":   "1912",
    "month":     "1012",   # 月
    "week":      "2012",   # 0=周日
    "year":      "0812",
    "ampm":      "0813",
    "battery":   "0841",
    "steps":     "0821",
    "calorie":   "0823",
    "heart":     "0822",
    "weather":   "3031",
    "temp":      "2031",
}

# ---------------------------------------------------------------------------
# 位置：LVGL 对齐枚举 + 附加像素偏移。
# 主屏走 Lua 的 lvgl.ALIGN.*；AOD 走 fprj 的 X/Y 绝对坐标（都归一化成这 9 个位置选）。
ALIGN_KEYS = [
    "TOP_LEFT", "TOP_MID", "TOP_RIGHT",
    "LEFT_MID", "CENTER", "RIGHT_MID",
    "BOTTOM_LEFT", "BOTTOM_MID", "BOTTOM_RIGHT",
]
ALIGN_LABELS = {
    "TOP_LEFT": "左上", "TOP_MID": "上中", "TOP_RIGHT": "右上",
    "LEFT_MID": "左中", "CENTER": "居中", "RIGHT_MID": "右中",
    "BOTTOM_LEFT": "左下", "BOTTOM_MID": "下中", "BOTTOM_RIGHT": "右下",
}

# ---------------------------------------------------------------------------
# 点击交互（全部走 Lua 层，表盘内生效）
TAP_ACTIONS = {
    "none":  {"label": "无（不响应点击）"},
    "cycle": {"label": "切换壁纸（多张壁纸轮换）"},
    "info":  {"label": "显示 / 隐藏时间日期"},
    "anim":  {"label": "暂停 / 继续动画"},
}

# ---------------------------------------------------------------------------
# AOD（息屏显示）配置
#
# 实测代价模型（AOD 屏，逐项差分）：
#   AOD 空屏          +88 B
#   每个 Shape=30     w*h*4 + 60 B
#   每个 Shape=32     图宽*图高*4 * 图数   ← 多控件共用同一 BitmapList 会去重
# 参考量级：46x64 的时分数字（共 11 张图）≈ 126 KB；20x28 的日期 ≈ 24 KB。
#
# ⚠️ 主屏上的 Shape=30 会被合成为整屏位图（+441 KB/个），AOD 屏不会 —— 
#    这也是"AOD 加小图很便宜、主屏加小控件很贵"的原因。
AOD_BG_MODES = {
    "none":   {"label": "无底图（靠屏幕黑底，不额外占体积）"},
    "black":  {"label": "纯黑底图（+431 KB，最保险）"},
    "custom": {"label": "自定义图片（+431 KB）"},
}

AOD_TIME_MODES = {
    "none": {"label": "不显示"},
    "time": {"label": "只显示时间"},
    "both": {"label": "时间 + 日期"},
}

# 数字位图默认尺寸（像素/单个数字）
AOD_TIME_DIGIT_W = 46
AOD_TIME_DIGIT_H = 64
AOD_DATE_DIGIT_W = 20
AOD_DATE_DIGIT_H = 28
AOD_COLON_W = 12          # 时与分之间的冒号（Shape=30 静态图）

# 默认字体：Windows 自带的 Arial Bold；找不到就退回 PIL 内置位图字体。
AOD_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
