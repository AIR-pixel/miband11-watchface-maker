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
    p.add_argument("--no-time", action="store_true", help="不叠加时间")
    # ---- 功能自定义 ----
    p.add_argument("--date", action="store_true", help="叠加日期（默认只叠加时间）")
    p.add_argument("--date-fmt", default="%m/%d", help="日期 strftime 格式，默认 %%m/%%d")
    p.add_argument("--time-fmt", default="%H:%M", help="时间 strftime 格式，默认 %%H:%%M")
    p.add_argument("--time-pos", default="TOP_MID", help="时间位置（LVGL 对齐名，如 TOP_MID）")
    p.add_argument("--time-ofs", default="0,30", help="时间像素偏移 dx,dy")
    p.add_argument("--time-size", type=int, default=48, help="时间字号")
    p.add_argument("--time-color", default="FFFFFF", help="时间颜色 RRGGBB")
    p.add_argument("--date-pos", default="TOP_MID", help="日期位置")
    p.add_argument("--date-ofs", default="0,86", help="日期像素偏移 dx,dy")
    p.add_argument("--date-size", type=int, default=16, help="日期字号")
    p.add_argument("--date-color", default="EEEEEE", help="日期颜色 RRGGBB")
    p.add_argument("--tap", default="none", choices=["none", "cycle", "info", "anim"],
                   help="短按表盘：none 无 / cycle 切换壁纸 / info 显隐时间日期 / anim 暂停动画")
    p.add_argument("--wall", action="append", default=[],
                   help="额外壁纸路径（可重复）；沿用主素材的参数")
    p.add_argument("--aod", action="store_true", help="生成息屏显示（AOD）子工程")
    p.add_argument("--aod-bg", default="none", choices=["none", "black", "custom"],
                   help="AOD 底图：none 靠屏幕黑底（不占体积）/ black 纯黑 / custom 自定义")
    p.add_argument("--aod-bg-image", default=None, help="--aod-bg custom 时的图片路径")
    p.add_argument("--aod-content", default="time", choices=["none", "time", "both"],
                   help="AOD 显示内容：none / time 时间 / both 时间+日期")
    p.add_argument("--aod-time-y", type=int, default=200, help="AOD 时间行 Y")
    p.add_argument("--aod-date-y", type=int, default=300, help="AOD 日期行 Y")
    p.add_argument("--aod-color", default="#FFFFFF", help="AOD 数字颜色 #RRGGBB")
    p.add_argument("--aod-font", default=None, help="AOD 数字字体 TTF 路径")
    args = p.parse_args(argv)

    crop_box = None
    if args.crop:
        crop_box = tuple(int(x) for x in args.crop.split(","))
        assert len(crop_box) == 4

    def _ofs(s):
        a, b = s.split(",")
        return (int(a), int(b))

    r = pipeline.generate_face(
        source_path=args.src,
        crop_box=crop_box,
        level=args.level,
        target_fps=args.fps,
        face_name=args.name,
        face_id=args.id,
        compiler_exe=args.compiler,
        show_time=not args.no_time,
        show_date=args.date,
        time_align=args.time_pos,
        time_ofs=_ofs(args.time_ofs),
        time_size=args.time_size,
        time_color=int(args.time_color.lstrip("#"), 16),
        time_fmt=args.time_fmt,
        date_align=args.date_pos,
        date_ofs=_ofs(args.date_ofs),
        date_size=args.date_size,
        date_color=int(args.date_color.lstrip("#"), 16),
        date_fmt=args.date_fmt,
        tap_action=args.tap,
        extra_walls=[(w, None) for w in args.wall],
        aod={
            "enabled": args.aod,
            "bg_mode": args.aod_bg,
            "bg_image": args.aod_bg_image,
            "time_mode": args.aod_content,
            "time_y": args.aod_time_y,
            "date_y": args.aod_date_y,
            "color": args.aod_color,
            "font_path": args.aod_font,
        },
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
    extra = []
    if getattr(r, "n_walls", 1) > 1:
        extra.append(f"{r.n_walls} 张壁纸")
    if getattr(r, "aod_enabled", False):
        extra.append(f"AOD +{r.aod_bytes / 1024:.0f} KB")
    extra_txt = (" · " + " · ".join(extra)) if extra else ""
    print(f"{r.n_frames} 帧 @ {r.effective_fps:.1f}fps · "
          f"{r.face_size / 1048576:.2f} MB · {r.level_label} · {fmt_txt}"
          f"{speed_txt}{extra_txt}")


def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        _cli(sys.argv[1:])
        return
    from gui.window import run
    run()


if __name__ == "__main__":
    main()
