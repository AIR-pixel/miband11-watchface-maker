# -*- coding: utf-8 -*-
"""手环 11 动态表盘制作工具 —— 入口。

默认启动 GUI；也支持命令行无界面生成（便于脚本化 / 测试）：

    python main.py --cli --src in.gif --level balanced --fps 16 \
        --name MyFace --compiler path/to/Compiler.exe [--crop x0,y0,x1,y1]
"""
import argparse
import sys

from watchface_tool import pipeline
from watchface_tool.constants import DEFAULT_MAX_FRAMES, JPG_QUALITY


def _cli(argv):
    p = argparse.ArgumentParser(description="手环 11 动态表盘生成（命令行）")
    p.add_argument("--src", required=True, help="素材路径（gif/mp4/图片）")
    p.add_argument("--level", default="balanced",
                   choices=["high", "balanced", "small", "tiny", "micro", "nano"])
    p.add_argument("--fps", type=float, default=None, help="目标帧率；省略则用源帧率")
    p.add_argument("--clip-start", type=float, default=0.0, help="起始时间（秒）")
    p.add_argument("--clip-dur", type=float, default=None, help="截取时长（秒）；省略取到结尾")
    p.add_argument("--max-frames", type=int, default=DEFAULT_MAX_FRAMES,
                   help=f"总帧数上限（默认 {DEFAULT_MAX_FRAMES}，超出自动降帧率）")
    p.add_argument("--fmt", default="png", choices=["png", "jpg"],
                   help="编码格式；jpg 体积小很多但为有损（已真机验证可用）")
    p.add_argument("--jpg-quality", type=int, default=JPG_QUALITY,
                   help=f"JPEG 质量（仅 --fmt jpg 生效，默认 {JPG_QUALITY}）；"
                        "实测单帧 q90 41K / q85 33K / q80 28K / q70 21K")
    p.add_argument("--speedup", action="store_true",
                   help="保持帧率、压缩时长（播放时快放）；默认是保时长、降帧率")
    p.add_argument("--crop", default=None, help="裁剪框 x0,y0,x1,y1；省略则默认居中")
    p.add_argument("--name", default="MyWatchface")
    p.add_argument("--id", default=None, help="表盘 ID（数字，省略自动生成）")
    p.add_argument("--compiler", required=True, help="Compiler.exe 路径")
    p.add_argument("--out", default=None, help="输出目录")
    p.add_argument("--no-time", action="store_true", help="不叠加时间日期")
    args = p.parse_args(argv)

    crop_box = None
    if args.crop:
        crop_box = tuple(int(x) for x in args.crop.split(","))
        assert len(crop_box) == 4

    r = pipeline.generate_face(
        source_path=args.src,
        crop_box=crop_box,
        level=args.level,
        target_fps=args.fps,
        face_name=args.name,
        face_id=args.id,
        compiler_exe=args.compiler,
        show_time=not args.no_time,
        output_dir=args.out,
        clip_start=args.clip_start,
        clip_dur=args.clip_dur,
        max_frames=args.max_frames,
        fmt=args.fmt,
        speedup=args.speedup,
        jpg_quality=args.jpg_quality,
        progress=lambda f, m: print(f"[{f * 100:5.1f}%] {m}"),
    )
    print(f"\n完成: {r.face_path}")
    speed_txt = ""
    if getattr(r, "speed_mult", 1.0) > 1.01:
        speed_txt = (f" · 覆盖 {r.span_seconds:.1f}s 快放 {r.speed_mult:.1f}x"
                     f"（播放 {r.play_seconds:.1f}s）")
    elif getattr(r, "play_seconds", 0):
        speed_txt = f" · 播放 {r.play_seconds:.1f}s"
    fmt_txt = "PNG" if r.fmt == "png" else f"JPEG q{r.jpg_quality}"
    print(f"{r.n_frames} 帧 @ {r.effective_fps:.1f}fps · "
          f"{r.face_size / 1048576:.2f} MB · {r.level_label} · {fmt_txt}{speed_txt}")


def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        _cli(sys.argv[1:])
        return
    from gui.window import run
    run()


if __name__ == "__main__":
    main()
