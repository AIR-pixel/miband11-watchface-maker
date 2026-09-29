# -*- coding: utf-8 -*-
"""裁切：把用户框选吸附到 212:520 比例并 clamp 到画面内。"""
from .constants import ASPECT, SCREEN_H, SCREEN_W


def resolve_crop(box, W, H):
    """把 (x0, y0, x1, y1) 吸附为 212:520 比例的裁切窗，返回 (x0, y0, x1, y1)。

    以框高为主算对应宽度；越界就回缩；中心 clamp 到画面内。保证无黑边。
    """
    bx0, by0, bx1, by1 = box
    cx = (bx0 + bx1) / 2.0
    cy = (by0 + by1) / 2.0
    ch = max(1.0, by1 - by0)
    cw = ch * ASPECT
    if cw > W:
        cw = float(W)
        ch = cw / ASPECT
    if ch > H:
        ch = float(H)
        cw = ch * ASPECT
    cx = min(max(cx, cw / 2.0), W - cw / 2.0)
    cy = min(max(cy, ch / 2.0), H - ch / 2.0)
    x0 = round(cx - cw / 2.0)
    y0 = round(cy - ch / 2.0)
    x1 = round(cx + cw / 2.0)
    y1 = round(cy + ch / 2.0)
    return x0, y0, x1, y1


def default_crop(W, H):
    """默认：全高 + 水平居中的裁切窗。"""
    ch = float(H)
    cw = ch * ASPECT
    if cw > W:
        cw = float(W)
        ch = cw / ASPECT
    cx, cy = W / 2.0, H / 2.0
    return resolve_crop((cx - cw / 2.0, cy - ch / 2.0, cx + cw / 2.0, cy + ch / 2.0), W, H)


def apply_crop(img, box, W, H):
    """对单帧执行裁切并 Lanczos 缩放到 212x520。返回 RGB Image。"""
    x0, y0, x1, y1 = resolve_crop(box, W, H)
    return img.crop((x0, y0, x1, y1)).resize((SCREEN_W, SCREEN_H), resample=3)  # 3 = LANCZOS
