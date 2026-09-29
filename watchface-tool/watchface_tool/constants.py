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
