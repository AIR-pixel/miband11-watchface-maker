# -*- coding: utf-8 -*-
"""压缩：把裁切好的 212x520 帧按等级量化并保存为 PNG / JPEG。

实测（212x520 单帧）：
    RGB 146.8KB / P256 66.7KB / P128 53.0KB / P64 41.5KB
    / P32 31.6KB / P16 20.4KB / P8 14.3KB
    JPEG 4:4:4 —— q95 60.3KB / q90 41.4KB / q85 32.7KB / q80 27.5KB / q70 21.4KB / q60 17.7KB

体积的第一杠杆是**帧数**（时长 x 帧率），色深只是次要杠杆：
P256 -> P64 只降 38%，而 24fps -> 8fps 让帧数直接降 67%。

JPEG 与 PNG 不是单纯替代关系：
  - P64 PNG 是无损调色板，平涂区有**量化色带**，但没有有损噪点；
  - JPEG 是连续色调，没有色带，但有**蚊子噪点/块效应**。
  真人/渐变内容 JPEG 观感更好，动漫平涂 PNG 更干净。
"""
import io
import os

from PIL import Image

from .constants import (COMPRESS_LEVELS, ENCODE_FORMATS, JPG_QUALITY,
                        JPG_SUBSAMPLING)


def quantize_frame(img_rgb, level):
    """返回处理后的 Image（RGB 或 P 模式）。"""
    cfg = COMPRESS_LEVELS[level]
    if cfg["mode"] == "RGB":
        return img_rgb.convert("RGB")
    dither = Image.FLOYDSTEINBERG if cfg.get("dither") else Image.NONE
    return img_rgb.convert("RGB").quantize(
        colors=cfg["colors"], method=Image.MEDIANCUT, dither=dither
    )


def _encode(img, fmt, jpg_quality=JPG_QUALITY):
    """把 Image 编码成字节，返回 bytes。

    jpg_quality 仅对 fmt="jpg" 生效；色度子采样固定关掉（详见 constants）。
    """
    buf = io.BytesIO()
    if fmt == "jpg":
        img.convert("RGB").save(
            buf, format="JPEG", quality=int(jpg_quality),
            optimize=True, subsampling=JPG_SUBSAMPLING)
    elif img.mode == "P":
        info = dict(img.info)
        info.pop("transparency", None)
        img.save(buf, format="PNG", optimize=True, **info)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def save_frame(img, path, fmt="png", jpg_quality=JPG_QUALITY):
    """保存单帧。P 模式需先剥离 transparency 字段，否则报 ValueError。"""
    with open(path, "wb") as f:
        f.write(_encode(img, fmt, jpg_quality))


def frame_size_bytes(img, level, fmt="png", jpg_quality=JPG_QUALITY):
    """单帧落盘后的真实字节数（用于体积预估）。"""
    return len(_encode(quantize_frame(img, level), fmt, jpg_quality))


def estimate_total_bytes(img_rgb, level, fmt, n_frames, header_overhead=300 * 1024,
                         jpg_quality=JPG_QUALITY):
    """预估整个 .face 的体积：首帧真实编码字节 x 帧数 + 头部/预览图开销。

    帧间差异实测在 3% 以内，用首帧外推足够准。
    """
    return frame_size_bytes(img_rgb, level, fmt, jpg_quality) * n_frames + header_overhead


def save_preview(img, path):
    """生成表盘选择器里的静态预览图（直接存 212x520 原图即可）。"""
    img.convert("RGB").save(path, format="PNG", optimize=True)


def format_ext(fmt):
    """编码格式对应的文件扩展名。"""
    return ENCODE_FORMATS.get(fmt, ENCODE_FORMATS["png"])["ext"]
