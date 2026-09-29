# -*- coding: utf-8 -*-
"""源素材（视频 / GIF / 静态图）→ RGB 帧序列。

GIF 和静态图直接用 Pillow 解码；视频调用系统 ffmpeg（不打包进工具，
合规原因同 Compiler.exe —— 由用户自行安装并加入 PATH）。
"""
import os
import re
import shutil
import subprocess
import tempfile
from collections import namedtuple

from PIL import Image

from .constants import MAX_FRAMES

# 抽帧规划结果。
# sample_fps 决定"抽多少帧"，play_fps 决定"播放节奏"，两者在默认模式下相等；
# 在「快放」模式下 play_fps > sample_fps，比值就是加速倍数。
FramePlan = namedtuple("FramePlan", "n sample_fps play_fps span period_ms speedup")


VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".ts", ".flv"}
GIF_EXTS = {".gif"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class SourceError(RuntimeError):
    pass


def find_ffmpeg():
    p = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    return p


def _gif_duration_ms(im):
    """GIF 总时长（毫秒），逐帧累加 duration。"""
    total = 0
    try:
        for i in range(im.n_frames):
            im.seek(i)
            total += im.info.get("duration", 100)
    except Exception:
        pass
    finally:
        im.seek(0)
    return total


def _gif_avg_period_ms(im):
    n = im.n_frames
    if n <= 1:
        return 100
    return round(_gif_duration_ms(im) / n)


def load_source_meta(path):
    """返回素材元信息 dict。"""
    if not os.path.exists(path):
        raise SourceError(f"文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()

    if ext in GIF_EXTS:
        im = Image.open(path)
        return {
            "type": "gif",
            "size": im.size,
            "n_frames": im.n_frames,
            "duration_ms": _gif_duration_ms(im),
        }
    if ext in IMAGE_EXTS:
        im = Image.open(path)
        return {"type": "image", "size": im.size, "n_frames": 1, "duration_ms": 0}
    if ext in VIDEO_EXTS:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise SourceError("处理视频需要 ffmpeg，但未在 PATH 中找到。请安装 ffmpeg 并加入 PATH。")
        w, h, dur, fps = _probe_video(ffmpeg, path)
        return {
            "type": "video",
            "size": (w, h),
            "duration_ms": dur,
            "fps": fps,
            "ffmpeg": ffmpeg,
        }
    raise SourceError(f"不支持的格式: {ext}（支持 GIF / 图片 / mp4·mov·webm 等视频）")


def _probe_video(ffmpeg, path):
    """用 ffmpeg -i 的 stderr 解析宽高/时长/帧率。"""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    info = proc.stderr or ""

    w = h = fps = dur = None
    m = re.search(r"(\d{2,5})x(\d{2,5})", info)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", info)
    if m:
        fps = float(m.group(1))
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if m:
        hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
        dur = round((hh * 3600 + mm * 60 + ss) * 1000)
    return w, h, dur, fps


def extract_preview(path):
    """抽一帧作为裁剪预览。返回 RGB Image 与素材 meta。"""
    meta = load_source_meta(path)
    if meta["type"] == "gif":
        im = Image.open(path)
        im.seek(0)
        return im.convert("RGB"), meta
    if meta["type"] == "image":
        return Image.open(path).convert("RGB"), meta
    # video
    tmp = tempfile.mkdtemp(prefix="wf_prev_")
    out = os.path.join(tmp, "prev.png")
    subprocess.run(
        [meta["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error",
         "-i", path, "-frames:v", "1", out],
        capture_output=True,
    )
    if not os.path.exists(out):
        raise SourceError("ffmpeg 抽帧失败，请确认该视频文件可正常解码。")
    return Image.open(out).convert("RGB"), meta


def extract_frames(path, target_fps, max_frames=MAX_FRAMES,
                   clip_start=0.0, clip_dur=None, speedup=False):
    """按 FramePlan 抽取帧，支持时长裁剪、总帧数上限与快放模式。

    clip_start: 起始时间（秒），默认 0。
    clip_dur:   截取时长（秒），None/0 表示取到素材结尾。
    speedup:    True 时保持帧率、压缩时长（播放时快放）。

    返回 (frames: list[RGB Image], period_ms: int)。period_ms 是**播放**节奏。
    体积的第一杠杆是帧数 —— 8s@24fps 有 192 帧，即使 P64 也要 7.8MB。
    """
    meta = load_source_meta(path)

    if meta["type"] == "image":
        return [Image.open(path).convert("RGB")], 0

    plan = plan_frames(meta, target_fps, max_frames, clip_start, clip_dur, speedup)

    if meta["type"] == "gif":
        im = Image.open(path)
        n = im.n_frames
        dur_total = meta["duration_ms"]
        # 按时间比例把 clip 区间映射到帧下标
        cs = clip_start or 0.0
        if dur_total > 0:
            f0 = min(1.0, max(0.0, cs * 1000.0 / dur_total))
            f1 = 1.0 if not clip_dur else min(1.0, (cs + clip_dur) * 1000.0 / dur_total)
        else:
            f0, f1 = 0.0, 1.0
        if f1 <= f0:
            f1 = min(1.0, f0 + 1e-3)
        i0 = int(round(f0 * (n - 1)))
        i1 = max(i0 + 1, int(round(f1 * (n - 1))))
        n_out = max(1, min(plan.n, i1 - i0 + 1))
        step = i1 - i0
        idxs = ([i0] if n_out == 1
                else [i0 + round(k * step / (n_out - 1)) for k in range(n_out)])
        frames = []
        for i in idxs:
            im.seek(min(int(i), n - 1))
            frames.append(im.convert("RGB"))
        return frames, plan.period_ms

    # video
    tmp = tempfile.mkdtemp(prefix="wf_frames_")
    fps_arg = (f"{plan.sample_fps:g}" if plan.sample_fps
               else (f"{meta['fps']:g}" if meta.get("fps") else "24"))
    outpat = os.path.join(tmp, "f_%04d.png")
    cmd = [meta["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error"]
    if clip_start and clip_start > 0:
        cmd += ["-ss", f"{clip_start:g}"]        # 输入 seek：快且对 mp4 足够精确
    cmd += ["-i", path]
    if clip_dur and clip_dur > 0:
        cmd += ["-t", f"{clip_dur:g}"]
    cmd += ["-vf", f"fps={fps_arg}", outpat]
    subprocess.run(cmd, capture_output=True)
    files = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
    files = files[:max_frames]
    if not files:
        raise SourceError("ffmpeg 未抽到任何帧，请确认视频有效、时长/起始时间设置合理。")
    frames = [Image.open(os.path.join(tmp, f)).convert("RGB") for f in files]
    return frames, plan.period_ms


def plan_frames(meta, target_fps, max_frames, clip_start=0.0, clip_dur=None,
                speedup=False):
    """在真正抽帧前规划帧数与播放节奏（供 UI 实时预估，也供抽帧统一取值）。

    两种模式在"时长 x 帧率 > max_frames"时才分道扬镳：

    - speedup=False（默认，**保时长、降帧率**）
      内容完整、速度正常，代价是掉帧。例：8s@24fps 限 96 帧 -> 自动降到 12fps，仍是 8 秒。
    - speedup=True（**保帧率、压时长 / 快放**）
      流畅、内容完整，代价是变快。例：8s@24fps 限 46 帧 -> 抽 46 帧摊到 8 秒上，
      仍按 24fps 播放 = 1.92 秒，约 4.2 倍速。

    流畅度 x 时长 x 体积是三角权衡，两者只能选一边牺牲。
    """
    if meta.get("type") == "image":
        return FramePlan(1, 0.0, 0.0, 0.0, 0, speedup)

    dur_ms = meta.get("duration_ms") or 0
    if dur_ms <= 0:
        # GIF 无时长信息：只能按帧数估
        n = min(meta.get("n_frames", 1) or 1, max_frames)
        f = float(target_fps or 0)
        return FramePlan(int(n), f, f, 0.0,
                         round(1000.0 / f) if f > 0 else 100, speedup)

    total_s = dur_ms / 1000.0
    start = max(0.0, min(clip_start or 0.0, total_s))
    span = total_s - start if not clip_dur else min(clip_dur, total_s - start)
    span = max(0.0, span)

    fps = float(target_fps or meta.get("fps") or 24.0)

    if speedup:
        n = min(max(1, round(span * fps)), max_frames)
        sample = (n / span) if span > 0 else fps
        play = fps
    else:
        n = max(1, round(span * fps))
        if n > max_frames:
            n = max_frames
            fps = (n / span) if span > 0 else fps
        sample = fps
        play = fps

    period = round(1000.0 / play) if play > 0 else 42
    return FramePlan(int(n), float(sample), float(play), float(span), int(period), bool(speedup))
