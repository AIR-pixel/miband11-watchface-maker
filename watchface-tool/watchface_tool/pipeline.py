# -*- coding: utf-8 -*-
"""编排：素材 → 抽帧 → 裁切 → 量化 → 生成 lua/fprj → 打包 .face。"""
import os
import shutil
import tempfile

from . import build as build_mod
from . import crop as crop_mod
from . import extract as extract_mod
from . import fprj as fprj_mod
from . import lua as lua_mod
from . import quantize as quantize_mod
from .constants import (COMPRESS_LEVELS, DEFAULT_FPS, DEFAULT_MAX_FRAMES,
                        JPG_QUALITY)


class PipelineResult:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def generate_face(
    source_path,
    crop_box=None,
    level="balanced",
    target_fps=DEFAULT_FPS,
    face_name="MyWatchface",
    face_id=None,
    compiler_exe=None,
    show_time=True,
    output_dir=None,
    progress=None,
    clip_start=0.0,
    clip_dur=None,
    max_frames=DEFAULT_MAX_FRAMES,
    fmt="png",
    speedup=False,
    jpg_quality=JPG_QUALITY,
):
    """完整生成 .face。返回 PipelineResult。

    crop_box: (x0, y0, x1, y1) 源像素坐标；None 则用默认居中裁切。
    target_fps: None 表示用源素材原生帧率。
    clip_start/clip_dur: 截取区间（秒）；clip_dur=None 表示取到结尾。
    max_frames: 总帧数上限。
    fmt: 'png'（无损调色板）或 'jpg'（有损，已真机验证可用、体积小很多）。
    jpg_quality: 仅 fmt='jpg' 生效；默认 80（实测比 P64 PNG 小 34%）。
    speedup: False=保时长降帧率（内容完整、速度正常、会掉帧）；
             True =保帧率压时长（流畅、内容完整、播放变快）。
    face_id: None 则用时间戳生成一个（避免与市集表盘撞车）。
    """
    def report(frac, msg):
        if progress:
            progress(frac, msg)

    if face_id is None:
        import time
        face_id = str(int(time.time()))[-8:]

    workdir = tempfile.mkdtemp(prefix="wf_build_")
    try:
        # 1. 抽帧（先按 plan_frames 预估，帧率超限时自动下调）
        report(0.02, "读取素材…")
        meta = extract_mod.load_source_meta(source_path)
        W, H = meta["size"]

        if crop_box is None:
            crop_box = crop_mod.default_crop(W, H)
        x0, y0, x1, y1 = crop_mod.resolve_crop(crop_box, W, H)

        plan = extract_mod.plan_frames(
            meta, target_fps, max_frames, clip_start, clip_dur, speedup)
        if plan.sample_fps > 0 and abs(plan.sample_fps - plan.play_fps) > 0.01:
            mult = plan.play_fps / plan.sample_fps
            report(0.05, f"快放模式：{plan.n} 帧覆盖 {plan.span:.1f}s，按 "
                         f"{plan.play_fps:.1f}fps 播放 ≈ {plan.n / plan.play_fps:.1f}s"
                         f"（{mult:.1f} 倍速）")
        elif target_fps and abs(plan.play_fps - target_fps) > 0.01:
            report(0.05, f"时长 {plan.span:.1f}s x {target_fps}fps 超过帧数上限 "
                         f"{max_frames}，自动降到 {plan.play_fps:.1f}fps（时长不变）")

        frames, period_ms = extract_mod.extract_frames(
            source_path, target_fps, max_frames, clip_start, clip_dur, speedup)
        n = len(frames)
        report(0.15, f"共 {n} 帧，{period_ms}ms/帧")

        ext = quantize_mod.format_ext(fmt)

        # 2. 裁切 + 量化 + 落盘
        app_lua_dir = os.path.join(workdir, "app", "lua")
        images_dir = os.path.join(workdir, "images")
        # Compiler.exe 会把 .info 写到 <fprj 同级的>/output/，目录必须预先存在
        info_dir = os.path.join(workdir, "output")
        os.makedirs(app_lua_dir, exist_ok=True)
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(info_dir, exist_ok=True)

        total = 0
        first_frame = None
        for i, fr in enumerate(frames):
            cropped = crop_mod.apply_crop(fr, crop_box, W, H)
            q = quantize_mod.quantize_frame(cropped, level)
            quantize_mod.save_frame(
                q, os.path.join(app_lua_dir, f"face_{i + 1:02d}.{ext}"), fmt,
                jpg_quality)
            total += 1
            if i == 0:
                first_frame = cropped
            report(0.2 + 0.5 * (i + 1) / n, f"处理帧 {i + 1}/{n}")

        # preview.png（用第一帧）
        quantize_mod.save_preview(first_frame, os.path.join(images_dir, "preview.png"))

        # 3. 生成 main.lua + .fprj
        report(0.75, "生成脚本与项目文件…")
        lua_src = lua_mod.generate_lua(n, period_ms, show_time=show_time, ext=ext)
        with open(os.path.join(app_lua_dir, "main.lua"), "w", encoding="utf-8") as f:
            f.write(lua_src)

        fprj_bytes = fprj_mod.generate_fprj(face_name)
        fprj_path = os.path.join(workdir, f"{face_name}.fprj")
        with open(fprj_path, "wb") as f:
            f.write(fprj_bytes)

        # 4. 打包
        report(0.85, "Compiler.exe 打包…")
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(source_path) or ".", "watchface_out")
        face_path = build_mod.build_face(
            compiler_exe, fprj_path, output_dir, f"{face_name}.face", face_id
        )

        report(1.0, "完成")
        play_fps = 1000.0 / period_ms if period_ms else 0
        speed_mult = (plan.play_fps / plan.sample_fps
                      if plan.sample_fps > 0 and plan.sample_fps != plan.play_fps else 1.0)
        return PipelineResult(
            face_path=face_path,
            face_size=os.path.getsize(face_path),
            n_frames=n,
            period_ms=period_ms,
            crop=(x0, y0, x1, y1),
            level=level,
            level_label=COMPRESS_LEVELS[level]["label"],
            fmt=fmt,
            jpg_quality=jpg_quality,
            clip_start=clip_start,
            clip_dur=clip_dur,
            effective_fps=play_fps,
            speedup=speedup,
            speed_mult=speed_mult,
            play_seconds=(n * period_ms / 1000.0) if period_ms else 0.0,
            span_seconds=plan.span,
            face_id=face_id,
            face_name=face_name,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
