# -*- coding: utf-8 -*-
"""编排：素材 → 抽帧 → 裁切 → 量化 → 生成 lua/fprj/AOD → 打包 .face。"""
import os
import shutil
import tempfile

from . import aod as aod_mod
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


def _wall_prefix(index):
    """壁纸 → 文件名前缀。第 1 张沿用 face_ 保持与单壁纸版本字节级兼容。"""
    return "face" if index == 0 else "w%d" % (index + 1)


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
    # ---- 功能自定义：主屏叠加元素 ----
    show_date=False,
    time_align="TOP_MID", time_ofs=(0, 30), time_size=48,
    time_color=0xFFFFFF, time_fmt="%H:%M",
    date_align="TOP_MID", date_ofs=(0, 86), date_size=16,
    date_color=0xEEEEEE, date_fmt="%m/%d",
    # ---- 功能自定义：交互 ----
    tap_action="none",
    # ---- 功能自定义：多壁纸 ----
    extra_walls=None,
    # ---- 功能自定义：息屏显示 ----
    aod=None,
):
    """完整生成 .face。返回 PipelineResult。

    crop_box: (x0, y0, x1, y1) 源像素坐标；None 则用默认居中裁切。
    target_fps: None 表示用源素材原生帧率。
    clip_start/clip_dur: 截取区间（秒）；clip_dur=None 表示取到结尾。
    max_frames: **每张壁纸**的帧数上限（多壁纸时总体积 = 各壁纸之和）。
    fmt: 'png'（无损调色板）或 'jpg'（有损，已真机验证可用、体积小很多）。
    jpg_quality: 仅 fmt='jpg' 生效；默认 80（实测比 P64 PNG 小 34%）。
    speedup: False=保时长降帧率（内容完整、速度正常、会掉帧）；
             True =保帧率压时长（流畅、内容完整、播放变快）。
    face_id: None 则用时间戳生成一个（避免与市集表盘撞车）。

    extra_walls: [(路径, crop_box 或 None), ...]，第 2 张及以后的壁纸。
                 它们沿用同一套 level/fmt/fps/裁剪时长/max_frames 参数。
    aod: 息屏显示配置 dict，字段见 aod.build_aod；None 或 enabled=False 则不加 AOD。
    """
    def report(frac, msg):
        if progress:
            progress(frac, msg)

    if face_id is None:
        import time
        face_id = str(int(time.time()))[-8:]

    walls_in = [(source_path, crop_box)] + [
        (w[0], w[1] if len(w) > 1 else None) for w in (extra_walls or [])
    ]

    workdir = tempfile.mkdtemp(prefix="wf_build_")
    try:
        app_lua_dir = os.path.join(workdir, "app", "lua")
        images_dir = os.path.join(workdir, "images")
        # Compiler.exe 会把 .info 写到 <fprj 同级的>/output/，目录必须预先存在
        info_dir = os.path.join(workdir, "output")
        for d in (app_lua_dir, images_dir, info_dir):
            os.makedirs(d, exist_ok=True)

        ext = quantize_mod.format_ext(fmt)
        wall_meta = []          # 喂给 lua 生成器
        first_frame = None
        total_frames = 0
        total_span = 0.0
        speed_max = 1.0
        n_walls = len(walls_in)

        for wi, (src, cbox) in enumerate(walls_in):
            tag = "壁纸 %d/%d" % (wi + 1, n_walls) if n_walls > 1 else ""
            report(0.02 + 0.7 * wi / n_walls, "读取素材…" + tag)

            meta = extract_mod.load_source_meta(src)
            W, H = meta["size"]
            if cbox is None:
                cbox = crop_mod.default_crop(W, H)
            x0, y0, x1, y1 = crop_mod.resolve_crop(cbox, W, H)

            plan = extract_mod.plan_frames(
                meta, target_fps, max_frames, clip_start, clip_dur, speedup)
            if n_walls == 1:
                if plan.sample_fps > 0 and abs(plan.sample_fps - plan.play_fps) > 0.01:
                    mult = plan.play_fps / plan.sample_fps
                    report(0.05, f"快放模式：{plan.n} 帧覆盖 {plan.span:.1f}s，按 "
                                 f"{plan.play_fps:.1f}fps 播放 ≈ "
                                 f"{plan.n / plan.play_fps:.1f}s（{mult:.1f} 倍速）")
                elif target_fps and abs(plan.play_fps - target_fps) > 0.01:
                    report(0.05, f"时长 {plan.span:.1f}s x {target_fps}fps 超过帧数上限 "
                                 f"{max_frames}，自动降到 {plan.play_fps:.1f}fps（时长不变）")

            frames, period_ms = extract_mod.extract_frames(
                src, target_fps, max_frames, clip_start, clip_dur, speedup)
            n = len(frames)
            prefix = _wall_prefix(wi)
            report(0.05 + 0.7 * wi / n_walls, f"共 {n} 帧，{period_ms}ms/帧 {tag}")

            for i, fr in enumerate(frames):
                cropped = crop_mod.apply_crop(fr, cbox, W, H)
                q = quantize_mod.quantize_frame(cropped, level)
                quantize_mod.save_frame(
                    q, os.path.join(app_lua_dir, f"{prefix}_{i + 1:02d}.{ext}"),
                    fmt, jpg_quality)
                if wi == 0 and i == 0:
                    first_frame = cropped
                report(0.05 + 0.7 * (wi + (i + 1) / max(1, n)) / n_walls,
                       f"处理{tag} 帧 {i + 1}/{n}")

            wall_meta.append({"prefix": prefix, "count": n, "period_ms": period_ms})
            total_frames += n
            if period_ms:
                total_span += n * period_ms / 1000.0
            if plan.sample_fps and plan.sample_fps > 0:
                speed_max = max(speed_max, plan.play_fps / plan.sample_fps)

        # preview.png（用第 1 张壁纸的首帧）
        if first_frame is None:
            first_frame = _black_frame()
        quantize_mod.save_preview(first_frame, os.path.join(images_dir, "preview.png"))

        # ---- main.lua ----
        report(0.78, "生成脚本与项目文件…")
        lua_src = lua_mod.generate_lua(
            wall_meta, wall_meta[0]["period_ms"], ext=ext,
            show_time=show_time, show_date=show_date,
            time_align=time_align, time_ofs=time_ofs, time_size=time_size,
            time_color=time_color, time_fmt=time_fmt,
            date_align=date_align, date_ofs=date_ofs, date_size=date_size,
            date_color=date_color, date_fmt=date_fmt,
            tap_action=tap_action,
            fps_desc="%d 张壁纸 / 共 %d 帧" % (n_walls, total_frames))
        with open(os.path.join(app_lua_dir, "main.lua"), "w", encoding="utf-8") as f:
            f.write(lua_src)

        fprj_bytes = fprj_mod.generate_fprj(face_name)
        fprj_path = os.path.join(workdir, f"{face_name}.fprj")
        with open(fprj_path, "wb") as f:
            f.write(fprj_bytes)

        # ---- AOD 子工程 ----
        aod_bytes = 0
        if aod and aod.get("enabled"):
            report(0.82, "生成息屏显示（AOD）…")
            aod_mod.build_aod(workdir, aod)
            aod_bytes = aod_mod.estimate_aod_bytes(aod)

        # ---- 打包 ----
        report(0.88, "Compiler.exe 打包…")
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(source_path) or ".", "watchface_out")
        face_path = build_mod.build_face(
            compiler_exe, fprj_path, output_dir, f"{face_name}.face", face_id
        )

        report(1.0, "完成")
        play_fps = 1000.0 / wall_meta[0]["period_ms"] if wall_meta[0]["period_ms"] else 0
        return PipelineResult(
            face_path=face_path,
            face_size=os.path.getsize(face_path),
            n_frames=total_frames,
            period_ms=wall_meta[0]["period_ms"],
            level=level,
            level_label=COMPRESS_LEVELS[level]["label"],
            fmt=fmt,
            jpg_quality=jpg_quality,
            clip_start=clip_start,
            clip_dur=clip_dur,
            effective_fps=play_fps,
            speedup=speedup,
            speed_mult=speed_max,
            play_seconds=total_span,
            span_seconds=total_span,
            face_id=face_id,
            face_name=face_name,
            n_walls=n_walls,
            aod_enabled=bool(aod and aod.get("enabled")),
            aod_bytes=aod_bytes,
            tap_action=tap_action,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _black_frame():
    from PIL import Image
    from .constants import SCREEN_H, SCREEN_W
    return Image.new("RGB", (SCREEN_W, SCREEN_H), (0, 0, 0))
